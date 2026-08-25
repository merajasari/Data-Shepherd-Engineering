"""Read-only presentation of the non-applying activation transition plan."""
from __future__ import annotations
from ml.trading.paper_shadow_activation_transition import current_plan


def get_paper_shadow_transition_status():
    try:
        result = current_plan()
    except (OSError, ValueError, RuntimeError, KeyError):
        result = {
            "status": "BLOCKED",
            "eligible": False,
            "gates_passed": 0,
            "gates_total": 9,
            "planned_pre_state": "PREREGISTERED_DISABLED",
            "planned_post_state": "PAPER_SHADOW_ACTIVE",
            "destination_mode": "PAPER_ONLY",
            "starting_capital_usd": "5000",
        }
    result.update({
        "application_implementation_present": False,
        "transition_applied": False,
        "bridge_contract_modified": False,
        "activation_lease_written": False,
        "paper_signal_export": False,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    })
    return result
