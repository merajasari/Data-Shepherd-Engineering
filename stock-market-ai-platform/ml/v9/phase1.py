"""Stock V9 Phase 1: complementary signal discovery beyond frozen V8.

V9 is a new research track. It does not modify, retune, or rescue V8.

Hypothesis
----------
After removing contemporaneous cross-sectional exposure to the frozen V8 raw
signal (distance_from_low_20d), 20-session volatility, and 60-session SPY beta,
features describing trend acceleration, return consistency, downside asymmetry,
and volume participation may retain independent ability to rank 5-session
SPY-relative forward returns.

Scientific contract
-------------------
* Universe: the existing stock feature parquet universe excluding SPY.
* Target: exact 5-session forward stock return minus exact SPY forward return.
* Candidate features are fixed in code before results are inspected.
* Every candidate is derived only from information available at decision close.
* Every candidate is residualized same-day cross-sectionally against the frozen
  V8 raw feature plus volatility_20d and beta_60 before IC is measured.
* Phase 1 performs discovery diagnostics only: no signal selection, model fit,
  portfolio simulation, Top-N tuning, holding-period tuning, cost tuning,
  candidate freeze, production state mutation, or brokerage orders.
* V8 frozen artifacts and the V8 Sep-2026 forward holdout are never modified or
  scored by this module.
* V9 reserves its own untouched future holdout beginning 2026-10-01 UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v9.config import (
    BENCHMARK_SYMBOL,
    FUTURE_HOLDOUT_START_UTC,
    RESEARCH_VERSION,
    TARGET_HORIZON_SESSIONS,
)

PHASE = 1
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v9/phase1")
PANEL_PATH = OUTPUT_ROOT / "complementary_signal_panel.parquet"
DAILY_IC_PATH = OUTPUT_ROOT / "daily_orthogonal_ic.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "signal_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNALS = [
    "momentum_accel_5_20",
    "momentum_accel_20_60",
    "positive_day_fraction_20",
    "return_consistency_20",
    "downside_vol_ratio_20",
    "volume_trend_5_20",
    "overnight_gap_1d",
    "intraday_return_1d",
]
CONTROLS = ["distance_from_low_20d", "volatility_20d", "beta_60"]


def _rank_corr(a, b):
    x = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < 20 or x["a"].nunique() < 2 or x["b"].nunique() < 2:
        return np.nan
    return float(x["a"].corr(x["b"], method="spearman"))


def _residualize(y, controls):
    frame = pd.concat([pd.Series(y, name="y"), controls], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    out = pd.Series(np.nan, index=pd.Series(y).index, dtype=float)
    if len(frame) < max(25, controls.shape[1] + 8):
        return out
    X = frame[list(controls.columns)].to_numpy(float)
    X = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X, frame["y"].to_numpy(float), rcond=None)
    out.loc[frame.index] = frame["y"].to_numpy(float) - X @ beta
    return out


def _discover_files():
    by_symbol = {}
    for p in sorted(FEATURE_ROOT.glob("*/*.parquet")):
        by_symbol.setdefault(p.parent.name.upper(), p)
    if BENCHMARK_SYMBOL not in by_symbol:
        raise FileNotFoundError("SPY feature parquet not found")
    return by_symbol


def _read_symbol(path: Path, symbol: str):
    d = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in d.columns else "timestamp"
    required = {ts_col, "open", "close"}
    missing = sorted(required - set(d.columns))
    if missing:
        raise ValueError(f"{symbol}: missing {missing}")

    ts = pd.to_datetime(d[ts_col], utc=True, errors="coerce")
    close = pd.to_numeric(d["close"], errors="coerce")
    open_ = pd.to_numeric(d["open"], errors="coerce")
    volume = pd.to_numeric(d["volume"], errors="coerce") if "volume" in d.columns else pd.Series(np.nan, index=d.index)

    x = pd.DataFrame({"timestamp_utc": ts, "open": open_, "close": close, "volume": volume})
    x = x.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")

    r1 = x["close"].pct_change()
    r5 = x["close"].pct_change(5)
    r20 = x["close"].pct_change(20)
    r60 = x["close"].pct_change(60)
    vol20 = r1.rolling(20, min_periods=20).std(ddof=0)
    downside20 = r1.clip(upper=0).rolling(20, min_periods=20).std(ddof=0)
    positive_fraction20 = r1.gt(0).astype(float).rolling(20, min_periods=20).mean()
    sign_consistency20 = np.sign(r1).rolling(20, min_periods=20).mean()
    v5 = x["volume"].rolling(5, min_periods=5).mean()
    v20 = x["volume"].rolling(20, min_periods=20).mean()
    prev_close = x["close"].shift(1)

    out = pd.DataFrame({
        "timestamp_utc": x["timestamp_utc"],
        "symbol": symbol,
        "return_1d": r1,
        "return_5d": r5,
        "return_20d": r20,
        "return_60d": r60,
        "volatility_20d": vol20,
        "distance_from_low_20d": x["close"] / x["close"].rolling(20, min_periods=20).min() - 1.0,
        "momentum_accel_5_20": r5 - (r20 / 4.0),
        "momentum_accel_20_60": r20 - (r60 / 3.0),
        "positive_day_fraction_20": positive_fraction20,
        "return_consistency_20": sign_consistency20,
        "downside_vol_ratio_20": downside20 / vol20,
        "volume_trend_5_20": v5 / v20 - 1.0,
        "overnight_gap_1d": x["open"] / prev_close - 1.0,
        "intraday_return_1d": x["close"] / x["open"] - 1.0,
        "forward_return_5d": x["close"].shift(-TARGET_HORIZON_SESSIONS) / x["close"] - 1.0,
    })
    return out


def _build_panel():
    files = _discover_files()
    spy = _read_symbol(files[BENCHMARK_SYMBOL], BENCHMARK_SYMBOL)[
        ["timestamp_utc", "return_1d", "forward_return_5d"]
    ].rename(columns={
        "return_1d": "spy_return_1d",
        "forward_return_5d": "spy_forward_return_5d",
    })

    frames = []
    for symbol, path in files.items():
        if symbol == BENCHMARK_SYMBOL:
            continue
        x = _read_symbol(path, symbol).merge(spy, on="timestamp_utc", how="left", validate="one_to_one")
        x["forward_relative_return_5d"] = x["forward_return_5d"] - x["spy_forward_return_5d"]
        x["beta_60"] = (
            x["return_1d"].rolling(60, min_periods=60).cov(x["spy_return_1d"])
            / x["spy_return_1d"].rolling(60, min_periods=60).var()
        )
        frames.append(x)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    return panel


def _orthogonal_ic(panel):
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        controls = day[CONTROLS].copy()
        target = day["forward_relative_return_5d"]
        for signal in SIGNALS:
            resid = _residualize(day[signal], controls)
            valid = pd.concat([resid.rename("signal"), target.rename("target")], axis=1).dropna()
            rows.append({
                "timestamp_utc": ts,
                "signal_id": signal,
                "asset_count": int(len(valid)),
                "orthogonal_ic": _rank_corr(resid, target),
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
            "ic_std": float(x.std(ddof=0)) if len(x) else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["mean_orthogonal_ic", "ic_hit_rate"], ascending=[False, False])


def _year_stability(daily):
    x = daily.copy()
    x["year"] = pd.to_datetime(x["timestamp_utc"], utc=True).dt.year
    return (
        x.groupby(["signal_id", "year"], observed=True)
        .agg(
            days=("orthogonal_ic", "count"),
            mean_orthogonal_ic=("orthogonal_ic", "mean"),
            median_orthogonal_ic=("orthogonal_ic", "median"),
            ic_hit_rate=("orthogonal_ic", lambda s: s.dropna().gt(0).mean() if s.notna().any() else np.nan),
        )
        .reset_index()
    )


def main():
    panel = _build_panel()
    daily = _orthogonal_ic(panel)
    summary = _summary(daily)
    years = _year_stability(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    daily.to_parquet(DAILY_IC_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_complementary_signal_discovery",
        "objective": "Find decision-time signals with incremental 5-session SPY-relative cross-sectional information after neutralizing the frozen V8 raw signal, realized volatility, and SPY beta.",
        "hypothesis": "Trend acceleration, consistency, downside asymmetry, and volume/price participation can contain ranking information not explained by frozen V8 distance-from-low exposure, volatility, or beta.",
        "candidate_signals": SIGNALS,
        "neutralization_controls": CONTROLS,
        "target": "forward_relative_return_5d",
        "benchmark": BENCHMARK_SYMBOL,
        "candidate_count": int(panel["symbol"].nunique()),
        "panel_rows": int(len(panel)),
        "date_range": {
            "start": panel["timestamp_utc"].min().isoformat(),
            "end": panel["timestamp_utc"].max().isoformat(),
        },
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "signal_selected": None,
        "candidate_frozen": False,
        "research_safety": {
            "v8_modified": False,
            "v8_holdout_scored": False,
            "v8_holdout_journal_modified": False,
            "paper_state_modified": False,
            "crypto_tracks_modified": False,
            "model_fitting": False,
            "portfolio_simulation": False,
            "signal_selection": False,
            "top_n_optimization": False,
            "holding_period_tuning": False,
            "cost_tuning": False,
            "v9_candidate_frozen": False,
            "v9_future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V9 PHASE 1")
    print("=" * 104)
    print("Complementary signal discovery beyond frozen V8")
    print(f"Candidates: {manifest['candidate_count']} | Rows: {manifest['panel_rows']:,}")
    print(f"Dates: {manifest['date_range']['start']} -> {manifest['date_range']['end']}")
    print(f"V9 untouched holdout begins: {manifest['v9_future_holdout_start_utc']}")
    print()
    print("===== SIGNAL SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== YEAR STABILITY =====")
    print(years.to_string(index=False))
    print()
    print("No signal selection. No model fit. No portfolio simulation. V8 unchanged. No holdout score. No orders.")


if __name__ == "__main__":
    main()
