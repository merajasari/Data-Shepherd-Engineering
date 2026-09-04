"""Regression checks for read-only V13 lease-renewal readiness."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import (
    REQUIRED_ACKNOWLEDGEMENT,
    activate,
)
from ml.v13.regime_overlay_lease_renewal import (
    EXPECTED_CONTRACT_SHA256,
    validate_renewal_readiness,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    production_preflight = {
        "status": "READY_DISABLED",
        "contract_sha256": "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702",
        "v12_disposition_sha256": "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2",
        "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "production_journal_events": 0,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
    }
    with TemporaryDirectory(prefix="v13_renewal_readiness_") as raw:
        root = Path(raw)
        approval_path = root / "approval.json"
        lease_path = root / "lease.json"
        journal_path = root / "evidence.jsonl"
        issued = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
        activate(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=issued,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=lambda: production_preflight,
        )
        before = (approval_path.read_bytes(), lease_path.read_bytes())
        active = validate_renewal_readiness(
            now_utc=datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc),
            approval_path=approval_path,
            lease_path=lease_path,
            journal_path=journal_path,
        )
        require(
            active["status"] == "CURRENT_LEASE_STILL_ACTIVE"
            and active["ready"] is False,
            "Overlapping lease renewal is rejected",
        )
        expired = validate_renewal_readiness(
            now_utc=datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc),
            approval_path=approval_path,
            lease_path=lease_path,
            journal_path=journal_path,
        )
        require(
            expired["status"] == "READY_FOR_EXPLICIT_RENEWAL"
            and expired["ready"] is True,
            "Expired structurally valid lease becomes renewal-ready",
        )
        require(
            expired["contract_sha256"] == EXPECTED_CONTRACT_SHA256,
            "Renewal-control contract identity is locked",
        )
        require(
            expired["journal_events"] == 0
            and expired["existing_evidence_allowed"] is True,
            "Validated existing journal is preserved across renewal",
        )
        require(
            expired["artifacts_modified"] is False
            and expired["scheduler_changed"] is False
            and expired["market_data_requested"] is False
            and expired["evidence_appended"] is False,
            "Readiness validation performs no writes or collection",
        )
        require(
            expired["live_trading_enabled"] is False
            and expired["brokerage_orders"] is False,
            "Renewal readiness has no live trading authority",
        )
        require(
            (approval_path.read_bytes(), lease_path.read_bytes()) == before,
            "Existing activation artifacts remain byte-for-byte unchanged",
        )
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        lease["operator"] = "tampered"
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        tampered = validate_renewal_readiness(
            now_utc=datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc),
            approval_path=approval_path,
            lease_path=lease_path,
            journal_path=journal_path,
        )
        require(
            tampered["status"] == "BLOCKED_FAIL_CLOSED",
            "Tampered prior lease blocks renewal",
        )

    print("Status: PASSED")
    print("V13 lease renewal readiness: VERIFIED READ ONLY")
    print("Renewal implementation present: NO")
    print("Activation artifacts modified: NO")
    print("Evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
