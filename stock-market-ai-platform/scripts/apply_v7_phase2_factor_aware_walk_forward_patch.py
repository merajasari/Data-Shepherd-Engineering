"""Apply Stock V7 Phase 2 factor-aware walk-forward comparison."""

from pathlib import Path

PHASE2 = Path("ml/v7/phase2.py")


def main():
    PHASE2.parent.mkdir(parents=True, exist_ok=True)
    PHASE2.write_text(r'''"""Stock V7 Phase 2: factor-aware expanding walk-forward comparison.

Purpose
-------
Test whether V7 learns something beyond simply ranking high-volatility stocks.
The estimator is held fixed (Elastic Net); only three pre-registered feature
families are compared:

* VOL_ONLY: volatility/range features only.
* VOL_CONTEXT: volatility plus trend/location/context features motivated by
  Phase 1 attribution evidence.
* FULL_V7: the complete non-redundant registered V7 feature set.

All scoring is development-only and strictly before the new V7 future holdout
beginning 2026-09-01. No portfolio simulation, policy tuning, candidate freeze,
or brokerage orders occur in this phase.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.v7.config import (
    FEATURE_COLUMNS,
    FUTURE_HOLDOUT_START_UTC,
    PANEL_PATH,
    PRIMARY_HORIZON_DAYS,
)

PHASE = 2
TARGET = f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d"
ENDPOINT = "stock_target_endpoint_utc"
OUTPUT_ROOT = Path("data/model/v7/phase2")
PREDICTIONS_PATH = OUTPUT_ROOT / "predictions.parquet"
DAILY_METRICS_PATH = OUTPUT_ROOT / "daily_rank_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
COEFFICIENTS_PATH = OUTPUT_ROOT / "standardized_coefficients.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

RANDOM_SEED = 42
ELASTIC_NET_ALPHA = 0.0005
ELASTIC_NET_L1_RATIO = 0.25

VOL_ONLY = (
    "volatility_20d",
    "volatility_5d",
    "volatility_ratio_5_20",
    "intraday_range",
)

VOL_CONTEXT = (
    *VOL_ONLY,
    "distance_from_20d_high",
    "distance_from_20d_low",
    "return_20d",
    "return_60d",
    "price_vs_sma_20",
    "price_vs_sma_200",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "rsi_centered",
    "volume_ratio",
)

# trend_20_50 duplicates sma_20_vs_sma_50 and trend_50_200 duplicates
# sma_50_vs_sma_200 in the current feature registry, so exclude those two from
# FULL_V7 to keep this family explicitly non-redundant.
FULL_V7 = tuple(
    f for f in FEATURE_COLUMNS
    if f not in {"trend_20_50", "trend_50_200"}
)

FEATURE_FAMILIES = {
    "vol_only": VOL_ONLY,
    "vol_context": VOL_CONTEXT,
    "full_v7": FULL_V7,
}

# Fixed before Phase 2 results are inspected. These extend the same semiannual
# development structure used in V6 through all currently available V7
# pre-holdout observations.
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


def utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def make_model():
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", ElasticNet(
            alpha=ELASTIC_NET_ALPHA,
            l1_ratio=ELASTIC_NET_L1_RATIO,
            max_iter=5000,
            random_state=RANDOM_SEED,
        )),
    ])


def load_panel():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"V7 Phase 1 panel not found: {PANEL_PATH}")
    panel = pd.read_parquet(PANEL_PATH).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if ENDPOINT not in panel.columns:
        raise ValueError(f"V7 panel missing leakage endpoint column: {ENDPOINT}")
    panel[ENDPOINT] = pd.to_datetime(panel[ENDPOINT], utc=True)

    required = {
        "timestamp_utc", "symbol", "sector", TARGET, ENDPOINT,
        "feature_complete", "is_labeled", *FULL_V7,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V7 Phase 2 panel missing columns: " + ", ".join(missing))
    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        raise ValueError("Duplicate timestamp/symbol rows in V7 Phase 2 panel")
    return panel


def fold_masks(panel, start, end):
    start = utc(start)
    end = utc(end)
    usable = (
        panel["feature_complete"].fillna(False).astype(bool)
        & panel["is_labeled"].fillna(False).astype(bool)
        & panel[TARGET].notna()
        & panel[ENDPOINT].notna()
    )
    # Strict endpoint rule is stronger than a simple date purge: no training
    # target may realize on or after the validation start.
    train = usable & (panel["timestamp_utc"] < start) & (panel[ENDPOINT] < start)
    validation = (
        usable
        & (panel["timestamp_utc"] >= start)
        & (panel["timestamp_utc"] < end)
        & (panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
        & (panel[ENDPOINT] < FUTURE_HOLDOUT_START_UTC)
    )
    return train, validation


def generate_predictions(panel):
    outputs = []
    coefficient_rows = []

    for fold_id, start, end in FOLDS:
        train_mask, val_mask = fold_masks(panel, start, end)
        train = panel.loc[train_mask]
        val = panel.loc[val_mask]
        if train.empty:
            raise RuntimeError(f"Empty training data for {fold_id}")
        if val.empty:
            # A final partial fold may legitimately have no labeled rows if the
            # local data ends earlier; skip rather than manufacturing data.
            print(f"{fold_id}: no validation rows; skipped")
            continue
        if train[ENDPOINT].max() >= utc(start):
            raise AssertionError(f"{fold_id} training endpoint overlaps validation")
        if (val["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
            raise AssertionError(f"{fold_id} reached V7 future holdout")

        print(
            f"{fold_id}: train_rows={len(train):,} "
            f"train_dates={train['timestamp_utc'].nunique():,} "
            f"validation_rows={len(val):,} "
            f"validation_dates={val['timestamp_utc'].nunique():,}"
        )

        base = val[["timestamp_utc", "symbol", "sector", TARGET]].copy()
        base = base.rename(columns={TARGET: "actual_relative_return_5d"})

        for family_id, features in FEATURE_FAMILIES.items():
            estimator = make_model()
            estimator.fit(train[list(features)], train[TARGET])
            scores = estimator.predict(val[list(features)])

            pred = base.copy()
            pred["predicted_score"] = np.asarray(scores, dtype=float)
            pred["fold_id"] = fold_id
            pred["split"] = "development"
            pred["family_id"] = family_id
            outputs.append(pred)

            coefs = estimator.named_steps["model"].coef_
            for feature, coef in zip(features, coefs):
                coefficient_rows.append({
                    "family_id": family_id,
                    "fold_id": fold_id,
                    "feature": feature,
                    "standardized_coefficient": float(coef),
                    "abs_standardized_coefficient": float(abs(coef)),
                })

    if not outputs:
        raise RuntimeError("V7 Phase 2 produced no predictions")

    out = pd.concat(outputs, ignore_index=True)
    out["predicted_rank_pct"] = out.groupby(
        ["family_id", "timestamp_utc"], observed=True
    )["predicted_score"].rank(method="average", pct=True)
    out["actual_rank_pct"] = out.groupby(
        ["family_id", "timestamp_utc"], observed=True
    )["actual_relative_return_5d"].rank(method="average", pct=True)
    return out, pd.DataFrame(coefficient_rows)


def daily_metric(group):
    ordered = group.sort_values("predicted_score", ascending=False)
    predicted = group["predicted_score"]
    actual = group["actual_relative_return_5d"]
    q = max(1, len(ordered) // 5)
    ic = predicted.corr(actual, method="spearman") if predicted.nunique() > 1 else np.nan
    return pd.Series({
        "asset_count": int(len(group)),
        "ic": ic,
        "top_5_relative_return": ordered.head(5)["actual_relative_return_5d"].mean(),
        "top_10_relative_return": ordered.head(10)["actual_relative_return_5d"].mean(),
        "top_quintile_relative_return": ordered.head(q)["actual_relative_return_5d"].mean(),
        "bottom_quintile_relative_return": ordered.tail(q)["actual_relative_return_5d"].mean(),
        "top_minus_bottom_spread": (
            ordered.head(q)["actual_relative_return_5d"].mean()
            - ordered.tail(q)["actual_relative_return_5d"].mean()
        ),
        "top_5_positive_fraction": ordered.head(5)["actual_relative_return_5d"].gt(0).mean(),
    })


def compute_daily_metrics(predictions):
    return (
        predictions.groupby(["family_id", "fold_id", "timestamp_utc"], observed=True)
        .apply(daily_metric, include_groups=False)
        .reset_index()
    )


def build_summaries(predictions, daily):
    overall = []
    for family_id, group in predictions.groupby("family_id", observed=True):
        d = daily[daily["family_id"] == family_id]
        err = group["predicted_score"] - group["actual_relative_return_5d"]
        overall.append({
            "family_id": family_id,
            "feature_count": len(FEATURE_FAMILIES[family_id]),
            "observations": int(len(group)),
            "days": int(group["timestamp_utc"].nunique()),
            "folds": int(group["fold_id"].nunique()),
            "mean_ic": float(d["ic"].mean()),
            "median_ic": float(d["ic"].median()),
            "ic_hit_rate": float(d["ic"].gt(0).mean()),
            "mean_top_5_relative_return": float(d["top_5_relative_return"].mean()),
            "mean_top_10_relative_return": float(d["top_10_relative_return"].mean()),
            "mean_top_minus_bottom_spread": float(d["top_minus_bottom_spread"].mean()),
            "mean_top_5_positive_fraction": float(d["top_5_positive_fraction"].mean()),
            "mae": float(err.abs().mean()),
            "rmse": float(np.sqrt(np.mean(np.square(err)))),
        })

    folds = (
        daily.groupby(["family_id", "fold_id"], observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_ic=("ic", "mean"),
            median_ic=("ic", "median"),
            ic_hit_rate=("ic", lambda s: s.gt(0).mean()),
            mean_top_5_relative_return=("top_5_relative_return", "mean"),
            mean_top_10_relative_return=("top_10_relative_return", "mean"),
            mean_top_minus_bottom_spread=("top_minus_bottom_spread", "mean"),
        )
        .reset_index()
    )
    return pd.DataFrame(overall), folds


def main():
    panel = load_panel()
    predictions, coefficients = generate_predictions(panel)
    daily = compute_daily_metrics(predictions)
    summary, fold_summary = build_summaries(predictions, daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS_PATH, index=False)
    daily.to_csv(DAILY_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    fold_summary.to_csv(FOLD_METRICS_PATH, index=False)
    coefficients.to_csv(COEFFICIENTS_PATH, index=False)

    vol = summary.set_index("family_id").loc["vol_only"]
    comparisons = {}
    for family_id in ("vol_context", "full_v7"):
        row = summary.set_index("family_id").loc[family_id]
        comparisons[family_id] = {
            "mean_ic_minus_vol_only": float(row["mean_ic"] - vol["mean_ic"]),
            "mean_top5_return_minus_vol_only": float(
                row["mean_top_5_relative_return"] - vol["mean_top_5_relative_return"]
            ),
            "mean_top10_return_minus_vol_only": float(
                row["mean_top_10_relative_return"] - vol["mean_top_10_relative_return"]
            ),
            "mean_spread_minus_vol_only": float(
                row["mean_top_minus_bottom_spread"] - vol["mean_top_minus_bottom_spread"]
            ),
        }

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "stage": "development_only_factor_aware_walk_forward_comparison",
        "objective": "Test whether contextual/full V7 information adds predictive value beyond volatility alone.",
        "candidate_count": 100,
        "benchmark_symbol": "SPY",
        "primary_target": TARGET,
        "estimator": "ElasticNet",
        "estimator_contract": {
            "alpha": ELASTIC_NET_ALPHA,
            "l1_ratio": ELASTIC_NET_L1_RATIO,
            "max_iter": 5000,
            "random_seed": RANDOM_SEED,
            "preprocessing": ["median_imputation", "standard_scaling"],
        },
        "feature_families": {k: list(v) for k, v in FEATURE_FAMILIES.items()},
        "development_folds": [
            {"fold_id": fid, "start": start, "end_exclusive": end}
            for fid, start, end in FOLDS
        ],
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "comparison_to_vol_only": comparisons,
        "family_selected": None,
        "candidate_frozen": False,
        "outputs": {
            "predictions": str(PREDICTIONS_PATH),
            "daily_metrics": str(DAILY_METRICS_PATH),
            "summary": str(SUMMARY_PATH),
            "fold_metrics": str(FOLD_METRICS_PATH),
            "standardized_coefficients": str(COEFFICIENTS_PATH),
        },
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
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 2")
    print("=" * 104)
    print("Fixed estimator: Elastic Net")
    print("Question: does context/full information add value beyond volatility alone?")
    print()
    print("===== OVERALL FAMILY SUMMARY =====")
    print(summary.sort_values("mean_ic", ascending=False).to_string(index=False))
    print()
    print("===== COMPARISON VS VOL_ONLY =====")
    print(json.dumps(comparisons, indent=2))
    print()
    print("===== FOLD STABILITY =====")
    print(fold_summary.to_string(index=False))
    print()
    print("Future holdout begins:", FUTURE_HOLDOUT_START_UTC.isoformat())
    print("Holdout scored: False")
    print("No family selected. No portfolio simulation, tuning, freeze, or orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase2.py")
    print()
    print("Stock V7 Phase 2 factor-aware walk-forward patch complete.")
    print("Fixed Elastic Net estimator; VOL_ONLY vs VOL_CONTEXT vs FULL_V7 only.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation or orders.")


if __name__ == "__main__":
    main()
