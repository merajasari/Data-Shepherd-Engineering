"""Read-only presentation service for the preregistered V8 shadow bridge."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT_PATH=Path("ml/trading/paper_shadow_bridge_contract.json")


def get_paper_shadow_bridge_status()->dict[str,Any]:
    try:
        raw=CONTRACT_PATH.read_bytes()
        contract=json.loads(raw)
    except (OSError,json.JSONDecodeError):
        return {
            "status":"FAIL_CLOSED","contract_sha256":None,
            "alert":"Bridge contract is unavailable or malformed.",
            "brokerage_orders":False,"holdout_outcomes_read":False,
        }
    safe=(
        contract.get("status")=="PREREGISTERED_DISABLED"
        and contract.get("activation_mode")=="MANUAL_SEPARATE_APPROVAL"
        and contract.get("brokerage_orders") is False
        and contract.get("holdout_outcomes_read") is False
        and contract.get("production_holdout_journal_write") is False
    )
    return {
        "status":"PREREGISTERED_DISABLED" if safe else "FAIL_CLOSED",
        "contract_sha256":hashlib.sha256(raw).hexdigest(),
        "activation_mode":contract.get("activation_mode"),
        "activation_not_before_utc":contract.get("activation_not_before_utc"),
        "strategy_id":contract.get("source_strategy_id"),
        "frozen_sha256":contract.get("source_frozen_sha256"),
        "universe_size":contract.get("source_universe_size"),
        "selected_names":contract.get("selected_names"),
        "target_weight_each":contract.get("target_weight_each"),
        "execution_timing":contract.get("execution_timing"),
        "holding_sessions":contract.get("holding_sessions"),
        "modeled_cost_bps":contract.get("modeled_cost_bps"),
        "holdout_outcomes_read":False,
        "production_holdout_journal_write":False,
        "brokerage_orders":False,
        "alert":None if safe else "Bridge safety contract requires review.",
    }
