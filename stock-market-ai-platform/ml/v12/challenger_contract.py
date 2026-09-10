"""Validation and identity for the V12 V10-challenger research contract.

This module grants no execution authority. It validates a fixed development
experiment that keeps frozen V10 unchanged, limits V11 to entry confirmation,
and evaluates every candidate under identical $5,000 paper constraints.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

CONTRACT_PATH = Path(__file__).with_name("challenger_contract.json")

EXPECTED_V10_CANDIDATE_ID = "c3_confirm2_blend50"
EXPECTED_V10_SHA256 = (
    "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
)
EXPECTED_V11_SHA256 = (
    "f539fabe9532752adb2a3b6b98aa244671b5ec8d8ae86b5eaacf8076f812a6c8"
)
EXPECTED_CANDIDATES = (
    "V10_CONTROL_5K",
    "V12_INTRADAY_CONFIRM_5K",
    "V12_VOL_CONTROL_5K",
    "V12_COMBINED_5K",
)
EXPECTED_CONFIRMATION_TESTS = (
    "return_15m_minus_spy_return_15m >= 0",
    "volume_acceleration >= 0",
    "realized_volatility_30m <= cross_section_percentile_80",
)


def contract_sha256(contract: Mapping[str, object]) -> str:
    encoded = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, reason: str, reasons: list[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        reasons.append(reason)
        return {}
    return value


def validate_contract(contract: Mapping[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    if contract.get("contract_id") != "V12_V10_CHALLENGER_RESEARCH_V1":
        reasons.append("CONTRACT_ID_CHANGED")
    if contract.get("status") != "PREREGISTERED_DEVELOPMENT_ONLY":
        reasons.append("STATUS_MUST_REMAIN_DEVELOPMENT_ONLY")
    try:
        registered = datetime.fromisoformat(str(contract["registered_at_utc"]))
        if registered.tzinfo is None:
            reasons.append("REGISTRATION_TIME_NOT_TIMEZONE_AWARE")
    except (KeyError, TypeError, ValueError):
        reasons.append("REGISTRATION_TIME_INVALID")

    baseline = _mapping(contract.get("baseline"), "BASELINE_INVALID", reasons)
    if baseline.get("model_id") != "V10_CYCLE3_FROZEN":
        reasons.append("BASELINE_MUST_BE_FROZEN_V10")
    if baseline.get("candidate_id") != EXPECTED_V10_CANDIDATE_ID:
        reasons.append("V10_CANDIDATE_ID_CHANGED")
    if baseline.get("frozen_spec_sha256") != EXPECTED_V10_SHA256:
        reasons.append("V10_FROZEN_SHA_CHANGED")
    if baseline.get("ranking_contract_immutable") is not True:
        reasons.append("V10_RANKING_MUST_REMAIN_IMMUTABLE")
    for field in (
        "production_reads",
        "production_writes",
        "original_holdout_outcomes_read",
        "fresh_holdout_outcomes_read",
    ):
        if baseline.get(field) is not False:
            reasons.append(f"BASELINE_{field.upper()}_MUST_BE_FALSE")

    v11 = _mapping(
        contract.get("v11_input_boundary"),
        "V11_INPUT_BOUNDARY_INVALID",
        reasons,
    )
    if v11.get("contract_sha256") != EXPECTED_V11_SHA256:
        reasons.append("V11_CONTRACT_SHA_CHANGED")
    if v11.get("role") != "ENTRY_CONFIRMATION_ONLY":
        reasons.append("V11_ROLE_MUST_BE_CONFIRMATION_ONLY")
    if v11.get("ranking_weight") != 0:
        reasons.append("V11_RANKING_WEIGHT_MUST_BE_ZERO")
    for field in (
        "model_selection_authority",
        "fresh_confirmation_outcomes_read",
        "production_journal_reads",
        "production_journal_writes",
    ):
        if v11.get(field) is not False:
            reasons.append(f"V11_{field.upper()}_MUST_BE_FALSE")

    candidates = contract.get("candidate_set")
    if not isinstance(candidates, list):
        reasons.append("CANDIDATE_SET_INVALID")
        candidates = []
    candidate_ids = tuple(
        str(item.get("candidate_id"))
        for item in candidates
        if isinstance(item, Mapping)
    )
    if candidate_ids != EXPECTED_CANDIDATES:
        reasons.append("CANDIDATE_SET_OR_ORDER_CHANGED")
    if len(candidates) != 4:
        reasons.append("EXACTLY_FOUR_CANDIDATES_REQUIRED")

    confirmation = _mapping(
        contract.get("intraday_confirmation_rule"),
        "INTRADAY_CONFIRMATION_RULE_INVALID",
        reasons,
    )
    if confirmation.get("ranking_source") != "UNCHANGED_V10_CYCLE3_RANKS":
        reasons.append("INTRADAY_RULE_CANNOT_REPLACE_V10_RANKING")
    if confirmation.get("ranking_weight") != 0:
        reasons.append("INTRADAY_RANKING_WEIGHT_MUST_BE_ZERO")
    if tuple(confirmation.get("confirm_symbol_if_all", ())) != EXPECTED_CONFIRMATION_TESTS:
        reasons.append("INTRADAY_CONFIRMATION_TESTS_CHANGED")
    if confirmation.get("minimum_confirmed_positions") != 3:
        reasons.append("MINIMUM_CONFIRMED_POSITIONS_CHANGED")
    if confirmation.get("missing_or_stale_intraday_data_action") != "HOLD_CASH":
        reasons.append("STALE_INTRADAY_DATA_MUST_HOLD_CASH")

    volatility = _mapping(
        contract.get("volatility_control_rule"),
        "VOLATILITY_CONTROL_RULE_INVALID",
        reasons,
    )
    if volatility.get("target_annualized_volatility") != 0.15:
        reasons.append("VOLATILITY_TARGET_CHANGED")
    if volatility.get("minimum_exposure_multiplier") != 0.5:
        reasons.append("MINIMUM_EXPOSURE_CHANGED")
    if volatility.get("maximum_exposure_multiplier") != 1.0:
        reasons.append("MAXIMUM_EXPOSURE_CHANGED")
    if volatility.get("leverage_allowed") is not False:
        reasons.append("LEVERAGE_PROHIBITION_MISSING")
    if volatility.get("missing_or_stale_volatility_action") != "HOLD_CASH":
        reasons.append("STALE_VOLATILITY_DATA_MUST_HOLD_CASH")

    account = _mapping(
        contract.get("small_account_execution"),
        "SMALL_ACCOUNT_EXECUTION_INVALID",
        reasons,
    )
    expected_account = {
        "starting_capital_usd": 5000,
        "integer_shares_only": True,
        "fractional_shares": False,
        "margin": False,
        "short_selling": False,
        "maximum_deployed_capital_pct": 0.9,
        "minimum_cash_buffer_pct": 0.1,
        "maximum_position_notional_pct": 0.2,
        "minimum_positions": 3,
        "maximum_positions": 10,
        "maximum_spread_bps": 20,
    }
    for field, expected in expected_account.items():
        if account.get(field) != expected:
            reasons.append(f"SMALL_ACCOUNT_{field.upper()}_CHANGED")
    for field in ("options", "extended_hours"):
        if account.get(field) is not False:
            reasons.append(f"SMALL_ACCOUNT_{field.upper()}_MUST_BE_FALSE")
    for field in (
        "insufficient_diversification_action",
        "missing_quote_or_spread_action",
    ):
        if account.get(field) != "HOLD_CASH":
            reasons.append(f"SMALL_ACCOUNT_{field.upper()}_MUST_HOLD_CASH")

    cost = _mapping(contract.get("cost_contract"), "COST_CONTRACT_INVALID", reasons)
    if cost.get("minimum_modeled_total_cost_bps_round_trip") != 10:
        reasons.append("MINIMUM_COST_ASSUMPTION_CHANGED")

    validation = _mapping(
        contract.get("development_validation"),
        "DEVELOPMENT_VALIDATION_INVALID",
        reasons,
    )
    if validation.get("minimum_folds") != 5:
        reasons.append("MINIMUM_FOLDS_CHANGED")
    if validation.get("purge_sessions") != 5:
        reasons.append("PURGE_CHANGED")
    if validation.get("candidate_set_fixed_before_evaluation") is not True:
        reasons.append("CANDIDATE_SET_MUST_BE_FIXED")
    if validation.get("test_data_selection_allowed") is not False:
        reasons.append("TEST_DATA_SELECTION_PROHIBITION_MISSING")
    gates = _mapping(
        validation.get("required_gates"),
        "REQUIRED_GATES_INVALID",
        reasons,
    )
    if gates.get("net_annualized_return_delta_at_least") != 0.03:
        reasons.append("RETURN_IMPROVEMENT_GATE_CHANGED")
    if gates.get("walk_forward_fold_win_rate_at_least") != 0.7:
        reasons.append("FOLD_WIN_RATE_GATE_CHANGED")
    if gates.get("turnover_not_more_than_control_multiple") != 1.25:
        reasons.append("TURNOVER_GATE_CHANGED")
    if gates.get("small_account_feasibility_pass_rate") != 1.0:
        reasons.append("SMALL_ACCOUNT_FEASIBILITY_GATE_CHANGED")
    required_true_gates = (
        "terminal_wealth_greater_than_control",
        "maximum_drawdown_not_worse_than_control",
        "positive_spy_regime_noninferior",
        "negative_spy_regime_outperformance",
        "high_volatility_regime_outperformance",
        "all_costs_included",
    )
    for field in required_true_gates:
        if gates.get(field) is not True:
            reasons.append(f"GATE_{field.upper()}_MUST_BE_TRUE")

    paper = _mapping(
        contract.get("fresh_paper_confirmation"),
        "FRESH_PAPER_CONFIRMATION_INVALID",
        reasons,
    )
    if paper.get("activation_status") != "DISABLED_PENDING_DEVELOPMENT_FREEZE":
        reasons.append("FRESH_PAPER_ACTIVATION_MUST_REMAIN_DISABLED")
    if paper.get("minimum_sessions") != 60:
        reasons.append("FRESH_PAPER_MINIMUM_SESSIONS_CHANGED")
    for field in ("append_only", "duplicate_safe", "no_early_promotion"):
        if paper.get(field) is not True:
            reasons.append(f"FRESH_PAPER_{field.upper()}_REQUIRED")

    authority = _mapping(contract.get("authority"), "AUTHORITY_INVALID", reasons)
    for field in ("research_only", "paper_trading_only", "brokerage_sdks_prohibited"):
        if authority.get(field) is not True:
            reasons.append(f"AUTHORITY_{field.upper()}_MUST_BE_TRUE")
    required_false = (
        "live_trading_enabled",
        "brokerage_orders",
        "v8_production_reads",
        "v8_production_writes",
        "v10_production_reads",
        "v10_production_writes",
        "v10_holdout_outcomes_read",
        "v11_production_reads",
        "v11_production_writes",
        "v11_fresh_outcomes_read",
        "post_result_tuning_allowed",
        "candidate_freeze_authorized",
        "fresh_confirmation_activation_authorized",
    )
    for field in required_false:
        if authority.get(field) is not False:
            reasons.append(f"AUTHORITY_{field.upper()}_MUST_BE_FALSE")
    return tuple(dict.fromkeys(reasons))


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    reasons = validate_contract(contract)
    if reasons:
        raise ValueError("V12_CONTRACT_INVALID:" + ",".join(reasons))
    return contract


def main() -> None:
    contract = load_contract()
    print("DATA SHEPHERD V12 V10-CHALLENGER PREREGISTRATION")
    print("=" * 84)
    print(f"Status: {contract['status']}")
    print(f"Baseline: {contract['baseline']['candidate_id']}")
    print(f"Candidates: {len(contract['candidate_set'])}")
    print(
        "Candidate IDs: "
        + ", ".join(item["candidate_id"] for item in contract["candidate_set"])
    )
    print(
        "Small-account capital: "
        f"${contract['small_account_execution']['starting_capital_usd']:,.0f}"
    )
    print(f"Contract SHA-256: {contract_sha256(contract)}")
    print("V11 authority: ENTRY CONFIRMATION ONLY")
    print("V10 ranking modified: NO")
    print("Development evaluation performed: NO")
    print("Fresh paper confirmation: DISABLED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production modified: NO")


if __name__ == "__main__":
    main()
