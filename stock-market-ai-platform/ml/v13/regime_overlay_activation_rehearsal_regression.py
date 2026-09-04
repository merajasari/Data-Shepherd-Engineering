"""Regression coverage for the no-write V13 activation rehearsal."""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory

import ml.v13.regime_overlay_activation_rehearsal as rehearsal_module
from ml.v13.regime_overlay_activation_rehearsal import run_rehearsal


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        journal = root / "evidence.jsonl"
        approval = root / "manual_approval.json"
        lease = root / "lease.json"
        result = run_rehearsal(
            now_utc=datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc),
            journal_path=journal,
            approval_path=approval,
            lease_path=lease,
        )

        require(
            result["status"] == "PASSED_REHEARSAL_ONLY",
            "End-to-end activation ceremony rehearsal passes",
        )
        require(
            result["approval_status"] == "VALID_FOR_SEPARATE_ACTIVATION_STEP"
            and result["approval_valid"] is True,
            "Exact in-memory manual approval satisfies its locked validator",
        )
        require(
            result["transition_status"] == "ELIGIBLE_PLAN_ONLY"
            and result["transition_eligible_in_rehearsal"] is True,
            "Valid rehearsal approval satisfies all transition-plan gates",
        )
        require(
            result["transition_gates_passed"] == result["transition_gates_total"],
            "All preregistered transition gates pass in rehearsal",
        )
        require(
            result["proposed_lease"]["activation_state"]
            == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
            and result["proposed_lease"]["paper_trading_only"] is True
            and result["proposed_lease"]["brokerage_orders"] is False,
            "Proposed lease is limited to fresh paper evidence",
        )
        require(
            len(str(result["approval_payload_sha256"])) == 64
            and len(str(result["proposed_lease_sha256"])) == 64,
            "Approval and proposed lease have canonical identities",
        )
        require(
            not journal.exists() and not approval.exists() and not lease.exists(),
            "Rehearsal creates no journal, approval or lease file",
        )
        require(
            result["protected_paths_unchanged"] is True
            and result["approval_artifact_written"] is False
            and result["activation_lease_written"] is False,
            "Protected activation paths remain unchanged",
        )
        require(
            result["transition_applied"] is False
            and result["activation_performed"] is False
            and result["scheduler_changed"] is False,
            "Rehearsal cannot apply activation or change a scheduler",
        )
        require(
            result["market_data_requested"] is False
            and result["evidence_appended"] is False
            and result["production_evidence_modified"] is False,
            "Rehearsal requests no data and writes no evidence",
        )
        require(
            result["live_trading_enabled"] is False
            and result["brokerage_orders"] is False,
            "Live trading and brokerage authority remain absent",
        )
        require(
            all(
                result[field] is False
                for field in (
                    "v8_modified",
                    "v10_modified",
                    "v11_modified",
                    "v12_modified",
                )
            ),
            "V8 through V12 remain isolated",
        )

    source = inspect.getsource(rehearsal_module).lower()
    require(
        all(
            token not in source
            for token in (
                ".write_text(",
                ".write_bytes(",
                "open(",
                "os.replace(",
                "subprocess",
                "launchctl",
                "collect_complete_snapshot",
                "run_session_decision(",
                "import alpaca",
                "from alpaca",
                "robin_stocks",
                "ib_insync",
            )
        ),
        "Rehearsal source has no write, collection, scheduler or brokerage surface",
    )

    print("Status: PASSED")
    print("V13 approval -> transition -> proposed lease: VERIFIED IN MEMORY")
    print("Approval artifact written: NO")
    print("Activation lease written: NO")
    print("Transition applied: NO")
    print("Fresh evidence activation: DISABLED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
