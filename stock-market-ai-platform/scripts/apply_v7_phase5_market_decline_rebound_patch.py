"""Apply isolated Stock V7 Phase 5 market-decline/rebound robustness diagnostics."""

from pathlib import Path

PHASE5 = Path("ml/v7/phase5.py")


def main():
    PHASE5.parent.mkdir(parents=True, exist_ok=True)
    PHASE5.write_text(r'''"""Stock V7 Phase 5: market-decline / rebound robustness diagnostics.

Purpose
-------
Phase 4 rejected a general independent volatility premium after fixed controls,
but found a positive fully-orthogonalized residual relationship after meaningful
prior SPY declines. Phase 5 does NOT search for a trading rule. It asks whether
that already-observed conditional effect is stable across chronological folds,
pre-registered prior-decline severities, and realized subsequent SPY paths.

Important interpretation
------------------------
This is still development-side follow-up analysis because the -5% prior-decline
pattern was observed in Phase 4. It is not an independent confirmation. The
2026-09-01+ V7 holdout remains sealed.

Research safety
---------------
No portfolio simulation, threshold optimization, model selection, candidate
freeze, holdout scoring, paper-state mutation, or brokerage orders.
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

PHASE = 5
OUTPUT_ROOT = Path("data/model/v7/phase5")
THRESHOLD_PATH = OUTPUT_ROOT / "decline_threshold_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_stability.csv"
PATH_METRICS_PATH = OUTPUT_ROOT / "subsequent_market_path_metrics.csv"
DAILY_PATH = OUTPUT_ROOT / "daily_conditional_metrics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
SPY_FEATURE_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")

# Fixed before Phase 5 results are inspected. These are robustness diagnostics,
# not candidate trading thresholds.
DECLINE_THRESHOLDS = {
    "PRIOR_DOWN_3PCT": -0.03,
    "PRIOR_DOWN_5PCT": -0.05,
    "PRIOR_DOWN_8PCT": -0.08,
}
PRIMARY_DECLINE_ID = "PRIOR_DOWN_5PCT"
MIN_REGIME_DAYS_PER_FOLD = 8

# Subsequent market-path bins are realized diagnostics only. They never define
# the signal or an investable decision.
SUBSEQUENT_PATH_DOWN = -0.02
SUBSEQUENT_PATH_UP = 0.02

FOLDS = (
    ("dev_01", "2022-01-01", "2022-07-01"),
    ("dev_02", "2022-07-01", "2023-01-01"),
    ("dev_03", "2023-01-01", "2023-07-01"),
    ("dev_04", "2023-07-01", "2024-01-01"),
    ("dev_05", "2024-01-01", "2024-07-01"),
    ("dev_06", "2024-07-01", "2025-01-01"),
    ("dev_07", "2025-01-01", "2025-07-01"),
    ("dev_08", "2025-07-01", "2026-01-01"),
    ("dev_09", "2026-01-01", "2026-07-01"),
    ("dev_10", "2026-07-01", "2026-09-01"),
)


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _spy_forward_5d():
    if not SPY_FEATURE_PATH.exists():
        raise FileNotFoundError(f"Missing SPY features: {SPY_FEATURE_PATH}")
    spy = pd.read_parquet(SPY_FEATURE_PATH).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = pd.to_datetime(spy[ts_col], utc=True)
    if "close" not in spy.columns:
        raise ValueError("SPY feature history requires close for forward-path diagnostics")
    spy = spy.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    spy["spy_forward_return_5d"] = spy["close"].shift(-5) / spy["close"] - 1.0
    return spy[["timestamp_utc", "spy_forward_return_5d"]]


def _fold_id(ts):
    for fold_id, start, end in FOLDS:
        if _utc(start) <= ts < _utc(end):
            return fold_id
    return None


def _build_daily():
    panel = _add_beta(_load_panel(), _load_spy())
    controls = CONTROL_SETS["full_confounders"]
    rows = []

    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if ts >= FUTURE_HOLDOUT_START_UTC or day[TARGET].notna().sum() < 20:
            continue
        raw_ic = _rank_corr(day[VOL], day[TARGET])
        resid_signal = _residualize(day, VOL, controls)
        resid_target = _residualize(day, TARGET, controls)
        residual_ic = _rank_corr(resid_signal, resid_target)
        rows.append({
            "timestamp_utc": ts,
            "fold_id": _fold_id(ts),
            "spy_return_20d": float(day["spy_return_20d"].iloc[0]),
            "raw_vol20_ic": raw_ic,
            "full_confounder_residual_ic": residual_ic,
            "asset_count": int((resid_signal.notna() & resid_target.notna()).sum()),
        })

    daily = pd.DataFrame(rows)
    daily = daily.merge(_spy_forward_5d(), on="timestamp_utc", how="left", validate="one_to_one")
    daily["subsequent_spy_path"] = np.select(
        [
            daily["spy_forward_return_5d"] < SUBSEQUENT_PATH_DOWN,
            daily["spy_forward_return_5d"] > SUBSEQUENT_PATH_UP,
        ],
        ["NEXT_5D_DOWN", "NEXT_5D_UP"],
        default="NEXT_5D_FLAT",
    )
    return daily


def _threshold_summary(daily):
    rows = []
    for decline_id, cutoff in DECLINE_THRESHOLDS.items():
        g = daily[daily["spy_return_20d"] <= cutoff].copy()
        rows.append({
            "decline_id": decline_id,
            "prior_spy_20d_cutoff": cutoff,
            "days": int(len(g)),
            "mean_raw_ic": float(g["raw_vol20_ic"].mean()) if len(g) else np.nan,
            "raw_ic_hit_rate": float((g["raw_vol20_ic"] > 0).mean()) if len(g) else np.nan,
            "mean_full_residual_ic": float(g["full_confounder_residual_ic"].mean()) if len(g) else np.nan,
            "median_full_residual_ic": float(g["full_confounder_residual_ic"].median()) if len(g) else np.nan,
            "full_residual_ic_hit_rate": float((g["full_confounder_residual_ic"] > 0).mean()) if len(g) else np.nan,
        })
    return pd.DataFrame(rows)


def _fold_stability(daily):
    rows = []
    for decline_id, cutoff in DECLINE_THRESHOLDS.items():
        for fold_id, _, _ in FOLDS:
            g = daily[(daily["fold_id"] == fold_id) & (daily["spy_return_20d"] <= cutoff)]
            rows.append({
                "decline_id": decline_id,
                "fold_id": fold_id,
                "days": int(len(g)),
                "eligible_fold": bool(len(g) >= MIN_REGIME_DAYS_PER_FOLD),
                "mean_full_residual_ic": float(g["full_confounder_residual_ic"].mean()) if len(g) else np.nan,
                "median_full_residual_ic": float(g["full_confounder_residual_ic"].median()) if len(g) else np.nan,
                "full_residual_ic_hit_rate": float((g["full_confounder_residual_ic"] > 0).mean()) if len(g) else np.nan,
            })
    return pd.DataFrame(rows)


def _subsequent_path_metrics(daily):
    rows = []
    for decline_id, cutoff in DECLINE_THRESHOLDS.items():
        base = daily[daily["spy_return_20d"] <= cutoff].copy()
        for path, g in base.groupby("subsequent_spy_path", observed=True):
            rows.append({
                "decline_id": decline_id,
                "subsequent_spy_path": path,
                "days": int(len(g)),
                "mean_spy_forward_return_5d": float(g["spy_forward_return_5d"].mean()),
                "mean_raw_ic": float(g["raw_vol20_ic"].mean()),
                "mean_full_residual_ic": float(g["full_confounder_residual_ic"].mean()),
                "full_residual_ic_hit_rate": float((g["full_confounder_residual_ic"] > 0).mean()),
            })
    return pd.DataFrame(rows)


def main():
    daily = _build_daily()
    threshold = _threshold_summary(daily)
    folds = _fold_stability(daily)
    paths = _subsequent_path_metrics(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    threshold.to_csv(THRESHOLD_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    paths.to_csv(PATH_METRICS_PATH, index=False)

    primary = threshold[threshold["decline_id"] == PRIMARY_DECLINE_ID].iloc[0]
    primary_folds = folds[
        (folds["decline_id"] == PRIMARY_DECLINE_ID) & folds["eligible_fold"]
    ].copy()
    positive_fold_fraction = (
        float((primary_folds["mean_full_residual_ic"] > 0).mean())
        if len(primary_folds) else np.nan
    )

    # Pre-registered descriptive robustness gates. Passing these does NOT freeze
    # a candidate because Phase 5 is still development-side follow-up analysis.
    gates = {
        "primary_days_at_least_50": bool(primary["days"] >= 50),
        "primary_mean_full_residual_ic_positive": bool(primary["mean_full_residual_ic"] > 0),
        "primary_residual_hit_rate_above_52pct": bool(primary["full_residual_ic_hit_rate"] > 0.52),
        "at_least_three_eligible_chronological_folds": bool(len(primary_folds) >= 3),
        "positive_eligible_fold_fraction_at_least_two_thirds": bool(
            np.isfinite(positive_fold_fraction) and positive_fold_fraction >= 2 / 3
        ),
    }

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_market_decline_rebound_robustness",
        "objective": (
            "Assess whether the fully-confounder-controlled volatility residual observed "
            "after prior broad-market declines is stable across time, decline severity, "
            "and subsequent market paths."
        ),
        "interpretation_constraint": (
            "Phase 5 is follow-up development analysis motivated by Phase 4; it is not "
            "independent confirmation of the prior-down effect."
        ),
        "signal": VOL,
        "target": TARGET,
        "controls": CONTROL_SETS["full_confounders"],
        "decline_thresholds": DECLINE_THRESHOLDS,
        "primary_decline_id": PRIMARY_DECLINE_ID,
        "min_regime_days_per_fold": MIN_REGIME_DAYS_PER_FOLD,
        "subsequent_path_cutoffs": {
            "down_lt": SUBSEQUENT_PATH_DOWN,
            "up_gt": SUBSEQUENT_PATH_UP,
        },
        "primary_summary": primary.to_dict(),
        "primary_eligible_folds": int(len(primary_folds)),
        "primary_positive_eligible_fold_fraction": positive_fold_fraction,
        "robustness_gates": gates,
        "all_robustness_gates_passed": bool(all(gates.values())),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_selection": False,
            "portfolio_simulation": False,
            "portfolio_policy_tuning": False,
            "threshold_optimization": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 5")
    print("=" * 104)
    print("Conditional prior-market-decline / rebound robustness diagnostics only")
    print("Development-side follow-up; 2026-09-01+ holdout remains sealed")
    print()
    print("===== DECLINE THRESHOLD SUMMARY =====")
    print(threshold.to_string(index=False))
    print()
    print("===== CHRONOLOGICAL FOLD STABILITY =====")
    print(folds.to_string(index=False))
    print()
    print("===== SUBSEQUENT MARKET PATH =====")
    print(paths.to_string(index=False))
    print()
    print("===== PRIMARY (-5%) ROBUSTNESS GATES =====")
    for key, passed in gates.items():
        print(key, "PASS" if passed else "FAIL")
    print("ALL GATES:", "PASS" if all(gates.values()) else "FAIL")
    print()
    print("No portfolio simulation. No candidate freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase5.py")
    print()
    print("Stock V7 Phase 5 market-decline/rebound robustness patch complete.")
    print("Fixed full-confounder residual; -3%/-5%/-8% prior-SPY decline diagnostics only.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
