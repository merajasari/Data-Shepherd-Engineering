"""Fail-closed pre-trade risk evaluation.

The evaluator is pure: it performs no I/O, imports no brokerage SDK, and cannot
submit an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ml.trading.execution import OrderIntent


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    intent_id: str

    @property
    def status(self) -> str:
        return "APPROVED_FOR_EXECUTION_BOUNDARY" if self.approved else "REJECTED_FAIL_CLOSED"


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


def evaluate_pretrade(
    contract: dict[str, Any],
    intent: OrderIntent,
    *,
    account: dict[str, Any],
    market: dict[str, Any],
    runtime: dict[str, Any],
) -> RiskDecision:
    reasons: list[str] = []
    limits = contract.get("limits") or {}

    if contract.get("status") != "LIVE_AUTHORIZED":
        reasons.append("CONTRACT_NOT_LIVE_AUTHORIZED")
    if contract.get("live_trading_enabled") is not True:
        reasons.append("LIVE_TRADING_DISABLED")
    if contract.get("human_activation_required") and runtime.get("human_activated") is not True:
        reasons.append("HUMAN_ACTIVATION_MISSING")
    if not contract.get("broker") or not contract.get("account_id"):
        reasons.append("BROKER_OR_ACCOUNT_UNSELECTED")
    if runtime.get("kill_switch_clear") is not True:
        reasons.append("KILL_SWITCH_NOT_CLEAR")
    if runtime.get("frozen_model_verified") is not True:
        reasons.append("FROZEN_MODEL_NOT_VERIFIED")
    if intent.strategy_id != contract.get("strategy_id"):
        reasons.append("STRATEGY_ID_MISMATCH")
    if intent.frozen_strategy_sha256 != contract.get("frozen_strategy_sha256"):
        reasons.append("FROZEN_SHA_MISMATCH")
    if market.get("session_open") is not True:
        reasons.append("MARKET_SESSION_CLOSED")
    if market.get("quote_current") is not True:
        reasons.append("MARKET_DATA_STALE")
    if account.get("reconciled") is not True:
        reasons.append("ACCOUNT_NOT_RECONCILED")
    if runtime.get("idempotency_key_new") is not True:
        reasons.append("DUPLICATE_IDEMPOTENCY_KEY")

    required_limits = (
        "maximum_deployed_capital_usd","maximum_order_notional_usd",
        "maximum_position_notional_usd","maximum_daily_loss_usd",
        "maximum_open_positions","maximum_orders_per_session",
        "maximum_signal_age_seconds","maximum_quote_age_seconds",
        "maximum_spread_bps",
    )
    if any(limits.get(name) is None for name in required_limits):
        reasons.append("RISK_LIMITS_INCOMPLETE")

    quote = _decimal(market.get("reference_price"))
    notional = intent.requested_notional
    if notional is None and quote is not None:
        notional = intent.quantity * quote
    max_order = _decimal(limits.get("maximum_order_notional_usd"))
    if notional is None or notional <= 0:
        reasons.append("ORDER_NOTIONAL_UNAVAILABLE")
    elif max_order is not None and notional > max_order:
        reasons.append("MAXIMUM_ORDER_NOTIONAL_EXCEEDED")

    buying_power = _decimal(account.get("buying_power_usd"))
    if notional is not None and (buying_power is None or buying_power < notional):
        reasons.append("BUYING_POWER_INSUFFICIENT")

    daily_pnl = _decimal(account.get("daily_pnl_usd"))
    max_loss = _decimal(limits.get("maximum_daily_loss_usd"))
    if daily_pnl is None:
        reasons.append("DAILY_PNL_UNAVAILABLE")
    elif max_loss is not None and daily_pnl <= -max_loss:
        reasons.append("DAILY_LOSS_LIMIT_REACHED")

    open_positions = account.get("open_positions")
    max_positions = limits.get("maximum_open_positions")
    if not isinstance(open_positions, int):
        reasons.append("OPEN_POSITION_COUNT_UNAVAILABLE")
    elif isinstance(max_positions, int) and open_positions >= max_positions and intent.side.upper() == "BUY":
        reasons.append("MAXIMUM_OPEN_POSITIONS_REACHED")

    spread = _decimal(market.get("spread_bps"))
    max_spread = _decimal(limits.get("maximum_spread_bps"))
    if spread is None:
        reasons.append("SPREAD_UNAVAILABLE")
    elif max_spread is not None and spread > max_spread:
        reasons.append("MAXIMUM_SPREAD_EXCEEDED")

    now = datetime.now(timezone.utc)
    age = (now - intent.created_at_utc.astimezone(timezone.utc)).total_seconds()
    max_signal_age = _decimal(limits.get("maximum_signal_age_seconds"))
    if max_signal_age is not None and Decimal(str(max(age, 0))) > max_signal_age:
        reasons.append("SIGNAL_STALE")

    return RiskDecision(not reasons, tuple(dict.fromkeys(reasons)), intent.intent_id)
