"""Read-only readiness validator for a future V13 lease renewal.

This module never creates, archives, replaces, or deletes activation artifacts.
It validates that a prior 24-hour paper-only lease is structurally authentic,
has expired, and that any existing V13 evidence journal remains hash-chain
valid before a separately authorized renewal ceremony may be considered.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ml.v13.regime_overlay_activation import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    REQUIRED_ACKNOWLEDGEMENT,
    validate_activation_lease,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    RegimeOverlayEvidenceJournal,
    V13EvidenceJournalCorrupt,
    canonical_sha256,
)


CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_lease_renewal_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_lease_renewal_contract.sha256"
)
EXPECTED_CONTRACT_SHA256 = (
    "2445260818b4c18f999e5cd72f7042f6c3da7999461cc545c037b6fc524e7d0b"
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("V13_RENEWAL_NOW_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _load_contract() -> tuple[dict[str, object], str, list[str]]:
    failures: list[str] = []
    try:
        raw = CONTRACT_PATH.read_bytes()
        contract = json.loads(raw)
        locked = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        return {}, "", [f"RENEWAL_CONTRACT_INVALID:{type(exc).__name__}"]
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_CONTRACT_SHA256 or locked != EXPECTED_CONTRACT_SHA256:
        failures.append("RENEWAL_CONTRACT_IDENTITY_CHANGED")
    expected = {
        "status": "PREREGISTERED_VALIDATION_ONLY",
        "required_acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
        "renewal_lease_hours": 24,
        "current_lease_must_be_expired": True,
        "current_lease_must_validate_structurally": True,
        "previous_lease_sha256_binding_required": True,
        "same_operator_required": True,
        "validated_existing_evidence_allowed": True,
        "journal_hash_chain_must_validate": True,
        "artifact_archive_required_before_replacement": True,
        "artifact_overwrite_allowed": False,
        "renewal_implementation_present": False,
        "scheduler_install_or_change": False,
        "market_data_request": False,
        "evidence_append": False,
        "holdout_outcomes_read": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            failures.append(f"RENEWAL_{key.upper()}_CHANGED")
    return contract, digest, failures


def validate_renewal_readiness(
    *,
    now_utc: datetime | None = None,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, object]:
    """Return renewal readiness without mutating any supplied path."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    contract, contract_sha, failures = _load_contract()
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        approval, lease = {}, {}
        failures.append(f"CURRENT_ACTIVATION_ARTIFACT_INVALID:{type(exc).__name__}")

    issued: datetime | None = None
    expires: datetime | None = None
    if lease:
        try:
            issued = _utc(datetime.fromisoformat(str(lease["issued_at_utc"])))
            expires = _utc(datetime.fromisoformat(str(lease["expires_at_utc"])))
            structural = validate_activation_lease(
                approval_path=approval_path,
                lease_path=lease_path,
                now_utc=issued,
            )
            if structural.get("valid") is not True:
                failures.extend(
                    f"CURRENT_{item}" for item in structural.get("failures", [])
                )
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"CURRENT_LEASE_TIMESTAMP_INVALID:{type(exc).__name__}")

    journal_events: int | None = None
    try:
        journal_events = len(RegimeOverlayEvidenceJournal(journal_path).read())
    except V13EvidenceJournalCorrupt as exc:
        failures.append(f"CURRENT_EVIDENCE_JOURNAL_INVALID:{exc}")

    expired = expires is not None and now >= expires
    operator = approval.get("operator") if isinstance(approval, dict) else None
    if not isinstance(operator, str) or len(operator.strip()) < 3:
        failures.append("CURRENT_OPERATOR_IDENTITY_INVALID")
    if approval.get("acknowledgement") != REQUIRED_ACKNOWLEDGEMENT:
        failures.append("CURRENT_ACKNOWLEDGEMENT_INVALID")

    ready = not failures and expired
    status = (
        "READY_FOR_EXPLICIT_RENEWAL"
        if ready
        else "CURRENT_LEASE_STILL_ACTIVE"
        if not failures and not expired
        else "BLOCKED_FAIL_CLOSED"
    )
    return {
        "status": status,
        "ready": ready,
        "failures": failures,
        "contract_sha256": contract_sha,
        "previous_lease_sha256": canonical_sha256(lease) if lease else None,
        "operator": operator,
        "lease_expires_at_utc": expires.isoformat() if expires else None,
        "journal_events": journal_events,
        "existing_evidence_allowed": contract.get(
            "validated_existing_evidence_allowed"
        ) is True,
        "renewal_implementation_present": False,
        "artifacts_modified": False,
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
    result = validate_renewal_readiness()
    print("V13 PAPER-ONLY LEASE RENEWAL READINESS")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Lease expires: {result['lease_expires_at_utc']}")
    print(f"Journal events: {result['journal_events']}")
    print("Renewal implementation present: NO")
    print("Activation artifacts modified: NO")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    for failure in result["failures"]:
        print(f"[FAIL] {failure}")
    if result["status"] == "BLOCKED_FAIL_CLOSED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
