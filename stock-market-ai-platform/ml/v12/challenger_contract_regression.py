"""Regression checks for the preregistered V12 challenger contract."""
from __future__ import annotations

import copy
from pathlib import Path

from ml.v12.challenger_contract import (
    EXPECTED_CANDIDATES,
    EXPECTED_CONFIRMATION_TESTS,
    EXPECTED_V10_CANDIDATE_ID,
    EXPECTED_V10_SHA256,
    EXPECTED_V11_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    contract = load_contract()
    require(not validate_contract(contract), "V12 preregistered contract validates")
    require(
        contract["baseline"]["candidate_id"] == EXPECTED_V10_CANDIDATE_ID,
        "Frozen V10 Cycle 3 candidate is the control",
    )
    require(
        contract["baseline"]["frozen_spec_sha256"] == EXPECTED_V10_SHA256,
        "Frozen V10 identity is locked",
    )
    require(
        contract["baseline"]["ranking_contract_immutable"] is True,
        "V10 ranking remains immutable",
    )
    require(
        contract["v11_input_boundary"]["contract_sha256"] == EXPECTED_V11_SHA256,
        "V11 contract identity is locked",
    )
    require(
        contract["v11_input_boundary"]["role"] == "ENTRY_CONFIRMATION_ONLY",
        "V11 is limited to entry confirmation",
    )
    require(
        contract["v11_input_boundary"]["ranking_weight"] == 0,
        "V11 cannot alter V10 rankings",
    )
    require(
        tuple(item["candidate_id"] for item in contract["candidate_set"])
        == EXPECTED_CANDIDATES,
        "Exactly one control and three challengers are fixed",
    )
    require(
        tuple(contract["intraday_confirmation_rule"]["confirm_symbol_if_all"])
        == EXPECTED_CONFIRMATION_TESTS,
        "Intraday confirmation tests are locked",
    )
    require(
        contract["volatility_control_rule"]["maximum_exposure_multiplier"] == 1.0,
        "Volatility control cannot add leverage",
    )
    account = contract["small_account_execution"]
    require(account["starting_capital_usd"] == 5000, "$5,000 starting capital is locked")
    require(account["integer_shares_only"] is True, "Integer-share execution is required")
    require(account["fractional_shares"] is False, "Fractional shares remain prohibited")
    require(account["margin"] is False, "Margin remains prohibited")
    require(account["short_selling"] is False, "Short selling remains prohibited")
    require(account["maximum_deployed_capital_pct"] == 0.9, "Ten-percent cash buffer is locked")
    require(account["maximum_position_notional_pct"] == 0.2, "Position notional is capped at twenty percent")
    require(account["maximum_spread_bps"] == 20, "Maximum spread is locked at twenty bps")
    validation = contract["development_validation"]
    require(validation["minimum_folds"] == 5, "At least five walk-forward folds are required")
    require(validation["purge_sessions"] == 5, "Five-session purge is required")
    require(
        validation["required_gates"]["net_annualized_return_delta_at_least"] == 0.03,
        "V12 must improve annualized net return by at least three points",
    )
    require(
        validation["required_gates"]["maximum_drawdown_not_worse_than_control"] is True,
        "V12 drawdown cannot be worse than the control",
    )
    require(
        validation["required_gates"]["walk_forward_fold_win_rate_at_least"] == 0.7,
        "V12 must win at least seventy percent of folds",
    )
    require(
        contract["fresh_paper_confirmation"]["activation_status"]
        == "DISABLED_PENDING_DEVELOPMENT_FREEZE",
        "Fresh paper confirmation remains disabled",
    )
    authority = contract["authority"]
    require(authority["research_only"] is True, "V12 authority is research only")
    require(authority["live_trading_enabled"] is False, "Live trading remains disabled")
    require(authority["brokerage_orders"] is False, "Brokerage orders remain off")
    require(authority["v10_holdout_outcomes_read"] is False, "V10 holdout outcomes are prohibited")
    require(authority["v11_fresh_outcomes_read"] is False, "V11 fresh outcomes are prohibited")
    require(authority["post_result_tuning_allowed"] is False, "Post-result tuning is prohibited")
    require(len(contract_sha256(contract)) == 64, "Contract has a SHA-256 identity")

    tampered_v10 = copy.deepcopy(contract)
    tampered_v10["baseline"]["candidate_id"] = "different_candidate"
    require(
        "V10_CANDIDATE_ID_CHANGED" in validate_contract(tampered_v10),
        "V10 candidate tampering fails closed",
    )
    promoted_v11 = copy.deepcopy(contract)
    promoted_v11["v11_input_boundary"]["ranking_weight"] = 0.25
    require(
        "V11_RANKING_WEIGHT_MUST_BE_ZERO" in validate_contract(promoted_v11),
        "V11 ranking promotion fails closed",
    )
    leveraged = copy.deepcopy(contract)
    leveraged["volatility_control_rule"]["maximum_exposure_multiplier"] = 1.25
    require(
        "MAXIMUM_EXPOSURE_CHANGED" in validate_contract(leveraged),
        "Leverage drift fails closed",
    )
    enlarged = copy.deepcopy(contract)
    enlarged["small_account_execution"]["starting_capital_usd"] = 100000
    require(
        "SMALL_ACCOUNT_STARTING_CAPITAL_USD_CHANGED" in validate_contract(enlarged),
        "Small-account capital drift fails closed",
    )
    activated = copy.deepcopy(contract)
    activated["fresh_paper_confirmation"]["activation_status"] = "ENABLED"
    require(
        "FRESH_PAPER_ACTIVATION_MUST_REMAIN_DISABLED" in validate_contract(activated),
        "Premature paper activation fails closed",
    )
    live = copy.deepcopy(contract)
    live["authority"]["live_trading_enabled"] = True
    require(
        "AUTHORITY_LIVE_TRADING_ENABLED_MUST_BE_FALSE" in validate_contract(live),
        "Live-trading activation fails closed",
    )

    source = Path(__file__).with_name("challenger_contract.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(
            forbidden_import not in source,
            f"Brokerage SDK absent: {forbidden_import}",
        )

    print("Status: PASSED")
    print("V12 experiment: PREREGISTERED DEVELOPMENT ONLY")
    print("Control/challengers: 1/3")
    print("Small-account basis: $5,000 INTEGER SHARES")
    print("V11 authority: ENTRY CONFIRMATION ONLY")
    print("Fresh paper confirmation: DISABLED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production evidence modified: NO")


if __name__ == "__main__":
    main()
