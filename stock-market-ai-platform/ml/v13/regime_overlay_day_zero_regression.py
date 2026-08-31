"""Regression coverage for the read-only V13 day-zero checkpoint."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
)
from ml.v13.regime_overlay_day_zero import run_checkpoint


def require(condition: object, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def fixture_preflight(**_kwargs: object) -> dict[str, object]:
    return {
        "status": "READY_DISABLED",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "fresh_evidence_boundary_utc": "2026-09-01T14:00:00+00:00",
        "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "production_journal_events": 0,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="v13_day_zero_") as directory:
        root = Path(directory)
        journal_path = root / "evidence.jsonl"
        approval_path = root / "manual_approval.json"
        lease_path = root / "lease.json"
        before = {
            path: (path.exists(), path.read_bytes() if path.exists() else None)
            for path in (journal_path, approval_path, lease_path)
        }

        ready = run_checkpoint(
            now_utc=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=fixture_preflight,
        )
        require(
            ready["status"] == "READY_FOR_2026_09_01_MANUAL_APPROVAL",
            "Complete pre-boundary checkpoint is ready",
        )
        require(
            all(row["passed"] for row in ready["checks"]),
            "Every pre-boundary readiness check passes",
        )
        require(ready["journal_events"] == 0, "Production journal is empty")
        require(
            ready["manual_approval_present"] is False,
            "Manual approval artifact remains absent",
        )
        require(
            ready["activation_lease_present"] is False,
            "Activation lease remains absent",
        )
        require(
            ready["activation"] == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
            "V13 activation remains disabled",
        )
        require(
            ready["production_evidence_modified"] is False
            and ready["approval_artifact_modified"] is False
            and ready["activation_lease_modified"] is False,
            "Checkpoint performs no protected writes",
        )
        require(
            ready["paper_trading_only"] is True
            and ready["live_trading_enabled"] is False
            and ready["brokerage_orders"] is False,
            "Paper-only authority remains enforced",
        )
        require(
            all(
                ready[field] is False
                for field in (
                    "v8_modified",
                    "v10_modified",
                    "v11_modified",
                    "v12_modified",
                )
            ),
            "V8, V10, V11 and V12 remain isolated",
        )

        after = {
            path: (path.exists(), path.read_bytes() if path.exists() else None)
            for path in (journal_path, approval_path, lease_path)
        }
        require(before == after, "Protected paths are byte-for-byte unchanged")

        boundary_ready = run_checkpoint(
            now_utc=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=fixture_preflight,
        )
        require(
            boundary_ready["status"] == "READY_FOR_MANUAL_APPROVAL",
            "Post-boundary absent approval becomes ready for ceremony",
        )
        require(
            all(row["passed"] for row in boundary_ready["checks"]),
            "Post-boundary readiness remains fully gated",
        )

        def failed_preflight(**_kwargs: object) -> dict[str, object]:
            payload = fixture_preflight()
            payload["status"] = "FAILED"
            return payload

        failed = run_checkpoint(
            now_utc=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=failed_preflight,
        )
        require(failed["status"] == "FAILED", "Failed preflight blocks readiness")
        require(
            failed["brokerage_orders"] is False,
            "Readiness failure cannot grant brokerage authority",
        )

        journal_path.write_text("{invalid\n", encoding="utf-8")
        journal_before = journal_path.read_bytes()
        corrupt = run_checkpoint(
            now_utc=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=fixture_preflight,
        )
        require(corrupt["status"] == "FAILED", "Corrupt journal fails readiness")
        require(
            journal_path.read_bytes() == journal_before,
            "Corrupt journal is never rewritten",
        )
        journal_path.unlink()

        approval_path.write_text(json.dumps({"invalid": True}) + "\n", encoding="utf-8")
        approval_before = approval_path.read_bytes()
        premature = run_checkpoint(
            now_utc=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=fixture_preflight,
        )
        require(
            premature["status"] == "FAILED",
            "Pre-boundary approval artifact fails readiness",
        )
        require(
            approval_path.read_bytes() == approval_before,
            "Unexpected approval artifact is never rewritten",
        )
        approval_path.unlink()

        lease_path.write_text(json.dumps({"invalid": True}) + "\n", encoding="utf-8")
        lease_before = lease_path.read_bytes()
        leased = run_checkpoint(
            now_utc=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=fixture_preflight,
        )
        require(
            leased["status"] == "FAILED",
            "Preactivation lease fails readiness",
        )
        require(
            lease_path.read_bytes() == lease_before,
            "Unexpected lease is never rewritten",
        )

    print("Status: PASSED")
    print("V13 day-zero readiness: VERIFIED")
    print("Manual approval artifact: ABSENT")
    print("Activation lease: ABSENT")
    print("Fresh evidence activation: DISABLED")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
