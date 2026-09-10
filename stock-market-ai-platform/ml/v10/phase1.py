"""Stock V10 Phase 1: regime-conditioned ranking discovery.

Hypothesis
----------
The defensive information discovered in V9 may be useful conditionally rather
than as an always-on replacement for frozen V8. V10 therefore asks whether a
predeclared decision-time market-state switch can improve cross-sectional
5-session SPY-relative ranking information while leaving V8 untouched.

Scientific contract
-------------------
* Development-only diagnostics; no portfolio simulation or production changes.
* Frozen V8 raw score proxy: distance_from_low_20d.
* V9 defensive score: fixed 50/50 cross-sectional rank blend of
  downside_vol_ratio_20 and volume_trend_5_20.
* Regime states use SPY information available at the decision close only.
* Candidate switch rules are fixed in code before results are inspected.
* V10 future holdout beginning 2026-11-02 UTC is never scored.
* No Top-N tuning, holding-period tuning, blend-weight tuning, candidate freeze,
  brokerage orders, or V8 mutation.
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

PHASE = 1
SOURCE_PANEL = Path("data/model/v9/phase1/complementary_signal_panel.parquet")
OUTPUT_ROOT = Path("data/model/v10/phase1")
DAILY_PATH = OUTPUT_ROOT / "daily_regime_ic.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "regime_conditioned_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_breakdown.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BASELINE = "v8_distance_only"
DEFENSIVE = "v9_fixed_defensive_blend"
CANDIDATES = [
    BASELINE,
    "switch_on_negative_spy20",
    "switch_on_highvol_negative_spy20",
]


def _rank_corr(a, b):
    x = pd.DataFrame({"a": a, "b": b}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < 20 or x["a"].nunique() < 2 or x["b"].nunique() < 2:
        return np.nan
    return float(x["a"].corr(x["b"], method="spearman"))


def _load_panel():
    if not SOURCE_PANEL.exists():
        raise FileNotFoundError(f"Missing {SOURCE_PANEL}; run V9 Phase 1 first")
    p = pd.read_parquet(SOURCE_PANEL).copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    if p["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Source panel reaches V10 future holdout boundary; refusing to score holdout data")
    required = {
        "timestamp_utc", "symbol", "distance_from_low_20d",
        "downside_vol_ratio_20", "volume_trend_5_20",
        "spy_return_1d", "forward_relative_return_5d",
    }
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError(f"V10 Phase 1 source panel missing columns: {missing}")
    return p


def _market_state(panel):
    spy = (
        panel[["timestamp_utc", "spy_return_1d"]]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .copy()
    )
    r = pd.to_numeric(spy["spy_return_1d"], errors="coerce")
    spy["spy_trailing_return_20"] = (1.0 + r).rolling(SPY_TREND_LOOKBACK, min_periods=SPY_TREND_LOOKBACK).apply(np.prod, raw=True) - 1.0
    spy["spy_vol_20"] = r.rolling(SPY_VOL_LOOKBACK, min_periods=SPY_VOL_LOOKBACK).std(ddof=0)
    # Expanding/rolling baseline is lagged one session so today's state never uses
    # today's volatility to define its historical threshold.
    spy["spy_vol_baseline"] = (
        spy["spy_vol_20"].shift(1)
        .rolling(SPY_VOL_BASELINE_LOOKBACK, min_periods=60)
        .median()
    )
    spy["negative_spy20"] = spy["spy_trailing_return_20"] < 0
    spy["high_vol"] = spy["spy_vol_20"] > spy["spy_vol_baseline"]
    spy["regime"] = np.select(
        [
            spy["negative_spy20"] & spy["high_vol"],
            spy["negative_spy20"] & ~spy["high_vol"],
            ~spy["negative_spy20"] & spy["high_vol"],
        ],
        ["NEGATIVE_HIGH_VOL", "NEGATIVE_LOW_VOL", "POSITIVE_HIGH_VOL"],
        default="POSITIVE_LOW_VOL",
    )
    return spy


def _cross_sectional_scores(panel):
    parts = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        d = day.copy()
        # Higher V8 score means farther above the recent low, matching the existing
        # DISTANCE_ONLY orientation used by the frozen research lineage.
        d[BASELINE] = pd.to_numeric(d["distance_from_low_20d"], errors="coerce")
        r1 = pd.to_numeric(d["downside_vol_ratio_20"], errors="coerce").rank(pct=True, method="average")
        r2 = pd.to_numeric(d["volume_trend_5_20"], errors="coerce").rank(pct=True, method="average")
        d[DEFENSIVE] = 0.5 * r1 + 0.5 * r2
        parts.append(d[["timestamp_utc", "symbol", "forward_relative_return_5d", BASELINE, DEFENSIVE]])
    return pd.concat(parts, ignore_index=True)


def _daily_diagnostics(panel):
    state = _market_state(panel)
    scores = _cross_sectional_scores(panel).merge(state, on="timestamp_utc", how="left", validate="many_to_one")
    rows = []
    for ts, day in scores.groupby("timestamp_utc", sort=True):
        if day.empty:
            continue
        neg = bool(day["negative_spy20"].iloc[0]) if pd.notna(day["negative_spy20"].iloc[0]) else False
        high = bool(day["high_vol"].iloc[0]) if pd.notna(day["high_vol"].iloc[0]) else False
        regime = str(day["regime"].iloc[0])
        target = day["forward_relative_return_5d"]

        candidate_scores = {
            BASELINE: day[BASELINE],
            "switch_on_negative_spy20": day[DEFENSIVE] if neg else day[BASELINE],
            "switch_on_highvol_negative_spy20": day[DEFENSIVE] if (neg and high) else day[BASELINE],
        }
        base_ic = _rank_corr(day[BASELINE], target)
        for cid, score in candidate_scores.items():
            ic = _rank_corr(score, target)
            rows.append({
                "timestamp_utc": ts,
                "candidate_id": cid,
                "regime": regime,
                "negative_spy20": neg,
                "high_vol": high,
                "asset_count": int(pd.concat([score.rename("s"), target.rename("t")], axis=1).dropna().shape[0]),
                "ic": ic,
                "baseline_v8_ic": base_ic,
                "delta_ic_vs_v8": ic - base_ic if np.isfinite(ic) and np.isfinite(base_ic) else np.nan,
            })
    return pd.DataFrame(rows)


def _summary(daily):
    rows = []
    for cid, g in daily.groupby("candidate_id", sort=True):
        x = g["ic"].dropna()
        d = g["delta_ic_vs_v8"].dropna()
        rows.append({
            "candidate_id": cid,
            "days": int(len(x)),
            "mean_ic": float(x.mean()) if len(x) else np.nan,
            "median_ic": float(x.median()) if len(x) else np.nan,
            "ic_hit_rate": float((x > 0).mean()) if len(x) else np.nan,
            "mean_delta_ic_vs_v8": float(d.mean()) if len(d) else np.nan,
            "delta_ic_positive_rate": float((d > 0).mean()) if len(d) else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["mean_delta_ic_vs_v8", "mean_ic"], ascending=[False, False])


def _regime_breakdown(daily):
    rows = []
    for (cid, regime), g in daily.groupby(["candidate_id", "regime"], sort=True):
        x = g["ic"].dropna()
        d = g["delta_ic_vs_v8"].dropna()
        rows.append({
            "candidate_id": cid,
            "regime": regime,
            "days": int(len(x)),
            "mean_ic": float(x.mean()) if len(x) else np.nan,
            "ic_hit_rate": float((x > 0).mean()) if len(x) else np.nan,
            "mean_delta_ic_vs_v8": float(d.mean()) if len(d) else np.nan,
            "delta_ic_positive_rate": float((d > 0).mean()) if len(d) else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    panel = _load_panel()
    daily = _daily_diagnostics(panel)
    summary = _summary(daily)
    regimes = _regime_breakdown(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(DAILY_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_regime_conditioned_discovery",
        "hypothesis": "V9 defensive information may improve V8 conditionally in predeclared decision-time SPY regimes even though V9 failed as an always-on replacement.",
        "baseline": BASELINE,
        "defensive_score": DEFENSIVE,
        "candidate_rules": CANDIDATES,
        "spy_trend_lookback": SPY_TREND_LOOKBACK,
        "spy_vol_lookback": SPY_VOL_LOOKBACK,
        "spy_vol_baseline_lookback": SPY_VOL_BASELINE_LOOKBACK,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "portfolio_simulation": False,
        "candidate_frozen": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V10 PHASE 1")
    print("=" * 96)
    print("Regime-conditioned ranking discovery")
    print(f"Development rows: {len(panel):,}")
    print(f"Trading days: {daily['timestamp_utc'].nunique():,}")
    print(f"V10 untouched holdout begins: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print("\nCANDIDATE SUMMARY")
    print(summary.to_string(index=False))
    print("\nNo portfolio simulation. No candidate freeze. V8 unchanged. V10 holdout untouched. No orders.")


if __name__ == "__main__":
    main()
