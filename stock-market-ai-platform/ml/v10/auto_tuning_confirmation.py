"""Confirm the fixed V9 development winner without reopening selection.

The winner ID and confirmation rules are fixed in code before confirmation
outputs are inspected. Failure does not select the runner-up. This module never
accesses the V10 future holdout, promotes a candidate, changes production, or
places brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v10.auto_tuning_evaluator import (
    LEADERBOARD_PATH,
    _annualized_stats,
    _load_development_inputs,
    _transition_notional,
)
from ml.v10.auto_tuning_registry import build_candidate_registry

WINNER_ID = "V10TUNE_4548D4C7828AB971"
EXPECTED_CONFIG = {
    "score_id": "downside_vol_ratio_20",
    "top_n": 5,
    "holding_sessions": 10,
}
COST_STRESS_BPS = (10, 20, 30)
PRIMARY_COST_BPS = 10

OUTPUT_ROOT = Path("data/model/v10/auto_tuning/cycle1/confirmation")
PERIODS_PATH = OUTPUT_ROOT / "winner_periods.csv"
COST_PATH = OUTPUT_ROOT / "cost_stress.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_stability.csv"
DECISION_PATH = OUTPUT_ROOT / "decision.json"

MIN_POSITIVE_YEAR_RATE = 0.70
MIN_WORST_FOLD_SHARPE = 0.0
MIN_WORST_YEAR_RELATIVE_RETURN = -0.05
MAX_ALLOWED_DRAWDOWN = -0.25


def _winner():
    matches = [
        row
        for row in build_candidate_registry()
        if row["candidate_id"] == WINNER_ID
    ]
    if len(matches) != 1:
        raise RuntimeError("Fixed V9 development winner is missing from registry")
    winner = matches[0]
    for key, expected in EXPECTED_CONFIG.items():
        if winner["config"].get(key) != expected:
            raise RuntimeError(f"Winner contract mismatch for {key}")
    return winner


def _simulate_periods(winner, scores, opens, trading_dates, date_to_idx):
    config = winner["config"]
    score_id = config["score_id"]
    top_n = int(config["top_n"])
    hold = int(config["holding_sessions"])
    selected = scores[scores["score_id"] == score_id]
    previous_by_cohort = {}
    rows = []

    for decision_ts, day in selected.groupby("timestamp_utc", sort=True):
        decision_ts = pd.Timestamp(decision_ts)
        i = date_to_idx.get(decision_ts)
        if i is None:
            continue
        entry_i, exit_i = i + 1, i + 1 + hold
        if exit_i >= len(trading_dates):
            continue
        entry_ts, exit_ts = trading_dates[entry_i], trading_dates[exit_i]
        if exit_ts >= FUTURE_HOLDOUT_START_UTC:
            continue

        picks = (
            day.sort_values(["score", "symbol"], ascending=[False, True])
            .head(top_n)["symbol"]
            .astype(str)
            .tolist()
        )
        if len(picks) != top_n:
            continue

        returns = []
        valid = True
        for symbol in picks:
            series = opens[symbol]
            if entry_ts not in series.index or exit_ts not in series.index:
                valid = False
                break
            start, end = float(series.loc[entry_ts]), float(series.loc[exit_ts])
            if not (np.isfinite(start) and np.isfinite(end) and start > 0):
                valid = False
                break
            returns.append(end / start - 1.0)

        spy = opens["SPY"]
        if not valid or entry_ts not in spy.index or exit_ts not in spy.index:
            continue
        spy_start, spy_end = float(spy.loc[entry_ts]), float(spy.loc[exit_ts])
        if not (
            np.isfinite(spy_start)
            and np.isfinite(spy_end)
            and spy_start > 0
        ):
            continue

        cohort = int(i % hold)
        turnover = _transition_notional(
            previous_by_cohort.get(cohort),
            picks,
            top_n,
        )
        gross = float(np.mean(returns))
        spy_return = float(spy_end / spy_start - 1.0)
        rows.append(
            {
                "candidate_id": WINNER_ID,
                "decision_timestamp_utc": decision_ts,
                "entry_timestamp_utc": entry_ts,
                "exit_timestamp_utc": exit_ts,
                "cohort_offset": cohort,
                "symbols": "|".join(picks),
                "gross_portfolio_return": gross,
                "spy_return": spy_return,
                "turnover": turnover,
            }
        )
        previous_by_cohort[cohort] = picks

    periods = pd.DataFrame(rows)
    if periods.empty:
        raise RuntimeError("Fixed winner produced no confirmation periods")
    if pd.to_datetime(periods["exit_timestamp_utc"], utc=True).max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Confirmation periods reach the V10 future holdout")
    return periods


def _with_cost(periods, cost_bps):
    out = periods.copy()
    cost_rate = out["turnover"] * cost_bps / 10000.0
    out["net_portfolio_return"] = (
        (1.0 + out["gross_portfolio_return"]) * (1.0 - cost_rate) - 1.0
    )
    out["net_relative_return"] = (
        out["net_portfolio_return"] - out["spy_return"]
    )
    return out


def _summary(periods, holding_sessions):
    cohort_rows = []
    for _, group in periods.groupby("cohort_offset", sort=True):
        stats = _annualized_stats(
            group["net_portfolio_return"],
            holding_sessions,
        )
        cohort_rows.append(
            {
                **stats,
                "mean_relative_return": float(
                    group["net_relative_return"].mean()
                ),
                "relative_hit_rate": float(
                    (group["net_relative_return"] > 0).mean()
                ),
                "mean_turnover": float(group["turnover"].mean()),
            }
        )
    cohorts = pd.DataFrame(cohort_rows)
    return {
        "periods": int(len(periods)),
        "cohorts": int(len(cohorts)),
        "mean_cagr": float(cohorts["cagr"].mean()),
        "mean_sharpe": float(cohorts["sharpe"].mean()),
        "mean_sortino": float(cohorts["sortino"].mean()),
        "mean_max_drawdown": float(cohorts["max_drawdown"].mean()),
        "mean_calmar": float(cohorts["calmar"].mean()),
        "mean_relative_return": float(
            cohorts["mean_relative_return"].mean()
        ),
        "relative_hit_rate": float(cohorts["relative_hit_rate"].mean()),
        "mean_turnover": float(cohorts["mean_turnover"].mean()),
    }


def build_confirmation_tables(periods, holding_sessions):
    cost_rows = []
    for cost_bps in COST_STRESS_BPS:
        metrics = _summary(_with_cost(periods, cost_bps), holding_sessions)
        cost_rows.append({"cost_bps": cost_bps, **metrics})
    costs = pd.DataFrame(cost_rows)

    primary = _with_cost(periods, PRIMARY_COST_BPS)
    primary["year"] = pd.to_datetime(
        primary["entry_timestamp_utc"],
        utc=True,
    ).dt.year
    year_rows = []
    for year, group in primary.groupby("year", sort=True):
        year_rows.append({"year": int(year), **_summary(group, holding_sessions)})
    years = pd.DataFrame(year_rows)

    primary["trend_regime"] = np.where(
        primary["spy_return"] >= 0,
        "SPY_UP",
        "SPY_DOWN",
    )
    median_abs_spy = float(primary["spy_return"].abs().median())
    primary["volatility_regime"] = np.where(
        primary["spy_return"].abs() >= median_abs_spy,
        "HIGH_ABS_SPY_MOVE",
        "LOW_ABS_SPY_MOVE",
    )
    regime_rows = []
    for column in ("trend_regime", "volatility_regime"):
        for regime, group in primary.groupby(column, sort=True):
            regime_rows.append(
                {
                    "regime_type": column,
                    "regime": regime,
                    **_summary(group, holding_sessions),
                }
            )
    regimes = pd.DataFrame(regime_rows)
    return costs, years, regimes


def confirmation_decision(leaderboard, costs, years, regimes):
    winner_row = leaderboard[
        leaderboard["candidate_id"] == WINNER_ID
    ]
    if len(winner_row) != 1 or int(winner_row.iloc[0]["development_rank"]) != 1:
        raise RuntimeError("Fixed winner is not rank 1 in development leaderboard")
    winner_row = winner_row.iloc[0]
    primary = costs[costs["cost_bps"] == PRIMARY_COST_BPS].iloc[0]
    stressed = costs[costs["cost_bps"] == max(COST_STRESS_BPS)].iloc[0]

    positive_year_rate = float((years["mean_relative_return"] > 0).mean())
    worst_year_relative = float(years["mean_relative_return"].min())
    all_regimes_positive = bool((regimes["mean_relative_return"] > 0).all())

    gates = {
        "all_walk_forward_folds_relative_positive": bool(
            winner_row["positive_relative_fold_rate"] == 1.0
        ),
        "worst_fold_sharpe_nonnegative": bool(
            winner_row["worst_fold_sharpe"] >= MIN_WORST_FOLD_SHARPE
        ),
        "primary_10bps_relative_return_positive": bool(
            primary["mean_relative_return"] > 0
        ),
        "stress_30bps_relative_return_positive": bool(
            stressed["mean_relative_return"] > 0
        ),
        "positive_year_rate_at_least_70pct": bool(
            positive_year_rate >= MIN_POSITIVE_YEAR_RATE
        ),
        "worst_year_relative_return_above_minus_5pct": bool(
            worst_year_relative >= MIN_WORST_YEAR_RELATIVE_RETURN
        ),
        "all_predeclared_regimes_relative_positive": all_regimes_positive,
        "primary_max_drawdown_above_minus_25pct": bool(
            primary["mean_max_drawdown"] >= MAX_ALLOWED_DRAWDOWN
        ),
    }
    confirmed = all(gates.values())
    return {
        "research_version": RESEARCH_VERSION,
        "stage": "fixed_winner_development_confirmation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": WINNER_ID,
        "status": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
        "gates": gates,
        "gates_passed": int(sum(gates.values())),
        "gates_total": len(gates),
        "positive_year_rate": positive_year_rate,
        "worst_year_relative_return": worst_year_relative,
        "challenger_registered": False,
        "runner_up_considered": False,
        "candidate_promoted": False,
        "v10_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v10_future_holdout_scored": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "production_modified": False,
        "brokerage_orders": False,
    }


def main():
    winner = _winner()
    if not LEADERBOARD_PATH.exists():
        raise FileNotFoundError(
            f"Missing {LEADERBOARD_PATH}; run V9 tuning evaluator first"
        )
    leaderboard = pd.read_csv(LEADERBOARD_PATH)
    scores, opens, trading_dates, date_to_idx = _load_development_inputs()
    periods = _simulate_periods(
        winner,
        scores,
        opens,
        trading_dates,
        date_to_idx,
    )
    hold = int(winner["config"]["holding_sessions"])
    costs, years, regimes = build_confirmation_tables(periods, hold)
    decision = confirmation_decision(leaderboard, costs, years, regimes)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIODS_PATH, index=False)
    costs.to_csv(COST_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    DECISION_PATH.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n"
    )

    print("STOCK V10 FIXED-WINNER CONFIRMATION")
    print("=" * 96)
    print(f"Candidate: {WINNER_ID}")
    print(f"Status: {decision['status']}")
    print(
        f"Gates passed: {decision['gates_passed']}/"
        f"{decision['gates_total']}"
    )
    for name, passed in decision["gates"].items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(
        "No runner-up substitution, holdout access, challenger registration, "
        "promotion, production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
