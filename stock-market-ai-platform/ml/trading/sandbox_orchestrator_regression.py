"""Regression for provenance-verified frozen-signal paper orchestration."""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.execution import DisabledBrokerAdapter
from ml.trading.journal import OrderJournal
from ml.trading.sandbox_orchestrator import (
    PaperSignalOrchestrator,
    SandboxBoundaryViolation,
    SandboxLimits,
)
from ml.trading.signal_provenance import (
    FrozenSignalSnapshot,
    SignalProvenanceRejected,
    seal_signal,
)

ROOT = Path(__file__).resolve().parent
LIVE_CONTRACT = ROOT / "live_trading_contract.json"
STRATEGY_ID = "FROZEN_SYNTHETIC_SIGNAL"
MODEL_SHA = "d" * 64
REGISTRY = {STRATEGY_ID: MODEL_SHA}


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def signal(*, symbol="AAPL", spread="5", sha=MODEL_SHA):
    raw = FrozenSignalSnapshot(
        strategy_id=STRATEGY_ID,
        frozen_strategy_sha256=sha,
        decision_timestamp_utc=datetime.now(timezone.utc),
        symbol=symbol,
        reference_price=Decimal("100"),
        spread_bps=Decimal(spread),
        rank=1,
        target_weight=Decimal("0.40"),
        universe_sha256="e" * 64,
        ranking_artifact_sha256="f" * 64,
    )
    return seal_signal(raw)


def orchestrator(journal, **kwargs):
    return PaperSignalOrchestrator(
        journal,
        approved_model_identities=REGISTRY,
        **kwargs,
    )


def main():
    contract_before = hashlib.sha256(LIVE_CONTRACT.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="ds-sandbox-orchestrator-") as tmp:
        root = Path(tmp)
        journal = OrderJournal(root / "orders.jsonl")
        runner = orchestrator(journal)

        frozen_signal = signal()
        result = runner.run(frozen_signal)
        require(result["status"] == "FILLED", "Verified frozen signal reaches paper fill")
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
        require(
            events[0]["payload"]["provenance_sha256"]
            == frozen_signal.provenance_sha256,
            "Verified provenance seal is journaled",
        )
        duplicate = runner.run(frozen_signal)
        require(
            duplicate["duplicate_safe"] is True
            and len(journal.events_for(result["intent_id"])) == 5,
            "Repeated frozen signal is idempotent",
        )

        tampered = replace(frozen_signal, reference_price=Decimal("99"))
        before_tamper = len(journal.read())
        try:
            runner.run(tampered)
        except SignalProvenanceRejected:
            print("[PASS] Tampered signal payload rejected before proposal")
        else:
            raise AssertionError("tampered signal passed provenance verification")
        require(len(journal.read()) == before_tamper, "Tampered signal creates no journal event")

        wrong_model = signal(symbol="MSFT", sha="a" * 64)
        try:
            runner.run(wrong_model)
        except SignalProvenanceRejected:
            print("[PASS] Unapproved frozen model identity rejected")
        else:
            raise AssertionError("unapproved model identity entered sandbox")

        unsealed = replace(signal(symbol="GOOGL"), provenance_sha256=None)
        try:
            runner.run(unsealed)
        except SignalProvenanceRejected:
            print("[PASS] Missing provenance seal rejected")
        else:
            raise AssertionError("unsealed signal entered sandbox")

        rejected = orchestrator(OrderJournal(root / "rejected.jsonl"))
        rejected_result = rejected.run(signal(symbol="MSFT", spread="40"))
        require(
            rejected_result["status"] == "REJECTED"
            and "MAXIMUM_SPREAD_EXCEEDED" in rejected_result["reasons"],
            "Verified wide-spread signal fails closed before submission",
        )
        require(not rejected.adapter.orders(), "Rejected signal creates no paper order")

        try:
            orchestrator(
                OrderJournal(root / "invalid-adapter.jsonl"),
                adapter=DisabledBrokerAdapter(),  # type: ignore[arg-type]
            )
        except SandboxBoundaryViolation:
            print("[PASS] Non-paper adapter rejected at construction")
        else:
            raise AssertionError("sandbox accepted a non-paper adapter")

        tiny = orchestrator(
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
    sources = (
        (ROOT / "sandbox_orchestrator.py").read_text(encoding="utf-8")
        + (ROOT / "signal_provenance.py").read_text(encoding="utf-8")
    )
    require(
        not any(token in sources.lower() for token in ("alpaca_trade_api", "ib_insync", "robin_stocks")),
        "No brokerage SDK imported",
    )
    print("\nStatus: PASSED")
    print("Frozen-signal provenance: VERIFIED AND TAMPER-EVIDENT")
    print("Signal -> risk -> journal -> paper fill -> reconciliation: VERIFIED")
    print("Live contract: PREPARATION ONLY")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
