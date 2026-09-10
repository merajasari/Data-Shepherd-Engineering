"""Pure, non-applying V13 fresh-evidence activation transition planner.

The planner evaluates the already locked prerequisites and describes a future
paper-only transition. This version cannot create an approval, write a lease,
change a scheduler, append evidence, modify the V13 contract, or place orders.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ml.v13.regime_overlay_manual_approval import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_APPROVAL_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    EXPECTED_V13_CONTRACT_SHA256,
    get_manual_approval_status,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_activation_transition_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_activation_transition_contract.sha256"
)
APPROVAL_PATH = ROOT / "data/research/v13/activation/manual_approval.json"
ACTIVATION_LEASE_PATH = ROOT / "data/research/v13/activation/lease.json"
PRODUCTION_JOURNAL_PATH = (
    ROOT / "data/research/v13/fresh_regime_overlay/evidence.jsonl"
)
EXPECTED_CONTRACT_SHA256 = (
    "4df4dca1db55afd1272a27c5f6f7826d3178d201eba2548d4a0d4fab822389ab"
)
DISABLED_ACTIVATION = "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT"


def _parse_timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return timestamp.astimezone(timezone.utc)


def _load_transition_contract(
    *,
    contract_path: Path = CONTRACT_PATH,
    lock_path: Path = LOCK_PATH,
) -> tuple[dict[str, object], str, list[str]]:
    failures: list[str] = []
    try:
        raw = contract_path.read_bytes()
        contract = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, "", [f"TRANSITION_CONTRACT_INVALID:{type(exc).__name__}"]
    digest = hashlib.sha256(raw).hexdigest()
    try:
        locked = lock_path.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, IndexError):
        locked = ""
    if digest != EXPECTED_CONTRACT_SHA256 or locked != EXPECTED_CONTRACT_SHA256:
        failures.append("TRANSITION_CONTRACT_IDENTITY_CHANGED")
    expected = {
        "status": "PREREGISTERED_PLAN_ONLY",
        "activation_not_before_utc": "2026-09-01T14:00:00+00:00",
        "required_preflight_status": "READY_DISABLED",
        "required_approval_status": "VALID_FOR_SEPARATE_ACTIVATION_STEP",
        "required_manual_approval_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "required_v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "required_v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "required_activation_pre_state": DISABLED_ACTIVATION,
        "planned_activation_post_state": "ENABLED_FRESH_EVIDENCE_PAPER_ONLY",
        "destination_mode": "PAPER_ONLY",
        "application_implementation_present": False,
        "manual_approval_write": False,
        "activation_lease_write": False,
        "v13_contract_write": False,
        "production_journal_write": False,
        "scheduler_install_or_change": False,
        "market_data_request": False,
        "evidence_append": False,
        "v10_holdout_outcomes_read": False,
        "v11_fresh_outcomes_read": False,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            failures.append(f"TRANSITION_{key.upper()}_CHANGED")
    return contract, digest, failures


def plan_transition(
    *,
    preflight: Mapping[str, object],
    approval: Mapping[str, object],
    now: datetime | None = None,
    contract_path: Path = CONTRACT_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, object]:
    """Build an in-memory plan. No branch in this function applies it."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract, contract_sha, contract_failures = _load_transition_contract(
        contract_path=contract_path,
        lock_path=lock_path,
    )
    try:
        boundary = _parse_timestamp(
            contract.get("activation_not_before_utc", "invalid")
        )
    except (TypeError, ValueError):
        boundary = datetime.max.replace(tzinfo=timezone.utc)
        contract_failures.append("TRANSITION_BOUNDARY_INVALID")

    gates = [
        ("transition_contract_locked", not contract_failures),
        ("boundary_reached", now >= boundary),
        (
            "preflight_ready_disabled",
            preflight.get("status") == contract.get("required_preflight_status"),
        ),
        (
            "v13_contract_identity",
            preflight.get("contract_sha256") == EXPECTED_V13_CONTRACT_SHA256,
        ),
        (
            "v12_disposition_identity",
            preflight.get("v12_disposition_sha256")
            == EXPECTED_V12_DISPOSITION_SHA256,
        ),
        (
            "activation_pre_state",
            preflight.get("activation") == DISABLED_ACTIVATION,
        ),
        (
            "preactivation_journal_empty",
            preflight.get("production_journal_events") == 0,
        ),
        (
            "preflight_read_only",
            preflight.get("production_evidence_modified") is False,
        ),
        (
            "preflight_paper_only",
            preflight.get("paper_trading_only") is True,
        ),
        (
            "preflight_brokerage_off",
            preflight.get("brokerage_orders") is False,
        ),
        (
            "manual_approval_valid",
            approval.get("status") == contract.get("required_approval_status")
            and approval.get("valid") is True,
        ),
        (
            "manual_approval_contract_identity",
            approval.get("control_contract_sha256")
            == EXPECTED_APPROVAL_CONTRACT_SHA256,
        ),
        (
            "manual_approval_non_applying",
            approval.get("activation_performed") is False,
        ),
        (
            "destination_paper_only",
            contract.get("destination_mode") == "PAPER_ONLY",
        ),
        (
            "application_implementation_absent",
            contract.get("application_implementation_present") is False,
        ),
        (
            "all_write_capabilities_absent",
            all(
                contract.get(key) is False
                for key in (
                    "manual_approval_write",
                    "activation_lease_write",
                    "v13_contract_write",
                    "production_journal_write",
                    "scheduler_install_or_change",
                    "evidence_append",
                )
            ),
        ),
    ]
    gate_map = dict(gates)
    structural_names = {
        "transition_contract_locked",
        "preflight_ready_disabled",
        "v13_contract_identity",
        "v12_disposition_identity",
        "activation_pre_state",
        "preactivation_journal_empty",
        "preflight_read_only",
        "preflight_paper_only",
        "preflight_brokerage_off",
        "destination_paper_only",
        "application_implementation_absent",
        "all_write_capabilities_absent",
    }
    structural_ready = all(gate_map[name] for name in structural_names)
    approval_ready = (
        gate_map["manual_approval_valid"]
        and gate_map["manual_approval_contract_identity"]
        and gate_map["manual_approval_non_applying"]
    )
    eligible = structural_ready and now >= boundary and approval_ready
    if eligible:
        status = "ELIGIBLE_PLAN_ONLY"
    elif not structural_ready:
        status = "BLOCKED"
    elif now < boundary:
        status = "WAITING_FOR_BOUNDARY"
    elif not approval_ready:
        status = "WAITING_FOR_MANUAL_APPROVAL"
    else:
        status = "BLOCKED"
    return {
        "status": status,
        "eligible": eligible,
        "contract_sha256": contract_sha,
        "contract_failures": contract_failures,
        "gates": [
            {"gate": name, "passed": bool(passed)} for name, passed in gates
        ],
        "gates_passed": sum(bool(passed) for _, passed in gates),
        "gates_total": len(gates),
        "planned_pre_state": contract.get("required_activation_pre_state"),
        "planned_post_state": contract.get("planned_activation_post_state"),
        "destination_mode": "PAPER_ONLY",
        "application_implementation_present": False,
        "transition_applied": False,
        "manual_approval_written": False,
        "activation_lease_written": False,
        "v13_contract_modified": False,
        "production_journal_modified": False,
        "scheduler_changed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "holdout_outcomes_read": False,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def current_plan(*, now: datetime | None = None) -> dict[str, object]:
    """Read current prerequisites and return a non-applying plan."""
    from ml.v13.regime_overlay_preflight import run_preflight

    preflight = run_preflight()
    approval = get_manual_approval_status(preflight=preflight, now=now)
    return plan_transition(preflight=preflight, approval=approval, now=now)


def main() -> None:
    result = current_plan()
    print("DATA SHEPHERD V13 ACTIVATION TRANSITION PLAN")
    print("=" * 84)
    for gate in result["gates"]:
        marker = "PASS" if gate["passed"] else "WAIT"
        print(f"[{marker}] {gate['gate']}")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(f"Planned post-state: {result['planned_post_state']}")
    print("Apply implementation present: NO")
    print("Transition applied: NO")
    print("Manual approval written: NO")
    print("Activation lease written: NO")
    print("V13 contract modified: NO")
    print("Production evidence modified: NO")
    print("Scheduler changed: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] == "BLOCKED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
