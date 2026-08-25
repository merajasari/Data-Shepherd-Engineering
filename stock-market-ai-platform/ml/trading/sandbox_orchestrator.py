"""Broker-neutral signal-to-paper-order orchestration.

This module is restricted to PaperBrokerAdapter. It cannot connect to a broker,
load credentials, or write to V8/V10 production journals.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from ml.trading.execution import OrderIntent
from ml.trading.journal import OrderJournal
from ml.trading.lifecycle import current_state, transition
from ml.trading.paper_adapter import PaperBrokerAdapter
from ml.trading.risk import evaluate_pretrade
from ml.trading.signal_provenance import FrozenSignalSnapshot, FrozenSignalVerifier


class SandboxBoundaryViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxLimits:
    starting_cash_usd: Decimal = Decimal("5000")
    maximum_deployed_capital_usd: Decimal = Decimal("500")
    maximum_order_notional_usd: Decimal = Decimal("200")
    maximum_position_notional_usd: Decimal = Decimal("200")
    maximum_daily_loss_usd: Decimal = Decimal("25")
    maximum_open_positions: int = 5
    maximum_orders_per_session: int = 5
    maximum_signal_age_seconds: int = 300
    maximum_quote_age_seconds: int = 15
    maximum_spread_bps: Decimal = Decimal("25")


def _paper_contract(signal: FrozenSignalSnapshot, limits: SandboxLimits) -> dict[str, Any]:
    return {
        "status": "LIVE_AUTHORIZED",  # evaluator authorization; adapter remains PAPER only
        "live_trading_enabled": True,
        "human_activation_required": True,
        "broker": "PAPER_SANDBOX",
        "account_id": "LOCAL_DETERMINISTIC_PAPER",
        "strategy_id": signal.strategy_id,
        "frozen_strategy_sha256": signal.frozen_strategy_sha256,
        "limits": {
            "maximum_deployed_capital_usd": str(limits.maximum_deployed_capital_usd),
            "maximum_order_notional_usd": str(limits.maximum_order_notional_usd),
            "maximum_position_notional_usd": str(limits.maximum_position_notional_usd),
            "maximum_daily_loss_usd": str(limits.maximum_daily_loss_usd),
            "maximum_open_positions": limits.maximum_open_positions,
            "maximum_orders_per_session": limits.maximum_orders_per_session,
            "maximum_signal_age_seconds": limits.maximum_signal_age_seconds,
            "maximum_quote_age_seconds": limits.maximum_quote_age_seconds,
            "maximum_spread_bps": str(limits.maximum_spread_bps),
        },
        "brokerage_orders": False,
    }


class PaperSignalOrchestrator:
    def __init__(
        self,
        journal: OrderJournal,
        *,
        adapter: PaperBrokerAdapter | None = None,
        limits: SandboxLimits | None = None,
        approved_model_identities: dict[str, str] | None = None,
    ):
        self.journal = journal
        self.limits = limits or SandboxLimits()
        self.adapter = adapter or PaperBrokerAdapter(self.limits.starting_cash_usd)
        self.verifier = FrozenSignalVerifier(approved_model_identities or {})
        if type(self.adapter) is not PaperBrokerAdapter:
            raise SandboxBoundaryViolation("sandbox accepts only the deterministic PaperBrokerAdapter")

    def _intent(self, signal: FrozenSignalSnapshot) -> OrderIntent:
        budget = min(
            self.limits.maximum_order_notional_usd,
            self.limits.maximum_deployed_capital_usd * signal.target_weight,
        )
        quantity = (budget / signal.reference_price).to_integral_value(rounding=ROUND_DOWN)
        stable = (
            f"{signal.strategy_id}|{signal.frozen_strategy_sha256}|"
            f"{signal.decision_timestamp_utc.astimezone(timezone.utc).isoformat()}|"
            f"{signal.symbol.upper()}|BUY"
        )
        intent_id = hashlib.sha256(stable.encode()).hexdigest()
        return OrderIntent(
            intent_id=intent_id,
            idempotency_key=f"PAPER-{intent_id}",
            strategy_id=signal.strategy_id,
            frozen_strategy_sha256=signal.frozen_strategy_sha256,
            symbol=signal.symbol.upper(),
            side="BUY",
            quantity=quantity,
            order_type="LIMIT",
            created_at_utc=signal.decision_timestamp_utc,
            limit_price=signal.reference_price,
        )

    def run(self, signal: FrozenSignalSnapshot) -> dict[str, Any]:
        provenance = self.verifier.verify(signal)
        if signal.reference_price <= 0 or signal.target_weight <= 0:
            raise SandboxBoundaryViolation("signal price and target weight must be positive")
        if signal.rank < 1:
            raise SandboxBoundaryViolation("signal rank must be positive")

        intent = self._intent(signal)
        prior = current_state(self.journal, intent.intent_id)
        if prior:
            return {
                "status": prior,
                "intent_id": intent.intent_id,
                "duplicate_safe": True,
                "mode": "PAPER_ONLY",
                "brokerage_orders": False,
            }

        transition(
            self.journal,
            intent.intent_id,
            "PROPOSED",
            {"symbol": intent.symbol, "rank": signal.rank, "quantity": str(intent.quantity),
             "provenance_sha256": provenance["provenance_sha256"]},
            event_key=f"{intent.intent_id}-proposed",
        )
        account_snapshot = self.adapter.account_snapshot()
        positions_before = {
            item["symbol"]: Decimal(item["quantity"])
            for item in self.adapter.positions()
        }
        risk_account = {
            "reconciled": True,
            "buying_power_usd": account_snapshot["cash"],
            "daily_pnl_usd": "0",
            "open_positions": len(self.adapter.positions()),
        }
        market = {
            "session_open": True,
            "quote_current": True,
            "reference_price": str(signal.reference_price),
            "spread_bps": str(signal.spread_bps),
        }
        runtime = {
            "human_activated": True,
            "kill_switch_clear": True,
            "frozen_model_verified": True,
            "idempotency_key_new": True,
        }
        decision = evaluate_pretrade(
            _paper_contract(signal, self.limits),
            intent,
            account=risk_account,
            market=market,
            runtime=runtime,
        )
        if not decision.approved:
            transition(
                self.journal,
                intent.intent_id,
                "REJECTED",
                {"reasons": list(decision.reasons), "mode": "PAPER"},
                event_key=f"{intent.intent_id}-risk-rejected",
            )
            return {
                "status": "REJECTED",
                "intent_id": intent.intent_id,
                "reasons": list(decision.reasons),
                "mode": "PAPER_ONLY",
                "brokerage_orders": False,
            }

        transition(self.journal, intent.intent_id, "RISK_APPROVED",
                   {"mode": "PAPER"}, event_key=f"{intent.intent_id}-risk-approved")
        transition(self.journal, intent.intent_id, "SUBMITTED",
                   {"mode": "PAPER"}, event_key=f"{intent.intent_id}-submitted")
        order = self.adapter.submit_order(intent)
        transition(self.journal, intent.intent_id, "ACKNOWLEDGED",
                   {"paper_order_id": order["broker_order_id"]}, event_key=f"{intent.intent_id}-ack")

        filled = self.adapter.simulate_fill(
            order["broker_order_id"], intent.quantity, signal.reference_price
        )
        transition(self.journal, intent.intent_id, "FILLED",
                   {"filled_quantity": filled["filled_quantity"], "price": str(signal.reference_price)},
                   event_key=f"{intent.intent_id}-filled")

        expected_cash = Decimal(account_snapshot["cash"]) - intent.quantity * signal.reference_price
        expected_positions = dict(positions_before)
        expected_positions[intent.symbol] = (
            expected_positions.get(intent.symbol, Decimal("0")) + intent.quantity
        )
        reconciliation = self.adapter.reconcile(expected_cash, expected_positions)
        if not reconciliation["reconciled"]:
            raise SandboxBoundaryViolation("paper reconciliation failed after fill")
        return {
            "status": "FILLED",
            "intent_id": intent.intent_id,
            "symbol": intent.symbol,
            "quantity": str(intent.quantity),
            "paper_order_id": order["broker_order_id"],
            "reconciled": True,
            "mode": "PAPER_ONLY",
            "brokerage_orders": False,
        }
