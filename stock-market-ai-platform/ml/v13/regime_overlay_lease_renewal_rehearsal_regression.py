"""Regression checks for the in-memory V13 renewal ceremony rehearsal."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT, activate
from ml.v13.regime_overlay_lease_renewal_rehearsal import build_rehearsal


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    preflight = {
        "status": "READY_DISABLED",
        "contract_sha256": "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702",
        "v12_disposition_sha256": "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2",
        "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "production_journal_events": 0,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
    }
    with TemporaryDirectory(prefix="v13_renewal_rehearsal_") as raw:
        root = Path(raw)
        approval_path = root / "approval.json"
        lease_path = root / "lease.json"
        journal_path = root / "evidence.jsonl"
        activate(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc),
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=lambda: preflight,
        )
        before = (approval_path.read_bytes(), lease_path.read_bytes())
        result = build_rehearsal(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc),
            approval_path=approval_path,
            lease_path=lease_path,
            journal_path=journal_path,
        )
        require(result["status"] == "PASSED_REHEARSAL_ONLY", "Renewal ceremony rehearsal passes")
        require(
            result["simulated_at_utc"] == "2026-09-05T14:00:00+00:00",
            "Active lease is never overlapped",
        )
        require(
            result["journal_event_count"] == 0
            and result["journal_head_sha256"] == "0" * 64,
            "Proposal binds the validated journal head",
        )
        require(
            result["approval_artifact_written"] is False
            and result["activation_lease_written"] is False
            and result["protected_artifacts_modified"] is False,
            "Rehearsal writes no activation artifact",
        )
        require(
            result["scheduler_changed"] is False
            and result["market_data_requested"] is False
            and result["evidence_appended"] is False,
            "Rehearsal performs no collection or scheduling",
        )
        require(
            result["paper_trading_only"] is True
            and result["live_trading_enabled"] is False
            and result["brokerage_orders"] is False,
            "Proposed renewal remains paper-only",
        )
        require(
            (approval_path.read_bytes(), lease_path.read_bytes()) == before
            and not journal_path.exists(),
            "Protected paths remain byte-for-byte unchanged",
        )
        try:
            build_rehearsal(
                operator="Different Operator",
                acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
                approval_path=approval_path,
                lease_path=lease_path,
                journal_path=journal_path,
            )
        except ValueError:
            require(True, "Different operator is rejected")
        else:
            raise AssertionError("Different operator is rejected")
        try:
            build_rehearsal(
                operator="Meraj Asari",
                acknowledgement="APPROVE",
                approval_path=approval_path,
                lease_path=lease_path,
                journal_path=journal_path,
            )
        except ValueError:
            require(True, "Non-exact acknowledgement is rejected")
        else:
            raise AssertionError("Non-exact acknowledgement is rejected")

    print("Status: PASSED")
    print("V13 renewal proposal: VERIFIED IN MEMORY")
    print("Approval artifact written: NO")
    print("Activation lease written: NO")
    print("Evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
