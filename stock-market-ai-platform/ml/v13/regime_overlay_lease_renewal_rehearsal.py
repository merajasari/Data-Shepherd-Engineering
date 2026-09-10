"""In-memory rehearsal of a future V13 paper-only lease renewal.

The rehearsal binds a proposed renewal to the exact prior lease and current
validated journal head. It creates no approval, lease, archive, scheduler,
market-data request, evidence event, or brokerage authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Mapping

from ml.v13.regime_overlay_activation import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    REQUIRED_ACKNOWLEDGEMENT,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    GENESIS_HASH,
    RegimeOverlayEvidenceJournal,
    canonical_sha256,
)
from ml.v13.regime_overlay_lease_renewal import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_RENEWAL_CONTRACT_SHA256,
    validate_renewal_readiness,
)


LEASE_HOURS = 24


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("V13_RENEWAL_REHEARSAL_TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def build_rehearsal(
    *,
    operator: str,
    acknowledgement: str,
    now_utc: datetime | None = None,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    simulate_at_expiry: bool = True,
) -> dict[str, object]:
    """Construct and validate a renewal proposal without persisting it."""
    if acknowledgement != REQUIRED_ACKNOWLEDGEMENT:
        raise ValueError("V13_EXACT_PAPER_ONLY_ACKNOWLEDGEMENT_REQUIRED")
    identity = operator.strip()
    if len(identity) < 3:
        raise ValueError("V13_EXPLICIT_OPERATOR_IDENTITY_REQUIRED")

    before = {
        "approval": _snapshot(approval_path),
        "lease": _snapshot(lease_path),
        "journal": _snapshot(journal_path),
    }
    current_approval = json.loads(approval_path.read_text(encoding="utf-8"))
    current_lease = json.loads(lease_path.read_text(encoding="utf-8"))
    if identity != str(current_approval.get("operator", "")).strip():
        raise ValueError("V13_RENEWAL_OPERATOR_MUST_MATCH_CURRENT_OPERATOR")

    requested = _utc(now_utc or datetime.now(timezone.utc))
    expires = _utc(datetime.fromisoformat(str(current_lease["expires_at_utc"])))
    evaluation_time = max(requested, expires) if simulate_at_expiry else requested
    readiness = validate_renewal_readiness(
        now_utc=evaluation_time,
        approval_path=approval_path,
        lease_path=lease_path,
        journal_path=journal_path,
    )
    if readiness.get("ready") is not True:
        raise RuntimeError(f"V13_RENEWAL_NOT_READY:{readiness.get('status')}")

    rows = RegimeOverlayEvidenceJournal(journal_path).read()
    journal_head = str(rows[-1]["record_sha256"]) if rows else GENESIS_HASH
    previous_lease_sha = canonical_sha256(current_lease)
    approval: dict[str, object] = {
        "approval_type": "V13_FRESH_PAPER_EVIDENCE_LEASE_RENEWAL",
        "approved_at_utc": evaluation_time.isoformat(),
        "operator": identity,
        "acknowledgement": acknowledgement,
        "previous_lease_sha256": previous_lease_sha,
        "journal_event_count": len(rows),
        "journal_head_sha256": journal_head,
        "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "rehearsal": True,
        "persisted": False,
    }
    lease: dict[str, object] = {
        "lease_type": "V13_FRESH_PAPER_EVIDENCE_RENEWAL",
        "issued_at_utc": evaluation_time.isoformat(),
        "expires_at_utc": (
            evaluation_time + timedelta(hours=LEASE_HOURS)
        ).isoformat(),
        "operator": identity,
        "approval_sha256": canonical_sha256(approval),
        "previous_lease_sha256": previous_lease_sha,
        "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "activation_state": "ENABLED_FRESH_EVIDENCE_PAPER_ONLY",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "scheduler_installed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "rehearsal": True,
        "persisted": False,
    }

    after = {
        "approval": _snapshot(approval_path),
        "lease": _snapshot(lease_path),
        "journal": _snapshot(journal_path),
    }
    if before != after:
        raise RuntimeError("V13_RENEWAL_REHEARSAL_MODIFIED_PROTECTED_PATH")
    return {
        "status": "PASSED_REHEARSAL_ONLY",
        "simulated_at_utc": evaluation_time.isoformat(),
        "prior_lease_sha256": previous_lease_sha,
        "journal_event_count": len(rows),
        "journal_head_sha256": journal_head,
        "proposed_approval_sha256": canonical_sha256(approval),
        "proposed_lease_sha256": canonical_sha256(lease),
        "proposed_lease_expires_at_utc": lease["expires_at_utc"],
        "approval_artifact_written": False,
        "activation_lease_written": False,
        "protected_artifacts_modified": False,
        "scheduler_changed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rehearse a V13 paper-only lease renewal without writes."
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--acknowledgement", required=True)
    args = parser.parse_args()
    result = build_rehearsal(
        operator=args.operator,
        acknowledgement=args.acknowledgement,
    )
    print("V13 LEASE RENEWAL CEREMONY — IN-MEMORY REHEARSAL")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(f"Simulated renewal time: {result['simulated_at_utc']}")
    print(f"Prior lease SHA-256: {result['prior_lease_sha256']}")
    print(f"Journal events bound: {result['journal_event_count']}")
    print(f"Journal head bound: {result['journal_head_sha256']}")
    print(f"Proposed lease SHA-256: {result['proposed_lease_sha256']}")
    print(f"Proposed lease expires: {result['proposed_lease_expires_at_utc']}")
    print("Approval artifact written: NO")
    print("Activation lease written: NO")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
