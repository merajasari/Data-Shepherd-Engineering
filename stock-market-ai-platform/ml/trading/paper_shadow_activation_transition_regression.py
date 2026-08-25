"""Regression tests for the non-applying activation transition plan."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
from ml.trading.paper_shadow_activation_transition import plan_transition


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def fixtures():
    audit = {"status": "READY_FOR_MANUAL_APPROVAL"}
    approval = {"status": "VALID_FOR_SEPARATE_ACTIVATION_STEP", "valid": True}
    account = {"status": "EMPTY_READY", "reconciled": True}
    return audit, approval, account


def main():
    audit, approval, account = fixtures()
    before = plan_transition(
        audit=audit, approval=approval, runtime_locked=True,
        bridge_status="PREREGISTERED_DISABLED", paper_account=account,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    require(before["status"] == "WAITING_FOR_BOUNDARY", "Pre-boundary plan waits")
    ready = plan_transition(
        audit=audit, approval=approval, runtime_locked=True,
        bridge_status="PREREGISTERED_DISABLED", paper_account=account,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    require(ready["status"] == "ELIGIBLE_PLAN_ONLY", "All gates produce plan-only eligibility")
    require(ready["application_implementation_present"] is False,
            "No activation application implementation exists")
    require(ready["transition_applied"] is False, "Planner cannot apply transition")
    require(ready["bridge_contract_modified"] is False, "Planner cannot modify bridge contract")
    require(ready["activation_lease_written"] is False, "Planner cannot write activation lease")
    require(ready["paper_signal_export"] is False, "Planner cannot export signals")
    require(ready["brokerage_orders"] is False, "Planner has no brokerage authority")

    bad = copy.deepcopy(approval)
    bad["valid"] = False
    require(plan_transition(
        audit=audit, approval=bad, runtime_locked=True,
        bridge_status="PREREGISTERED_DISABLED", paper_account=account,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )["status"] == "BLOCKED", "Invalid approval fails closed")
    require(plan_transition(
        audit=audit, approval=approval, runtime_locked=False,
        bridge_status="PREREGISTERED_DISABLED", paper_account=account,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )["status"] == "BLOCKED", "Unlocked runtime fails closed")
    require(plan_transition(
        audit=audit, approval=approval, runtime_locked=True,
        bridge_status="ACTIVE", paper_account=account,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )["status"] == "BLOCKED", "Unexpected bridge state fails closed")
    print("\nStatus: PASSED")
    print("Transition planner: VERIFIED NON-APPLYING")
    print("Activation authority: NONE")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
