"""Pure, non-applying paper-shadow activation transition planner."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "ml/trading/paper_shadow_activation_transition_contract.json"
LOCK_PATH = ROOT / "ml/trading/paper_shadow_activation_transition_contract.sha256"
AUDIT_PATH = ROOT / "data/trading/readiness/paper_shadow_activation_audit.json"
EXPECTED_CONTRACT_SHA = "16c626c9d0abba309a167d7d0b24714da4fb76ab724826c7e6cc308ab6de707f"
BOUNDARY = datetime(2026, 9, 1, tzinfo=timezone.utc)


def plan_transition(*, audit: dict, approval: dict, runtime_locked: bool,
                    bridge_status: str, paper_account: dict, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    raw = CONTRACT_PATH.read_bytes()
    contract = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    lock = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    gates = [
        ("contract_locked", digest == lock == EXPECTED_CONTRACT_SHA),
        ("boundary_reached", now >= BOUNDARY),
        ("audit_ready", audit.get("status") == contract["required_audit_status"]),
        ("approval_valid", approval.get("status") == contract["required_approval_status"]
         and approval.get("valid") is True),
        ("runtime_locked", runtime_locked is True),
        ("bridge_disabled", bridge_status == contract["required_bridge_pre_state"]),
        ("paper_account_reconciled", paper_account.get("status") in {"EMPTY_READY", "HEALTHY"}
         and paper_account.get("reconciled") is True),
        ("paper_mode_only", contract.get("destination_mode") == "PAPER_ONLY"),
        ("no_application_implementation", contract.get("application_implementation_present") is False),
    ]
    eligible = all(value for _, value in gates)
    return {
        "status": "ELIGIBLE_PLAN_ONLY" if eligible else (
            "WAITING_FOR_BOUNDARY" if now < BOUNDARY and
            all(value for name, value in gates if name != "boundary_reached")
            else "BLOCKED"
        ),
        "eligible": eligible,
        "contract_sha256": digest,
        "gates": [{"gate": name, "passed": bool(value)} for name, value in gates],
        "gates_passed": sum(bool(value) for _, value in gates),
        "gates_total": len(gates),
        "planned_pre_state": contract["required_bridge_pre_state"],
        "planned_post_state": contract["planned_bridge_post_state"],
        "destination_mode": "PAPER_ONLY",
        "starting_capital_usd": contract["starting_capital_usd"],
        "application_implementation_present": False,
        "transition_applied": False,
        "bridge_contract_modified": False,
        "activation_lease_written": False,
        "paper_signal_export": False,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }


def current_plan() -> dict:
    try:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        audit = {}
    from webapp.services.paper_shadow_manual_approval_service import get_manual_approval_status
    from webapp.services.paper_shadow_scheduler_service import get_paper_shadow_scheduler_status
    from webapp.services.paper_shadow_service import get_paper_shadow_status
    from ml.trading.paper_shadow_operational_change_control import verify
    approval = get_manual_approval_status()
    monitor = get_paper_shadow_scheduler_status()
    account = get_paper_shadow_status()
    _, _, failures = verify()
    return plan_transition(
        audit=audit, approval=approval, runtime_locked=not failures,
        bridge_status=monitor.get("bridge_status"), paper_account=account,
    )


def main() -> None:
    result = current_plan()
    print("DATA SHEPHERD PAPER-SHADOW ACTIVATION TRANSITION PLAN")
    print("=" * 80)
    for gate in result["gates"]:
        print(f"[{'PASS' if gate['passed'] else 'WAIT'}] {gate['gate']}")
    print(f"\nStatus: {result['status']}")
    print("Implementation present: NO")
    print("Transition applied: NO")
    print("Bridge contract modified: NO")
    print("Activation lease written: NO")
    print("Paper signal export: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
