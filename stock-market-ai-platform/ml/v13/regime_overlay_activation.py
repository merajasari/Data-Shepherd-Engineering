"""Apply the explicitly approved V13 fresh paper-evidence activation ceremony.

This module writes only the manual-approval artifact and a short-lived,
paper-only activation lease. It never installs a scheduler, requests market
data, appends evidence, imports a brokerage SDK, or modifies V8 through V12.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    EXPECTED_CONTRACT_SHA256 as EXPECTED_TRANSITION_CONTRACT_SHA256,
    plan_transition,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_V13_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
)
from ml.v13.regime_overlay_manual_approval import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_APPROVAL_CONTRACT_SHA256,
    canonical_sha256,
    verify_approval,
)


REQUIRED_ACKNOWLEDGEMENT = (
    "I APPROVE V13 FRESH PAPER EVIDENCE ONLY; NO LIVE BROKERAGE AUTHORITY"
)
ENABLED_ACTIVATION = "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
LEASE_HOURS = 24


class V13ActivationRejected(RuntimeError):
    """Raised before any activation artifact is committed."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise V13ActivationRejected("V13_ACTIVATION_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _write_staged(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = (
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    return staged


def _commit_pair(
    *,
    approval_path: Path,
    approval: Mapping[str, object],
    lease_path: Path,
    lease: Mapping[str, object],
) -> None:
    if approval_path.resolve() == lease_path.resolve():
        raise V13ActivationRejected("V13_APPROVAL_AND_LEASE_PATHS_MUST_DIFFER")
    if approval_path.exists() or lease_path.exists():
        raise V13ActivationRejected("V13_ACTIVATION_ARTIFACT_ALREADY_EXISTS")
    approval_stage: Path | None = None
    lease_stage: Path | None = None
    approval_committed = False
    try:
        approval_stage = _write_staged(approval_path, approval)
        lease_stage = _write_staged(lease_path, lease)
        if approval_path.exists() or lease_path.exists():
            raise V13ActivationRejected("V13_ACTIVATION_ARTIFACT_RACE")
        os.replace(approval_stage, approval_path)
        approval_stage = None
        approval_committed = True
        os.replace(lease_stage, lease_path)
        lease_stage = None
    except Exception:
        if approval_committed:
            approval_path.unlink(missing_ok=True)
        raise
    finally:
        if approval_stage is not None:
            approval_stage.unlink(missing_ok=True)
        if lease_stage is not None:
            lease_stage.unlink(missing_ok=True)


def build_approval(
    *,
    operator: str,
    acknowledgement: str,
    preflight: Mapping[str, object],
    approved_at_utc: datetime,
) -> dict[str, object]:
    identity = operator.strip()
    if len(identity) < 3:
        raise V13ActivationRejected("V13_EXPLICIT_OPERATOR_IDENTITY_REQUIRED")
    if acknowledgement != REQUIRED_ACKNOWLEDGEMENT:
        raise V13ActivationRejected("V13_EXACT_PAPER_ONLY_ACKNOWLEDGEMENT_REQUIRED")
    approved_at = _utc(approved_at_utc)
    return {
        "approval_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "approved_at_utc": approved_at.isoformat(),
        "operator": identity,
        "acknowledgement": acknowledgement,
        "preflight_sha256": canonical_sha256(preflight),
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "rehearsal": False,
        "persisted": True,
    }


def build_lease(
    *,
    approval: Mapping[str, object],
    issued_at_utc: datetime,
) -> dict[str, object]:
    issued_at = _utc(issued_at_utc)
    return {
        "lease_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "issued_at_utc": issued_at.isoformat(),
        "expires_at_utc": (issued_at + timedelta(hours=LEASE_HOURS)).isoformat(),
        "operator": approval["operator"],
        "approval_sha256": canonical_sha256(approval),
        "manual_approval_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "transition_contract_sha256": EXPECTED_TRANSITION_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
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


def validate_activation_lease(
    *,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    now = _utc(now_utc or datetime.now(timezone.utc))
    failures: list[str] = []
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "NOT_ACTIVE",
            "valid": False,
            "failures": [f"V13_ACTIVATION_ARTIFACT_INVALID:{type(exc).__name__}"],
            "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
    if not isinstance(approval, dict) or not isinstance(lease, dict):
        failures.append("V13_ACTIVATION_ARTIFACT_NOT_OBJECT")
    expected = {
        "lease_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "approval_sha256": canonical_sha256(approval),
        "manual_approval_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "transition_contract_sha256": EXPECTED_TRANSITION_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
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
    for key, value in expected.items():
        if lease.get(key) != value:
            failures.append(f"V13_ACTIVATION_LEASE_{key.upper()}_INVALID")
    if approval.get("operator") != lease.get("operator"):
        failures.append("V13_ACTIVATION_OPERATOR_BINDING_INVALID")
    if approval.get("acknowledgement") != REQUIRED_ACKNOWLEDGEMENT:
        failures.append("V13_ACTIVATION_ACKNOWLEDGEMENT_INVALID")
    if approval.get("rehearsal") is not False or approval.get("persisted") is not True:
        failures.append("V13_ACTIVATION_APPROVAL_MODE_INVALID")
    try:
        issued = _utc(datetime.fromisoformat(str(lease.get("issued_at_utc"))))
        expires = _utc(datetime.fromisoformat(str(lease.get("expires_at_utc"))))
        approved = _utc(datetime.fromisoformat(str(approval.get("approved_at_utc"))))
        if not (approved <= issued <= now < expires):
            failures.append("V13_ACTIVATION_LEASE_TIME_INVALID")
        if expires - issued != timedelta(hours=LEASE_HOURS):
            failures.append("V13_ACTIVATION_LEASE_DURATION_INVALID")
    except (TypeError, ValueError, V13ActivationRejected):
        failures.append("V13_ACTIVATION_TIMESTAMP_INVALID")
    valid = not failures
    return {
        "status": "ACTIVE_PAPER_ONLY" if valid else "NOT_ACTIVE",
        "valid": valid,
        "failures": failures,
        "activation": ENABLED_ACTIVATION if valid else "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "operator": lease.get("operator"),
        "issued_at_utc": lease.get("issued_at_utc"),
        "expires_at_utc": lease.get("expires_at_utc"),
        "approval_sha256": lease.get("approval_sha256"),
        "lease_sha256": canonical_sha256(lease),
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def activate(
    *,
    operator: str,
    acknowledgement: str,
    now_utc: datetime | None = None,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    preflight_runner: Callable[[], dict[str, object]] | None = None,
) -> dict[str, object]:
    now = _utc(now_utc or datetime.now(timezone.utc))
    if approval_path.exists() or lease_path.exists():
        raise V13ActivationRejected("V13_ACTIVATION_REQUIRES_ABSENT_ARTIFACTS")
    if preflight_runner is None:
        from ml.v13.regime_overlay_preflight import run_preflight
        preflight = run_preflight()
    else:
        preflight = preflight_runner()
    if preflight.get("status") != "READY_DISABLED":
        raise V13ActivationRejected(f"V13_PREFLIGHT_NOT_READY:{preflight.get('status')}")
    approval = build_approval(
        operator=operator,
        acknowledgement=acknowledgement,
        preflight=preflight,
        approved_at_utc=now,
    )
    approval_result = verify_approval(approval, preflight, now=now)
    if approval_result.get("valid") is not True:
        raise V13ActivationRejected(
            "V13_APPROVAL_REJECTED:" + ",".join(approval_result.get("failures", []))
        )
    transition = plan_transition(
        preflight=preflight,
        approval=approval_result,
        now=now,
    )
    if transition.get("eligible") is not True or transition.get("gates_passed") != 16:
        raise V13ActivationRejected(
            f"V13_TRANSITION_NOT_ELIGIBLE:{transition.get('status')}"
        )
    lease = build_lease(approval=approval, issued_at_utc=now)
    _commit_pair(
        approval_path=approval_path,
        approval=approval,
        lease_path=lease_path,
        lease=lease,
    )
    validated = validate_activation_lease(
        approval_path=approval_path,
        lease_path=lease_path,
        now_utc=now,
    )
    if validated.get("valid") is not True:
        lease_path.unlink(missing_ok=True)
        approval_path.unlink(missing_ok=True)
        raise V13ActivationRejected("V13_POST_WRITE_VALIDATION_FAILED")
    return {
        **validated,
        "status": "ACTIVATED_FRESH_EVIDENCE_PAPER_ONLY",
        "approval_written": True,
        "lease_written": True,
        "transition_gates_passed": 16,
        "transition_gates_total": 16,
        "scheduler_changed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "production_evidence_modified": False,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Activate V13 fresh paper evidence for one guarded 24-hour lease."
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Required explicit write switch.",
    )
    args = parser.parse_args()
    result = activate(
        operator=args.operator,
        acknowledgement=args.acknowledgement,
    )
    print("V13 FRESH PAPER-EVIDENCE ACTIVATION CEREMONY")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(f"Operator: {result['operator']}")
    print(f"Lease expires: {result['expires_at_utc']}")
    print(f"Lease SHA-256: {result['lease_sha256']}")
    print("Manual approval artifact written: YES")
    print("Activation lease written: YES")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Fresh evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
