"""Stock V9 Phase 3: fixed-contract portfolio simulation.

Purpose
-------
Translate the three already-defined Phase-2 V9 scores into executable portfolio
economics under the same primary execution contract used by frozen V8.

Scientific contract
-------------------
* Scores are fixed before Phase 3 results are inspected:
    - downside_vol_ratio_20
    - volume_trend_5_20
    - equal_weight_rank_blend (fixed 50/50 rank blend)
* No score search or blend-weight optimization.
* Portfolio is fixed Top 10, equal weight, long only, fully invested.
* Decision uses completed-session information only.
* Entry is next trading-session open; exit is five sessions later at the open.
* All five cohort offsets 0..4 are evaluated; none is selected.
* Primary transaction cost is fixed at 10 bps per dollar traded.
* Costs are charged on actual equal-weight transition notional; first entry from
  cash is charged and no forced final liquidation is added.
* SPY is benchmark only and is measured over the identical entry/exit interval.
* V8 is read-only. V8 holdout evidence is never read or modified.
* V9 future holdout beginning 2026-10-01 UTC remains untouched.
* No Top-N optimization, holding-period tuning, cost tuning, candidate freeze,
  production-state mutation, or brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v9.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v9.phase2 import SURVIVORS, BLEND_ID, SCORES, _build_score_panel

PHASE = 3
PHASE1_PANEL = Path("data/model/v9/phase1/complementary_signal_panel.parquet")
FEATURE_ROOT = Path("data/features/stocks")
V8_PHASE5_PERIODS = Path("data/model/v8/phase5/economic_period_results.csv")
OUTPUT_ROOT = Path("data/model/v9/phase3")
PERIOD_PATH = OUTPUT_ROOT / "economic_period_results.csv"
SUMMARY_PATH = OUTPUT_ROOT / "portfolio_summary.csv"
COHORT_PATH = OUTPUT_ROOT / "cohort_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_summary.csv"
V8_PATH = OUTPUT_ROOT / "v8_reference_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

TOP_N = 10
HOLD_SESSIONS = 5
COHORT_OFFSETS = [0, 1, 2, 3, 4]
PRIMARY_COST_BPS = 10
PERIODS_PER_YEAR = 252.0 / HOLD_SESSIONS


def _discover_feature_files():
    files = {}
    for p in sorted(FEATURE_ROOT.glob("*/*.parquet")):
        files.setdefault(p.parent.name.upper(), p)
    if "SPY" not in files:
        raise FileNotFoundError("SPY feature parquet not found under data/features/stocks")
    return files


def _open_series(path: Path):
    df = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    if ts_col not in df.columns or "open" not in df.columns:
        raise ValueError(f"{path}: timestamp/open columns required for V9 Phase 3")
    out = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(df[ts_col], utc=True),
        "open": pd.to_numeric(df["open"], errors="coerce"),
    })
    return (
        out.dropna(subset=["timestamp_utc"])
        .sort_values("timestamp_utc")
        .drop_duplicates("timestamp_utc", keep="last")
        .set_index("timestamp_utc")["open"]
    )


def _load_execution_data(symbols):
    files = _discover_feature_files()
    missing = sorted(set(symbols) - set(files))
    if missing:
        raise FileNotFoundError("Missing feature parquet for: " + ", ".join(missing))
    opens = {sym: _open_series(files[sym]) for sym in sorted(set(symbols) | {"SPY"})}
    trading_dates = list(opens["SPY"].dropna().sort_index().index)
    date_to_idx = {ts: i for i, ts in enumerate(trading_dates)}
    return opens, trading_dates, date_to_idx


def _load_score_panel():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(f"Missing {PHASE1_PANEL}; run V9 Phase 1 first")
    panel = pd.read_parquet(PHASE1_PANEL).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase-1 panel reaches V9 future holdout boundary; refusing to score holdout data")
    score_panel = _build_score_panel(panel)
    score_panel["timestamp_utc"] = pd.to_datetime(score_panel["timestamp_utc"], utc=True)
    return score_panel


def _transition_notional(previous_symbols, new_symbols):
    new_w = {s: 1.0 / TOP_N for s in new_symbols}
    if previous_symbols is None:
        return float(sum(new_w.values()))
    old_w = {s: 1.0 / TOP_N for s in previous_symbols}
    names = set(old_w) | set(new_w)
    return float(sum(abs(new_w.get(s, 0.0) - old_w.get(s, 0.0)) for s in names))


def _build_periods():
    ranked = _load_score_panel()
    symbols = ranked["symbol"].astype(str).unique().tolist()
    opens, trading_dates, date_to_idx = _load_execution_data(symbols)

    raw = []
    for score_id in SCORES:
        score_panel = ranked[ranked["score_id"] == score_id]
        decisions = sorted(score_panel["timestamp_utc"].unique())
        for decision_ts in decisions:
            decision_ts = pd.Timestamp(decision_ts)
            if decision_ts not in date_to_idx:
                continue
            i = date_to_idx[decision_ts]
            entry_i = i + 1
            exit_i = entry_i + HOLD_SESSIONS
            if exit_i >= len(trading_dates):
                continue
            entry_ts = trading_dates[entry_i]
            exit_ts = trading_dates[exit_i]
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
                p0, p1 = s.loc[entry_ts], s.loc[exit_ts]
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
                "decision_index": int(i),
                "cohort_offset": int(i % HOLD_SESSIONS),
                "symbols": "|".join(picks),
                "gross_portfolio_return": float(np.mean(stock_returns)),
                "spy_return": float(spy1 / spy0 - 1.0),
            })

    periods = pd.DataFrame(raw)
    if periods.empty:
        raise RuntimeError("No V9 Phase-3 executable periods produced")

    periods = periods.sort_values(["score_id", "cohort_offset", "decision_index"]).reset_index(drop=True)
    out = []
    for (score_id, offset), g in periods.groupby(["score_id", "cohort_offset"], sort=True):
        previous = None
        for _, row in g.iterrows():
            picks = row["symbols"].split("|")
            traded = _transition_notional(previous, picks)
            cost_rate = traded * PRIMARY_COST_BPS / 10000.0
            gross = float(row["gross_portfolio_return"])
            net = (1.0 + gross) * (1.0 - cost_rate) - 1.0
            rec = row.to_dict()
            rec["transition_notional"] = float(traded)
            rec["cost_bps_per_dollar_traded"] = PRIMARY_COST_BPS
            rec["modeled_transaction_cost_rate"] = float(cost_rate)
            rec["net_portfolio_return"] = float(net)
            rec["gross_relative_return"] = float(gross - row["spy_return"])
            rec["net_relative_return"] = float(net - row["spy_return"])
            rec["transaction_cost_drag"] = float(gross - net)
            out.append(rec)
            previous = picks
    return pd.DataFrame(out)


def _max_drawdown(returns):
    x = pd.Series(returns, dtype=float).dropna()
    if x.empty:
        return np.nan
    wealth = (1.0 + x).cumprod()
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def _annualized_stats(returns):
    x = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return {"terminal_wealth": np.nan, "cagr": np.nan, "annualized_volatility": np.nan, "sharpe": np.nan, "sortino": np.nan, "max_drawdown": np.nan, "calmar": np.nan}
    wealth = float((1.0 + x).prod())
    years = len(x) / PERIODS_PER_YEAR
    cagr = float(wealth ** (1.0 / years) - 1.0) if wealth > 0 and years > 0 else np.nan
    vol = float(x.std(ddof=0) * np.sqrt(PERIODS_PER_YEAR)) if len(x) > 1 else np.nan
    ann_mean = float(x.mean() * PERIODS_PER_YEAR)
    sharpe = float(ann_mean / vol) if np.isfinite(vol) and vol > 0 else np.nan
    downside = x[x < 0]
    downside_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(PERIODS_PER_YEAR)) if len(downside) else np.nan
    sortino = float(ann_mean / downside_dev) if np.isfinite(downside_dev) and downside_dev > 0 else np.nan
    mdd = _max_drawdown(x)
    calmar = float(cagr / abs(mdd)) if np.isfinite(cagr) and np.isfinite(mdd) and mdd < 0 else np.nan
    return {"terminal_wealth": wealth, "cagr": cagr, "annualized_volatility": vol, "sharpe": sharpe, "sortino": sortino, "max_drawdown": mdd, "calmar": calmar}


def _cohort_summary(periods):
    rows = []
    for (score_id, offset), g in periods.groupby(["score_id", "cohort_offset"], sort=True):
        g = g.sort_values("entry_timestamp_utc")
        s = _annualized_stats(g["net_portfolio_return"])
        spy_s = _annualized_stats(g["spy_return"])
        rows.append({
            "score_id": score_id,
            "cohort_offset": int(offset),
            "periods": int(len(g)),
            **{f"strategy_{k}": v for k, v in s.items()},
            **{f"spy_{k}": v for k, v in spy_s.items()},
            "mean_gross_portfolio_return": float(g["gross_portfolio_return"].mean()),
            "mean_net_portfolio_return": float(g["net_portfolio_return"].mean()),
            "mean_spy_return": float(g["spy_return"].mean()),
            "mean_net_relative_return": float(g["net_relative_return"].mean()),
            "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
            "mean_transition_notional": float(g["transition_notional"].mean()),
            "mean_cost_drag": float(g["transaction_cost_drag"].mean()),
        })
    return pd.DataFrame(rows)


def _portfolio_summary(cohorts):
    metric_cols = [
        "strategy_terminal_wealth", "strategy_cagr", "strategy_annualized_volatility",
        "strategy_sharpe", "strategy_sortino", "strategy_max_drawdown", "strategy_calmar",
        "spy_terminal_wealth", "spy_cagr", "mean_net_relative_return", "net_relative_hit_rate",
        "mean_transition_notional", "mean_cost_drag",
    ]
    rows = []
    for score_id, g in cohorts.groupby("score_id", sort=True):
        rec = {"score_id": score_id, "cohorts": int(len(g)), "mean_periods_per_cohort": float(g["periods"].mean())}
        for col in metric_cols:
            rec[f"mean_{col}_across_cohorts"] = float(g[col].mean())
        rec["positive_cagr_cohorts"] = int((g["strategy_cagr"] > 0).sum())
        rec["strategy_beats_spy_terminal_wealth_cohorts"] = int((g["strategy_terminal_wealth"] > g["spy_terminal_wealth"]).sum())
        rows.append(rec)
    return pd.DataFrame(rows)


def _year_summary(periods):
    x = periods.copy()
    x["year"] = pd.to_datetime(x["entry_timestamp_utc"], utc=True).dt.year
    rows = []
    for (score_id, year), g in x.groupby(["score_id", "year"], sort=True):
        rows.append({
            "score_id": score_id,
            "year": int(year),
            "periods": int(len(g)),
            "mean_net_portfolio_return": float(g["net_portfolio_return"].mean()),
            "mean_spy_return": float(g["spy_return"].mean()),
            "mean_net_relative_return": float(g["net_relative_return"].mean()),
            "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
            "mean_transition_notional": float(g["transition_notional"].mean()),
        })
    return pd.DataFrame(rows)


def _regime_summary(periods):
    x = periods.copy()
    median_abs_spy = float(x["spy_return"].abs().median())
    x["trend_regime"] = np.where(x["spy_return"] >= 0, "SPY_UP", "SPY_DOWN")
    x["vol_regime"] = np.where(x["spy_return"].abs() >= median_abs_spy, "HIGH_ABS_SPY_MOVE", "LOW_ABS_SPY_MOVE")
    rows = []
    for regime_type in ["trend_regime", "vol_regime"]:
        for (score_id, regime), g in x.groupby(["score_id", regime_type], sort=True):
            rows.append({
                "score_id": score_id,
                "regime_type": regime_type,
                "regime": regime,
                "periods": int(len(g)),
                "mean_net_portfolio_return": float(g["net_portfolio_return"].mean()),
                "mean_spy_return": float(g["spy_return"].mean()),
                "mean_net_relative_return": float(g["net_relative_return"].mean()),
                "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
            })
    return pd.DataFrame(rows)


def _v8_reference_summary():
    if not V8_PHASE5_PERIODS.exists():
        return pd.DataFrame([{"available": False, "reason": f"Missing {V8_PHASE5_PERIODS}; V8 reference not fabricated."}])
    v8 = pd.read_csv(V8_PHASE5_PERIODS)
    if "cost_bps_per_dollar_traded" in v8.columns:
        v8 = v8[v8["cost_bps_per_dollar_traded"] == PRIMARY_COST_BPS].copy()
    if "score_id" in v8.columns:
        v8 = v8[v8["score_id"] == "DISTANCE_ONLY"].copy()
    if v8.empty:
        return pd.DataFrame([{"available": False, "reason": "V8 Phase-5 primary DISTANCE_ONLY reference rows unavailable."}])
    rows = []
    for offset, g in v8.groupby("cohort_offset", sort=True):
        s = _annualized_stats(g["net_portfolio_return"])
        spy_s = _annualized_stats(g["spy_return"])
        rows.append({
            "available": True,
            "reference": "V8_DISTANCE_ONLY",
            "cohort_offset": int(offset),
            "periods": int(len(g)),
            "strategy_terminal_wealth": s["terminal_wealth"],
            "strategy_cagr": s["cagr"],
            "strategy_sharpe": s["sharpe"],
            "strategy_sortino": s["sortino"],
            "strategy_max_drawdown": s["max_drawdown"],
            "strategy_calmar": s["calmar"],
            "spy_terminal_wealth": spy_s["terminal_wealth"],
            "mean_net_relative_return": float(g["net_relative_return"].mean()),
            "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
        })
    return pd.DataFrame(rows)


def main():
    periods = _build_periods()
    cohorts = _cohort_summary(periods)
    summary = _portfolio_summary(cohorts)
    years = _year_summary(periods)
    regimes = _regime_summary(periods)
    v8_reference = _v8_reference_summary()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIOD_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    cohorts.to_csv(COHORT_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    v8_reference.to_csv(V8_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_fixed_contract_portfolio_simulation",
        "score_ids": SCORES,
        "portfolio_contract": {
            "top_n": TOP_N,
            "weighting": "equal_weight",
            "long_only": True,
            "fully_invested": True,
            "decision_information": "completed session only",
            "entry": "next trading-session open",
            "holding_sessions": HOLD_SESSIONS,
            "exit": "open five trading sessions after entry",
            "cohort_offsets": COHORT_OFFSETS,
            "cohort_selection": False,
            "primary_cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
            "cost_basis": "actual equal-weight transition notional",
        },
        "annualization": {"periods_per_year_per_cohort": PERIODS_PER_YEAR, "note": "risk/return metrics computed within each non-overlapping cohort, then averaged across all five cohorts"},
        "v8_reference_source": str(V8_PHASE5_PERIODS),
        "candidate_selected": None,
        "candidate_frozen": False,
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "research_safety": {
            "v8_modified": False,
            "v8_holdout_scored": False,
            "v8_holdout_journal_modified": False,
            "blend_weight_optimization": False,
            "top_n_optimization": False,
            "holding_period_tuning": False,
            "cost_tuning": False,
            "cohort_selection": False,
            "candidate_frozen": False,
            "v9_future_holdout_scored": False,
            "production_state_modified": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V9 PHASE 3")
    print("=" * 112)
    print("Fixed-contract portfolio simulation under frozen V8 execution mechanics")
    print(f"Top {TOP_N} equal weight | next-open entry | {HOLD_SESSIONS}-session hold | {PRIMARY_COST_BPS} bps | cohorts 0..4")
    print(f"V9 untouched holdout begins: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print()
    print("===== PORTFOLIO SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== COHORT SUMMARY =====")
    print(cohorts.to_string(index=False))
    print()
    print("===== YEAR SUMMARY =====")
    print(years.to_string(index=False))
    print()
    print("===== REGIME SUMMARY =====")
    print(regimes.to_string(index=False))
    print()
    print("===== V8 READ-ONLY REFERENCE =====")
    print(v8_reference.to_string(index=False))
    print()
    print("No tuning. No candidate freeze. V8 unchanged. V9 holdout untouched. No orders.")


if __name__ == "__main__":
    main()
