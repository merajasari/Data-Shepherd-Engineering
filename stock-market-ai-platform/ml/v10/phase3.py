"""Stock V10 Phase 3: fixed-contract portfolio simulation.

Purpose
-------
Translate the already-fixed V10 regime-conditioned ranking rules into portfolio
economics under the same execution contract used by frozen V8.

Scientific contract
-------------------
* Candidates are fixed before Phase 3 results are inspected:
    - v8_distance_only
    - switch_on_negative_spy20
    - switch_on_highvol_negative_spy20
* No threshold, lookback, blend-weight, Top-N, holding-period, or cost tuning.
* Top 10 equal weight, long only, fully invested.
* Decision uses completed-session information only.
* Entry is next trading-session open; exit is five sessions later at the open.
* All five cohort offsets 0..4 are evaluated; none is selected.
* Transaction cost is fixed at 10 bps per dollar traded.
* SPY is benchmark only over the identical entry/exit interval.
* Frozen V8 remains read-only and unchanged.
* V10 future holdout beginning 2026-11-02 UTC remains untouched.
* No candidate freeze, production-state mutation, or brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10.config import (
    FUTURE_HOLDOUT_START_UTC,
    RESEARCH_VERSION,
    SPY_TREND_LOOKBACK,
    SPY_VOL_BASELINE_LOOKBACK,
    SPY_VOL_LOOKBACK,
)

PHASE = 3
PHASE1_PANEL = Path("data/model/v10/source_panel/complementary_signal_panel.parquet")
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v10/phase3")
PERIOD_PATH = OUTPUT_ROOT / "economic_period_results.csv"
SUMMARY_PATH = OUTPUT_ROOT / "portfolio_summary.csv"
COHORT_PATH = OUTPUT_ROOT / "cohort_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

TOP_N = 10
HOLD_SESSIONS = 5
COHORT_OFFSETS = [0, 1, 2, 3, 4]
PRIMARY_COST_BPS = 10
PERIODS_PER_YEAR = 252.0 / HOLD_SESSIONS

V8_ID = "v8_distance_only"
SWITCH_NEG = "switch_on_negative_spy20"
SWITCH_HV_NEG = "switch_on_highvol_negative_spy20"
CANDIDATES = [V8_ID, SWITCH_NEG, SWITCH_HV_NEG]


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
        raise ValueError(f"{path}: timestamp/open columns required for V10 Phase 3")
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


def _load_panel():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(f"Missing {PHASE1_PANEL}; run python -m ml.v10.source_panel first")
    p = pd.read_parquet(PHASE1_PANEL).copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    if p["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Source panel reaches V10 future holdout boundary; refusing to score holdout data")
    required = {
        "timestamp_utc", "symbol", "distance_from_low_20d",
        "downside_vol_ratio_20", "volume_trend_5_20", "spy_return_1d",
    }
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError(f"V10 Phase 3 source panel missing columns: {missing}")
    return p


def _market_state(panel):
    spy = (
        panel[["timestamp_utc", "spy_return_1d"]]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .copy()
    )
    r = pd.to_numeric(spy["spy_return_1d"], errors="coerce")
    spy["spy_trailing_return_20"] = (1.0 + r).rolling(
        SPY_TREND_LOOKBACK, min_periods=SPY_TREND_LOOKBACK
    ).apply(np.prod, raw=True) - 1.0
    spy["spy_vol_20"] = r.rolling(SPY_VOL_LOOKBACK, min_periods=SPY_VOL_LOOKBACK).std(ddof=0)
    spy["spy_vol_baseline"] = (
        spy["spy_vol_20"].shift(1)
        .rolling(SPY_VOL_BASELINE_LOOKBACK, min_periods=60)
        .median()
    )
    spy["negative_spy20"] = spy["spy_trailing_return_20"] < 0
    spy["high_vol"] = spy["spy_vol_20"] > spy["spy_vol_baseline"]
    spy["decision_regime"] = np.select(
        [
            spy["negative_spy20"] & spy["high_vol"],
            spy["negative_spy20"] & ~spy["high_vol"],
            ~spy["negative_spy20"] & spy["high_vol"],
        ],
        ["NEGATIVE_HIGH_VOL", "NEGATIVE_LOW_VOL", "POSITIVE_HIGH_VOL"],
        default="POSITIVE_LOW_VOL",
    )
    return spy


def _build_score_panel(panel):
    state = _market_state(panel)
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        d = day.copy()
        base = pd.to_numeric(d["distance_from_low_20d"], errors="coerce")
        r1 = pd.to_numeric(d["downside_vol_ratio_20"], errors="coerce").rank(pct=True, method="average")
        r2 = pd.to_numeric(d["volume_trend_5_20"], errors="coerce").rank(pct=True, method="average")
        defensive = 0.5 * r1 + 0.5 * r2
        st = state[state["timestamp_utc"] == ts]
        if st.empty:
            continue
        neg = bool(st["negative_spy20"].iloc[0]) if pd.notna(st["negative_spy20"].iloc[0]) else False
        high = bool(st["high_vol"].iloc[0]) if pd.notna(st["high_vol"].iloc[0]) else False
        regime = str(st["decision_regime"].iloc[0])

        candidate_scores = {
            V8_ID: base,
            SWITCH_NEG: defensive if neg else base,
            SWITCH_HV_NEG: defensive if (neg and high) else base,
        }
        for cid, score in candidate_scores.items():
            x = pd.DataFrame({
                "candidate_id": cid,
                "timestamp_utc": ts,
                "symbol": d["symbol"].astype(str).values,
                "score": pd.to_numeric(score, errors="coerce").values,
                "negative_spy20": neg,
                "high_vol": high,
                "decision_regime": regime,
            })
            rows.append(x)
    return pd.concat(rows, ignore_index=True)


def _transition_notional(previous_symbols, new_symbols):
    new_w = {s: 1.0 / TOP_N for s in new_symbols}
    if previous_symbols is None:
        return float(sum(new_w.values()))
    old_w = {s: 1.0 / TOP_N for s in previous_symbols}
    names = set(old_w) | set(new_w)
    return float(sum(abs(new_w.get(s, 0.0) - old_w.get(s, 0.0)) for s in names))


def _build_periods():
    panel = _load_panel()
    ranked = _build_score_panel(panel)
    symbols = ranked["symbol"].unique().tolist()
    opens, trading_dates, date_to_idx = _load_execution_data(symbols)

    raw = []
    for cid in CANDIDATES:
        score_panel = ranked[ranked["candidate_id"] == cid]
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

            day = score_panel[score_panel["timestamp_utc"] == decision_ts].dropna(subset=["score"])
            day = day.sort_values(["score", "symbol"], ascending=[False, True])
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
                "candidate_id": cid,
                "decision_timestamp_utc": decision_ts,
                "entry_timestamp_utc": entry_ts,
                "exit_timestamp_utc": exit_ts,
                "decision_index": int(i),
                "cohort_offset": int(i % HOLD_SESSIONS),
                "decision_regime": str(day["decision_regime"].iloc[0]),
                "negative_spy20": bool(day["negative_spy20"].iloc[0]),
                "high_vol": bool(day["high_vol"].iloc[0]),
                "symbols": "|".join(picks),
                "gross_portfolio_return": float(np.mean(stock_returns)),
                "spy_return": float(spy1 / spy0 - 1.0),
            })

    periods = pd.DataFrame(raw)
    if periods.empty:
        raise RuntimeError("No V10 Phase-3 executable periods produced")

    periods = periods.sort_values(["candidate_id", "cohort_offset", "decision_index"]).reset_index(drop=True)
    out = []
    for (cid, offset), g in periods.groupby(["candidate_id", "cohort_offset"], sort=True):
        previous = None
        for _, row in g.iterrows():
            picks = row["symbols"].split("|")
            traded = _transition_notional(previous, picks)
            cost_rate = traded * PRIMARY_COST_BPS / 10000.0
            gross = float(row["gross_portfolio_return"])
            net = (1.0 + gross) * (1.0 - cost_rate) - 1.0
            rec = row.to_dict()
            rec["transition_notional"] = float(traded)
            rec["modeled_transaction_cost_rate"] = float(cost_rate)
            rec["net_portfolio_return"] = float(net)
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
        return {k: np.nan for k in ["terminal_wealth", "cagr", "annualized_volatility", "sharpe", "sortino", "max_drawdown", "calmar"]}
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
    for (cid, offset), g in periods.groupby(["candidate_id", "cohort_offset"], sort=True):
        g = g.sort_values("entry_timestamp_utc")
        s = _annualized_stats(g["net_portfolio_return"])
        spy_s = _annualized_stats(g["spy_return"])
        rows.append({
            "candidate_id": cid,
            "cohort_offset": int(offset),
            "periods": int(len(g)),
            **{f"strategy_{k}": v for k, v in s.items()},
            **{f"spy_{k}": v for k, v in spy_s.items()},
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
    for cid, g in cohorts.groupby("candidate_id", sort=True):
        rec = {"candidate_id": cid, "cohorts": int(len(g)), "mean_periods_per_cohort": float(g["periods"].mean())}
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
    for (cid, year), g in x.groupby(["candidate_id", "year"], sort=True):
        rows.append({
            "candidate_id": cid,
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
    rows = []
    for (cid, regime), g in periods.groupby(["candidate_id", "decision_regime"], sort=True):
        rows.append({
            "candidate_id": cid,
            "decision_regime": regime,
            "periods": int(len(g)),
            "mean_net_portfolio_return": float(g["net_portfolio_return"].mean()),
            "mean_spy_return": float(g["spy_return"].mean()),
            "mean_net_relative_return": float(g["net_relative_return"].mean()),
            "net_relative_hit_rate": float((g["net_relative_return"] > 0).mean()),
            "mean_transition_notional": float(g["transition_notional"].mean()),
            "mean_cost_drag": float(g["transaction_cost_drag"].mean()),
        })
    return pd.DataFrame(rows)


def main():
    periods = _build_periods()
    cohorts = _cohort_summary(periods)
    portfolio = _portfolio_summary(cohorts)
    years = _year_summary(periods)
    regimes = _regime_summary(periods)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIOD_PATH, index=False)
    cohorts.to_csv(COHORT_PATH, index=False)
    portfolio.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_fixed_contract_portfolio_simulation",
        "candidates": CANDIDATES,
        "primary_challenger": SWITCH_NEG,
        "secondary_comparator": SWITCH_HV_NEG,
        "top_n": TOP_N,
        "equal_weight": True,
        "entry": "next_session_open",
        "hold_sessions": HOLD_SESSIONS,
        "cohort_offsets": COHORT_OFFSETS,
        "cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
        "benchmark": "SPY",
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "threshold_tuning": False,
        "lookback_tuning": False,
        "blend_weight_tuning": False,
        "top_n_tuning": False,
        "holding_period_tuning": False,
        "cost_tuning": False,
        "candidate_frozen": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V10 PHASE 3")
    print("=" * 104)
    print("Fixed-contract portfolio simulation under frozen V8 execution mechanics")
    print(f"Top {TOP_N} equal weight | next-open entry | {HOLD_SESSIONS}-session hold | {PRIMARY_COST_BPS} bps | cohorts 0..4")
    print(f"V10 untouched holdout begins: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print("\nPORTFOLIO SUMMARY")
    print(portfolio.to_string(index=False))
    print("\nNo tuning. No candidate freeze. V8 unchanged. V10 holdout untouched. No orders.")


if __name__ == "__main__":
    main()
