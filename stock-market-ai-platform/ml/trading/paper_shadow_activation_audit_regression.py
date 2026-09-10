"""Regression tests for the preregistered paper-shadow activation audit."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from ml.trading.paper_shadow_activation_audit import (
    CONTRACT_PATH, EXPECTED_CONTRACT_SHA, run_audit,
)


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def fixtures():
    v8 = {
        "frozen_sha256": "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41",
        "readiness_status": "READY",
        "ranking_eligible_count": 100,
        "latest_research_top10": [{"rank": i} for i in range(1, 11)],
        "launch_operations": {
            "scheduler_healthy": True,
            "market_data_current": True,
            "journal_writable": True,
            "journal_duplicate_safe": True,
            "request_time_historical_parquet_load": False,
            "brokerage_orders": False,
        },
    }
    monitor = {"status": "HEALTHY", "bridge_status": "PREREGISTERED_DISABLED"}
    account = {"status": "EMPTY_READY", "reconciled": True, "brokerage_orders": False}
    return v8, monitor, account


def main():
    original = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    v8, monitor, account = fixtures()
    before = run_audit(
        now=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
        v8_payload=v8, paper_monitor=monitor, paper_account=account,
        runtime_locked=True, check_services=False, persist=False,
    )
    require(before["status"] == "WAITING_FOR_BOUNDARY", "Pre-boundary state waits")
    require(before["activation_performed"] is False, "Pre-boundary audit cannot activate")
    require(before["paper_signal_export"] is False, "Pre-boundary audit exports no signals")

    day_zero = run_audit(
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        v8_payload=v8, paper_monitor=monitor, paper_account=account,
        runtime_locked=True, check_services=False, persist=False,
    )
    require(day_zero["status"] == "READY_FOR_MANUAL_APPROVAL", "Boundary permits eligibility only")
    require(day_zero["manual_approval_required"] is True, "Separate manual approval remains mandatory")
    require(day_zero["manual_approval_present"] is False, "Audit does not manufacture approval")
    require(day_zero["activation_performed"] is False, "Passing audit never self-activates")
    require(day_zero["brokerage_orders"] is False, "Audit has no brokerage authority")
    require(day_zero["holdout_outcomes_read"] is False, "Audit reads no holdout outcomes")

    v8["launch_operations"]["market_data_current"] = False
    blocked = run_audit(
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        v8_payload=v8, paper_monitor=monitor, paper_account=account,
        runtime_locked=True, check_services=False, persist=False,
    )
    require(blocked["status"] == "BLOCKED", "Stale market data fails closed")
    require(blocked["activation_performed"] is False, "Blocked audit cannot activate")
    require(hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() == original == EXPECTED_CONTRACT_SHA,
            "Preregistered audit contract unchanged")
    approval = Path("data/trading/paper_shadow/activation/manual_approval.json")
    require(not approval.exists(), "No manual approval artifact created")
    print("\nStatus: PASSED")
    print("Activation authority: NONE")
    print("Paper signal export: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
