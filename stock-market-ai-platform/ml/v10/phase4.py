"""Stock V10 Phase 4: pre-freeze challenger validation gate.

Consumes only V10 development outputs. It does not score the reserved holdout,
modify V8/production, freeze a candidate, or place orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

OUTPUT_ROOT = Path("data/model/v10/phase4")
PHASE2_ROOT = Path("data/model/v10/phase2")
PHASE3_ROOT = Path("data/model/v10/phase3")

PRIMARY = "switch_on_negative_spy20"
BASELINE = "v8_distance_only"


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    robust = pd.read_csv(PHASE2_ROOT / "robustness_summary.csv").set_index("candidate_id")
    rolling = pd.DataFrame(json.loads((PHASE2_ROOT / "manifest.json").read_text())["rolling_summary"]).set_index("candidate_id")
    portfolio = pd.read_csv(PHASE3_ROOT / "portfolio_summary.csv").set_index("candidate_id")
    cohorts = pd.read_csv(PHASE3_ROOT / "cohort_summary.csv")
    years = pd.read_csv(PHASE3_ROOT / "year_summary.csv")
    regimes = pd.read_csv(PHASE3_ROOT / "regime_summary.csv")

    c, b = portfolio.loc[PRIMARY], portfolio.loc[BASELINE]
    cy = years[years.candidate_id == PRIMARY].set_index("year")
    by = years[years.candidate_id == BASELINE].set_index("year")
    common_years = cy.index.intersection(by.index)
    year_wins = int((cy.loc[common_years, "mean_net_relative_return"] > by.loc[common_years, "mean_net_relative_return"]).sum())

    cc = cohorts[cohorts.candidate_id == PRIMARY].set_index("cohort_offset")
    bc = cohorts[cohorts.candidate_id == BASELINE].set_index("cohort_offset")
    common_cohorts = cc.index.intersection(bc.index)
    cohort_cagr_wins = int((cc.loc[common_cohorts, "strategy_cagr"] > bc.loc[common_cohorts, "strategy_cagr"]).sum())
    cohort_sharpe_wins = int((cc.loc[common_cohorts, "strategy_sharpe"] > bc.loc[common_cohorts, "strategy_sharpe"]).sum())

    cr = regimes[regimes.candidate_id == PRIMARY].set_index("decision_regime")
    br = regimes[regimes.candidate_id == BASELINE].set_index("decision_regime")
    neg = [x for x in cr.index if x.startswith("NEGATIVE_") and x in br.index]
    pos = [x for x in cr.index if x.startswith("POSITIVE_") and x in br.index]
    neg_wins = int(sum(cr.loc[x, "mean_net_relative_return"] > br.loc[x, "mean_net_relative_return"] for x in neg))
    pos_noninferior = int(sum(cr.loc[x, "mean_net_relative_return"] >= br.loc[x, "mean_net_relative_return"] - 0.00025 for x in pos))

    gates = [
        ("development_mean_delta_ic_positive", robust.loc[PRIMARY, "mean_delta_ic_vs_v8"] > 0),
        ("rolling_252d_positive_rate_ge_75pct", rolling.loc[PRIMARY, "positive_252d_windows_rate"] >= 0.75),
        ("cagr_beats_v8", c["mean_strategy_cagr_across_cohorts"] > b["mean_strategy_cagr_across_cohorts"]),
        ("sharpe_beats_v8", c["mean_strategy_sharpe_across_cohorts"] > b["mean_strategy_sharpe_across_cohorts"]),
        ("terminal_wealth_beats_v8", c["mean_strategy_terminal_wealth_across_cohorts"] > b["mean_strategy_terminal_wealth_across_cohorts"]),
        ("relative_return_beats_v8", c["mean_mean_net_relative_return_across_cohorts"] > b["mean_mean_net_relative_return_across_cohorts"]),
        ("drawdown_not_worse_by_more_than_10pct_abs", c["mean_strategy_max_drawdown_across_cohorts"] >= b["mean_strategy_max_drawdown_across_cohorts"] - 0.10),
        ("calmar_not_below_90pct_v8", c["mean_strategy_calmar_across_cohorts"] >= 0.90 * b["mean_strategy_calmar_across_cohorts"]),
        ("cagr_wins_at_least_3_of_5_cohorts", cohort_cagr_wins >= 3),
        ("sharpe_wins_at_least_3_of_5_cohorts", cohort_sharpe_wins >= 3),
        ("year_relative_return_wins_at_least_half", year_wins >= (len(common_years) + 1) // 2),
        ("wins_all_negative_regimes", neg_wins == len(neg) and len(neg) > 0),
        ("positive_regime_relative_noninferiority", pos_noninferior == len(pos) and len(pos) > 0),
    ]
    gate_df = pd.DataFrame(gates, columns=["gate", "passed"])
    gate_df.to_csv(OUTPUT_ROOT / "gate_results.csv", index=False)
    passed = int(gate_df.passed.sum())
    total = int(len(gate_df))
    decision = "ADVANCE_TO_FREEZE_DESIGN" if passed == total else "DO_NOT_FREEZE"

    manifest = {
        "research_version": "stock_v10", "phase": 4,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_pre_freeze_challenger_gate",
        "primary_challenger": PRIMARY, "baseline": BASELINE,
        "gates_passed": passed, "gates_total": total, "decision": decision,
        "cohort_cagr_wins": cohort_cagr_wins, "cohort_sharpe_wins": cohort_sharpe_wins,
        "year_relative_return_wins": year_wins, "years_compared": int(len(common_years)),
        "negative_regime_wins": neg_wins, "negative_regimes_compared": len(neg),
        "positive_regime_noninferior": pos_noninferior, "positive_regimes_compared": len(pos),
        "candidate_frozen": False, "holdout_scored": False, "v8_modified": False,
        "production_modified": False, "brokerage_orders": False,
    }
    (OUTPUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V10 PHASE 4")
    print("=" * 96)
    print("Development-only pre-freeze challenger validation gate")
    print(gate_df.to_string(index=False))
    print(f"\nDecision: {decision} | gates {passed}/{total}")
    print(f"Cohort CAGR wins: {cohort_cagr_wins}/5 | Sharpe wins: {cohort_sharpe_wins}/5")
    print(f"Year relative-return wins: {year_wins}/{len(common_years)}")
    print("No freeze. Holdout untouched. V8/production unchanged. No orders.")


if __name__ == "__main__":
    main()
