"""Stock V9 Phase 4: formal champion/challenger decision gate.

Consumes Phase 3 summaries only. V8 remains read-only. This phase performs no
parameter tuning, candidate freeze, holdout access, production mutation, or
brokerage activity.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_ROOT = Path("data/model/v9/phase4")
V9_SUMMARY = Path("data/model/v9/phase3/portfolio_summary.csv")
V8_REFERENCE = Path("data/model/v9/phase3/v8_reference_summary.csv")
DECISION_JSON = OUTPUT_ROOT / "decision.json"
COMPARISON_CSV = OUTPUT_ROOT / "champion_challenger_comparison.csv"

V8_ID = "V8_DISTANCE_ONLY"
METRICS = {
    "cagr": ("mean_strategy_cagr_across_cohorts", "strategy_cagr", "higher"),
    "sharpe": ("mean_strategy_sharpe_across_cohorts", "strategy_sharpe", "higher"),
    "sortino": ("mean_strategy_sortino_across_cohorts", "strategy_sortino", "higher"),
    "max_drawdown": ("mean_strategy_max_drawdown_across_cohorts", "strategy_max_drawdown", "higher"),
    "calmar": ("mean_strategy_calmar_across_cohorts", "strategy_calmar", "higher"),
    "terminal_wealth": ("mean_strategy_terminal_wealth_across_cohorts", "strategy_terminal_wealth", "higher"),
    "net_relative_return": ("mean_mean_net_relative_return_across_cohorts", "mean_net_relative_return", "higher"),
    "net_relative_hit_rate": ("mean_net_relative_hit_rate_across_cohorts", "net_relative_hit_rate", "higher"),
}


def _load():
    if not V9_SUMMARY.exists() or not V8_REFERENCE.exists():
        raise FileNotFoundError("Run V9 Phase 3 before Phase 4")
    v9 = pd.read_csv(V9_SUMMARY)
    v8 = pd.read_csv(V8_REFERENCE)
    if v9.empty or v8.empty or "available" not in v8.columns or not v8["available"].astype(bool).all():
        raise RuntimeError("Complete V8 read-only reference is required")
    return v9, v8


def _v8_means(v8):
    return {name: float(pd.to_numeric(v8[v8_col], errors="coerce").mean()) for name, (_, v8_col, _) in METRICS.items()}


def _candidate_metrics(row):
    return {name: float(row[v9_col]) for name, (v9_col, _, _) in METRICS.items()}


def main():
    v9, v8 = _load()
    v8m = _v8_means(v8)
    rows = []
    for _, row in v9.iterrows():
        cid = str(row["score_id"])
        cm = _candidate_metrics(row)
        wins = 0
        rec = {"candidate": cid}
        for metric, (_, _, direction) in METRICS.items():
            cv, vv = cm[metric], v8m[metric]
            win = bool(np.isfinite(cv) and np.isfinite(vv) and (cv > vv if direction == "higher" else cv < vv))
            wins += int(win)
            rec[f"v9_{metric}"] = cv
            rec[f"v8_{metric}"] = vv
            rec[f"beats_v8_{metric}"] = win
        rec["metrics_won"] = wins
        rec["metrics_total"] = len(METRICS)
        rows.append(rec)

    comparison = pd.DataFrame(rows).sort_values(
        ["metrics_won", "v9_sharpe", "v9_cagr"], ascending=[False, False, False]
    ).reset_index(drop=True)
    best = comparison.iloc[0]

    # Promotion is intentionally strict: challenger must beat frozen V8 on every
    # predeclared full-cycle metric. Phase 4 does not optimize this rule.
    promote = bool(best["metrics_won"] == best["metrics_total"])
    disposition = "PROMOTED" if promote else "REJECTED"
    champion = str(best["candidate"]) if promote else V8_ID

    decision = {
        "phase": 4,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "champion": champion,
        "frozen_v8_champion_before_gate": V8_ID,
        "best_v9_challenger": str(best["candidate"]),
        "v9_promotion": disposition,
        "promotion_rule": "best V9 challenger must beat frozen V8 on all predeclared full-cycle metrics",
        "metrics_won_by_best_v9": int(best["metrics_won"]),
        "metrics_total": int(best["metrics_total"]),
        "v8_remains_frozen_champion": not promote,
        "v9_candidate_frozen": False,
        "v9_holdout_opened": False,
        "production_modified": False,
        "brokerage_orders": False,
        "no_tuning": True,
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(COMPARISON_CSV, index=False)
    DECISION_JSON.write_text(json.dumps(decision, indent=2) + "\n")

    print("STOCK V9 PHASE 4")
    print("=" * 88)
    print("Formal champion / challenger gate")
    print(f"Champion: {champion}")
    print(f"Best V9 challenger: {decision['best_v9_challenger']}")
    print(f"V9 promotion: {disposition}")
    print(f"Metrics won: {decision['metrics_won_by_best_v9']}/{decision['metrics_total']}")
    print(f"V8 remains frozen champion: {decision['v8_remains_frozen_champion']}")
    print("V9 candidate frozen: False")
    print("V9 holdout opened: False")
    print("Production modified: False")
    print("Brokerage orders: False")
    print("No tuning. V8 read-only. V9 holdout untouched.")


if __name__ == "__main__":
    main()
