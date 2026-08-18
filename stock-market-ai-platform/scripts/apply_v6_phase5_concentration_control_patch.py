"""Apply isolated Stock V6 Phase 5 concentration-control validation."""

from pathlib import Path

PHASE5 = Path("ml/v6/phase5.py")


def main():
    PHASE5.parent.mkdir(parents=True, exist_ok=True)
    PHASE5.write_text(r'''"""Stock V6 Phase 5: concentration-controlled development validation.

Purpose
-------
Keep the Elastic Net ranking model, Top-10 sleeve, 60% SPY / 40% stocks,
5-session rebalance cadence, and next-open execution fixed. Test only a small
pre-registered diversification family designed to address the Phase 4 name and
sector concentration failures. The final 2026-02-01+ holdout remains sealed.

Policies
--------
* baseline_top10: unchanged Phase 4 reference.
* sector_cap_3: at most 3 Top-10 names from one sector per rebalance.
* sector_cap_3_no_consecutive: sector cap 3 plus no stock may be held in two
  consecutive rebalance periods.
* sector_cap_2_no_consecutive: sector cap 2 plus no consecutive stock holding.

The no-consecutive rule is deliberately simple and forward-only: it depends
only on the previous rebalance selection, never future outcomes.

Research safety
---------------
No model refit, feature change, Top-N change, threshold search, holdout scoring,
candidate freeze, portfolio-state mutation, or brokerage orders.
"""

from __future__ import annotations

from collections import Counter
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

PHASE = 5
TOP_N = 10
OUTPUT_ROOT = Path("data/model/v6/phase5")
DECISIONS_PATH = OUTPUT_ROOT / "portfolio_decisions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

POLICIES = {
    "baseline_top10": {"sector_cap": None, "no_consecutive": False},
    "sector_cap_3": {"sector_cap": 3, "no_consecutive": False},
    "sector_cap_3_no_consecutive": {"sector_cap": 3, "no_consecutive": True},
    "sector_cap_2_no_consecutive": {"sector_cap": 2, "no_consecutive": True},
}
COST_BPS_SCENARIOS = (10, 30)


def _select(daily: pd.DataFrame, policy, previous):
    chosen = []
    sector_counts = Counter()
    cap = policy["sector_cap"]
    no_consecutive = policy["no_consecutive"]

    for row in daily.sort_values("predicted_score", ascending=False).itertuples(index=False):
        symbol = row.symbol
        sector = get_v5_sector(symbol)
        if no_consecutive and symbol in previous:
            continue
        if cap is not None and sector_counts[sector] >= cap:
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
    previous = []
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
            raise AssertionError("Holdout reached in V6 Phase 5")
        daily = fold_pred[fold_pred["timestamp_utc"] == decision_date]
        chosen = _select(daily, policy, previous)

        desired_weight = STOCK_SLEEVE_WEIGHT / TOP_N
        desired = {s: desired_weight for s in chosen}
        all_symbols = set(previous_weights) | set(desired)
        # Correct traded-notional accounting: sells and buys are both traded.
        traded_fraction = sum(
            abs(desired.get(s, 0.0) - previous_weights.get(s, 0.0))
            for s in all_symbols
        ) if previous_weights else STOCK_SLEEVE_WEIGHT
        cost = traded_fraction * cost_rate
        actions = sum(
            1 for s in all_symbols
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
        rows.append({
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
        })
        previous = chosen
        previous_weights = desired

    strat_eq = float(np.prod(1.0 + np.asarray(returns))) if returns else 1.0
    spy_eq = float(np.prod(1.0 + np.asarray(spy_returns))) if spy_returns else 1.0
    risk = _risk_metrics(returns)
    return {
        "policy_id": policy_id,
        "cost_bps_per_traded_side": cost_bps,
        "fold_id": fold_id,
        "rebalance_periods": len(returns),
        "trade_actions": trade_actions,
        "average_traded_notional_fraction": total_turnover / len(returns) if returns else np.nan,
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
            for s in symbols:
                name_counts[s] += 1
                sector_counts[get_v5_sector(s)] += 1
        total_slots = period_count * TOP_N
        for symbol, count in name_counts.items():
            out.append({
                "policy_id": policy_id,
                "dimension": "symbol",
                "key": symbol,
                "count": count,
                "selection_period_fraction": count / period_count,
                "slot_fraction": count / total_slots,
            })
        for sector, count in sector_counts.items():
            out.append({
                "policy_id": policy_id,
                "dimension": "sector",
                "key": sector,
                "count": count,
                "selection_period_fraction": np.nan,
                "slot_fraction": count / total_slots,
            })
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
        summary_rows.append({
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
            "mean_traded_notional_fraction": float(group["average_traded_notional_fraction"].mean()),
            "total_modeled_cost_fraction": float(group["total_modeled_cost_fraction"].sum()),
            "max_name_selection_period_fraction": float(max_name),
            "max_sector_slot_fraction": float(max_sector),
        })
    summary = pd.DataFrame(summary_rows)

    eligibility = {}
    for policy_id in POLICIES:
        s10 = summary[(summary["policy_id"] == policy_id) & (summary["cost_bps_per_traded_side"] == 10)].iloc[0]
        s30 = summary[(summary["policy_id"] == policy_id) & (summary["cost_bps_per_traded_side"] == 30)].iloc[0]
        gates = {
            "10bps_positive_fold_fraction_at_least_two_thirds": bool(s10["positive_excess_fold_fraction"] >= 2/3),
            "10bps_mean_excess_positive": bool(s10["mean_excess_ending_equity"] > 0),
            "30bps_mean_excess_positive": bool(s30["mean_excess_ending_equity"] > 0),
            "late_development_mean_excess_positive": bool(s10["late_mean_excess_ending_equity"] > 0),
            "max_name_no_more_than_50pct_periods": bool(s10["max_name_selection_period_fraction"] <= 0.50 + 1e-12),
            "max_sector_no_more_than_40pct_slots": bool(s10["max_sector_slot_fraction"] <= 0.40 + 1e-12),
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
        "stage": "development_only_concentration_control_validation",
        "model_id": MODEL_ID,
        "top_n": TOP_N,
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

    print("STOCK V6 PHASE 5")
    print("=" * 104)
    print("Fixed model: Elastic Net | Top-10 | 60% SPY / 40% stocks")
    print("Development only; 2026-02-01+ holdout remains sealed")
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
    print("No policy selected or frozen. No holdout score. No brokerage orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v6/phase5.py")
    print()
    print("Stock V6 Phase 5 concentration-control patch complete.")
    print("Fixed Elastic Net/Top-10; pre-registered sector caps and no-consecutive diversification only.")
    print("The 2026-02-01+ holdout remains sealed. No candidate freeze or orders.")


if __name__ == "__main__":
    main()
