"""Apply Stock V8 Phase 5 fixed economic-robustness diagnostics."""

from pathlib import Path

PHASE5 = Path("ml/v8/phase5.py")


def main():
    PHASE5.parent.mkdir(parents=True, exist_ok=True)
    PHASE5.write_text(r'''"""Stock V8 Phase 5: fixed economic robustness diagnostics.

Purpose
-------
Phase 4 showed that DISTANCE_ONLY has the strongest and most chronologically
consistent upper-tail returns, while the untuned 50/50 EQUAL_RANK_BLEND has
better whole-cross-section ranking structure and lower name concentration.
Phase 5 tests whether those two already-defined scores survive a realistic,
causal execution contract and fixed transaction-cost sensitivity.

Scientific contract
-------------------
* Compare DISTANCE_ONLY and the pre-registered EQUAL_RANK_BLEND only.
* Reuse Phase-4 scores exactly; no score or weight tuning.
* Portfolio size is fixed at Top 10 because Phase 4 showed Top-10 DISTANCE_ONLY
  positive in all ten development folds. Phase 5 does not search Top-N.
* Decision uses completed close information; execution enters at the next
  trading-session open and exits five trading sessions later at the open.
* Five staggered non-overlapping 5-session cohorts (offsets 0..4) are all
  evaluated; no cohort is selected.
* Equal weight, long only, fully invested, no leverage, no shorting.
* Transaction-cost sensitivity is fixed at 0, 5, 10, 25, and 50 bps per dollar
  traded. Ten bps is the pre-registered primary reporting assumption.
* Costs are charged on actual equal-weight transition notional between one
  Top-10 basket and the next within each staggered cohort. First entry is also
  charged; final mark-to-market is not forcibly liquidated.
* SPY is measured over the identical next-open to five-session-later-open
  interval. It is a benchmark, not an investable candidate.
* No cost tuning, portfolio-rule tuning, candidate freeze, holdout scoring,
  paper-state mutation, or brokerage orders.
* 2026-09-01+ V8 holdout remains sealed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

PHASE = 5
PHASE4_PANEL = Path("data/model/v8/phase4/fixed_complementarity_ranked_panel.parquet")
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v8/phase5")
PERIOD_PATH = OUTPUT_ROOT / "economic_period_results.csv"
COST_SUMMARY_PATH = OUTPUT_ROOT / "cost_sensitivity_summary.csv"
COHORT_PATH = OUTPUT_ROOT / "cohort_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SCORES = ["DISTANCE_ONLY", "EQUAL_RANK_BLEND"]
TOP_N = 10
HOLD_SESSIONS = 5
COHORT_OFFSETS = [0, 1, 2, 3, 4]
COST_BPS = [0, 5, 10, 25, 50]
PRIMARY_COST_BPS = 10


def _fold_id(ts):
    year = pd.Timestamp(ts).year
    if year <= 2017:
        return "dev_01"
    mapping = {
        2018: "dev_02", 2019: "dev_03", 2020: "dev_04",
        2021: "dev_05", 2022: "dev_06", 2023: "dev_07",
        2024: "dev_08", 2025: "dev_09", 2026: "dev_10",
    }
    return mapping.get(year)


def _discover_feature_files():
    files = {}
    for p in sorted(FEATURE_ROOT.glob("*/*.parquet")):
        files.setdefault(p.parent.name.upper(), p)
    if "SPY" not in files:
        raise FileNotFoundError("SPY feature parquet not found under data/features/stocks")
    return files


def _open_series(path):
    df = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    if ts_col not in df.columns or "open" not in df.columns:
        raise ValueError(f"{path}: timestamp/open columns required for Phase 5")
    out = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(df[ts_col], utc=True),
        "open": pd.to_numeric(df["open"], errors="coerce"),
    })
    return out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last").set_index("timestamp_utc")["open"]


def _load_execution_data(symbols):
    files = _discover_feature_files()
    missing = sorted(set(symbols) - set(files))
    if missing:
        raise FileNotFoundError("Missing feature parquet for: " + ", ".join(missing))
    opens = {sym: _open_series(files[sym]) for sym in sorted(set(symbols) | {"SPY"})}
    spy = opens["SPY"].dropna().sort_index()
    trading_dates = list(spy.index)
    date_to_idx = {ts: i for i, ts in enumerate(trading_dates)}
    return opens, trading_dates, date_to_idx


def _load_ranked():
    if not PHASE4_PANEL.exists():
        raise FileNotFoundError(f"Missing V8 Phase-4 ranked panel: {PHASE4_PANEL}. Run Phase 4 first.")
    p = pd.read_parquet(PHASE4_PANEL).copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    p = p[(p["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC) & p["score_id"].isin(SCORES)].copy()
    required = {"timestamp_utc", "symbol", "score_id", "score"}
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError("Phase-4 panel missing: " + ", ".join(missing))
    return p


def _transition_notional(previous_symbols, new_symbols):
    # Sum absolute changes in equal weights. First entry from cash has notional 1.
    new_w = {s: 1.0 / TOP_N for s in new_symbols}
    if previous_symbols is None:
        return float(sum(new_w.values()))
    old_w = {s: 1.0 / TOP_N for s in previous_symbols}
    names = set(old_w) | set(new_w)
    return float(sum(abs(new_w.get(s, 0.0) - old_w.get(s, 0.0)) for s in names))


def _build_periods():
    ranked = _load_ranked()
    symbols = ranked["symbol"].astype(str).unique().tolist()
    opens, trading_dates, date_to_idx = _load_execution_data(symbols)

    raw = []
    for score_id in SCORES:
        score_panel = ranked[ranked["score_id"] == score_id]
        decisions = sorted(score_panel["timestamp_utc"].unique())
        for decision_ts in decisions:
            if decision_ts not in date_to_idx:
                continue
            i = date_to_idx[decision_ts]
            if i + 1 >= len(trading_dates) or i + 1 + HOLD_SESSIONS >= len(trading_dates):
                continue
            entry_ts = trading_dates[i + 1]
            exit_ts = trading_dates[i + 1 + HOLD_SESSIONS]
            if exit_ts >= FUTURE_HOLDOUT_START_UTC:
                continue

            day = score_panel[score_panel["timestamp_utc"] == decision_ts].sort_values(
                ["score", "symbol"], ascending=[False, True]
            )
            picks = day.head(TOP_N)["symbol"].astype(str).tolist()
            if len(picks) != TOP_N:
                continue

            stock_returns = []
            valid = True
            for sym in picks:
                s = opens[sym]
                if entry_ts not in s.index or exit_ts not in s.index:
                    valid = False
                    break
                p0 = s.loc[entry_ts]
                p1 = s.loc[exit_ts]
                if not np.isfinite(p0) or not np.isfinite(p1) or p0 <= 0:
                    valid = False
                    break
                stock_returns.append(float(p1 / p0 - 1.0))
            if not valid:
                continue

            spy = opens["SPY"]
            if entry_ts not in spy.index or exit_ts not in spy.index:
                continue
            spy0, spy1 = spy.loc[entry_ts], spy.loc[exit_ts]
            if not np.isfinite(spy0) or not np.isfinite(spy1) or spy0 <= 0:
                continue

            raw.append({
                "score_id": score_id,
                "decision_timestamp_utc": decision_ts,
                "entry_timestamp_utc": entry_ts,
                "exit_timestamp_utc": exit_ts,
                "decision_index": i,
                "cohort_offset": int(i % HOLD_SESSIONS),
                "fold_id": _fold_id(decision_ts),
                "symbols": "|".join(picks),
                "gross_portfolio_return": float(np.mean(stock_returns)),
                "spy_return": float(spy1 / spy0 - 1.0),
            })

    periods = pd.DataFrame(raw)
    if periods.empty:
        raise RuntimeError("No V8 Phase-5 executable periods produced")

    # Keep only true non-overlapping sequences inside each offset: every fifth
    # trading-session decision. Duplicate/unexpected dates cannot sneak through.
    periods = periods.sort_values(["score_id", "cohort_offset", "decision_index"]).reset_index(drop=True)
    out = []
    for (score_id, offset), g in periods.groupby(["score_id", "cohort_offset"], sort=True):
        previous = None
        for _, row in g.iterrows():
            picks = row["symbols"].split("|")
            traded = _transition_notional(previous, picks)
            base = row.to_dict()
            base["transition_notional"] = traded
            for bps in COST_BPS:
                cost_rate = traded * bps / 10000.0
                net_return = (1.0 + base["gross_portfolio_return"]) * (1.0 - cost_rate) - 1.0
                rec = dict(base)
                rec["cost_bps_per_dollar_traded"] = int(bps)
                rec["modeled_transaction_cost_rate"] = float(cost_rate)
                rec["net_portfolio_return"] = float(net_return)
                rec["gross_relative_return"] = float(base["gross_portfolio_return"] - base["spy_return"])
                rec["net_relative_return"] = float(net_return - base["spy_return"])
                out.append(rec)
            previous = picks
    return pd.DataFrame(out)


def _max_drawdown(returns):
    wealth = (1.0 + pd.Series(returns, dtype=float)).cumprod()
    if wealth.empty:
        return np.nan
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def _summarize_group(g):
    x = g.sort_values("entry_timestamp_utc")
    strat_wealth = float((1.0 + x["net_portfolio_return"]).prod())
    spy_wealth = float((1.0 + x["spy_return"]).prod())
    return {
        "periods": int(len(x)),
        "mean_gross_portfolio_return": float(x["gross_portfolio_return"].mean()),
        "mean_net_portfolio_return": float(x["net_portfolio_return"].mean()),
        "mean_spy_return": float(x["spy_return"].mean()),
        "mean_net_relative_return": float(x["net_relative_return"].mean()),
        "median_net_relative_return": float(x["net_relative_return"].median()),
        "net_relative_hit_rate": float((x["net_relative_return"] > 0).mean()),
        "mean_transition_notional": float(x["transition_notional"].mean()),
        "mean_modeled_cost_rate": float(x["modeled_transaction_cost_rate"].mean()),
        "strategy_terminal_wealth": strat_wealth,
        "spy_terminal_wealth": spy_wealth,
        "strategy_minus_spy_terminal_wealth": float(strat_wealth - spy_wealth),
        "strategy_max_drawdown": _max_drawdown(x["net_portfolio_return"]),
        "spy_max_drawdown": _max_drawdown(x["spy_return"]),
    }


def _cost_summary(periods):
    rows = []
    for (score_id, bps), g in periods.groupby(["score_id", "cost_bps_per_dollar_traded"], sort=True):
        # Average cohort-level economics so one stagger does not dominate by one
        # extra observation at either endpoint.
        cohort_metrics = []
        for offset, c in g.groupby("cohort_offset", sort=True):
            rec = _summarize_group(c)
            rec["cohort_offset"] = int(offset)
            cohort_metrics.append(rec)
        cdf = pd.DataFrame(cohort_metrics)
        rows.append({
            "score_id": score_id,
            "cost_bps_per_dollar_traded": int(bps),
            "cohorts": int(len(cdf)),
            "mean_periods_per_cohort": float(cdf["periods"].mean()),
            "mean_net_relative_return_across_cohorts": float(cdf["mean_net_relative_return"].mean()),
            "mean_net_relative_hit_rate_across_cohorts": float(cdf["net_relative_hit_rate"].mean()),
            "positive_mean_net_relative_cohorts": int((cdf["mean_net_relative_return"] > 0).sum()),
            "mean_strategy_terminal_wealth": float(cdf["strategy_terminal_wealth"].mean()),
            "mean_spy_terminal_wealth": float(cdf["spy_terminal_wealth"].mean()),
            "mean_strategy_minus_spy_terminal_wealth": float(cdf["strategy_minus_spy_terminal_wealth"].mean()),
            "mean_strategy_max_drawdown": float(cdf["strategy_max_drawdown"].mean()),
            "mean_spy_max_drawdown": float(cdf["spy_max_drawdown"].mean()),
            "mean_transition_notional": float(cdf["mean_transition_notional"].mean()),
            "mean_modeled_cost_rate": float(cdf["mean_modeled_cost_rate"].mean()),
        })
    return pd.DataFrame(rows)


def _cohort_summary(periods):
    p = periods[periods["cost_bps_per_dollar_traded"] == PRIMARY_COST_BPS]
    rows = []
    for (score_id, offset), g in p.groupby(["score_id", "cohort_offset"], sort=True):
        rows.append({"score_id": score_id, "cohort_offset": int(offset), **_summarize_group(g)})
    return pd.DataFrame(rows)


def _fold_summary(periods):
    p = periods[periods["cost_bps_per_dollar_traded"] == PRIMARY_COST_BPS]
    rows = []
    for (score_id, fold_id), g in p.groupby(["score_id", "fold_id"], sort=True):
        rows.append({
            "score_id": score_id,
            "fold_id": fold_id,
            "periods": int(len(g)),
            "mean_net_relative_return": float(g["net_relative_return"].mean()),
            "median_net_relative_return": float(g["net_relative_return"].median()),
            "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
            "mean_gross_relative_return": float(g["gross_relative_return"].mean()),
            "mean_transition_notional": float(g["transition_notional"].mean()),
        })
    return pd.DataFrame(rows)


def main():
    periods = _build_periods()
    costs = _cost_summary(periods)
    cohorts = _cohort_summary(periods)
    folds = _fold_summary(periods)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIOD_PATH, index=False)
    costs.to_csv(COST_SUMMARY_PATH, index=False)
    cohorts.to_csv(COHORT_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)

    primary = costs[costs["cost_bps_per_dollar_traded"] == PRIMARY_COST_BPS].to_dict(orient="records")
    fold_gate = (
        folds.groupby("score_id")
        .agg(
            total_folds=("fold_id", "count"),
            positive_net_relative_folds=("mean_net_relative_return", lambda s: int((s > 0).sum())),
        )
        .reset_index()
        .to_dict(orient="records")
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_fixed_economic_robustness",
        "objective": "Compare DISTANCE_ONLY versus the pre-registered 50/50 EQUAL_RANK_BLEND under fixed causal next-open execution, five staggered 5-session cohorts, and fixed transaction-cost sensitivity.",
        "scores": SCORES,
        "top_n": TOP_N,
        "top_n_optimized": False,
        "holding_sessions": HOLD_SESSIONS,
        "execution_rule": "decision after completed close; enter next trading-session open; exit five trading sessions later at open",
        "cohort_offsets": COHORT_OFFSETS,
        "cohort_selection": False,
        "weighting": "equal weight across fixed Top 10",
        "leverage": False,
        "shorting": False,
        "transaction_cost_bps_per_dollar_traded": COST_BPS,
        "primary_cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
        "cost_policy": "transition cost = sum absolute equal-weight changes times bps; first entry charged; no forced terminal liquidation",
        "primary_cost_summary": primary,
        "primary_cost_fold_gate_summary": fold_gate,
        "score_selected": None,
        "candidate_frozen": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False,
            "v7_modified": False, "paper_portfolio_modified": False,
            "paper_journal_modified": False, "crypto_tracks_modified": False,
            "score_weight_tuning": False, "top_n_optimization": False,
            "holding_period_tuning": False, "cost_tuning": False,
            "cohort_selection": False, "candidate_frozen": False,
            "future_holdout_scored": False, "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V8 PHASE 5")
    print("=" * 112)
    print("Fixed economic robustness: DISTANCE_ONLY vs EQUAL_RANK_BLEND")
    print(f"Top {TOP_N} | next-open execution | hold {HOLD_SESSIONS} sessions | five staggered cohorts")
    print(f"Cost sensitivity (bps per dollar traded): {COST_BPS} | primary={PRIMARY_COST_BPS}")
    print()
    print("===== COST SENSITIVITY SUMMARY =====")
    print(costs.to_string(index=False))
    print()
    print(f"===== COHORT SUMMARY @ {PRIMARY_COST_BPS} BPS =====")
    print(cohorts.to_string(index=False))
    print()
    print(f"===== FOLD SUMMARY @ {PRIMARY_COST_BPS} BPS =====")
    print(folds.to_string(index=False))
    print()
    print("No tuning. No score selection. No freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v8/phase5.py")
    print()
    print("Stock V8 Phase 5 fixed economic-robustness patch complete.")
    print("DISTANCE_ONLY vs fixed 50/50 blend; Top-10; next-open execution; five staggered cohorts.")
    print("Fixed 0/5/10/25/50 bps cost sensitivity; 10 bps primary. No tuning or score selection.")
    print("The 2026-09-01+ holdout remains sealed. No freeze, paper-state changes, or orders.")


if __name__ == "__main__":
    main()
