"""Regression suite for the V12 small-account development evaluator."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from ml.v12.challenger_contract import contract_sha256, load_contract
from ml.v12.development_evaluator import (
    Candidate,
    EXPECTED_CONTRACT_SHA256,
    MarketPeriod,
    _canonical_sha,
    build_walk_forward_folds,
    evaluate_periods,
    gate_candidate,
    integer_allocation,
    select_candidate,
    simulate_period,
    validate_v11_manifest_preflight,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def _periods(count: int = 75) -> list[MarketPeriod]:
    symbols = tuple(f"S{index:02d}" for index in range(1, 13))
    start = date(2026, 1, 2)
    regimes = (
        "POSITIVE_LOW_VOL",
        "NEGATIVE_LOW_VOL",
        "POSITIVE_HIGH_VOL",
        "NEGATIVE_HIGH_VOL",
    )
    result = []
    for index in range(count):
        decision = start + timedelta(days=index)
        entry = decision + timedelta(days=1)
        exit_date = decision + timedelta(days=6)
        entry_prices = {symbol: 40.0 + position for position, symbol in enumerate(symbols)}
        return_rate = 0.002 + (index % 5) * 0.0005
        exit_prices = {
            symbol: price * (1.0 + return_rate)
            for symbol, price in entry_prices.items()
        }
        confirmations = {
            symbol: position < 8 for position, symbol in enumerate(symbols)
        }
        result.append(
            MarketPeriod(
                decision_session=decision.isoformat(),
                entry_session=entry.isoformat(),
                exit_session=exit_date.isoformat(),
                decision_index=index,
                cohort_offset=index % 5,
                decision_regime=regimes[index % len(regimes)],
                ranked_symbols=symbols,
                confirmations=confirmations,
                spy_annualized_volatility_20d=0.20,
                entry_prices=entry_prices,
                exit_prices=exit_prices,
                spy_entry_price=100.0,
                spy_exit_price=100.1,
            )
        )
    return result


def _summary(
    candidate_id: str,
    *,
    annualized: float,
    terminal: float,
    drawdown: float,
    turnover: float,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "mean_net_annualized_return": annualized,
        "mean_terminal_wealth": terminal,
        "maximum_drawdown": drawdown,
        "maximum_drawdown_abs": abs(drawdown),
        "mean_turnover_notional_ratio": turnover,
        "small_account_feasibility_pass_rate": 1.0,
        "costs_included": True,
    }


def main() -> None:
    contract = load_contract()
    require(
        contract_sha256(contract) == EXPECTED_CONTRACT_SHA256,
        "Locked V12 contract identity matches evaluator",
    )

    manifest_body = {
        "status": "COMPLETE_HISTORICAL_RESEARCH_DATASET",
        "last_common_session": "2026-08-27",
    }
    valid_manifest = {
        **manifest_body,
        "manifest_sha256": _canonical_sha(manifest_body),
    }
    validate_v11_manifest_preflight(valid_manifest)
    require(True, "Pre-boundary V11 manifest passes identity preflight")
    tampered_manifest = dict(valid_manifest)
    tampered_manifest["last_common_session"] = "2026-08-28"
    try:
        validate_v11_manifest_preflight(tampered_manifest)
    except ValueError:
        pass
    else:
        raise AssertionError("Tampered V11 manifest fails closed")
    require(True, "Tampered V11 manifest fails closed")
    post_boundary_body = {
        "status": "COMPLETE_HISTORICAL_RESEARCH_DATASET",
        "last_common_session": "2026-09-01",
    }
    post_boundary_manifest = {
        **post_boundary_body,
        "manifest_sha256": _canonical_sha(post_boundary_body),
    }
    try:
        validate_v11_manifest_preflight(post_boundary_manifest)
    except RuntimeError:
        pass
    else:
        raise AssertionError("V11 fresh-evidence boundary fails closed")
    require(True, "V11 fresh-evidence boundary fails closed before data load")

    symbols = [f"S{index:02d}" for index in range(1, 12)]
    prices = {symbol: 50.0 for symbol in symbols}
    prices["S01"] = 2_000.0
    allocation = integer_allocation(
        equity=5_000.0,
        ranked_symbols=symbols,
        entry_prices=prices,
        exposure_multiplier=1.0,
        contract=contract,
    )
    require("S01" not in allocation, "Unaffordable symbol is skipped")
    require(all(isinstance(value, int) for value in allocation.values()), "Shares are integers")
    deployed = sum(allocation[symbol] * prices[symbol] for symbol in allocation)
    require(deployed <= 4_500.0, "Maximum deployed capital is respected")
    require(
        all(allocation[symbol] * prices[symbol] <= 1_000.0 for symbol in allocation),
        "Twenty-percent position cap is respected",
    )

    period = _periods(1)[0]
    confirmation_candidate = Candidate("TEST_CONFIRM", True, False)
    missing_confirmation = replace(period, confirmations=None)
    held = simulate_period(
        period=missing_confirmation,
        candidate=confirmation_candidate,
        starting_equity=5_000.0,
        contract=contract,
    )
    require(not held["traded"], "Missing intraday confirmation holds cash")
    require(held["ending_equity"] == 5_000.0, "Fail-closed hold preserves cash")

    volatility_candidate = Candidate("TEST_VOL", False, True)
    missing_volatility = replace(period, spy_annualized_volatility_20d=None)
    held_volatility = simulate_period(
        period=missing_volatility,
        candidate=volatility_candidate,
        starting_equity=5_000.0,
        contract=contract,
    )
    require(not held_volatility["traded"], "Missing volatility input holds cash")

    control_candidate = Candidate("TEST_CONTROL", False, False)
    traded = simulate_period(
        period=period,
        candidate=control_candidate,
        starting_equity=5_000.0,
        contract=contract,
    )
    require(traded["traded"], "Complete control period executes in simulation")
    require(traded["transaction_cost_usd"] > 0, "Explicit costs are charged")
    require(traded["brokerage_orders"] is False, "Period has no brokerage authority")

    sessions = [item.decision_session for item in _periods()]
    folds = build_walk_forward_folds(
        sessions,
        minimum_folds=5,
        purge_sessions=5,
    )
    require(len(folds) == 5, "Exactly five purged walk-forward folds are built")
    require(
        all(fold["purge_sessions"] == 5 for fold in folds),
        "Every fold has a five-session purge",
    )
    require(
        all(fold["train_end"] < fold["purge_start"] < fold["test_start"] for fold in folds),
        "Training, purge and test windows are strictly ordered",
    )

    control_records = []
    candidate_records = []
    for index, session in enumerate(sessions):
        regime = (
            "NEGATIVE_HIGH_VOL" if index % 3 == 0
            else "NEGATIVE_LOW_VOL" if index % 3 == 1
            else "POSITIVE_HIGH_VOL"
        )
        control_records.append(
            {
                "decision_session": session,
                "decision_regime": regime,
                "cohort_offset": index % 5,
                "period_return": 0.001,
            }
        )
        candidate_records.append(
            {
                "decision_session": session,
                "decision_regime": regime,
                "cohort_offset": index % 5,
                "period_return": 0.002,
            }
        )
    control_summary = _summary(
        "V10_CONTROL_5K",
        annualized=0.10,
        terminal=5_500.0,
        drawdown=-0.10,
        turnover=1.50,
    )
    candidate_summary = _summary(
        "V12_COMBINED_5K",
        annualized=0.14,
        terminal=5_800.0,
        drawdown=-0.08,
        turnover=1.60,
    )
    gates, details = gate_candidate(
        candidate_summary=candidate_summary,
        control_summary=control_summary,
        candidate_records=candidate_records,
        control_records=control_records,
        folds=folds,
        contract=contract,
    )
    require(len(gates) == 10, "Every preregistered development gate is evaluated")
    require(details["all_gates_passed"], "Qualifying synthetic challenger passes every gate")
    require(details["fold_win_rate"] == 1.0, "Fold win rate is calculated")

    summaries = [
        control_summary,
        _summary(
            "V12_INTRADAY_CONFIRM_5K",
            annualized=0.18,
            terminal=5_900.0,
            drawdown=-0.07,
            turnover=1.50,
        ),
        _summary(
            "V12_VOL_CONTROL_5K",
            annualized=0.16,
            terminal=5_850.0,
            drawdown=-0.05,
            turnover=1.40,
        ),
        candidate_summary,
    ]
    eligibility = {
        str(summary["candidate_id"]): {"all_gates_passed": True}
        for summary in summaries
    }
    selected = select_candidate(summaries, eligibility)
    require(
        selected == "V12_VOL_CONTROL_5K",
        "Eligible tie-break selects the lowest drawdown",
    )
    for candidate_id in eligibility:
        if candidate_id != "V10_CONTROL_5K":
            eligibility[candidate_id]["all_gates_passed"] = False
    require(
        select_candidate(summaries, eligibility) == "V10_CONTROL_5K",
        "No passing challenger retains frozen V10 control",
    )

    synthetic_periods = _periods()
    first = evaluate_periods(synthetic_periods, contract)
    second = evaluate_periods(synthetic_periods, contract)
    require(
        first["evaluation_sha256"] == second["evaluation_sha256"],
        "Development evaluation is deterministic",
    )
    require(len(first["candidate_summaries"]) == 4, "One control and three challengers are evaluated")
    require(first["candidate_frozen"] is False, "Development result cannot freeze a candidate")
    require(
        first["fresh_paper_confirmation_activated"] is False,
        "Development result cannot activate fresh paper confirmation",
    )
    require(first["v10_holdout_outcomes_read"] is False, "V10 holdout outcomes remain unread")
    require(first["v11_fresh_outcomes_read"] is False, "V11 fresh outcomes remain unread")
    require(first["brokerage_orders"] is False, "Evaluation has no brokerage authority")
    require(
        first["v8_modified"] is first["v10_modified"] is first["v11_modified"] is False,
        "V8, V10 and V11 remain unchanged",
    )

    source = Path(__file__).with_name("development_evaluator.py").read_text(
        encoding="utf-8"
    )
    for prohibited in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(prohibited not in source, f"Brokerage SDK absent: {prohibited}")

    print("\nStatus: PASSED")
    print("V12 development evaluator: VERIFIED")
    print("Small-account integer execution: VERIFIED")
    print("Five-fold purged evaluation: VERIFIED")
    print("Candidate freeze authority: NONE")
    print("Fresh paper confirmation: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production evidence modified: NO")


if __name__ == "__main__":
    main()
