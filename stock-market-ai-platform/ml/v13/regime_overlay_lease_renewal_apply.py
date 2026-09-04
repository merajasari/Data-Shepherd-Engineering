"""Apply immutable, paper-only V13 activation-lease renewals.

Renewals are numbered, hash-linked artifacts.  The original manual approval
and activation lease are never replaced.  This module does not install or
change a scheduler, request market data, append evidence, or grant brokerage
authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from ml.v13.regime_overlay_activation import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    ENABLED_ACTIVATION,
    LEASE_HOURS,
    REQUIRED_ACKNOWLEDGEMENT,
    validate_activation_lease,
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
)


DEFAULT_RENEWALS_PATH = ACTIVATION_LEASE_PATH.parent / "renewals"
APPLICATION_CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_lease_renewal_apply_contract.json"
)
APPLICATION_LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_lease_renewal_apply_contract.sha256"
)
EXPECTED_APPLICATION_CONTRACT_SHA256 = (
    "db3cfdade2600beb094454f8fce18ffc0eaf7ef28c16fec8be16324bdcd4d79c"
)


class V13LeaseRenewalRejected(RuntimeError):
    """Raised before a renewal is committed or when its chain is invalid."""


def _require_application_contract() -> None:
    expected: dict[str, object] = {
        "artifact_layout": "IMMUTABLE_NUMBERED_SHA_CHAIN",
        "artifact_overwrite_allowed": False,
        "brokerage_orders": False,
        "current_lease_must_be_expired": True,
        "evidence_append": False,
        "exact_operator_acknowledgement_required": True,
        "journal_head_binding_required": True,
        "live_trading_enabled": False,
        "market_data_request": False,
        "paper_trading_only": True,
        "previous_lease_sha256_binding_required": True,
        "renewal_application_implementation_present": True,
        "renewal_lease_hours": 24,
        "root_activation_artifact_modification_allowed": False,
        "same_operator_required": True,
        "scheduler_install_or_change": False,
        "status": "PREREGISTERED_FAIL_CLOSED_APPLICATION",
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    try:
        raw = APPLICATION_CONTRACT_PATH.read_bytes()
        contract = json.loads(raw)
        locked = APPLICATION_LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        raise V13LeaseRenewalRejected("V13_RENEWAL_APPLICATION_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_APPLICATION_CONTRACT_SHA256 or locked != digest:
        raise V13LeaseRenewalRejected("V13_RENEWAL_APPLICATION_CONTRACT_IDENTITY_CHANGED")
    if not isinstance(contract, dict) or any(contract.get(k) != v for k, v in expected.items()):
        raise V13LeaseRenewalRejected("V13_RENEWAL_APPLICATION_CONTRACT_CHANGED")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise V13LeaseRenewalRejected("V13_RENEWAL_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V13LeaseRenewalRejected(
            f"V13_RENEWAL_ARTIFACT_INVALID:{path.name}:{type(exc).__name__}"
        ) from exc
    if not isinstance(value, dict):
        raise V13LeaseRenewalRejected(f"V13_RENEWAL_ARTIFACT_NOT_OBJECT:{path.name}")
    return value


def _renewal_directories(path: Path) -> list[Path]:
    if not path.exists():
        return []
    entries = sorted(path.iterdir())
    if any(not item.is_dir() for item in entries):
        raise V13LeaseRenewalRejected("V13_RENEWAL_ROOT_CONTENT_INVALID")
    expected = [f"{number:06d}" for number in range(1, len(entries) + 1)]
    if [item.name for item in entries] != expected:
        raise V13LeaseRenewalRejected("V13_RENEWAL_SEQUENCE_INVALID")
    for item in entries:
        if {child.name for child in item.iterdir()} != {"approval.json", "lease.json"}:
            raise V13LeaseRenewalRejected("V13_RENEWAL_DIRECTORY_CONTENT_INVALID")
    return entries


def validate_renewal_chain(
    *,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    renewals_path: Path = DEFAULT_RENEWALS_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    """Validate the root activation and every immutable renewal artifact."""
    _require_application_contract()
    now = _utc(now_utc or datetime.now(timezone.utc))
    root_approval = _load_object(approval_path)
    root_lease = _load_object(lease_path)
    try:
        root_issued = _utc(datetime.fromisoformat(str(root_lease["issued_at_utc"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise V13LeaseRenewalRejected("V13_ROOT_LEASE_TIMESTAMP_INVALID") from exc
    root_validation = validate_activation_lease(
        approval_path=approval_path, lease_path=lease_path, now_utc=root_issued
    )
    if root_validation.get("valid") is not True:
        raise V13LeaseRenewalRejected("V13_ROOT_ACTIVATION_INVALID")

    operator = str(root_approval.get("operator", "")).strip()
    if len(operator) < 3 or root_approval.get("acknowledgement") != REQUIRED_ACKNOWLEDGEMENT:
        raise V13LeaseRenewalRejected("V13_ROOT_APPROVAL_INVALID")
    rows = RegimeOverlayEvidenceJournal(journal_path).read()
    previous_lease = root_lease
    previous_sha = canonical_sha256(previous_lease)
    previous_expiry = _utc(datetime.fromisoformat(str(previous_lease["expires_at_utc"])))
    directories = _renewal_directories(renewals_path)

    for sequence, directory in enumerate(directories, start=1):
        approval = _load_object(directory / "approval.json")
        lease = _load_object(directory / "lease.json")
        expected_approval: dict[str, object] = {
            "approval_type": "V13_FRESH_PAPER_EVIDENCE_LEASE_RENEWAL",
            "operator": operator,
            "acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
            "sequence": sequence,
            "previous_lease_sha256": previous_sha,
            "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
            "renewal_application_sha256": EXPECTED_APPLICATION_CONTRACT_SHA256,
            "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
            "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "rehearsal": False,
            "persisted": True,
        }
        for key, value in expected_approval.items():
            if approval.get(key) != value:
                raise V13LeaseRenewalRejected(f"V13_RENEWAL_APPROVAL_{key.upper()}_INVALID")
        count = approval.get("journal_event_count")
        head = approval.get("journal_head_sha256")
        if not isinstance(count, int) or count < 0 or count > len(rows):
            raise V13LeaseRenewalRejected("V13_RENEWAL_JOURNAL_COUNT_INVALID")
        expected_head = str(rows[count - 1]["record_sha256"]) if count else GENESIS_HASH
        if head != expected_head:
            raise V13LeaseRenewalRejected("V13_RENEWAL_JOURNAL_HEAD_INVALID")

        expected_lease: dict[str, object] = {
            "lease_type": "V13_FRESH_PAPER_EVIDENCE_RENEWAL",
            "operator": operator,
            "sequence": sequence,
            "approval_sha256": canonical_sha256(approval),
            "previous_lease_sha256": previous_sha,
            "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
            "renewal_application_sha256": EXPECTED_APPLICATION_CONTRACT_SHA256,
            "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
            "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
            "activation_state": ENABLED_ACTIVATION,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "scheduler_installed": False,
            "market_data_requested": False,
            "evidence_appended": False,
            "rehearsal": False,
            "persisted": True,
        }
        for key, value in expected_lease.items():
            if lease.get(key) != value:
                raise V13LeaseRenewalRejected(f"V13_RENEWAL_LEASE_{key.upper()}_INVALID")
        try:
            approved = _utc(datetime.fromisoformat(str(approval["approved_at_utc"])))
            issued = _utc(datetime.fromisoformat(str(lease["issued_at_utc"])))
            expires = _utc(datetime.fromisoformat(str(lease["expires_at_utc"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise V13LeaseRenewalRejected("V13_RENEWAL_TIMESTAMP_INVALID") from exc
        if approved != issued or issued < previous_expiry:
            raise V13LeaseRenewalRejected("V13_RENEWAL_OVERLAP_OR_APPROVAL_TIME_INVALID")
        if expires - issued != timedelta(hours=LEASE_HOURS):
            raise V13LeaseRenewalRejected("V13_RENEWAL_DURATION_INVALID")
        previous_lease = lease
        previous_sha = canonical_sha256(lease)
        previous_expiry = expires

    active = now < previous_expiry
    return {
        "status": "ACTIVE_PAPER_ONLY" if active else "EXPIRED_RENEWAL_READY",
        "valid": True,
        "active": active,
        "operator": operator,
        "renewal_count": len(directories),
        "latest_lease_sha256": previous_sha,
        "latest_lease_expires_at_utc": previous_expiry.isoformat(),
        "journal_event_count": len(rows),
        "journal_head_sha256": str(rows[-1]["record_sha256"]) if rows else GENESIS_HASH,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)


def renew(
    *,
    operator: str,
    acknowledgement: str,
    now_utc: datetime | None = None,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    renewals_path: Path = DEFAULT_RENEWALS_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, object]:
    """Commit one non-overlapping immutable renewal after exact approval."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    if acknowledgement != REQUIRED_ACKNOWLEDGEMENT:
        raise V13LeaseRenewalRejected("V13_EXACT_PAPER_ONLY_ACKNOWLEDGEMENT_REQUIRED")
    state = validate_renewal_chain(
        approval_path=approval_path,
        lease_path=lease_path,
        renewals_path=renewals_path,
        journal_path=journal_path,
        now_utc=now,
    )
    identity = operator.strip()
    if identity != state["operator"]:
        raise V13LeaseRenewalRejected("V13_RENEWAL_OPERATOR_MUST_MATCH_ROOT_OPERATOR")
    if state["active"] is True:
        raise V13LeaseRenewalRejected("V13_RENEWAL_OVERLAP_PROHIBITED")

    sequence = int(state["renewal_count"]) + 1
    approval: dict[str, object] = {
        "approval_type": "V13_FRESH_PAPER_EVIDENCE_LEASE_RENEWAL",
        "approved_at_utc": now.isoformat(),
        "operator": identity,
        "acknowledgement": acknowledgement,
        "sequence": sequence,
        "previous_lease_sha256": state["latest_lease_sha256"],
        "journal_event_count": state["journal_event_count"],
        "journal_head_sha256": state["journal_head_sha256"],
        "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
        "renewal_application_sha256": EXPECTED_APPLICATION_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "rehearsal": False,
        "persisted": True,
    }
    lease: dict[str, object] = {
        "lease_type": "V13_FRESH_PAPER_EVIDENCE_RENEWAL",
        "issued_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(hours=LEASE_HOURS)).isoformat(),
        "operator": identity,
        "sequence": sequence,
        "approval_sha256": canonical_sha256(approval),
        "previous_lease_sha256": state["latest_lease_sha256"],
        "renewal_control_sha256": EXPECTED_RENEWAL_CONTRACT_SHA256,
        "renewal_application_sha256": EXPECTED_APPLICATION_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "activation_state": ENABLED_ACTIVATION,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "scheduler_installed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "rehearsal": False,
        "persisted": True,
    }

    renewals_path.mkdir(parents=True, exist_ok=True)
    directory = renewals_path / f"{sequence:06d}"
    directory_created = False
    try:
        directory.mkdir(mode=0o700)
        directory_created = True
        _write_exclusive(directory / "approval.json", approval)
        _write_exclusive(directory / "lease.json", lease)
        validated = validate_renewal_chain(
            approval_path=approval_path,
            lease_path=lease_path,
            renewals_path=renewals_path,
            journal_path=journal_path,
            now_utc=now,
        )
    except Exception:
        if directory_created:
            for name in ("lease.json", "approval.json"):
                (directory / name).unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return {
        **validated,
        "status": "RENEWED_FRESH_EVIDENCE_PAPER_ONLY",
        "sequence": sequence,
        "approval_sha256": canonical_sha256(approval),
        "lease_sha256": canonical_sha256(lease),
        "approval_written": True,
        "lease_written": True,
        "root_artifacts_modified": False,
        "scheduler_changed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Renew V13 fresh paper evidence for 24 hours.")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    result = renew(operator=args.operator, acknowledgement=args.acknowledgement)
    print("V13 FRESH PAPER-EVIDENCE LEASE RENEWAL")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Renewal sequence: {result['sequence']:06d}")
    print(f"Lease expires: {result['latest_lease_expires_at_utc']}")
    print(f"Lease SHA-256: {result['lease_sha256']}")
    print("Original activation artifacts modified: NO")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
