"""V10 Cycle 2: fixed one-session defensive-exit buffer.

Predeclared hypothesis
----------------------
Enter the defensive signal immediately when SPY trailing-20-session return is
negative. After it turns non-negative, remain defensive for exactly one
additional completed session before returning to the V8 distance signal.

The rule is fixed at one session before results are inspected. No search over
buffer length, thresholds, lookbacks, weights, Top-N, holding period, or cost.
The November 2, 2026 future holdout is never scored.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10 import phase3 as base
from ml.v10.config import FUTURE_HOLDOUT_START_UTC

CYCLE = 2
BASELINE = base.V8_ID
CANDIDATE = "switch_negative_exit_buffer_1d"
OUTPUT_ROOT = Path("data/model/v10/cycle2")
PERIOD_PATH = OUTPUT_ROOT / "economic_period_results.csv"
COHORT_PATH = OUTPUT_ROOT / "cohort_summary.csv"
PORTFOLIO_PATH = OUTPUT_ROOT / "portfolio_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_summary.csv"
DAILY_IC_PATH = OUTPUT_ROOT / "daily_ic.csv"
GATE_PATH = OUTPUT_ROOT / "gate_results.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
ROLLING_WINDOW = 252


def _rank_corr(left, right):
    paired = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(paired) < 20 or paired["left"].nunique() < 2 or paired["right"].nunique() < 2:
        return np.nan
    return float(paired["left"].corr(paired["right"], method="spearman"))


def _build_score_panel():
    panel = base._load_panel()
    if "forward_relative_return_5d" not in panel.columns:
        raise ValueError("Cycle 2 requires forward_relative_return_5d development target")

    state = base._market_state(panel).sort_values("timestamp_utc").copy()
    negative = state["negative_spy20"].fillna(False).astype(bool)
    # Fixed one-session exit buffer: immediate defensive entry, delayed exit.
    state["cycle2_defensive_active"] = negative | negative.shift(1, fill_value=False)

    parts = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        market = state[state["timestamp_utc"] == ts]
        if market.empty:
            continue
        defensive_active = bool(market["cycle2_defensive_active"].iloc[0])
        regime = str(market["decision_regime"].iloc[0])

        raw = pd.to_numeric(day["distance_from_low_20d"], errors="coerce")
        downside = pd.to_numeric(
            day["downside_vol_ratio_20"], errors="coerce"
        ).rank(pct=True, method="average")
        volume = pd.to_numeric(
            day["volume_trend_5_20"], errors="coerce"
        ).rank(pct=True, method="average")
        defensive = 0.5 * downside + 0.5 * volume
        target = pd.to_numeric(day["forward_relative_return_5d"], errors="coerce")

        for candidate_id, score in (
            (BASELINE, raw),
            (CANDIDATE, defensive if defensive_active else raw),
        ):
            parts.append(
                pd.DataFrame(
                    {
                        "candidate_id": candidate_id,
                        "timestamp_utc": ts,
                        "symbol": day["symbol"].astype(str).values,
                        "score": pd.to_numeric(score, errors="coerce").values,
                        "forward_relative_return_5d": target.values,
                        "decision_regime": regime,
                        "negative_spy20": bool(market["negative_spy20"].iloc[0]),
                        "cycle2_defensive_active": defensive_active,
                    }
                )
            )
    scored = pd.concat(parts, ignore_index=True)
    if scored["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Cycle-2 score panel reaches protected V10 holdout boundary")
    return scored


def _daily_ic(scored):
    rows = []
    baseline = scored[scored["candidate_id"] == BASELINE]
    candidate = scored[scored["candidate_id"] == CANDIDATE]
    for ts, candidate_day in candidate.groupby("timestamp_utc", sort=True):
        baseline_day = baseline[baseline["timestamp_utc"] == ts]
        merged = candidate_day[
            ["symbol", "score", "forward_relative_return_5d", "decision_regime", "cycle2_defensive_active"]
        ].merge(
            baseline_day[["symbol", "score"]],
            on="symbol",
            suffixes=("_candidate", "_baseline"),
            validate="one_to_one",
        )
        candidate_ic = _rank_corr(
            merged["score_candidate"], merged["forward_relative_return_5d"]
        )
        baseline_ic = _rank_corr(
            merged["score_baseline"], merged["forward_relative_return_5d"]
        )
        rows.append(
            {
                "timestamp_utc": ts,
                "candidate_id": CANDIDATE,
                "decision_regime": str(merged["decision_regime"].iloc[0]),
                "cycle2_defensive_active": bool(
                    merged["cycle2_defensive_active"].iloc[0]
                ),
                "candidate_ic": candidate_ic,
                "baseline_ic": baseline_ic,
                "delta_ic_vs_v8": (
                    candidate_ic - baseline_ic
                    if np.isfinite(candidate_ic) and np.isfinite(baseline_ic)
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_periods(scored):
    symbols = scored["symbol"].unique().tolist()
    opens, trading_dates, date_to_idx = base._load_execution_data(symbols)
    raw = []

    for candidate_id in (BASELINE, CANDIDATE):
        score_panel = scored[scored["candidate_id"] == candidate_id]
        for decision_ts in sorted(score_panel["timestamp_utc"].unique()):
            decision_ts = pd.Timestamp(decision_ts)
            if decision_ts not in date_to_idx:
                continue
            decision_index = date_to_idx[decision_ts]
            entry_index = decision_index + 1
            exit_index = entry_index + base.HOLD_SESSIONS
            if exit_index >= len(trading_dates):
                continue
            entry_ts = trading_dates[entry_index]
            exit_ts = trading_dates[exit_index]
            if exit_ts >= FUTURE_HOLDOUT_START_UTC:
                continue

            day = score_panel[
                score_panel["timestamp_utc"] == decision_ts
            ].dropna(subset=["score"])
            day = day.sort_values(["score", "symbol"], ascending=[False, True])
            picks = day.head(base.TOP_N)["symbol"].astype(str).tolist()
            if len(picks) != base.TOP_N:
                continue

            stock_returns = []
            valid = True
            for symbol in picks:
                series = opens[symbol]
                if entry_ts not in series.index or exit_ts not in series.index:
                    valid = False
                    break
                entry_price = float(series.loc[entry_ts])
                exit_price = float(series.loc[exit_ts])
                if not (
                    np.isfinite(entry_price)
                    and np.isfinite(exit_price)
                    and entry_price > 0
                    and exit_price > 0
                ):
                    valid = False
                    break
                stock_returns.append(exit_price / entry_price - 1.0)
            spy = opens["SPY"]
            if (
                not valid
                or entry_ts not in spy.index
                or exit_ts not in spy.index
            ):
                continue
            spy_entry = float(spy.loc[entry_ts])
            spy_exit = float(spy.loc[exit_ts])
            if not (
                np.isfinite(spy_entry)
                and np.isfinite(spy_exit)
                and spy_entry > 0
                and spy_exit > 0
            ):
                continue

            raw.append(
                {
                    "candidate_id": candidate_id,
                    "decision_timestamp_utc": decision_ts,
                    "entry_timestamp_utc": entry_ts,
                    "exit_timestamp_utc": exit_ts,
                    "decision_index": int(decision_index),
                    "cohort_offset": int(decision_index % base.HOLD_SESSIONS),
                    "decision_regime": str(day["decision_regime"].iloc[0]),
                    "cycle2_defensive_active": bool(
                        day["cycle2_defensive_active"].iloc[0]
                    ),
                    "symbols": "|".join(picks),
                    "gross_portfolio_return": float(np.mean(stock_returns)),
                    "spy_return": float(spy_exit / spy_entry - 1.0),
                }
            )

    periods = pd.DataFrame(raw).sort_values(
        ["candidate_id", "cohort_offset", "decision_index"]
    ).reset_index(drop=True)
    if periods.empty:
        raise RuntimeError("No V10 Cycle-2 executable periods produced")

    output = []
    for (candidate_id, offset), group in periods.groupby(
        ["candidate_id", "cohort_offset"], sort=True
    ):
        previous = None
        for _, row in group.iterrows():
            picks = row["symbols"].split("|")
            traded = base._transition_notional(previous, picks)
            cost_rate = traded * base.PRIMARY_COST_BPS / 10000.0
            gross = float(row["gross_portfolio_return"])
            net = (1.0 + gross) * (1.0 - cost_rate) - 1.0
            record = row.to_dict()
            record["transition_notional"] = float(traded)
            record["modeled_transaction_cost_rate"] = float(cost_rate)
            record["net_portfolio_return"] = float(net)
            record["net_relative_return"] = float(net - row["spy_return"])
            record["transaction_cost_drag"] = float(gross - net)
            output.append(record)
            previous = picks
    return pd.DataFrame(output)


def _gate_results(daily, cohorts, portfolio, years, regimes):
    candidate_portfolio = portfolio.set_index("candidate_id").loc[CANDIDATE]
    baseline_portfolio = portfolio.set_index("candidate_id").loc[BASELINE]

    valid_delta = daily["delta_ic_vs_v8"].dropna()
    rolling = valid_delta.rolling(
        ROLLING_WINDOW, min_periods=ROLLING_WINDOW
    ).mean().dropna()
    rolling_positive_rate = float((rolling > 0).mean()) if len(rolling) else np.nan

    candidate_cohorts = cohorts[
        cohorts["candidate_id"] == CANDIDATE
    ].set_index("cohort_offset")
    baseline_cohorts = cohorts[
        cohorts["candidate_id"] == BASELINE
    ].set_index("cohort_offset")
    common_cohorts = candidate_cohorts.index.intersection(baseline_cohorts.index)
    cagr_wins = int(
        (
            candidate_cohorts.loc[common_cohorts, "strategy_cagr"]
            > baseline_cohorts.loc[common_cohorts, "strategy_cagr"]
        ).sum()
    )
    sharpe_wins = int(
        (
            candidate_cohorts.loc[common_cohorts, "strategy_sharpe"]
            > baseline_cohorts.loc[common_cohorts, "strategy_sharpe"]
        ).sum()
    )

    candidate_years = years[years["candidate_id"] == CANDIDATE].set_index("year")
    baseline_years = years[years["candidate_id"] == BASELINE].set_index("year")
    common_years = candidate_years.index.intersection(baseline_years.index)
    year_wins = int(
        (
            candidate_years.loc[common_years, "mean_net_relative_return"]
            > baseline_years.loc[common_years, "mean_net_relative_return"]
        ).sum()
    )

    candidate_regimes = regimes[
        regimes["candidate_id"] == CANDIDATE
    ].set_index("decision_regime")
    baseline_regimes = regimes[
        regimes["candidate_id"] == BASELINE
    ].set_index("decision_regime")
    negative = [
        regime for regime in candidate_regimes.index
        if regime.startswith("NEGATIVE_") and regime in baseline_regimes.index
    ]
    positive = [
        regime for regime in candidate_regimes.index
        if regime.startswith("POSITIVE_") and regime in baseline_regimes.index
    ]
    negative_wins = int(
        sum(
            candidate_regimes.loc[regime, "mean_net_relative_return"]
            > baseline_regimes.loc[regime, "mean_net_relative_return"]
            for regime in negative
        )
    )
    positive_noninferior = int(
        sum(
            candidate_regimes.loc[regime, "mean_net_relative_return"]
            >= baseline_regimes.loc[regime, "mean_net_relative_return"] - 0.00025
            for regime in positive
        )
    )

    gates = [
        ("development_mean_delta_ic_positive", float(valid_delta.mean()) > 0),
        ("rolling_252d_positive_rate_ge_75pct", rolling_positive_rate >= 0.75),
        ("cagr_beats_v8", candidate_portfolio["mean_strategy_cagr_across_cohorts"] > baseline_portfolio["mean_strategy_cagr_across_cohorts"]),
        ("sharpe_beats_v8", candidate_portfolio["mean_strategy_sharpe_across_cohorts"] > baseline_portfolio["mean_strategy_sharpe_across_cohorts"]),
        ("terminal_wealth_beats_v8", candidate_portfolio["mean_strategy_terminal_wealth_across_cohorts"] > baseline_portfolio["mean_strategy_terminal_wealth_across_cohorts"]),
        ("relative_return_beats_v8", candidate_portfolio["mean_mean_net_relative_return_across_cohorts"] > baseline_portfolio["mean_mean_net_relative_return_across_cohorts"]),
        ("drawdown_not_worse_by_more_than_10pct_abs", candidate_portfolio["mean_strategy_max_drawdown_across_cohorts"] >= baseline_portfolio["mean_strategy_max_drawdown_across_cohorts"] - 0.10),
        ("calmar_not_below_90pct_v8", candidate_portfolio["mean_strategy_calmar_across_cohorts"] >= 0.90 * baseline_portfolio["mean_strategy_calmar_across_cohorts"]),
        ("cagr_wins_at_least_3_of_5_cohorts", cagr_wins >= 3),
        ("sharpe_wins_at_least_3_of_5_cohorts", sharpe_wins >= 3),
        ("year_relative_return_wins_at_least_half", year_wins >= (len(common_years) + 1) // 2),
        ("wins_all_negative_regimes", negative_wins == len(negative) and len(negative) > 0),
        ("positive_regime_relative_noninferiority", positive_noninferior == len(positive) and len(positive) > 0),
    ]
    return pd.DataFrame(gates, columns=["gate", "passed"]), {
        "rolling_252d_positive_rate": rolling_positive_rate,
        "cohort_cagr_wins": cagr_wins,
        "cohort_sharpe_wins": sharpe_wins,
        "year_relative_return_wins": year_wins,
        "years_compared": int(len(common_years)),
        "negative_regime_wins": negative_wins,
        "negative_regimes_compared": len(negative),
        "positive_regime_noninferior": positive_noninferior,
        "positive_regimes_compared": len(positive),
    }


def main():
    scored = _build_score_panel()
    daily = _daily_ic(scored)
    periods = _build_periods(scored)
    cohorts = base._cohort_summary(periods)
    portfolio = base._portfolio_summary(cohorts)
    years = base._year_summary(periods)
    regimes = base._regime_summary(periods)
    gates, details = _gate_results(daily, cohorts, portfolio, years, regimes)

    passed = int(gates["passed"].sum())
    total = int(len(gates))
    decision = "ADVANCE_TO_FREEZE_DESIGN" if passed == total else "DO_NOT_FREEZE"

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIOD_PATH, index=False)
    cohorts.to_csv(COHORT_PATH, index=False)
    portfolio.to_csv(PORTFOLIO_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    daily.to_csv(DAILY_IC_PATH, index=False)
    gates.to_csv(GATE_PATH, index=False)

    manifest = {
        "research_version": "stock_v10",
        "cycle": CYCLE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_fixed_exit_buffer_validation",
        "hypothesis": "One-session positive confirmation reduces regime-exit turnover while preserving immediate defensive entry.",
        "baseline": BASELINE,
        "candidate_id": CANDIDATE,
        "entry_rule": "defensive immediately when negative_spy20 is true",
        "exit_rule": "return to V8 after exactly one completed non-negative session",
        "exit_buffer_sessions": 1,
        "buffer_tuning": False,
        "top_n": base.TOP_N,
        "equal_weight": True,
        "entry": "next_session_open",
        "hold_sessions": base.HOLD_SESSIONS,
        "cohort_offsets": base.COHORT_OFFSETS,
        "cost_bps_per_dollar_traded": base.PRIMARY_COST_BPS,
        "benchmark": "SPY",
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "gates_passed": passed,
        "gates_total": total,
        "decision": decision,
        **details,
        "candidate_frozen": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V10 CYCLE 2")
    print("=" * 100)
    print("Fixed one-session defensive-exit buffer; no buffer-length search or tuning")
    print(f"Future holdout boundary: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print(gates.to_string(index=False))
    print(f"\nDecision: {decision} | gates {passed}/{total}")
    print("Candidate frozen: NO | holdout scored: NO | V8 modified: NO | orders: OFF")


if __name__ == "__main__":
    main()
