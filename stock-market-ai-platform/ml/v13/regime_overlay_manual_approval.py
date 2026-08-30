"""Read-only validator for a future V13 manual approval artifact.

This module deliberately has no approval-artifact creator and no activation,
lease, scheduler, market-data, evidence, or brokerage write surface. A valid
result only permits a later, separately implemented transition step to be
considered.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_manual_approval_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_manual_approval_contract.sha256"
)
APPROVAL_PATH = ROOT / "data/research/v13/activation/manual_approval.json"
EXPECTED_CONTRACT_SHA256 = (
    "c90f80c33215986fe512d7db3b57832417129fb3aefd45b5efffb66c89fc4d6f"
)
EXPECTED_V13_CONTRACT_SHA256 = (
    "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702"
)
EXPECTED_V12_DISPOSITION_SHA256 = (
    "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2"
)
DISABLED_ACTIVATION = "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT"


def canonical_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return timestamp.astimezone(timezone.utc)


def _load_control_contract(
    *,
    contract_path: Path = CONTRACT_PATH,
    lock_path: Path = LOCK_PATH,
) -> tuple[dict[str, object], str, list[str]]:
    failures: list[str] = []
    try:
        raw = contract_path.read_bytes()
        contract = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, "", [f"CONTROL_CONTRACT_INVALID:{type(exc).__name__}"]
    digest = hashlib.sha256(raw).hexdigest()
    try:
        locked = lock_path.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, IndexError):
        locked = ""
    if digest != EXPECTED_CONTRACT_SHA256 or locked != EXPECTED_CONTRACT_SHA256:
        failures.append("CONTROL_CONTRACT_IDENTITY_CHANGED")
    expected = {
        "status": "PREREGISTERED_VALIDATION_ONLY",
        "activation_not_before_utc": "2026-09-01T14:00:00+00:00",
        "required_preflight_status": "READY_DISABLED",
        "required_v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "required_v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "required_activation_pre_state": DISABLED_ACTIVATION,
        "approval_artifact_creation_implementation_present": False,
        "validator_authority": "READ_ONLY",
        "fresh_evidence_activation": False,
        "activation_lease_write": False,
        "evidence_append": False,
        "scheduler_change": False,
        "v13_contract_write": False,
        "v12_disposition_write": False,
        "v10_holdout_outcomes_read": False,
        "v11_fresh_outcomes_read": False,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            failures.append(f"CONTROL_{key.upper()}_CHANGED")
    return contract, digest, failures


def verify_approval(
    approval: Mapping[str, object],
    preflight: Mapping[str, object],
    *,
    now: datetime | None = None,
    contract_path: Path = CONTRACT_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, object]:
    """Validate an already supplied artifact without creating or applying it."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract, contract_sha, failures = _load_control_contract(
        contract_path=contract_path,
        lock_path=lock_path,
    )

    def gate(name: str, condition: bool, detail: object) -> None:
        if not condition:
            failures.append(f"{name}:{detail}")

    boundary_text = contract.get(
        "activation_not_before_utc", "2026-09-01T14:00:00+00:00"
    )
    try:
        boundary = _parse_timestamp(boundary_text)
    except (TypeError, ValueError):
        boundary = datetime.max.replace(tzinfo=timezone.utc)
        failures.append("boundary:invalid")

    gate("boundary_reached", now >= boundary, boundary.isoformat())
    gate(
        "preflight_status",
        preflight.get("status") == contract.get("required_preflight_status"),
        preflight.get("status"),
    )
    gate(
        "preflight_contract_identity",
        preflight.get("contract_sha256") == EXPECTED_V13_CONTRACT_SHA256,
        preflight.get("contract_sha256"),
    )
    gate(
        "preflight_predecessor_identity",
        preflight.get("v12_disposition_sha256")
        == EXPECTED_V12_DISPOSITION_SHA256,
        preflight.get("v12_disposition_sha256"),
    )
    gate(
        "preflight_activation_disabled",
        preflight.get("activation") == DISABLED_ACTIVATION,
        preflight.get("activation"),
    )
    gate(
        "preactivation_journal_empty",
        preflight.get("production_journal_events") == 0,
        preflight.get("production_journal_events"),
    )
    gate(
        "preflight_read_only",
        preflight.get("production_evidence_modified") is False,
        preflight.get("production_evidence_modified"),
    )
    gate(
        "preflight_brokerage_off",
        preflight.get("brokerage_orders") is False,
        preflight.get("brokerage_orders"),
    )
    gate(
        "approval_preflight_binding",
        approval.get("preflight_sha256") == canonical_sha256(preflight),
        "approval must bind the exact canonical preflight",
    )
    gate(
        "approval_v13_identity",
        approval.get("v13_contract_sha256") == EXPECTED_V13_CONTRACT_SHA256,
        approval.get("v13_contract_sha256"),
    )
    gate(
        "approval_v12_identity",
        approval.get("v12_disposition_sha256")
        == EXPECTED_V12_DISPOSITION_SHA256,
        approval.get("v12_disposition_sha256"),
    )
    gate(
        "approval_type",
        approval.get("approval_type") == "V13_FRESH_EVIDENCE_PAPER_ONLY",
        approval.get("approval_type"),
    )
    gate(
        "acknowledgement",
        approval.get("acknowledgement")
        == contract.get("required_acknowledgement"),
        "exact phrase required",
    )
    gate(
        "operator",
        isinstance(approval.get("operator"), str)
        and len(str(approval.get("operator", "")).strip()) >= 3,
        "explicit operator identity required",
    )
    gate(
        "approval_paper_only",
        approval.get("paper_trading_only") is True,
        approval.get("paper_trading_only"),
    )
    gate(
        "approval_live_trading_off",
        approval.get("live_trading_enabled") is False,
        approval.get("live_trading_enabled"),
    )
    gate(
        "approval_brokerage_off",
        approval.get("brokerage_orders") is False,
        approval.get("brokerage_orders"),
    )

    try:
        approved_at = _parse_timestamp(approval.get("approved_at_utc"))
        gate("approval_after_boundary", approved_at >= boundary, approved_at.isoformat())
        gate("approval_not_future", approved_at <= now, approved_at.isoformat())
        validity = timedelta(hours=int(contract.get("approval_validity_hours", 0)))
        gate("approval_fresh", now - approved_at <= validity, approved_at.isoformat())
    except (TypeError, ValueError):
        failures.append("approval_timestamp:valid timezone-aware timestamp required")

    valid = not failures
    return {
        "status": "VALID_FOR_SEPARATE_ACTIVATION_STEP" if valid else "REJECTED",
        "valid": valid,
        "failures": failures,
        "control_contract_sha256": contract_sha,
        "manual_approval_present": True,
        "manual_approval_required": True,
        "approval_artifact_created": False,
        "activation_performed": False,
        "activation_lease_written": False,
        "evidence_appended": False,
        "scheduler_changed": False,
        "holdout_outcomes_read": False,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def get_manual_approval_status(
    *,
    approval_path: Path = APPROVAL_PATH,
    preflight: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return current status without creating an approval or changing state."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if preflight is None:
        from ml.v13.regime_overlay_preflight import run_preflight

        preflight = run_preflight()
    contract, contract_sha, failures = _load_control_contract()
    if failures:
        return {
            "status": "REJECTED",
            "valid": False,
            "failures": failures,
            "control_contract_sha256": contract_sha,
            "manual_approval_present": approval_path.exists(),
            "activation_performed": False,
            "brokerage_orders": False,
        }
    if not approval_path.exists():
        boundary = _parse_timestamp(contract["activation_not_before_utc"])
        return {
            "status": "WAITING_FOR_BOUNDARY" if now < boundary else "NOT_PRESENT",
            "valid": False,
            "failures": [],
            "control_contract_sha256": contract_sha,
            "manual_approval_present": False,
            "manual_approval_required": True,
            "approval_artifact_created": False,
            "activation_performed": False,
            "activation_lease_written": False,
            "evidence_appended": False,
            "scheduler_changed": False,
            "holdout_outcomes_read": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "v8_modified": False,
            "v10_modified": False,
            "v11_modified": False,
            "v12_modified": False,
        }
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "REJECTED",
            "valid": False,
            "failures": [f"approval_artifact:{type(exc).__name__}"],
            "control_contract_sha256": contract_sha,
            "manual_approval_present": True,
            "activation_performed": False,
            "brokerage_orders": False,
        }
    return verify_approval(approval, preflight, now=now)


def main() -> None:
    result = get_manual_approval_status()
    print("DATA SHEPHERD V13 MANUAL APPROVAL VALIDATOR")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(
        "Manual approval artifact: "
        f"{'PRESENT' if result.get('manual_approval_present') else 'ABSENT'}"
    )
    for failure in result.get("failures", []):
        print(f"[FAIL] {failure}")
    print("Validator authority: READ ONLY")
    print("Approval artifact created: NO")
    print("Activation performed: NO")
    print("Activation lease written: NO")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] == "REJECTED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
