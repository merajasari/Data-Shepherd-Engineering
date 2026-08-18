"""Apply isolated Stock V6 Phase 6 rolling-exposure validation."""

from pathlib import Path

PHASE6 = Path("ml/v6/phase6.py")


def main():
    PHASE6.parent.mkdir(parents=True, exist_ok=True)
    PHASE6.write_text(r'''"""Stock V6 Phase 6: final development-side rolling exposure validation.

Purpose
-------
Keep the Elastic Net model, Top-10 sleeve, 60% SPY / 40% stocks, sector cap 3,
5-session rebalance cadence, next-open execution, and cost assumptions fixed.
Test one final, small pre-registered family of rolling individual-name exposure
controls intended to address the remaining Phase 5 repeated-name concentration
failure without using the 2026-02-01+ holdout.

Policies
--------
* sector_cap_3_reference: Phase 5 sector-cap-3 reference, no name exposure cap.
* sector_cap_3_roll4_max2: within each fold, a stock may appear at most twice
  among the previous four completed rebalance selections before being admitted
  to the next selection.
* sector_cap_3_roll6_max3: within each fold, a stock may appear at most three
  times among the previous six completed rebalance selections before being
  admitted to the next selection.

The rolling rules are forward-only and use selection history available before
that rebalance. They do not inspect returns, future ranks, or holdout results.
This is the final development-side portfolio-construction experiment for V6;
Phase 6 does not automatically select or freeze a candidate.

Research safety
---------------
No model refit, feature change, Top-N change, threshold search, holdout scoring,
candidate freeze, portfolio-state mutation, or brokerage orders.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))

from v5_symbols import V5_BENCHMARK_SYMBOL, get_v5_sector  # noqa: E402
from ml.v6.phase3 import (  # noqa: E402
    CORE_WEIGHT,
    STOCK_SLEEVE_WEIGHT,
    REBALANCE_STEP,
    FUTURE_HOLDOUT_START_UTC,
    MODEL_ID,
    _load_inputs,
    _build_execution_map,
    _max_drawdown,
    _risk_metrics,
)

PHASE = 6
TOP_N = 10
SECTOR_CAP = 3
OUTPUT_ROOT = Path("data/model/v6/phase6")
DECISIONS_PATH = OUTPUT_ROOT / "portfolio_decisions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

POLICIES = {
    "sector_cap_3_reference": {"rolling_window": None, "rolling_max": None},
    "sector_cap_3_roll4_max2": {"rolling_window": 4, "rolling_max": 2},
    "sector_cap_3_roll6_max3": {"rolling_window": 6, "rolling_max": 3},
}
COST_BPS_SCENARIOS = (10, 30)


def _select(daily: pd.DataFrame, policy, selection_history):
    chosen = []
    sector_counts = Counter()
    window = policy["rolling_window"]
    rolling_max = policy["rolling_max"]

    recent_counts = Counter()
    if window is not None:
        for prior_selection in list(selection_history)[-window:]:
            recent_counts.update(prior_selection)

    for row in daily.sort_values("predicted_score", ascending=False).itertuples(index=False):
        symbol = row.symbol
        sector = get_v5_sector(symbol)
        if sector_counts[sector] >= SECTOR_CAP:
            continue
        if window is not None and recent_counts[symbol] >= rolling_max:
            continue
        chosen.append(symbol)
        sector_counts[sector] += 1
        if len(chosen) == TOP_N:
            break

    if len(chosen) != TOP_N:
        raise RuntimeError(
            f"Could not fill Top-{TOP_N} under policy={policy}; selected={len(chosen)}"
        )
    return chosen


def _simulate_fold(fold_id, fold_pred, execution, policy_id, cost_bps):
    policy = POLICIES[policy_id]
    dates = pd.Index(sorted(fold_pred["timestamp_utc"].unique()))[::REBALANCE_STEP]
    history = deque()
    previous_weights = {}
    returns = []
    spy_returns = []
    rows = []
    total_cost = 0.0
    total_turnover = 0.0
    trade_actions = 0
    cost_rate = float(cost_bps) / 10_000.0

    spy_exec = execution[execution["symbol"] == V5_BENCHMARK_SYMBOL].set_index(
        "decision_timestamp_utc"
    )

    for decision_date in dates:
        if decision_date >= FUTURE_HOLDOUT_START_UTC:
            raise AssertionError("Holdout reached in V6 Phase 6")

        daily = fold_pred[fold_pred["timestamp_utc"] == decision_date]
        chosen = _select(daily, policy, history)

        desired_weight = STOCK_SLEEVE_WEIGHT / TOP_N
        desired = {s: desired_weight for s in chosen}
        all_symbols = set(previous_weights) | set(desired)
        traded_fraction = (
            sum(
                abs(desired.get(s, 0.0) - previous_weights.get(s, 0.0))
                for s in all_symbols
            )
            if previous_weights
            else STOCK_SLEEVE_WEIGHT
        )
        cost = traded_fraction * cost_rate
        actions = sum(
            1
            for s in all_symbols
            if not np.isclose(desired.get(s, 0.0), previous_weights.get(s, 0.0))
        )

        period = execution[
            (execution["decision_timestamp_utc"] == decision_date)
            & (execution["symbol"].isin(chosen))
        ]
        if len(period) != TOP_N or decision_date not in spy_exec.index:
            continue

        stock_map = dict(zip(period["symbol"], period["execution_return"]))
        sleeve_return = float(np.mean([stock_map[s] for s in chosen]))
        spy_row = spy_exec.loc[decision_date]
        if isinstance(spy_row, pd.DataFrame):
            spy_row = spy_row.iloc[0]
        spy_return = float(spy_row["execution_return"])

        gross = CORE_WEIGHT * spy_return + STOCK_SLEEVE_WEIGHT * sleeve_return
        net = gross - cost

        returns.append(net)
        spy_returns.append(spy_return)
        total_cost += cost
        total_turnover += traded_fraction
        trade_actions += actions
        rows.append(
            {
                "policy_id": policy_id,
                "cost_bps_per_traded_side": cost_bps,
                "fold_id": fold_id,
                "decision_timestamp_utc": decision_date,
                "selected_symbols": chosen,
                "stock_sleeve_return": sleeve_return,
                "spy_return": spy_return,
                "gross_strategy_return": gross,
                "traded_notional_fraction": traded_fraction,
                "modeled_cost": cost,
                "net_strategy_return": net,
            }
        )

        history.append(list(chosen))
        max_history = policy["rolling_window"]
        if max_history is not None:
            while len(history) > max_history:
                history.popleft()
        previous_weights = desired

    strat_eq = float(np.prod(1.0 + np.asarray(returns))) if returns else 1.0
    spy_eq = float(np.prod(1.0 + np.asarray(spy_returns))) if spy_returns else 1.0
    risk = _risk_metrics(returns)

    return {
        "policy_id": policy_id,
        "cost_bps_per_traded_side": int(cost_bps),
        "fold_id": fold_id,
        "rebalance_periods": len(returns),
        "trade_actions": trade_actions,
        "average_traded_notional_fraction": (
            total_turnover / len(returns) if returns else np.nan
        ),
        "total_modeled_cost_fraction": total_cost,
        "strategy_return": strat_eq - 1.0,
        "spy_return": spy_eq - 1.0,
        "excess_ending_equity": strat_eq - spy_eq,
        "max_drawdown": _max_drawdown(returns),
        **risk,
    }, rows


def _concentration(decisions):
    out = []
    base = decisions[decisions["cost_bps_per_traded_side"] == 10]
    for policy_id, group in base.groupby("policy_id"):
        period_count = len(group)
        name_counts = Counter()
        sector_counts = Counter()
        for symbols in group["selected_symbols"]:
            for symbol in symbols:
                name_counts[symbol] += 1
                sector_counts[get_v5_sector(symbol)] += 1
        total_slots = period_count * TOP_N
        for symbol, count in name_counts.items():
            out.append(
                {
                    "policy_id": policy_id,
                    "dimension": "symbol",
                    "key": symbol,
                    "count": count,
                    "selection_period_fraction": count / period_count,
                    "slot_fraction": count / total_slots,
                }
            )
        for sector, count in sector_counts.items():
            out.append(
                {
                    "policy_id": policy_id,
                    "dimension": "sector",
                    "key": sector,
                    "count": count,
                    "selection_period_fraction": np.nan,
                    "slot_fraction": count / total_slots,
                }
            )
    return pd.DataFrame(out)


def main():
    _, predictions, symbols = _load_inputs()
    predictions = predictions[
        (predictions["model_id"] == MODEL_ID)
        & (predictions["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
    ].copy()
    execution = _build_execution_map(symbols)

    fold_rows = []
    decision_rows = []
    for policy_id in POLICIES:
        for cost_bps in COST_BPS_SCENARIOS:
            for fold_id, fold_pred in predictions.groupby("fold_id", sort=True):
                metrics, rows = _simulate_fold(
                    fold_id, fold_pred, execution, policy_id, cost_bps
                )
                fold_rows.append(metrics)
                decision_rows.extend(rows)

    folds = pd.DataFrame(fold_rows)
    decisions = pd.DataFrame(decision_rows)
    concentration = _concentration(decisions)

    summary_rows = []
    for (policy_id, cost_bps), group in folds.groupby(
        ["policy_id", "cost_bps_per_traded_side"], sort=True
    ):
        positive = group["excess_ending_equity"] > 0
        late = group[group["fold_id"].isin(["dev_07", "dev_08", "dev_09"])]
        c = concentration[concentration["policy_id"] == policy_id]
        max_name = c[c["dimension"] == "symbol"]["selection_period_fraction"].max()
        max_sector = c[c["dimension"] == "sector"]["slot_fraction"].max()
        summary_rows.append(
            {
                "policy_id": policy_id,
                "cost_bps_per_traded_side": int(cost_bps),
                "folds": int(len(group)),
                "positive_excess_folds": int(positive.sum()),
                "positive_excess_fold_fraction": float(positive.mean()),
                "mean_strategy_return": float(group["strategy_return"].mean()),
                "mean_spy_return": float(group["spy_return"].mean()),
                "mean_excess_ending_equity": float(group["excess_ending_equity"].mean()),
                "median_excess_ending_equity": float(group["excess_ending_equity"].median()),
                "late_mean_excess_ending_equity": float(late["excess_ending_equity"].mean()),
                "mean_max_drawdown": float(group["max_drawdown"].mean()),
                "worst_max_drawdown": float(group["max_drawdown"].min()),
                "mean_sharpe_like": float(group["sharpe_like"].mean()),
                "mean_traded_notional_fraction": float(
                    group["average_traded_notional_fraction"].mean()
                ),
                "total_modeled_cost_fraction": float(
                    group["total_modeled_cost_fraction"].sum()
                ),
                "max_name_selection_period_fraction": float(max_name),
                "max_sector_slot_fraction": float(max_sector),
            }
        )
    summary = pd.DataFrame(summary_rows)

    eligibility = {}
    for policy_id in POLICIES:
        s10 = summary[
            (summary["policy_id"] == policy_id)
            & (summary["cost_bps_per_traded_side"] == 10)
        ].iloc[0]
        s30 = summary[
            (summary["policy_id"] == policy_id)
            & (summary["cost_bps_per_traded_side"] == 30)
        ].iloc[0]
        gates = {
            "10bps_positive_fold_fraction_at_least_two_thirds": bool(
                s10["positive_excess_fold_fraction"] >= 2 / 3
            ),
            "10bps_mean_excess_positive": bool(s10["mean_excess_ending_equity"] > 0),
            "30bps_mean_excess_positive": bool(s30["mean_excess_ending_equity"] > 0),
            "late_development_mean_excess_positive": bool(
                s10["late_mean_excess_ending_equity"] > 0
            ),
            "max_name_no_more_than_50pct_periods": bool(
                s10["max_name_selection_period_fraction"] <= 0.50 + 1e-12
            ),
            "max_sector_no_more_than_40pct_slots": bool(
                s10["max_sector_slot_fraction"] <= 0.40 + 1e-12
            ),
        }
        eligibility[policy_id] = {
            "gates": gates,
            "all_gates_passed": bool(all(gates.values())),
        }

    eligible = [p for p, x in eligibility.items() if x["all_gates_passed"]]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    decisions.to_parquet(DECISIONS_PATH, index=False)
    folds.to_csv(FOLD_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)

    manifest = {
        "research_version": "v6",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "final_development_rolling_name_exposure_validation",
        "model_id": MODEL_ID,
        "top_n": TOP_N,
        "sector_cap": SECTOR_CAP,
        "candidate_count": 100,
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "candidate_frozen": False,
        "policy_family": POLICIES,
        "cost_bps_scenarios": list(COST_BPS_SCENARIOS),
        "eligibility": eligibility,
        "eligible_policies": eligible,
        "policy_selected": None,
        "policy_selection_deferred": True,
        "development_policy_search_closed_after_phase6": True,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_refit": False,
            "feature_change": False,
            "top_n_changed": False,
            "threshold_tuning": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V6 PHASE 6")
    print("=" * 104)
    print("Fixed model: Elastic Net | Top-10 | sector cap 3 | 60% SPY / 40% stocks")
    print("Final development-side name-exposure experiment; holdout remains sealed")
    print()
    print("===== POLICY SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== ELIGIBILITY =====")
    for policy_id, result in eligibility.items():
        print(policy_id, "PASS" if result["all_gates_passed"] else "FAIL")
        for gate, passed in result["gates"].items():
            print("  ", gate, "PASS" if passed else "FAIL")
    print()
    print("Eligible policies:", eligible if eligible else "NONE")
    print("Development policy search is closed after Phase 6.")
    print("No policy selected or frozen. No holdout score. No brokerage orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v6/phase6.py")
    print()
    print("Stock V6 Phase 6 rolling-exposure patch complete.")
    print("Fixed Elastic Net/Top-10/sector-cap-3; final pre-registered rolling-name exposure family only.")
    print("The 2026-02-01+ holdout remains sealed. No candidate freeze or orders.")


if __name__ == "__main__":
    main()
