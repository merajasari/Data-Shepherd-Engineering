"""Regression checks for the V14 refresh-then-collect scheduler."""
from __future__ import annotations

from ml.v14.logistic_forward_scheduler import run_scheduler


def main() -> None:
    calls: list[str] = []

    blocked = run_scheduler(
        refresh_fn=lambda: {"status": "BRONZE_PARTIAL", "ready_for_collection": False},
        collector_fn=lambda **_: calls.append("collector") or {"status": "unexpected"},
    )
    assert blocked["status"] == "WAITING_FOR_DATA_REFRESH"
    assert blocked["collector_invoked"] is False
    assert calls == []

    allowed = run_scheduler(
        refresh_fn=lambda: {"status": "FEATURES_CURRENT", "ready_for_collection": True},
        collector_fn=lambda **_: calls.append("collector") or {"status": "COLLECTING_PAPER_FORWARD"},
    )
    assert allowed["status"] == "COLLECTED"
    assert allowed["collector_invoked"] is True
    assert calls == ["collector"]
    assert allowed["paper_trading_only"] is True
    assert allowed["brokerage_orders"] is False
    assert allowed["v8_v10_modified"] is False
    print("[PASS] Scheduler blocks collection until features are current")
    print("[PASS] Scheduler invokes only the isolated V14 collector")
    print("[PASS] Scheduler preserves paper-only and V8/V10 isolation")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
