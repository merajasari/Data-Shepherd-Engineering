"""Create Stock V6 Phase 2 leakage-safe walk-forward model comparison.

V6 remains isolated from frozen V5, V4 paper trading, dashboard runtime,
crypto research, and brokerage settings.
"""

from pathlib import Path

PHASE2 = Path("ml/v6/phase2.py")


def main():
    PHASE2.parent.mkdir(parents=True, exist_ok=True)
    PHASE2.write_text(r'''"""Stock V6 Phase 2: development-only expanding walk-forward model comparison.

Purpose
-------
Evaluate fixed baseline models on the complete 100-stock V6 cross-section using
chronological expanding-window folds. Training rows are leakage-safe: every
training target endpoint must occur strictly before the validation window.

A final holdout beginning 2026-02-01 is pre-registered and never scored here.
No portfolio simulation, threshold tuning, candidate freeze, or orders occur.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.v6.config import FEATURE_COLUMNS, PANEL_PATH, PRIMARY_HORIZON_DAYS

PHASE = 2
TARGET = f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d"
ENDPOINT = "stock_target_endpoint_utc"
PHASE_ROOT = Path("data/model/v6/phase2")
PREDICTIONS_PATH = PHASE_ROOT / "predictions.parquet"
DAILY_METRICS_PATH = PHASE_ROOT / "daily_rank_metrics.csv"
SUMMARY_PATH = PHASE_ROOT / "metrics_summary.csv"
FOLD_METRICS_PATH = PHASE_ROOT / "fold_metrics.csv"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"

FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-02-01", tz="UTC")
RANDOM_SEED = 42

MODEL_IDS = (
    "hist_gradient_boosting",
    "ridge",
    "elastic_net",
    "momentum_20d",
    "equal_score",
    "random_score",
)

HGB_PARAMS = {
    "learning_rate": 0.05,
    "max_iter": 100,
    "max_leaf_nodes": 31,
    "l2_regularization": 1.0,
    "random_state": RANDOM_SEED,
}
RIDGE_ALPHA = 1.0
ELASTIC_NET_ALPHA = 0.0005
ELASTIC_NET_L1_RATIO = 0.25

# Fixed before Phase 2 results are inspected.
FOLDS = (
    ("dev_01", "2022-01-01", "2022-07-01"),
    ("dev_02", "2022-07-01", "2023-01-01"),
    ("dev_03", "2023-01-01", "2023-07-01"),
    ("dev_04", "2023-07-01", "2024-01-01"),
    ("dev_05", "2024-01-01", "2024-07-01"),
    ("dev_06", "2024-07-01", "2025-01-01"),
    ("dev_07", "2025-01-01", "2025-07-01"),
    ("dev_08", "2025-07-01", "2026-01-01"),
    ("dev_09", "2026-01-01", "2026-02-01"),
)


def utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def make_model(model_id):
    if model_id == "hist_gradient_boosting":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(**HGB_PARAMS)),
        ])
    if model_id == "ridge":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=RIDGE_ALPHA)),
        ])
    if model_id == "elastic_net":
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
    raise KeyError(model_id)


def load_panel():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"V6 Phase 1 panel not found: {PANEL_PATH}")
    panel = pd.read_parquet(PANEL_PATH).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel[ENDPOINT] = pd.to_datetime(panel[ENDPOINT], utc=True)
    required = {
        "symbol", "sector", "timestamp_utc", "feature_complete", "is_labeled",
        TARGET, ENDPOINT, "return_20d", *FEATURE_COLUMNS,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V6 Phase 2 panel missing columns: " + ", ".join(missing))
    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        raise ValueError("Duplicate timestamp/symbol rows in V6 Phase 2 panel")
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
    rng = np.random.default_rng(RANDOM_SEED)
    features = list(FEATURE_COLUMNS)

    for fold_id, start, end in FOLDS:
        train_mask, val_mask = fold_masks(panel, start, end)
        train = panel.loc[train_mask]
        val = panel.loc[val_mask]
        if train.empty or val.empty:
            raise RuntimeError(f"Empty train/validation data for {fold_id}")
        if train[ENDPOINT].max() >= utc(start):
            raise AssertionError(f"{fold_id} training endpoint overlaps validation")

        print(
            f"{fold_id}: train_rows={len(train):,} "
            f"train_dates={train['timestamp_utc'].nunique():,} "
            f"validation_rows={len(val):,} "
            f"validation_dates={val['timestamp_utc'].nunique():,}"
        )

        base = val[["timestamp_utc", "symbol", "sector", TARGET, "return_20d"]].copy()
        base = base.rename(columns={TARGET: "actual_relative_return_5d"})

        for model_id in MODEL_IDS:
            pred = base.copy()
            if model_id in {"hist_gradient_boosting", "ridge", "elastic_net"}:
                estimator = make_model(model_id)
                estimator.fit(train[features], train[TARGET])
                scores = estimator.predict(val[features])
            elif model_id == "momentum_20d":
                scores = val["return_20d"].to_numpy(dtype=float)
            elif model_id == "equal_score":
                scores = np.zeros(len(val), dtype=float)
            elif model_id == "random_score":
                scores = rng.standard_normal(len(val))
            else:
                raise KeyError(model_id)

            pred["predicted_score"] = np.asarray(scores, dtype=float)
            pred["fold_id"] = fold_id
            pred["split"] = "development"
            pred["model_id"] = model_id
            outputs.append(pred)

    out = pd.concat(outputs, ignore_index=True)
    out["predicted_rank_pct"] = out.groupby(
        ["model_id", "timestamp_utc"], observed=True
    )["predicted_score"].rank(method="average", pct=True, ascending=True)
    out["actual_rank_pct"] = out.groupby(
        ["model_id", "timestamp_utc"], observed=True
    )["actual_relative_return_5d"].rank(method="average", pct=True, ascending=True)
    return out


def daily_metric(group):
    ordered = group.sort_values("predicted_score", ascending=False)
    actual = group["actual_relative_return_5d"]
    predicted = group["predicted_score"]
    q = max(1, len(ordered) // 5)
    ic = predicted.corr(actual, method="spearman") if predicted.nunique() > 1 else np.nan
    return pd.Series({
        "asset_count": int(len(group)),
        "ic": ic,
        "top_5_relative_return": ordered.head(5)["actual_relative_return_5d"].mean(),
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
        predictions.groupby(["model_id", "fold_id", "timestamp_utc"], observed=True)
        .apply(daily_metric, include_groups=False)
        .reset_index()
    )


def build_summaries(predictions, daily):
    overall = []
    for model_id, group in predictions.groupby("model_id", observed=True):
        d = daily[daily["model_id"] == model_id]
        err = group["predicted_score"] - group["actual_relative_return_5d"]
        overall.append({
            "model_id": model_id,
            "observations": int(len(group)),
            "days": int(group["timestamp_utc"].nunique()),
            "folds": int(group["fold_id"].nunique()),
            "mean_ic": d["ic"].mean(),
            "median_ic": d["ic"].median(),
            "ic_hit_rate": d["ic"].gt(0).mean(),
            "mean_top_5_relative_return": d["top_5_relative_return"].mean(),
            "mean_top_minus_bottom_spread": d["top_minus_bottom_spread"].mean(),
            "mean_top_5_positive_fraction": d["top_5_positive_fraction"].mean(),
            "mae": err.abs().mean(),
            "rmse": float(np.sqrt(np.mean(np.square(err)))),
        })

    folds = (
        daily.groupby(["model_id", "fold_id"], observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_ic=("ic", "mean"),
            median_ic=("ic", "median"),
            ic_hit_rate=("ic", lambda s: s.gt(0).mean()),
            mean_top_5_relative_return=("top_5_relative_return", "mean"),
            mean_top_minus_bottom_spread=("top_minus_bottom_spread", "mean"),
        )
        .reset_index()
    )
    return pd.DataFrame(overall), folds


def main():
    panel = load_panel()
    predictions = generate_predictions(panel)
    daily = compute_daily_metrics(predictions)
    summary, fold_summary = build_summaries(predictions, daily)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS_PATH, index=False)
    daily.to_csv(DAILY_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    fold_summary.to_csv(FOLD_METRICS_PATH, index=False)

    manifest = {
        "research_version": "v6",
        "phase": PHASE,
        "stage": "development_only_expanding_walk_forward_model_comparison",
        "candidate_count": 100,
        "benchmark_symbol": "SPY",
        "benchmark_is_investable": False,
        "primary_target": TARGET,
        "models": list(MODEL_IDS),
        "development_folds": [
            {"fold_id": fid, "start": start, "end_exclusive": end}
            for fid, start, end in FOLDS
        ],
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "model_contract": {
            "hist_gradient_boosting": HGB_PARAMS,
            "ridge_alpha": RIDGE_ALPHA,
            "elastic_net_alpha": ELASTIC_NET_ALPHA,
            "elastic_net_l1_ratio": ELASTIC_NET_L1_RATIO,
            "momentum_baseline": "return_20d",
            "random_seed": RANDOM_SEED,
        },
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "portfolio_simulation": False,
            "threshold_tuning": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nSTOCK V6 PHASE 2")
    print("=" * 96)
    print(summary.sort_values("mean_ic", ascending=False).to_string(index=False))
    print("\nFOLD STABILITY")
    print(fold_summary.to_string(index=False))
    print("\nFuture holdout begins:", FUTURE_HOLDOUT_START_UTC.isoformat())
    print("Holdout scored: False")
    print("No portfolio simulation, threshold tuning, candidate freeze, or orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v6/phase2.py")
    print()
    print("Stock V6 Phase 2 walk-forward comparison patch complete.")
    print("Development-only model comparison across the full 100-stock universe.")
    print("Future holdout begins 2026-02-01 and remains untouched.")
    print("No portfolio simulation, tuning, freeze, or brokerage orders.")


if __name__ == "__main__":
    main()
