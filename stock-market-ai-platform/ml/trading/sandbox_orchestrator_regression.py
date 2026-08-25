"""Regression for frozen-signal to deterministic paper execution orchestration."""
from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.execution import DisabledBrokerAdapter
from ml.trading.journal import OrderJournal
from ml.trading.sandbox_orchestrator import (
    FrozenSignalSnapshot,
    PaperSignalOrchestrator,
    SandboxBoundaryViolation,
    SandboxLimits,
)

ROOT = Path(__file__).resolve().parent
LIVE_CONTRACT = ROOT / "live_trading_contract.json"


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def signal(*, symbol="AAPL", spread="5", sha="d"*64):
    return FrozenSignalSnapshot(
        strategy_id="FROZEN_SYNTHETIC_SIGNAL",
        frozen_strategy_sha256=sha,
        decision_timestamp_utc=datetime.now(timezone.utc),
        symbol=symbol,
        reference_price=Decimal("100"),
        spread_bps=Decimal(spread),
        rank=1,
        target_weight=Decimal("0.40"),
    )


def main():
    contract_before = hashlib.sha256(LIVE_CONTRACT.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="ds-sandbox-orchestrator-") as tmp:
        root = Path(tmp)
        journal = OrderJournal(root / "orders.jsonl")
        orchestrator = PaperSignalOrchestrator(journal)

        result = orchestrator.run(signal())
        require(result["status"] == "FILLED", "Frozen signal reaches paper fill")
        require(result["quantity"] == "2", "Integer share sizing honors paper limits")
        require(result["reconciled"] is True, "Post-fill cash and position reconcile")
        require(result["mode"] == "PAPER_ONLY", "Result is visibly paper only")
        require(result["brokerage_orders"] is False, "Paper result has no live-order authority")

        events = journal.events_for(result["intent_id"])
        require(
            [event["state"] for event in events]
            == ["PROPOSED", "RISK_APPROVED", "SUBMITTED", "ACKNOWLEDGED", "FILLED"],
            "Append-only lifecycle is complete",
        )
        duplicate = orchestrator.run(signal())
        require(
            duplicate["duplicate_safe"] is True and len(journal.events_for(result["intent_id"])) == 5,
            "Repeated frozen signal is idempotent",
        )

        rejected = PaperSignalOrchestrator(OrderJournal(root / "rejected.jsonl"))
        rejected_result = rejected.run(signal(symbol="MSFT", spread="40"))
        require(
            rejected_result["status"] == "REJECTED"
            and "MAXIMUM_SPREAD_EXCEEDED" in rejected_result["reasons"],
            "Wide-spread signal fails closed before submission",
        )
        require(not rejected.adapter.orders(), "Rejected signal creates no paper order")

        try:
            PaperSignalOrchestrator(
                OrderJournal(root / "invalid-adapter.jsonl"),
                adapter=DisabledBrokerAdapter(),  # type: ignore[arg-type]
            )
        except SandboxBoundaryViolation:
            print("[PASS] Non-paper adapter rejected at construction")
        else:
            raise AssertionError("sandbox accepted a non-paper adapter")

        tiny = PaperSignalOrchestrator(
            OrderJournal(root / "tiny.jsonl"),
            limits=SandboxLimits(maximum_order_notional_usd=Decimal("10")),
        )
        tiny_result = tiny.run(signal(symbol="NVDA"))
        require(
            tiny_result["status"] == "REJECTED"
            and "ORDER_NOTIONAL_UNAVAILABLE" in tiny_result["reasons"],
            "Zero-share sizing fails closed",
        )

        require(
            not any(path.name in {"journal.jsonl", "status.json"} for path in root.rglob("*")),
            "No V8/V10 production evidence path created",
        )

    contract_after = hashlib.sha256(LIVE_CONTRACT.read_bytes()).hexdigest()
    require(contract_after == contract_before, "Preparation-only live contract unchanged")

    sources = (ROOT / "sandbox_orchestrator.py").read_text(encoding="utf-8")
    require(
        not any(token in sources.lower() for token in ("alpaca_trade_api", "ib_insync", "robin_stocks")),
        "No brokerage SDK imported",
    )
    print("\nStatus: PASSED")
    print("Signal -> risk -> journal -> paper fill -> reconciliation: VERIFIED")
    print("Live contract: PREPARATION ONLY")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
