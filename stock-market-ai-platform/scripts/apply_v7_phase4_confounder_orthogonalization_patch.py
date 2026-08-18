"""Apply isolated Stock V7 Phase 4 confounder/orthogonalization diagnostics."""

from pathlib import Path

PHASE4 = Path("ml/v7/phase4.py")


def main():
    PHASE4.parent.mkdir(parents=True, exist_ok=True)
    PHASE4.write_text(r'''"""Stock V7 Phase 4: volatility confounder and orthogonalization diagnostics.

Purpose
-------
V7 Phase 3 found that 20-session realized volatility alone explains most of the
cross-sectional ranking signal. Phase 4 does not search for a new model or
portfolio rule. It asks whether the volatility relationship survives fixed,
pre-registered controls for plausible confounders:

* rolling market beta / sensitivity to SPY,
* recent 5-session and 20-session stock returns,
* recent drawdown / 20-session price location,
* price versus 20-session moving average,
* sector membership.

The phase reports raw, sector-neutral, and residualized cross-sectional IC,
plus prior-market-regime diagnostics. All controls are contemporaneous or
trailing. No future information is used to create a score.

Research safety
---------------
No V7 portfolio simulation, no policy tuning, no threshold search, no family
selection, no candidate freeze, no 2026-09-01+ holdout scoring, and no orders.
V4/V5/V6, paper trading, dashboard runtime, and crypto tracks are unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import FUTURE_HOLDOUT_START_UTC

PHASE = 4
TARGET = "forward_relative_return_5d"
VOL = "volatility_20d"
PANEL_PATH = Path("data/model/v7/phase1/research_panel.parquet")
SPY_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")
OUTPUT_ROOT = Path("data/model/v7/phase4")
DAILY_PATH = OUTPUT_ROOT / "daily_orthogonalized_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "orthogonalization_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "prior_market_regime_metrics.csv"
BETA_PATH = OUTPUT_ROOT / "beta_diagnostics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BETA_WINDOW = 60
BETA_MIN_PERIODS = 40

# Fixed before Phase 4 results are inspected. These are explanatory control
# sets, not candidate predictive models.
CONTROL_SETS = {
    "raw_vol20": [],
    "sector_neutral": ["sector"],
    "beta_only": ["beta_60d", "sector"],
    "recent_returns": ["return_5d", "return_20d", "sector"],
    "price_location": [
        "distance_from_20d_high",
        "distance_from_20d_low",
        "price_vs_sma_20",
        "sector",
    ],
    "full_confounders": [
        "beta_60d",
        "return_5d",
        "return_20d",
        "distance_from_20d_high",
        "distance_from_20d_low",
        "price_vs_sma_20",
        "sector",
    ],
}


def _utc_series(s):
    return pd.to_datetime(s, utc=True)


def _load_panel():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Missing V7 Phase 1 panel: {PANEL_PATH}")
    panel = pd.read_parquet(PANEL_PATH).copy()
    panel["timestamp_utc"] = _utc_series(panel["timestamp_utc"])
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    required = {
        "timestamp_utc", "symbol", "sector", TARGET, VOL, "daily_return",
        "return_5d", "return_20d", "distance_from_20d_high",
        "distance_from_20d_low", "price_vs_sma_20",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V7 Phase 4 panel missing columns: " + ", ".join(missing))
    return panel.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)


def _load_spy():
    if not SPY_PATH.exists():
        raise FileNotFoundError(f"Missing SPY feature history: {SPY_PATH}")
    spy = pd.read_parquet(SPY_PATH).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = _utc_series(spy[ts_col])
    needed = {"timestamp_utc", "daily_return", "return_20d"}
    missing = sorted(needed - set(spy.columns))
    if missing:
        raise ValueError("SPY feature history missing columns: " + ", ".join(missing))
    return (
        spy[["timestamp_utc", "daily_return", "return_20d"]]
        .rename(columns={
            "daily_return": "spy_daily_return",
            "return_20d": "spy_return_20d",
        })
        .sort_values("timestamp_utc")
        .drop_duplicates("timestamp_utc", keep="last")
    )


def _add_beta(panel, spy):
    out = panel.merge(spy, on="timestamp_utc", how="left", validate="many_to_one")
    if out["spy_daily_return"].isna().any():
        raise RuntimeError("Missing SPY daily returns after merge")

    pieces = []
    for symbol, g in out.groupby("symbol", sort=False):
        g = g.sort_values("timestamp_utc").copy()
        stock = g["daily_return"].astype(float)
        market = g["spy_daily_return"].astype(float)
        cov = stock.rolling(BETA_WINDOW, min_periods=BETA_MIN_PERIODS).cov(market)
        var = market.rolling(BETA_WINDOW, min_periods=BETA_MIN_PERIODS).var()
        g["beta_60d"] = cov / var.replace(0.0, np.nan)
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True)


def _rank_corr(x, y):
    x = pd.Series(x)
    y = pd.Series(y)
    mask = x.notna() & y.notna()
    x = x[mask]
    y = y[mask]
    if len(x) < 20 or x.nunique() < 2 or y.nunique() < 2:
        return np.nan
    return float(x.rank(method="average").corr(y.rank(method="average"), method="pearson"))


def _zscore(s):
    s = pd.Series(s, dtype=float)
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd <= 1e-12:
        return pd.Series(np.zeros(len(s)), index=s.index, dtype=float)
    return (s - s.mean()) / sd


def _residualize(day, value_col, controls):
    """Cross-sectional OLS residual using same-day/trailing controls only."""
    if not controls:
        return pd.Series(day[value_col].astype(float).to_numpy(), index=day.index)

    numeric_controls = [c for c in controls if c != "sector"]
    cols = [value_col] + numeric_controls + (["sector"] if "sector" in controls else [])
    x = day[cols].copy()

    valid = x[value_col].notna()
    for c in numeric_controls:
        valid &= x[c].notna() & np.isfinite(x[c].astype(float))
    if "sector" in controls:
        valid &= x["sector"].notna()

    resid = pd.Series(np.nan, index=day.index, dtype=float)
    work = x.loc[valid].copy()
    if len(work) < max(20, len(numeric_controls) + 5):
        return resid

    design_parts = [np.ones((len(work), 1), dtype=float)]
    for c in numeric_controls:
        design_parts.append(_zscore(work[c]).to_numpy().reshape(-1, 1))
    if "sector" in controls:
        dummies = pd.get_dummies(work["sector"].astype(str), drop_first=True, dtype=float)
        if dummies.shape[1]:
            design_parts.append(dummies.to_numpy(dtype=float))

    X = np.hstack(design_parts)
    y = work[value_col].astype(float).to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid.loc[work.index] = y - X @ coef
    return resid


def _daily_metrics(panel):
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if day[TARGET].notna().sum() < 20:
            continue
        raw_ic = _rank_corr(day[VOL], day[TARGET])
        for control_id, controls in CONTROL_SETS.items():
            if control_id == "raw_vol20":
                signal = day[VOL].astype(float)
                target = day[TARGET].astype(float)
            else:
                signal = _residualize(day, VOL, controls)
                # Partial/rank-residual interpretation: remove the identical
                # explanatory controls from both signal and realized target.
                target = _residualize(day, TARGET, controls)

            ic = _rank_corr(signal, target)
            rows.append({
                "timestamp_utc": ts,
                "control_id": control_id,
                "raw_vol20_ic": raw_ic,
                "orthogonalized_ic": ic,
                "asset_count": int((signal.notna() & target.notna()).sum()),
                "spy_return_20d": float(day["spy_return_20d"].iloc[0]),
            })
    return pd.DataFrame(rows)


def _summary(daily):
    raw_mean = float(
        daily[daily["control_id"] == "raw_vol20"]["orthogonalized_ic"].mean()
    )
    rows = []
    for control_id, g in daily.groupby("control_id", sort=False):
        mean_ic = float(g["orthogonalized_ic"].mean())
        rows.append({
            "control_id": control_id,
            "days": int(g["timestamp_utc"].nunique()),
            "mean_ic": mean_ic,
            "median_ic": float(g["orthogonalized_ic"].median()),
            "ic_hit_rate": float((g["orthogonalized_ic"] > 0).mean()),
            "mean_abs_ic": float(g["orthogonalized_ic"].abs().mean()),
            "fraction_of_raw_mean_ic_retained": (
                mean_ic / raw_mean if abs(raw_mean) > 1e-12 else np.nan
            ),
        })
    return pd.DataFrame(rows)


def _regime_metrics(daily):
    base = daily.copy()
    # Prior-only market regimes. No future SPY returns are used to define them.
    base["prior_spy_regime"] = np.select(
        [base["spy_return_20d"] < -0.05, base["spy_return_20d"] > 0.05],
        ["PRIOR_DOWN_LT_MINUS_5PCT", "PRIOR_UP_GT_5PCT"],
        default="PRIOR_FLAT_PM_5PCT",
    )
    return (
        base.groupby(["control_id", "prior_spy_regime"], observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_ic=("orthogonalized_ic", "mean"),
            median_ic=("orthogonalized_ic", "median"),
            ic_hit_rate=("orthogonalized_ic", lambda s: s.gt(0).mean()),
        )
        .reset_index()
    )


def _beta_diagnostics(panel):
    x = panel[["timestamp_utc", "symbol", "beta_60d", VOL, TARGET]].dropna().copy()
    rows = []
    for ts, day in x.groupby("timestamp_utc", sort=True):
        if len(day) < 20:
            continue
        rows.append({
            "timestamp_utc": ts,
            "beta_vs_vol20_ic": _rank_corr(day["beta_60d"], day[VOL]),
            "beta_vs_target_ic": _rank_corr(day["beta_60d"], day[TARGET]),
            "vol20_vs_target_ic": _rank_corr(day[VOL], day[TARGET]),
        })
    d = pd.DataFrame(rows)
    if d.empty:
        return pd.DataFrame()
    return pd.DataFrame([{
        "days": int(len(d)),
        "mean_beta_vs_vol20_ic": float(d["beta_vs_vol20_ic"].mean()),
        "mean_beta_vs_target_ic": float(d["beta_vs_target_ic"].mean()),
        "mean_vol20_vs_target_ic": float(d["vol20_vs_target_ic"].mean()),
        "beta_vol20_ic_hit_rate": float((d["beta_vs_vol20_ic"] > 0).mean()),
        "beta_target_ic_hit_rate": float((d["beta_vs_target_ic"] > 0).mean()),
    }])


def main():
    panel = _add_beta(_load_panel(), _load_spy())

    daily = _daily_metrics(panel)
    summary = _summary(daily)
    regime = _regime_metrics(daily)
    beta_diag = _beta_diagnostics(panel)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    regime.to_csv(REGIME_PATH, index=False)
    beta_diag.to_csv(BETA_PATH, index=False)

    full = summary[summary["control_id"] == "full_confounders"].iloc[0]
    raw = summary[summary["control_id"] == "raw_vol20"].iloc[0]
    retained = float(full["fraction_of_raw_mean_ic_retained"])

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_volatility_confounder_orthogonalization",
        "objective": (
            "Determine whether the V7 20-day volatility cross-sectional signal "
            "survives fixed controls for beta, recent returns, price location, and sector."
        ),
        "signal": VOL,
        "target": TARGET,
        "beta_window_sessions": BETA_WINDOW,
        "beta_min_periods": BETA_MIN_PERIODS,
        "control_sets": CONTROL_SETS,
        "raw_mean_ic": float(raw["mean_ic"]),
        "full_confounder_mean_ic": float(full["mean_ic"]),
        "full_confounder_fraction_raw_ic_retained": retained,
        "signal_survives_full_confounders_flag": bool(
            full["mean_ic"] > 0 and retained >= 0.50
        ),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "family_selected": None,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "portfolio_simulation": False,
            "portfolio_policy_tuning": False,
            "threshold_tuning": False,
            "family_selected": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 4")
    print("=" * 100)
    print("20-day volatility confounder/orthogonalization diagnostics only")
    print()
    print("===== ORTHOGONALIZATION SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== PRIOR MARKET REGIMES =====")
    print(regime.to_string(index=False))
    print()
    print("===== BETA DIAGNOSTICS =====")
    print(beta_diag.to_string(index=False))
    print()
    print(
        "Full-confounder retained fraction:",
        f"{retained:.2%}",
        "| survives flag:",
        manifest["signal_survives_full_confounders_flag"],
    )
    print()
    print("Holdout scored: False | family selected: None | candidate frozen: False | orders: False")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase4.py")
    print()
    print("Stock V7 Phase 4 confounder/orthogonalization patch complete.")
    print("Fixed 20-day volatility signal; beta/returns/location/sector controls only.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
