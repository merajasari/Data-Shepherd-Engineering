"""Regression tests for the non-applying V13 activation transition plan."""
from __future__ import annotations

import copy
import inspect
from datetime import datetime, timezone
from pathlib import Path

import ml.v13.regime_overlay_activation_transition as transition_module
from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    EXPECTED_APPROVAL_CONTRACT_SHA256,
    EXPECTED_CONTRACT_SHA256,
    PRODUCTION_JOURNAL_PATH,
    plan_transition,
)
from ml.v13.regime_overlay_manual_approval_regression import fixture_preflight


def require(value: object, label: str) -> None:
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def fixture_validated_approval() -> dict[str, object]:
    return {
        "status": "VALID_FOR_SEPARATE_ACTIVATION_STEP",
        "valid": True,
        "control_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "manual_approval_present": True,
        "activation_performed": False,
        "brokerage_orders": False,
    }


def main() -> None:
    protected = (APPROVAL_PATH, ACTIVATION_LEASE_PATH, PRODUCTION_JOURNAL_PATH)
    before = {path: snapshot(path) for path in protected}
    preflight = fixture_preflight()
    approval = fixture_validated_approval()

    before_boundary = plan_transition(
        preflight=preflight,
        approval=approval,
        now=datetime(2026, 8, 31, 23, tzinfo=timezone.utc),
    )
    require(
        before_boundary["status"] == "WAITING_FOR_BOUNDARY",
        "Pre-boundary transition waits",
    )
    ready = plan_transition(
        preflight=preflight,
        approval=approval,
        now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc),
    )
    require(ready["status"] == "ELIGIBLE_PLAN_ONLY", "All gates yield plan-only eligibility")
    require(ready["eligible"] is True, "Eligible state is descriptive only")
    require(
        ready["contract_sha256"] == EXPECTED_CONTRACT_SHA256,
        "Transition-plan identity is locked",
    )
    require(
        ready["planned_post_state"] == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY",
        "Planned destination remains paper only",
    )
    require(
        ready["application_implementation_present"] is False,
        "Apply implementation is absent",
    )
    require(ready["transition_applied"] is False, "Planner cannot apply transition")
    require(ready["manual_approval_written"] is False, "Planner cannot write approval")
    require(ready["activation_lease_written"] is False, "Planner cannot write lease")
    require(ready["v13_contract_modified"] is False, "Planner cannot modify V13 contract")
    require(
        ready["production_journal_modified"] is False,
        "Planner cannot modify production evidence",
    )
    require(ready["scheduler_changed"] is False, "Planner cannot change scheduler")
    require(ready["market_data_requested"] is False, "Planner makes no market request")
    require(ready["evidence_appended"] is False, "Planner appends no evidence")
    require(ready["brokerage_orders"] is False, "Planner has no brokerage authority")

    absent = copy.deepcopy(approval)
    absent.update({"status": "NOT_PRESENT", "valid": False})
    require(
        plan_transition(
            preflight=preflight,
            approval=absent,
            now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc),
        )["status"]
        == "WAITING_FOR_MANUAL_APPROVAL",
        "Missing manual approval waits without applying",
    )
    wrong_approval_contract = copy.deepcopy(approval)
    wrong_approval_contract["control_contract_sha256"] = "0" * 64
    require(
        plan_transition(
            preflight=preflight,
            approval=wrong_approval_contract,
            now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc),
        )["status"]
        == "WAITING_FOR_MANUAL_APPROVAL",
        "Wrong approval-contract identity fails closed",
    )
    journal_not_empty = copy.deepcopy(preflight)
    journal_not_empty["production_journal_events"] = 1
    require(
        plan_transition(
            preflight=journal_not_empty,
            approval=approval,
            now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc),
        )["status"]
        == "BLOCKED",
        "Preactivation journal content blocks transition",
    )
    activated = copy.deepcopy(preflight)
    activated["activation"] = "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
    require(
        plan_transition(
            preflight=activated,
            approval=approval,
            now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc),
        )["status"]
        == "BLOCKED",
        "Unexpected activation pre-state fails closed",
    )
    require(
        not hasattr(transition_module, "apply_transition"),
        "Transition apply capability is absent",
    )
    require(
        not hasattr(transition_module, "write_activation_lease"),
        "Activation lease writer is absent",
    )
    source = inspect.getsource(transition_module).lower()
    for forbidden in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(forbidden not in source, f"Brokerage SDK absent: {forbidden}")
    after = {path: snapshot(path) for path in protected}
    require(before == after, "Protected approval, lease and evidence paths remain unchanged")

    print("\nStatus: PASSED")
    print("V13 activation transition planner: VERIFIED NON-APPLYING")
    print("Transition apply capability: ABSENT")
    print("Activation lease writes: DISABLED")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
