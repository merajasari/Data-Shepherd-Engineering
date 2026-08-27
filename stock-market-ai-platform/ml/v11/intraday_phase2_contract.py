"""Validation and identity for the preregistered V11 Phase 2 contract.

This module grants no execution authority. It validates a fixed, fresh-data
confirmation specification and computes its tamper-evident SHA-256 identity.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

CONTRACT_PATH = Path(__file__).with_name("intraday_phase2_contract.json")
FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "vwap_distance",
    "volume_acceleration",
    "realized_volatility_30m",
    "opening_gap",
)
EXPECTED_CONFIG_ID = "MOMENTUM_BALANCED_6"
EXPECTED_WEIGHTS = {
    "return_5m": 1.0,
    "return_15m": 1.0,
    "vwap_distance": 1.0,
    "volume_acceleration": 1.0,
    "realized_volatility_30m": -0.25,
    "opening_gap": 1.0,
}


def contract_sha256(contract: Mapping[str, object]) -> str:
    encoded = json.dumps(
        contract, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_contract(contract: Mapping[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    if contract.get("status") != "PREREGISTERED_FRESH_CONFIRMATION":
        reasons.append("STATUS_INVALID")
    try:
        boundary = datetime.fromisoformat(
            str(contract["fresh_confirmation_start_utc"])
        )
        if boundary.tzinfo is None:
            reasons.append("BOUNDARY_NOT_TIMEZONE_AWARE")
    except (KeyError, TypeError, ValueError):
        reasons.append("BOUNDARY_INVALID")

    origin = contract.get("hypothesis_origin", {})
    if not isinstance(origin, Mapping):
        reasons.append("HYPOTHESIS_ORIGIN_INVALID")
    else:
        if origin.get("development_observations_reused") != 0:
            reasons.append("DEVELOPMENT_EVIDENCE_REUSE_PROHIBITED")
        if origin.get("post_hoc_origin_disclosed") is not True:
            reasons.append("POST_HOC_ORIGIN_MUST_BE_DISCLOSED")
        digest = str(origin.get("development_diagnostic_sha256", ""))
        if len(digest) != 64:
            reasons.append("DEVELOPMENT_DIAGNOSTIC_IDENTITY_INVALID")

    configuration = contract.get("configuration", {})
    if not isinstance(configuration, Mapping):
        reasons.append("CONFIGURATION_INVALID")
    else:
        if configuration.get("config_id") != EXPECTED_CONFIG_ID:
            reasons.append("CONFIGURATION_ID_CHANGED")
        if configuration.get("holding_bars") != 6:
            reasons.append("HOLDING_PERIOD_CHANGED")
        weights = configuration.get("weights")
        if weights != EXPECTED_WEIGHTS:
            reasons.append("REGISTERED_WEIGHTS_CHANGED")

    if contract.get("decision_bar_index") != 5:
        reasons.append("DECISION_BAR_CHANGED")
    if contract.get("entry") != "NEXT_5MIN_BAR_OPEN":
        reasons.append("ENTRY_RULE_CHANGED")
    if contract.get("top_n") != 10:
        reasons.append("PORTFOLIO_SIZE_CHANGED")
    if contract.get("modeled_total_cost_bps_round_trip") != 10:
        reasons.append("COST_ASSUMPTION_CHANGED")
    if contract.get("required_universe_symbols") != 101:
        reasons.append("UNIVERSE_CHANGED")
    if contract.get("activation_status") != "DISABLED_PENDING_OPERATIONAL_PREFLIGHT":
        reasons.append("ACTIVATION_MUST_REMAIN_DISABLED")

    policy = contract.get("evidence_policy", {})
    if not isinstance(policy, Mapping):
        reasons.append("EVIDENCE_POLICY_INVALID")
    else:
        if policy.get("append_only") is not True:
            reasons.append("APPEND_ONLY_REQUIRED")
        if policy.get("duplicate_safe") is not True:
            reasons.append("DUPLICATE_SAFETY_REQUIRED")
        if int(policy.get("minimum_preliminary_sessions", 0)) < 20:
            reasons.append("PRELIMINARY_SAMPLE_TOO_SMALL")
        if int(policy.get("minimum_accumulating_sessions", 0)) < 60:
            reasons.append("ACCUMULATING_SAMPLE_TOO_SMALL")
        if policy.get("no_early_promotion") is not True:
            reasons.append("EARLY_PROMOTION_PROHIBITION_MISSING")

    required_false = (
        "model_selection_allowed",
        "configuration_changes_after_boundary",
        "live_trading_enabled",
        "brokerage_orders",
        "holdout_outcomes_read",
        "v8_production_reads",
        "v8_production_writes",
        "v10_production_reads",
        "v10_production_writes",
    )
    for field in required_false:
        if contract.get(field) is not False:
            reasons.append(f"{field.upper()}_MUST_BE_FALSE")
    if contract.get("paper_trading_only") is not True:
        reasons.append("PAPER_ONLY_BOUNDARY_MISSING")
    if contract.get("brokerage_sdks_prohibited") is not True:
        reasons.append("BROKERAGE_SDK_PROHIBITION_MISSING")
    return tuple(dict.fromkeys(reasons))


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    reasons = validate_contract(contract)
    if reasons:
        raise ValueError("PHASE2_CONTRACT_INVALID:" + ",".join(reasons))
    return contract


def main() -> None:
    print("V11 INTRADAY PHASE 2 PREREGISTRATION")
    print("=" * 80)
    contract = load_contract()
    print(f"Status: {contract['status']}")
    print(f"Configuration: {contract['configuration']['config_id']}")
    print(f"Fresh evidence boundary: {contract['fresh_confirmation_start_utc']}")
    print(f"Contract SHA-256: {contract_sha256(contract)}")
    print("Development observations reused: 0")
    print("Activation: DISABLED PENDING OPERATIONAL PREFLIGHT")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
