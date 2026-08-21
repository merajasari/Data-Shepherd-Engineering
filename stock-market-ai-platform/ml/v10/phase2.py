"""Stock V10 Phase 2: robustness validation for regime-conditioned ranking.

Phase 2 evaluates the two fixed Phase-1 switching rules without changing their
thresholds or lookbacks. It tests whether incremental IC versus frozen V8 is
statistically and temporally robust, and whether apparent gains are overly
concentrated in a few crisis episodes.

Scientific contract
-------------------
* Consume Phase-1 daily diagnostics only; do not recompute/tune signal rules.
* Candidate rules remain fixed:
    - switch_on_negative_spy20
    - switch_on_highvol_negative_spy20
* Frozen V8 remains read-only baseline.
* HAC/Newey-West inference uses a fixed lag of 5 sessions because the target is
  a 5-session forward return and therefore serial dependence is expected.
* No portfolio simulation, threshold search, lookback tuning, blend tuning,
  candidate freeze, production mutation, brokerage orders, or holdout scoring.
* V10 future holdout beginning 2026-11-02 UTC remains untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

PHASE = 2
PHASE1_DAILY = Path("data/model/v10/phase1/daily_regime_ic.parquet")
OUTPUT_ROOT = Path("data/model/v10/phase2")
ROBUSTNESS_PATH = OUTPUT_ROOT / "robustness_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
ROLLING_PATH = OUTPUT_ROOT / "rolling_252d_stability.csv"
REGIME_PATH = OUTPUT_ROOT / "negative_regime_stability.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "episode_concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BASELINE = "v8_distance_only"
CANDIDATES = [
    "switch_on_negative_spy20",
    "switch_on_highvol_negative_spy20",
]
HAC_LAG = 5
ROLLING_WINDOW = 252


def _load_daily():
    if not PHASE1_DAILY.exists():
        raise FileNotFoundError(f"Missing {PHASE1_DAILY}; run V10 Phase 1 first")
    d = pd.read_parquet(PHASE1_DAILY).copy()
    d["timestamp_utc"] = pd.to_datetime(d["timestamp_utc"], utc=True)
    if d["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase-1 diagnostics cross V10 holdout boundary; refusing to validate holdout data")
    required = {"timestamp_utc", "candidate_id", "regime", "ic", "baseline_v8_ic", "delta_ic_vs_v8"}
    missing = sorted(required - set(d.columns))
    if missing:
        raise ValueError(f"V10 Phase 2 missing columns: {missing}")
    return d[d["candidate_id"].isin([BASELINE] + CANDIDATES)].copy()


def _newey_west_mean_test(series: pd.Series, lag: int = HAC_LAG):
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(float)
    n = len(x)
    if n < max(30, lag + 5):
        return {"n": n, "mean": np.nan, "hac_se": np.nan, "hac_t": np.nan, "p_value_two_sided": np.nan}
    mu = float(x.mean())
    u = x - mu
    gamma0 = float(np.dot(u, u) / n)
    long_var = gamma0
    for k in range(1, lag + 1):
        gamma = float(np.dot(u[k:], u[:-k]) / n)
        weight = 1.0 - k / (lag + 1.0)
        long_var += 2.0 * weight * gamma
    long_var = max(long_var, 0.0)
    se = math.sqrt(long_var / n) if long_var > 0 else np.nan
    t = mu / se if np.isfinite(se) and se > 0 else np.nan
    # Normal approximation is appropriate here given ~2500 daily observations.
    p = math.erfc(abs(t) / math.sqrt(2.0)) if np.isfinite(t) else np.nan
    return {"n": n, "mean": mu, "hac_se": se, "hac_t": t, "p_value_two_sided": p}


def _robustness_summary(daily):
    rows = []
    for cid in CANDIDATES:
        g = daily[daily["candidate_id"] == cid].sort_values("timestamp_utc")
        all_test = _newey_west_mean_test(g["delta_ic_vs_v8"])
        neg = g[g["regime"].str.startswith("NEGATIVE")]
        neg_test = _newey_west_mean_test(neg["delta_ic_vs_v8"])
        rows.append({
            "candidate_id": cid,
            "days": int(g["delta_ic_vs_v8"].notna().sum()),
            "mean_delta_ic_vs_v8": all_test["mean"],
            "hac_se": all_test["hac_se"],
            "hac_t": all_test["hac_t"],
            "p_value_two_sided": all_test["p_value_two_sided"],
            "negative_regime_days": int(neg["delta_ic_vs_v8"].notna().sum()),
            "negative_regime_mean_delta_ic": neg_test["mean"],
            "negative_regime_hac_t": neg_test["hac_t"],
            "negative_regime_p_value_two_sided": neg_test["p_value_two_sided"],
            "delta_positive_rate_all_days": float((g["delta_ic_vs_v8"].dropna() > 0).mean()),
            "delta_positive_rate_negative_regime": float((neg["delta_ic_vs_v8"].dropna() > 0).mean()) if len(neg) else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["negative_regime_hac_t", "mean_delta_ic_vs_v8"], ascending=[False, False])


def _year_stability(daily):
    x = daily[daily["candidate_id"].isin(CANDIDATES)].copy()
    x["year"] = x["timestamp_utc"].dt.year
    rows = []
    for (cid, year), g in x.groupby(["candidate_id", "year"], sort=True):
        d = g["delta_ic_vs_v8"].dropna()
        neg = g[g["regime"].str.startswith("NEGATIVE")]["delta_ic_vs_v8"].dropna()
        rows.append({
            "candidate_id": cid,
            "year": int(year),
            "days": int(len(d)),
            "mean_delta_ic_vs_v8": float(d.mean()) if len(d) else np.nan,
            "delta_positive_rate": float((d > 0).mean()) if len(d) else np.nan,
            "negative_regime_days": int(len(neg)),
            "negative_regime_mean_delta_ic": float(neg.mean()) if len(neg) else np.nan,
            "negative_regime_positive_rate": float((neg > 0).mean()) if len(neg) else np.nan,
        })
    return pd.DataFrame(rows)


def _rolling_stability(daily):
    rows = []
    for cid in CANDIDATES:
        g = daily[daily["candidate_id"] == cid].sort_values("timestamp_utc").copy()
        s = pd.to_numeric(g["delta_ic_vs_v8"], errors="coerce")
        roll = s.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW)
        g["rolling_mean_delta_ic"] = roll.mean()
        g["rolling_positive_rate"] = roll.apply(lambda z: float((z > 0).mean()), raw=False)
        valid = g.dropna(subset=["rolling_mean_delta_ic"])
        for _, r in valid.iterrows():
            rows.append({
                "candidate_id": cid,
                "timestamp_utc": r["timestamp_utc"],
                "rolling_mean_delta_ic": float(r["rolling_mean_delta_ic"]),
                "rolling_positive_rate": float(r["rolling_positive_rate"]),
            })
    return pd.DataFrame(rows)


def _negative_regime_stability(daily):
    rows = []
    x = daily[daily["candidate_id"].isin(CANDIDATES)].copy()
    x = x[x["regime"].str.startswith("NEGATIVE")]
    for (cid, regime), g in x.groupby(["candidate_id", "regime"], sort=True):
        test = _newey_west_mean_test(g["delta_ic_vs_v8"])
        rows.append({
            "candidate_id": cid,
            "regime": regime,
            "days": int(test["n"]),
            "mean_delta_ic_vs_v8": test["mean"],
            "hac_t": test["hac_t"],
            "p_value_two_sided": test["p_value_two_sided"],
            "delta_positive_rate": float((g["delta_ic_vs_v8"].dropna() > 0).mean()),
        })
    return pd.DataFrame(rows)


def _episode_concentration(daily):
    rows = []
    for cid in CANDIDATES:
        g = daily[(daily["candidate_id"] == cid) & daily["regime"].str.startswith("NEGATIVE")].copy()
        g = g.dropna(subset=["delta_ic_vs_v8"]).sort_values("timestamp_utc")
        if g.empty:
            continue
        positive = g[g["delta_ic_vs_v8"] > 0].copy()
        total_positive = float(positive["delta_ic_vs_v8"].sum())
        ranked = positive.sort_values("delta_ic_vs_v8", ascending=False)
        top10 = float(ranked.head(10)["delta_ic_vs_v8"].sum()) if len(ranked) else 0.0
        top25 = float(ranked.head(25)["delta_ic_vs_v8"].sum()) if len(ranked) else 0.0
        top50 = float(ranked.head(50)["delta_ic_vs_v8"].sum()) if len(ranked) else 0.0
        monthly = g.assign(month=g["timestamp_utc"].dt.to_period("M").astype(str)).groupby("month")["delta_ic_vs_v8"].sum()
        abs_month = monthly.abs().sort_values(ascending=False)
        rows.append({
            "candidate_id": cid,
            "negative_regime_days": int(len(g)),
            "positive_delta_days": int(len(positive)),
            "total_positive_delta_ic": total_positive,
            "top10_positive_share": top10 / total_positive if total_positive > 0 else np.nan,
            "top25_positive_share": top25 / total_positive if total_positive > 0 else np.nan,
            "top50_positive_share": top50 / total_positive if total_positive > 0 else np.nan,
            "months": int(len(monthly)),
            "positive_month_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
            "largest_abs_month_share": float(abs_month.iloc[0] / abs_month.sum()) if len(abs_month) and abs_month.sum() > 0 else np.nan,
            "top3_abs_month_share": float(abs_month.head(3).sum() / abs_month.sum()) if len(abs_month) and abs_month.sum() > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    daily = _load_daily()
    robust = _robustness_summary(daily)
    years = _year_stability(daily)
    rolling = _rolling_stability(daily)
    regimes = _negative_regime_stability(daily)
    concentration = _episode_concentration(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    robust.to_csv(ROBUSTNESS_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    rolling.to_csv(ROLLING_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)

    rolling_summary = []
    for cid, g in rolling.groupby("candidate_id", sort=True):
        rolling_summary.append({
            "candidate_id": cid,
            "windows": int(len(g)),
            "positive_252d_windows_rate": float((g["rolling_mean_delta_ic"] > 0).mean()) if len(g) else np.nan,
            "median_252d_delta_ic": float(g["rolling_mean_delta_ic"].median()) if len(g) else np.nan,
            "latest_252d_delta_ic": float(g.iloc[-1]["rolling_mean_delta_ic"]) if len(g) else np.nan,
        })

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_regime_conditioned_robustness",
        "candidate_rules_fixed": CANDIDATES,
        "baseline": BASELINE,
        "hac_lag_sessions": HAC_LAG,
        "rolling_window_sessions": ROLLING_WINDOW,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "rolling_summary": rolling_summary,
        "portfolio_simulation": False,
        "threshold_tuning": False,
        "lookback_tuning": False,
        "blend_weight_tuning": False,
        "candidate_frozen": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V10 PHASE 2")
    print("=" * 104)
    print("Fixed-rule robustness validation")
    print(f"HAC lag: {HAC_LAG} sessions | rolling window: {ROLLING_WINDOW} sessions")
    print(f"V10 untouched holdout begins: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print("\nROBUSTNESS SUMMARY")
    print(robust.to_string(index=False))
    print("\nROLLING SUMMARY")
    print(pd.DataFrame(rolling_summary).to_string(index=False))
    print("\nNo portfolio simulation. No tuning. No candidate freeze. V8 unchanged. V10 holdout untouched. No orders.")


if __name__ == "__main__":
    main()
