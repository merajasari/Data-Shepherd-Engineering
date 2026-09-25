"""Scheduled entrypoint for the fixed-snapshot StockEagle prospective lane."""
from __future__ import annotations

from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase3 import run_once


def main() -> None:
    result = run_once()
    print("STOCKEAGLE250 AUTONOMOUS ML PROSPECTIVE SCHEDULED ENTRYPOINT")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(f"Decision status: {result.get('decision_status', 'N/A')}")
    print(
        "Decision / entry / exit batches: "
        f"{result['decision_batches']} / "
        f"{result['entry_batches']} / "
        f"{result['exit_batches']}"
    )
    print(
        "Completed cohorts / complete blocks: "
        f"{result['completed_cohorts_per_candidate']} / "
        f"{result['complete_five_sleeve_blocks']}"
    )
    print(
        "Formal review: "
        f"{result['formal_review_status']}"
    )
    print(
        "Missed decision sessions: "
        f"{len(result.get('missed_decision_sessions', []))}"
    )
    print(f"Appended this run: {result.get('appended_this_run', 0)}")
    print("Fixed V1/V2/V3 snapshots: YES")
    print("Retraining: OFF")
    print("Automatic selection/promotion: OFF")
    print("Paper only: YES")
    print("Brokerage orders: OFF")
    print("Live execution: OFF")


if __name__ == "__main__":
    main()
