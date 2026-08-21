"""Stock V9 Phase 2: robustness and complementarity validation.

Phase 1 identified two pre-holdout survivor signals with positive aggregate
orthogonal IC after removing frozen V8 distance-from-low exposure, volatility,
and beta. Phase 2 stress-tests those survivors without redefining them and adds
one fixed, non-optimized equal-weight rank blend.

Scientific contract
-------------------
* Survivors are fixed from Phase 1 before Phase-2 results are inspected:
  downside_vol_ratio_20 and volume_trend_5_20.
* Controls remain frozen V8 distance_from_low_20d, volatility_20d, beta_60.
* Target remains exact 5-session stock return minus exact SPY return.
* The blend is fixed 50/50 on same-day cross-sectional percentile ranks of the
  two orthogonalized survivor signals. No weight search is performed.
* Validation includes HAC/Newey-West inference (lag 5), calendar-year
  stability, 252-session rolling stability, SPY trend/volatility regimes, and
  cross-sectional quintile monotonicity.
* No portfolio simulation, Top-N optimization, holding-period tuning, cost
  tuning, candidate freeze, production-state mutation, or brokerage orders.
* Frozen V8 artifacts and V8 holdout evidence are never modified or scored.
* V9 holdout beginning 2026-10-01 UTC remains untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v9.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

PHASE = 2
PHASE1_ROOT = Path("data/model/v9/phase1")
PANEL_PATH = PHASE1_ROOT / "complementary_signal_panel.parquet"
OUTPUT_ROOT = Path("data/model/v9/phase2")
DAILY_PATH = OUTPUT_ROOT / "daily_ic.csv"
SUMMARY_PATH = OUTPUT_ROOT / "robustness_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
ROLLING_PATH = OUTPUT_ROOT / "rolling_252d_stability.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_stability.csv"
QUINTILE_PATH = OUTPUT_ROOT / "quintile_monotonicity.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SURVIVORS = ["downside_vol_ratio_20", "volume_trend_5_20"]
BLEND_ID = "equal_weight_rank_blend"
SCORES = SURVIVORS + [BLEND_ID]
CONTROLS = ["distance_from_low_20d", "volatility_20d", "beta_60"]
HAC_LAG = 5
ROLLING_WINDOW = 252


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


def _hac_mean_stats(series, lag=HAC_LAG):
    x = pd.Series(series, dtype=float).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
    n = len(x)
    if n < max(30, lag + 2):
        return {"n": n, "mean": np.nan, "hac_se": np.nan, "hac_t": np.nan, "p_two_sided_normal": np.nan}
    mean = float(x.mean())
    e = x - mean
    gamma0 = float(np.dot(e, e) / n)
    lrv = gamma0
    max_lag = min(lag, n - 1)
    for ell in range(1, max_lag + 1):
        weight = 1.0 - ell / (max_lag + 1.0)
        gamma = float(np.dot(e[ell:], e[:-ell]) / n)
        lrv += 2.0 * weight * gamma
    lrv = max(lrv, 0.0)
    se = sqrt(lrv / n) if n else np.nan
    t = mean / se if se and se > 0 else np.nan
    p = erfc(abs(t) / sqrt(2.0)) if np.isfinite(t) else np.nan
    return {"n": n, "mean": mean, "hac_se": se, "hac_t": t, "p_two_sided_normal": p}


def _build_score_panel(panel):
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        controls = day[CONTROLS].copy()
        target = day["forward_relative_return_5d"]
        residuals = {}
        for signal in SURVIVORS:
            residuals[signal] = _residualize(day[signal], controls)

        # Fixed 50/50 blend on same-day percentile ranks; no weight optimization.
        ranked = pd.concat(
            [residuals[s].rank(method="average", pct=True).rename(s) for s in SURVIVORS],
            axis=1,
        )
        residuals[BLEND_ID] = ranked.mean(axis=1, skipna=False)

        for score_id in SCORES:
            score = residuals[score_id]
            valid = pd.DataFrame({
                "timestamp_utc": ts,
                "symbol": day["symbol"],
                "score_id": score_id,
                "score": score,
                "target": target,
            }).replace([np.inf, -np.inf], np.nan).dropna(subset=["score", "target"])
            rows.append(valid)
    if not rows:
        raise RuntimeError("No valid V9 Phase-2 score rows")
    return pd.concat(rows, ignore_index=True)


def _daily_ic(score_panel):
    rows = []
    for (ts, score_id), g in score_panel.groupby(["timestamp_utc", "score_id"], sort=True):
        rows.append({
            "timestamp_utc": ts,
            "score_id": score_id,
            "asset_count": int(len(g)),
            "orthogonal_ic": _rank_corr(g["score"], g["target"]),
        })
    return pd.DataFrame(rows)


def _summary(daily):
    rows = []
    for score_id, g in daily.groupby("score_id", sort=True):
        x = g["orthogonal_ic"].dropna()
        hac = _hac_mean_stats(x)
        rows.append({
            "score_id": score_id,
            "days": int(len(x)),
            "mean_orthogonal_ic": float(x.mean()) if len(x) else np.nan,
            "median_orthogonal_ic": float(x.median()) if len(x) else np.nan,
            "ic_hit_rate": float((x > 0).mean()) if len(x) else np.nan,
            "ic_std": float(x.std(ddof=0)) if len(x) else np.nan,
            "hac_lag": HAC_LAG,
            "hac_se": hac["hac_se"],
            "hac_t": hac["hac_t"],
            "p_two_sided_normal": hac["p_two_sided_normal"],
        })
    return pd.DataFrame(rows).sort_values(["mean_orthogonal_ic", "ic_hit_rate"], ascending=[False, False])


def _year_stability(daily):
    x = daily.copy()
    x["year"] = pd.to_datetime(x["timestamp_utc"], utc=True).dt.year
    rows = []
    for (score_id, year), g in x.groupby(["score_id", "year"], sort=True):
        s = g["orthogonal_ic"].dropna()
        rows.append({
            "score_id": score_id,
            "year": int(year),
            "days": int(len(s)),
            "mean_orthogonal_ic": float(s.mean()) if len(s) else np.nan,
            "median_orthogonal_ic": float(s.median()) if len(s) else np.nan,
            "ic_hit_rate": float((s > 0).mean()) if len(s) else np.nan,
        })
    return pd.DataFrame(rows)


def _rolling_stability(daily):
    rows = []
    for score_id, g in daily.groupby("score_id", sort=True):
        g = g.sort_values("timestamp_utc").copy()
        g["rolling_mean_ic"] = g["orthogonal_ic"].rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean()
        valid = g.dropna(subset=["rolling_mean_ic"])
        if valid.empty:
            continue
        rows.append({
            "score_id": score_id,
            "window_sessions": ROLLING_WINDOW,
            "windows": int(len(valid)),
            "min_rolling_mean_ic": float(valid["rolling_mean_ic"].min()),
            "median_rolling_mean_ic": float(valid["rolling_mean_ic"].median()),
            "max_rolling_mean_ic": float(valid["rolling_mean_ic"].max()),
            "positive_window_fraction": float((valid["rolling_mean_ic"] > 0).mean()),
            "latest_rolling_mean_ic": float(valid["rolling_mean_ic"].iloc[-1]),
            "latest_window_end_utc": pd.Timestamp(valid["timestamp_utc"].iloc[-1]).isoformat(),
        })
    return pd.DataFrame(rows)


def _regime_labels(panel):
    spy = (
        panel[["timestamp_utc", "spy_return_1d"]]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .copy()
    )
    spy["spy_return_20d"] = (1.0 + spy["spy_return_1d"].fillna(0.0)).rolling(20, min_periods=20).apply(np.prod, raw=True) - 1.0
    spy["spy_vol_20d"] = spy["spy_return_1d"].rolling(20, min_periods=20).std(ddof=0)
    vol_median = float(spy["spy_vol_20d"].median(skipna=True))
    spy["trend_regime"] = np.where(spy["spy_return_20d"] >= 0, "SPY_20D_UP", "SPY_20D_DOWN")
    spy["vol_regime"] = np.where(spy["spy_vol_20d"] >= vol_median, "HIGH_VOL", "LOW_VOL")
    return spy[["timestamp_utc", "trend_regime", "vol_regime"]]


def _regime_stability(daily, panel):
    regimes = _regime_labels(panel)
    x = daily.merge(regimes, on="timestamp_utc", how="left", validate="many_to_one")
    rows = []
    for regime_type in ["trend_regime", "vol_regime"]:
        for (score_id, regime), g in x.groupby(["score_id", regime_type], sort=True):
            s = g["orthogonal_ic"].dropna()
            rows.append({
                "score_id": score_id,
                "regime_type": regime_type,
                "regime": regime,
                "days": int(len(s)),
                "mean_orthogonal_ic": float(s.mean()) if len(s) else np.nan,
                "median_orthogonal_ic": float(s.median()) if len(s) else np.nan,
                "ic_hit_rate": float((s > 0).mean()) if len(s) else np.nan,
            })
    return pd.DataFrame(rows)


def _quintile_monotonicity(score_panel):
    daily_rows = []
    for (ts, score_id), g in score_panel.groupby(["timestamp_utc", "score_id"], sort=True):
        if len(g) < 50 or g["score"].nunique() < 5:
            continue
        ranks = g["score"].rank(method="first", pct=True)
        quintile = np.minimum((ranks * 5).apply(np.ceil).astype(int), 5)
        q = g.assign(quintile=quintile).groupby("quintile", observed=True)["target"].mean()
        if len(q) != 5:
            continue
        for bucket, value in q.items():
            daily_rows.append({"timestamp_utc": ts, "score_id": score_id, "quintile": int(bucket), "mean_target": float(value)})
    daily_q = pd.DataFrame(daily_rows)
    rows = []
    if daily_q.empty:
        return pd.DataFrame(rows)
    for score_id, g in daily_q.groupby("score_id", sort=True):
        avg = g.groupby("quintile", observed=True)["mean_target"].mean().reindex(range(1, 6))
        corr = pd.Series(range(1, 6), dtype=float).corr(avg.reset_index(drop=True), method="spearman")
        rows.append({
            "score_id": score_id,
            "q1_mean_forward_relative_return": float(avg.loc[1]),
            "q2_mean_forward_relative_return": float(avg.loc[2]),
            "q3_mean_forward_relative_return": float(avg.loc[3]),
            "q4_mean_forward_relative_return": float(avg.loc[4]),
            "q5_mean_forward_relative_return": float(avg.loc[5]),
            "q5_minus_q1": float(avg.loc[5] - avg.loc[1]),
            "quintile_spearman": float(corr),
            "monotonic_non_decreasing": bool(np.all(np.diff(avg.to_numpy(float)) >= 0)),
        })
    return pd.DataFrame(rows)


def main():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Missing {PANEL_PATH}; run V9 Phase 1 first")

    panel = pd.read_parquet(PANEL_PATH).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase-1 panel reaches V9 future holdout boundary; refusing to score holdout data")

    missing = sorted(set(SURVIVORS + CONTROLS + ["symbol", "forward_relative_return_5d", "spy_return_1d"]) - set(panel.columns))
    if missing:
        raise ValueError(f"Phase-1 panel missing required columns: {missing}")

    score_panel = _build_score_panel(panel)
    daily = _daily_ic(score_panel)
    summary = _summary(daily)
    years = _year_stability(daily)
    rolling = _rolling_stability(daily)
    regimes = _regime_stability(daily, panel)
    quintiles = _quintile_monotonicity(score_panel)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    rolling.to_csv(ROLLING_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    quintiles.to_csv(QUINTILE_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_survivor_robustness_validation",
        "survivor_signals_fixed_before_phase2": SURVIVORS,
        "fixed_blend": {
            "score_id": BLEND_ID,
            "construction": "50/50 mean of same-day cross-sectional percentile ranks of the two orthogonalized survivors",
            "weight_optimization": False,
        },
        "neutralization_controls": CONTROLS,
        "target": "forward_relative_return_5d",
        "hac_lag": HAC_LAG,
        "rolling_window_sessions": ROLLING_WINDOW,
        "development_date_range": {
            "start": panel["timestamp_utc"].min().isoformat(),
            "end": panel["timestamp_utc"].max().isoformat(),
        },
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "candidate_selected": None,
        "candidate_frozen": False,
        "research_safety": {
            "v8_modified": False,
            "v8_holdout_scored": False,
            "v8_holdout_journal_modified": False,
            "portfolio_simulation": False,
            "top_n_optimization": False,
            "holding_period_tuning": False,
            "cost_tuning": False,
            "blend_weight_optimization": False,
            "v9_candidate_frozen": False,
            "v9_future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V9 PHASE 2")
    print("=" * 108)
    print("Robustness and complementarity validation of fixed Phase-1 survivors")
    print(f"Development dates: {manifest['development_date_range']['start']} -> {manifest['development_date_range']['end']}")
    print(f"V9 untouched holdout begins: {manifest['v9_future_holdout_start_utc']}")
    print()
    print("===== ROBUSTNESS SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== ROLLING 252-SESSION STABILITY =====")
    print(rolling.to_string(index=False))
    print()
    print("===== REGIME STABILITY =====")
    print(regimes.to_string(index=False))
    print()
    print("===== QUINTILE MONOTONICITY =====")
    print(quintiles.to_string(index=False))
    print()
    print("No portfolio simulation. No tuning. No candidate freeze. V8 unchanged. No holdout score. No orders.")


if __name__ == "__main__":
    main()
