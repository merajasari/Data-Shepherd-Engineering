"""Stock V8 Phase 1: volatility/beta-orthogonal signal discovery.

V8 is a new research track, not a continuation or rescue of V7.

Hypothesis
----------
After removing contemporaneous cross-sectional exposure to 20-session realized
volatility and 60-session beta to SPY, simple trend/reversal/location signals may
retain independent ability to rank 5-session SPY-relative forward returns.

Scientific contract
-------------------
* Universe: all stock feature parquet files except SPY; SPY is benchmark only.
* Target: exact 5-session forward stock return minus exact SPY forward return.
* Candidate signals are fixed before results are inspected and are derived only
  from close/volume history available at the decision close.
* Each candidate signal is residualized cross-sectionally against volatility_20d
  and beta_60 before IC is measured.
* No model fitting, feature-family selection, portfolio simulation, threshold
  tuning, candidate freeze, holdout scoring, state mutation, or brokerage orders.
* V8 has a new untouched holdout beginning 2026-09-01 UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8.config import (
    BENCHMARK_SYMBOL,
    FUTURE_HOLDOUT_START_UTC,
    RESEARCH_VERSION,
    TARGET_HORIZON_SESSIONS,
)

PHASE = 1
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v8/phase1")
PANEL_PATH = OUTPUT_ROOT / "orthogonal_signal_panel.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "signal_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "year_stability.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNALS = [
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "distance_from_high_20d",
    "distance_from_low_20d",
    "close_to_sma20",
    "close_to_sma60",
    "volume_ratio_20d",
]


def _rank_corr(a, b):
    x = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(x) < 20 or x["a"].nunique() < 2 or x["b"].nunique() < 2:
        return np.nan
    return float(x["a"].corr(x["b"], method="spearman"))


def _residualize(y, controls):
    frame = pd.concat([pd.Series(y, name="y"), controls], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    out = pd.Series(np.nan, index=pd.Series(y).index, dtype=float)
    if len(frame) < max(20, controls.shape[1] + 5):
        return out
    X = frame[controls.columns].to_numpy(float)
    X = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X, frame["y"].to_numpy(float), rcond=None)
    out.loc[frame.index] = frame["y"].to_numpy(float) - X @ beta
    return out


def _read_symbol(path, symbol):
    df = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    required = {ts_col, "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{symbol}: missing {missing}")
    df["timestamp_utc"] = pd.to_datetime(df[ts_col], utc=True)
    df = df.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    ret1 = close.pct_change()
    out = pd.DataFrame({
        "timestamp_utc": df["timestamp_utc"],
        "symbol": symbol,
        "close": close,
        "return_1d": ret1,
        "return_5d": close.pct_change(5),
        "return_20d": close.pct_change(20),
        "return_60d": close.pct_change(60),
        "volatility_20d": ret1.rolling(20, min_periods=20).std(ddof=0),
        "distance_from_high_20d": close / close.rolling(20, min_periods=20).max() - 1.0,
        "distance_from_low_20d": close / close.rolling(20, min_periods=20).min() - 1.0,
        "close_to_sma20": close / close.rolling(20, min_periods=20).mean() - 1.0,
        "close_to_sma60": close / close.rolling(60, min_periods=60).mean() - 1.0,
        "volume_ratio_20d": volume / volume.rolling(20, min_periods=20).mean(),
        "forward_return_5d": close.shift(-TARGET_HORIZON_SESSIONS) / close - 1.0,
    })
    return out


def _discover_files():
    paths = sorted(FEATURE_ROOT.glob("*/*.parquet"))
    by_symbol = {}
    for p in paths:
        sym = p.parent.name.upper()
        by_symbol.setdefault(sym, p)
    if BENCHMARK_SYMBOL not in by_symbol:
        raise FileNotFoundError("SPY feature parquet not found")
    return by_symbol


def _build_panel():
    files = _discover_files()
    spy = _read_symbol(files[BENCHMARK_SYMBOL], BENCHMARK_SYMBOL)[["timestamp_utc", "return_1d", "forward_return_5d"]].rename(columns={
        "return_1d": "spy_return_1d",
        "forward_return_5d": "spy_forward_return_5d",
    })

    stock_frames = []
    for symbol, path in files.items():
        if symbol == BENCHMARK_SYMBOL:
            continue
        x = _read_symbol(path, symbol).merge(spy, on="timestamp_utc", how="left", validate="one_to_one")
        x["forward_relative_return_5d"] = x["forward_return_5d"] - x["spy_forward_return_5d"]
        x["beta_60"] = (
            x["return_1d"].rolling(60, min_periods=60).cov(x["spy_return_1d"])
            / x["spy_return_1d"].rolling(60, min_periods=60).var()
        )
        stock_frames.append(x)

    panel = pd.concat(stock_frames, ignore_index=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    return panel


def _orthogonalize(panel):
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        controls = day[["volatility_20d", "beta_60"]].copy()
        for signal in SIGNALS:
            resid = _residualize(day[signal], controls)
            ic = _rank_corr(resid, day["forward_relative_return_5d"])
            rows.append({
                "timestamp_utc": ts,
                "signal_id": signal,
                "asset_count": int(pd.concat([resid, day["forward_relative_return_5d"]], axis=1).dropna().shape[0]),
                "orthogonal_ic": ic,
            })
    return pd.DataFrame(rows)


def _summary(daily):
    rows = []
    for signal, g in daily.groupby("signal_id", sort=True):
        x = g["orthogonal_ic"].dropna()
        rows.append({
            "signal_id": signal,
            "days": int(len(x)),
            "mean_orthogonal_ic": float(x.mean()) if len(x) else np.nan,
            "median_orthogonal_ic": float(x.median()) if len(x) else np.nan,
            "ic_hit_rate": float((x > 0).mean()) if len(x) else np.nan,
            "mean_abs_ic": float(x.abs().mean()) if len(x) else np.nan,
        })
    return pd.DataFrame(rows).sort_values("mean_orthogonal_ic", ascending=False)


def _year_stability(daily):
    x = daily.copy()
    x["year"] = pd.to_datetime(x["timestamp_utc"], utc=True).dt.year
    return (
        x.groupby(["signal_id", "year"], observed=True)
        .agg(
            days=("orthogonal_ic", "count"),
            mean_orthogonal_ic=("orthogonal_ic", "mean"),
            ic_hit_rate=("orthogonal_ic", lambda s: s.dropna().gt(0).mean() if s.notna().any() else np.nan),
        )
        .reset_index()
    )


def main():
    panel = _build_panel()
    daily = _orthogonalize(panel)
    summary = _summary(daily)
    years = _year_stability(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(FOLD_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_volatility_beta_orthogonal_signal_discovery",
        "objective": "Identify simple decision-time stock signals whose 5-session SPY-relative ranking information survives cross-sectional neutralization to 20-session volatility and 60-session SPY beta.",
        "candidate_signals": SIGNALS,
        "neutralization_controls": ["volatility_20d", "beta_60"],
        "target": "forward_relative_return_5d",
        "benchmark": BENCHMARK_SYMBOL,
        "candidate_count": int(panel["symbol"].nunique()),
        "panel_rows": int(len(panel)),
        "date_range": {
            "start": panel["timestamp_utc"].min().isoformat(),
            "end": panel["timestamp_utc"].max().isoformat(),
        },
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "signal_selected": None,
        "candidate_frozen": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "v7_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_fitting": False,
            "portfolio_simulation": False,
            "threshold_optimization": False,
            "signal_selected": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V8 PHASE 1")
    print("=" * 104)
    print("Volatility/beta-orthogonal signal discovery")
    print(f"Candidates: {manifest['candidate_count']} | Rows: {manifest['panel_rows']:,}")
    print(f"Dates: {manifest['date_range']['start']} -> {manifest['date_range']['end']}")
    print()
    print("===== SIGNAL SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== YEAR STABILITY =====")
    print(years.to_string(index=False))
    print()
    print("No model fitting. No signal selection. No portfolio simulation. No holdout score. No orders.")


if __name__ == "__main__":
    main()
