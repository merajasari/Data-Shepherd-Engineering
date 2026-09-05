"""Regression checks for the activation-aware V13 operational checkpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_operational_checkpoint import run_checkpoint
from ml.v13.regime_overlay_contract import EXPECTED_CONTRACT_SHA256


SOURCE = Path(__file__).with_name("regime_overlay_operational_checkpoint.py")
NOW = datetime(2026, 9, 5, 17, 40, tzinfo=timezone.utc)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def preflight(**_: object) -> dict[str, object]:
    return {
        "production_evidence_modified": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def lease(**_: object) -> dict[str, object]:
    return {
        "status": "ACTIVE_PAPER_ONLY",
        "valid": True,
        "activation": "ENABLED_FRESH_EVIDENCE_PAPER_ONLY",
        "operator": "Meraj Asari",
        "expires_at_utc": "2026-09-06T17:40:00+00:00",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "scheduler_installed": False,
        "market_data_requested": False,
        "evidence_appended": False,
    }


def expired_lease(**_: object) -> dict[str, object]:
    return {**lease(), "status": "NOT_ACTIVE", "valid": False}


def main() -> None:
    with TemporaryDirectory(prefix="v13_operational_checkpoint_regression_") as directory:
        root = Path(directory)
        journal = root / "evidence.jsonl"
        approval = root / "manual_approval.json"
        activation_lease = root / "lease.json"
        approval.write_text("approval", encoding="utf-8")
        activation_lease.write_text("lease", encoding="utf-8")
        before = {
            path: path.read_bytes()
            for path in (approval, activation_lease)
        }
        result = run_checkpoint(
            now_utc=NOW,
            journal_path=journal,
            approval_path=approval,
            lease_path=activation_lease,
            preflight_runner=preflight,
            lease_validator=lease,
        )
        require(result["status"] == "ACTIVE_PAPER_ONLY", "Active paper lease is reported accurately")
        require(result["activation"] == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY", "Effective activation state is exposed")
        require(result["approval_artifact_present"] and result["activation_lease_present"], "Existing activation artifacts are reported present")
        require(result["activation_lease_operator"] == "Meraj Asari", "Lease operator is preserved")
        require(result["journal_events"] == 0 and result["production_evidence_modified"] is False, "Production evidence remains untouched")
        require(
            before == {path: path.read_bytes() for path in (approval, activation_lease)},
            "Checkpoint leaves activation artifacts byte-for-byte unchanged",
        )

        expired = run_checkpoint(
            now_utc=NOW,
            journal_path=journal,
            approval_path=approval,
            lease_path=activation_lease,
            preflight_runner=preflight,
            lease_validator=expired_lease,
        )
        require(expired["status"] == "EXPIRED_OR_BLOCKED", "Expired lease fails closed")
        require(expired["activation"] == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT", "Expired lease cannot claim active authority")

    source = SOURCE.read_text(encoding="utf-8").lower()
    require(EXPECTED_CONTRACT_SHA256 not in source, "Checkpoint does not hard-code a replacement contract identity")
    for prohibited in (
        "commit_session_decision",
        "launchctl",
        "crontab",
        "import alpaca",
        "robin_stocks",
        "ib_insync",
    ):
        require(prohibited not in source, f"Checkpoint excludes {prohibited}")

    print("Status: PASSED")
    print("V13 activation-aware operational checkpoint: VERIFIED READ ONLY")
    print("Production evidence modified: NO")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
