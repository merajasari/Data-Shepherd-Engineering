"""Apply Stock V8 Phase 6 pre-freeze robustness audit."""

from pathlib import Path

PHASE6 = Path("ml/v8/phase6.py")


def main():
    PHASE6.parent.mkdir(parents=True, exist_ok=True)
    PHASE6.write_text(r'''"""Stock V8 Phase 6: pre-freeze robustness audit for DISTANCE_ONLY.

Scientific contract
-------------------
* Audit DISTANCE_ONLY only; no new signals or score search.
* Reuse Phase-5 realized period results at the pre-registered 10 bps cost.
* Top 10, five-session hold, next-open execution, equal weights, and all five
  staggered cohorts remain unchanged.
* Diagnostics only: calendar stability, SPY market regimes, SPY volatility
  regimes, stock contribution/concentration, and leave-one-stock-out sensitivity.
* Regime definitions are descriptive fixed partitions (SPY period return sign;
  SPY period absolute-return tertiles) and are not trading filters.
* No threshold optimization, regime selection, candidate freeze, holdout score,
  paper-state mutation, or brokerage orders.
* 2026-09-01+ V8 holdout remains sealed.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from ml.v8.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

PHASE = 6
PHASE5_ROOT = Path("data/model/v8/phase5")
PERIOD_PATH = PHASE5_ROOT / "economic_period_results.csv"
OUTPUT_ROOT = Path("data/model/v8/phase6")
PRIMARY_COST_BPS = 10
SCORE_ID = "DISTANCE_ONLY"


def _load():
    if not PERIOD_PATH.exists():
        raise FileNotFoundError(f"Missing {PERIOD_PATH}; run V8 Phase 5 first")
    p = pd.read_csv(PERIOD_PATH)
    for c in ["decision_timestamp_utc", "entry_timestamp_utc", "exit_timestamp_utc"]:
        p[c] = pd.to_datetime(p[c], utc=True)
    p = p[(p["score_id"] == SCORE_ID) &
          (p["cost_bps_per_dollar_traded"] == PRIMARY_COST_BPS) &
          (p["exit_timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)].copy()
    if p.empty:
        raise RuntimeError("No eligible V8 Phase-5 DISTANCE_ONLY periods")
    p["year"] = p["decision_timestamp_utc"].dt.year
    return p


def _summary(g):
    return {
        "periods": int(len(g)),
        "mean_net_relative_return": float(g["net_relative_return"].mean()),
        "median_net_relative_return": float(g["net_relative_return"].median()),
        "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
        "mean_net_portfolio_return": float(g["net_portfolio_return"].mean()),
        "mean_spy_return": float(g["spy_return"].mean()),
    }


def _calendar(p):
    rows = []
    for year, g in p.groupby("year", sort=True):
        rows.append({"year": int(year), **_summary(g)})
    return pd.DataFrame(rows)


def _market_regimes(p):
    q = p.copy()
    q["spy_direction_regime"] = np.where(q["spy_return"] < 0, "SPY_DOWN", "SPY_UP_OR_FLAT")
    rows = []
    for regime, g in q.groupby("spy_direction_regime", sort=True):
        rows.append({"regime": regime, **_summary(g)})
    return pd.DataFrame(rows)


def _volatility_regimes(p):
    q = p.copy()
    x = q["spy_return"].abs()
    lo, hi = x.quantile([1/3, 2/3]).tolist()
    q["spy_abs_return_regime"] = pd.cut(
        x, [-np.inf, lo, hi, np.inf], labels=["LOW", "MID", "HIGH"], include_lowest=True
    )
    rows = []
    for regime, g in q.groupby("spy_abs_return_regime", observed=True, sort=True):
        rows.append({"regime": str(regime), "lower_cut": float(lo), "upper_cut": float(hi), **_summary(g)})
    return pd.DataFrame(rows)


def _name_exposure(p):
    counts = {}
    total_slots = 0
    for s in p["symbols"].astype(str):
        names = [x for x in s.split("|") if x]
        total_slots += len(names)
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    rows = [{"symbol": k, "selection_count": v,
             "selection_slot_fraction": float(v / total_slots) if total_slots else np.nan,
             "period_selection_fraction": float(v / len(p))}
            for k, v in counts.items()]
    return pd.DataFrame(rows).sort_values(["selection_count", "symbol"], ascending=[False, True])


def _leave_one_stock_out(p):
    names = sorted({n for s in p["symbols"].astype(str) for n in s.split("|") if n})
    base = float(p["net_relative_return"].mean())
    rows = []
    # Conservative sensitivity proxy: remove every period containing the name.
    # This avoids fabricating constituent-level returns that Phase 5 did not persist.
    for name in names:
        mask = ~p["symbols"].astype(str).str.split("|").apply(lambda xs: name in xs)
        g = p[mask]
        rows.append({
            "symbol": name,
            "remaining_periods": int(len(g)),
            "excluded_periods": int((~mask).sum()),
            "mean_net_relative_return_without_symbol_periods": float(g["net_relative_return"].mean()) if len(g) else np.nan,
            "change_vs_full_mean": float(g["net_relative_return"].mean() - base) if len(g) else np.nan,
            "remains_positive": bool(len(g) and g["net_relative_return"].mean() > 0),
        })
    return pd.DataFrame(rows).sort_values("mean_net_relative_return_without_symbol_periods")


def main():
    p = _load()
    calendar = _calendar(p)
    market = _market_regimes(p)
    vol = _volatility_regimes(p)
    names = _name_exposure(p)
    loo = _leave_one_stock_out(p)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    calendar.to_csv(OUTPUT_ROOT / "calendar_stability.csv", index=False)
    market.to_csv(OUTPUT_ROOT / "market_regime_summary.csv", index=False)
    vol.to_csv(OUTPUT_ROOT / "spy_abs_return_regime_summary.csv", index=False)
    names.to_csv(OUTPUT_ROOT / "name_exposure.csv", index=False)
    loo.to_csv(OUTPUT_ROOT / "leave_one_stock_out.csv", index=False)

    full_mean = float(p["net_relative_return"].mean())
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "development_only_prefreeze_robustness_audit",
        "objective": "Stress-audit the fixed V8 DISTANCE_ONLY candidate before any freeze or future holdout scoring.",
        "score_id": SCORE_ID,
        "top_n": 10,
        "holding_sessions": 5,
        "execution_rule": "decision after completed close; enter next trading-session open; exit five trading sessions later at open",
        "cohort_offsets": [0, 1, 2, 3, 4],
        "primary_cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
        "full_mean_net_relative_return": full_mean,
        "positive_calendar_year_fraction": float((calendar["mean_net_relative_return"] > 0).mean()),
        "positive_market_regime_fraction": float((market["mean_net_relative_return"] > 0).mean()),
        "positive_abs_return_regime_fraction": float((vol["mean_net_relative_return"] > 0).mean()),
        "leave_one_stock_out_all_positive": bool(loo["remains_positive"].all()),
        "max_period_selection_fraction": float(names["period_selection_fraction"].max()),
        "candidate_frozen": False,
        "future_holdout_start_utc": str(FUTURE_HOLDOUT_START_UTC),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False, "v7_modified": False,
            "paper_portfolio_modified": False, "paper_journal_modified": False, "crypto_tracks_modified": False,
            "signal_search": False, "score_weight_tuning": False, "top_n_optimization": False,
            "holding_period_tuning": False, "cost_tuning": False, "regime_filter_tuning": False,
            "candidate_frozen": False, "future_holdout_scored": False, "brokerage_orders": False,
        },
    }
    (OUTPUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V8 PHASE 6")
    print("=" * 100)
    print("Pre-freeze robustness audit: DISTANCE_ONLY | Top 10 | 5 sessions | next-open | 10 bps")
    print(f"Full mean net relative return: {full_mean:.6f}")
    print("\n===== CALENDAR STABILITY =====")
    print(calendar.to_string(index=False))
    print("\n===== MARKET REGIMES =====")
    print(market.to_string(index=False))
    print("\n===== SPY ABS-RETURN REGIMES =====")
    print(vol.to_string(index=False))
    print("\n===== TOP NAME EXPOSURE =====")
    print(names.head(15).to_string(index=False))
    print("\n===== WORST LEAVE-ONE-STOCK-OUT RESULTS =====")
    print(loo.head(15).to_string(index=False))
    print("\nNo tuning. No freeze. No holdout score. No orders.")

if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v8/phase6.py")
    print("Stock V8 Phase 6 pre-freeze robustness patch complete.")
    print("DISTANCE_ONLY only; fixed Phase-5 execution/cost contract; robustness diagnostics only.")
    print("The 2026-09-01+ holdout remains sealed. No freeze, paper-state changes, or orders.")


if __name__ == "__main__":
    main()
