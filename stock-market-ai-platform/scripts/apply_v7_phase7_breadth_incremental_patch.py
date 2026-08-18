"""Apply isolated Stock V7 Phase 7 breadth incremental-information diagnostics."""

from pathlib import Path

PHASE7 = Path("ml/v7/phase7.py")


def main():
    PHASE7.parent.mkdir(parents=True, exist_ok=True)
    PHASE7.write_text(r'''"""Stock V7 Phase 7: 5-session breadth incremental-information diagnostics.

Purpose
-------
Phase 6 found that a simple composite stabilization score did not pass, while
5-session cross-sectional breadth was individually associated with stronger
fully-confounder-controlled volatility residual IC after prior SPY declines.

Phase 7 does not search breadth thresholds or construct a portfolio. It asks a
narrower causal question: does contemporaneous 5-session breadth, observed at
the decision close, explain variation in the already-fixed fully controlled
volatility residual after accounting for SPY's own 5-session and 20-session
returns?

Research safety
---------------
Development diagnostics only. The 2026-09-01+ holdout remains sealed. No model
selection, threshold optimization, portfolio simulation, candidate freeze,
state mutation, or brokerage orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import FUTURE_HOLDOUT_START_UTC
from ml.v7.phase4 import (
    TARGET,
    VOL,
    CONTROL_SETS,
    _add_beta,
    _load_panel,
    _load_spy,
    _rank_corr,
    _residualize,
)
from ml.v7.phase5 import FOLDS, _fold_id

PHASE = 7
PRIMARY_DECLINE_CUTOFF = -0.05
OUTPUT_ROOT = Path("data/model/v7/phase7")
DAILY_PATH = OUTPUT_ROOT / "daily_breadth_diagnostics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "breadth_incremental_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_stability.csv"
TERTILE_PATH = OUTPUT_ROOT / "breadth_tertiles.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def _load_spy_context():
    path = Path("data/features/stocks/SPY/SPY_features.parquet")
    spy = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = pd.to_datetime(spy[ts_col], utc=True)
    needed = {"timestamp_utc", "return_5d", "return_20d"}
    missing = sorted(needed - set(spy.columns))
    if missing:
        raise ValueError("SPY Phase 7 context missing columns: " + ", ".join(missing))
    return (
        spy[["timestamp_utc", "return_5d", "return_20d"]]
        .rename(columns={"return_5d": "spy_return_5d", "return_20d": "spy_return_20d_ctx"})
        .sort_values("timestamp_utc")
        .drop_duplicates("timestamp_utc", keep="last")
    )


def _build_daily():
    panel = _add_beta(_load_panel(), _load_spy())
    controls = CONTROL_SETS["full_confounders"]
    rows = []

    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if ts >= FUTURE_HOLDOUT_START_UTC or day[TARGET].notna().sum() < 20:
            continue
        residual_signal = _residualize(day, VOL, controls)
        residual_target = _residualize(day, TARGET, controls)
        residual_ic = _rank_corr(residual_signal, residual_target)
        breadth = float((pd.to_numeric(day["return_5d"], errors="coerce") > 0).mean())
        rows.append({
            "timestamp_utc": ts,
            "fold_id": _fold_id(ts),
            "spy_return_20d": float(day["spy_return_20d"].iloc[0]),
            "breadth_5d_positive_fraction": breadth,
            "breadth_5d_centered": breadth - 0.5,
            "full_confounder_residual_ic": residual_ic,
        })

    daily = pd.DataFrame(rows).merge(
        _load_spy_context(), on="timestamp_utc", how="left", validate="one_to_one"
    )
    daily = daily[daily["spy_return_20d"] <= PRIMARY_DECLINE_CUTOFF].copy()
    return daily.dropna(subset=[
        "full_confounder_residual_ic", "breadth_5d_centered",
        "spy_return_5d", "spy_return_20d_ctx"
    ]).reset_index(drop=True)


def _ols(y, X, names):
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    X = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    sigma2 = float((resid @ resid) / max(1, n - k))
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    t = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    out = {"intercept": float(beta[0]), "n": int(n), "r2": float(1 - (resid @ resid) / np.sum((y - y.mean()) ** 2)) if np.sum((y-y.mean())**2) > 0 else np.nan}
    for i, name in enumerate(names, start=1):
        out[f"coef_{name}"] = float(beta[i])
        out[f"se_{name}"] = float(se[i])
        out[f"t_{name}"] = float(t[i])
    return out


def _overall_summary(daily):
    y = daily["full_confounder_residual_ic"].to_numpy(float)
    b = daily["breadth_5d_centered"].to_numpy(float)
    spy5 = daily["spy_return_5d"].to_numpy(float)
    spy20 = daily["spy_return_20d_ctx"].to_numpy(float)

    simple = _ols(y, b.reshape(-1, 1), ["breadth"])
    adjusted = _ols(y, np.column_stack([b, spy5, spy20]), ["breadth", "spy5", "spy20"])
    pearson = float(pd.Series(b).corr(pd.Series(y), method="pearson"))
    spearman = float(pd.Series(b).corr(pd.Series(y), method="spearman"))

    return pd.DataFrame([
        {
            "model_id": "breadth_only",
            "days": len(daily),
            "breadth_vs_residual_ic_pearson": pearson,
            "breadth_vs_residual_ic_spearman": spearman,
            **simple,
        },
        {
            "model_id": "breadth_plus_spy_returns",
            "days": len(daily),
            "breadth_vs_residual_ic_pearson": pearson,
            "breadth_vs_residual_ic_spearman": spearman,
            **adjusted,
        },
    ])


def _fold_stability(daily):
    rows = []
    for fold_id, _, _ in FOLDS:
        g = daily[daily["fold_id"] == fold_id].copy()
        if len(g) < 8:
            rows.append({"fold_id": fold_id, "days": len(g), "eligible_fold": False})
            continue
        fit = _ols(
            g["full_confounder_residual_ic"].to_numpy(float),
            np.column_stack([
                g["breadth_5d_centered"].to_numpy(float),
                g["spy_return_5d"].to_numpy(float),
                g["spy_return_20d_ctx"].to_numpy(float),
            ]),
            ["breadth", "spy5", "spy20"],
        )
        rows.append({
            "fold_id": fold_id,
            "days": len(g),
            "eligible_fold": True,
            "breadth_coef_adjusted": fit["coef_breadth"],
            "breadth_t_adjusted": fit["t_breadth"],
            "breadth_residual_ic_spearman": float(g["breadth_5d_centered"].corr(g["full_confounder_residual_ic"], method="spearman")),
            "mean_residual_ic": float(g["full_confounder_residual_ic"].mean()),
        })
    return pd.DataFrame(rows)


def _tertiles(daily):
    # Descriptive only: sample terciles, not trading thresholds.
    x = daily.copy()
    x["breadth_tertile"] = pd.qcut(
        x["breadth_5d_positive_fraction"], q=3,
        labels=["LOW", "MID", "HIGH"], duplicates="drop"
    )
    return (
        x.groupby("breadth_tertile", observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_breadth=("breadth_5d_positive_fraction", "mean"),
            mean_residual_ic=("full_confounder_residual_ic", "mean"),
            median_residual_ic=("full_confounder_residual_ic", "median"),
            residual_ic_hit_rate=("full_confounder_residual_ic", lambda s: s.gt(0).mean()),
        )
        .reset_index()
    )


def main():
    daily = _build_daily()
    summary = _overall_summary(daily)
    folds = _fold_stability(daily)
    tertiles = _tertiles(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    tertiles.to_csv(TERTILE_PATH, index=False)

    adjusted = summary[summary["model_id"] == "breadth_plus_spy_returns"].iloc[0]
    eligible = folds[folds["eligible_fold"] == True].copy()
    positive_fold_fraction = float((eligible["breadth_coef_adjusted"] > 0).mean()) if len(eligible) else np.nan

    gates = {
        "at_least_50_decline_regime_days": bool(len(daily) >= 50),
        "adjusted_breadth_coefficient_positive": bool(adjusted.get("coef_breadth", np.nan) > 0),
        "adjusted_breadth_t_above_1": bool(adjusted.get("t_breadth", np.nan) > 1.0),
        "at_least_three_eligible_folds": bool(len(eligible) >= 3),
        "positive_adjusted_breadth_fold_fraction_at_least_two_thirds": bool(
            np.isfinite(positive_fold_fraction) and positive_fold_fraction >= 2/3
        ),
    }

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_breadth_incremental_information_diagnostics",
        "objective": (
            "Test whether decision-time 5-session cross-sectional breadth incrementally "
            "explains the fully-confounder-controlled volatility residual after prior SPY "
            "20-session declines of at least 5%, controlling for SPY 5-session and 20-session returns."
        ),
        "primary_decline_cutoff": PRIMARY_DECLINE_CUTOFF,
        "breadth_definition": "fraction of the 100-stock universe with return_5d > 0, observed at decision close",
        "breadth_threshold_optimization": False,
        "tertiles_are_descriptive_only": True,
        "adjusted_breadth_coefficient": float(adjusted.get("coef_breadth", np.nan)),
        "adjusted_breadth_t": float(adjusted.get("t_breadth", np.nan)),
        "eligible_folds": int(len(eligible)),
        "positive_adjusted_breadth_fold_fraction": positive_fold_fraction,
        "robustness_gates": gates,
        "all_robustness_gates_passed": bool(all(gates.values())),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False,
            "paper_portfolio_modified": False, "paper_journal_modified": False,
            "crypto_tracks_modified": False, "model_selection": False,
            "portfolio_simulation": False, "portfolio_policy_tuning": False,
            "threshold_optimization": False, "candidate_frozen": False,
            "future_holdout_scored": False, "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 7")
    print("=" * 104)
    print("Continuous 5-session breadth incremental-information diagnostics")
    print("Prior SPY 20-session decline <= -5%; no breadth threshold search")
    print()
    print("===== INCREMENTAL SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== BREADTH TERTILES (DESCRIPTIVE ONLY) =====")
    print(tertiles.to_string(index=False))
    print()
    print("===== CHRONOLOGICAL FOLD STABILITY =====")
    print(folds.to_string(index=False))
    print()
    print("===== ROBUSTNESS GATES =====")
    for key, passed in gates.items():
        print(key, "PASS" if passed else "FAIL")
    print("ALL GATES:", "PASS" if all(gates.values()) else "FAIL")
    print()
    print("No portfolio simulation. No candidate freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase7.py")
    print()
    print("Stock V7 Phase 7 breadth incremental-information patch complete.")
    print("Continuous breadth test only; no breadth threshold optimization.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
