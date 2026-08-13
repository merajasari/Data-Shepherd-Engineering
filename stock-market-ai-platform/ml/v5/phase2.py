"""V5 Phase 2: frozen walk-forward baseline cross-sectional ranking models.

This phase evaluates only the pre-registered development folds produced by
Phase 1. It fits fixed baseline models to predict 5-trading-day SPY-relative
return, emits out-of-fold predictions, and reports ranking diagnostics. It does
not run portfolio simulation, tune hyperparameters, optimize thresholds, or
inspect the future holdout beginning 2026-09-01.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.v5.config import RESEARCH_PANEL_PATH, V5_FEATURE_COLUMNS
from ml.v5.phase1 import FUTURE_HOLDOUT_START_UTC, PRIMARY_HORIZON_DAYS


PHASE = 2
TARGET = f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d"
ENDPOINT = f"target_endpoint_utc_{PRIMARY_HORIZON_DAYS}d"
PHASE1_ROOT = Path("data/model/v5/phase1")
FOLDS_PATH = PHASE1_ROOT / "folds.json"
PHASE_ROOT = Path("data/model/v5/phase2")
PREDICTIONS_PATH = PHASE_ROOT / "predictions.parquet"
DAILY_METRICS_PATH = PHASE_ROOT / "daily_rank_metrics.csv"
METRICS_SUMMARY_PATH = PHASE_ROOT / "metrics_summary.csv"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"

MODEL_IDS = (
    "hist_gradient_boosting",
    "ridge",
    "momentum_20d",
    "equal_score",
    "random_score",
)

RANDOM_SEED = 42

# Frozen before inspecting Phase 2 outcomes. These are baselines, not tuned
# production parameters.
HGB_PARAMS = {
    "learning_rate": 0.05,
    "max_iter": 100,
    "max_leaf_nodes": 31,
    "l2_regularization": 1.0,
    "random_state": RANDOM_SEED,
}
RIDGE_ALPHA = 1.0


def _utc(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def load_folds(path=FOLDS_PATH):
    if not Path(path).exists():
        raise FileNotFoundError(f"V5 Phase 1 folds not found: {path}")
    return json.loads(Path(path).read_text())


def validate_inputs(panel, folds):
    required = {
        "symbol",
        "timestamp_utc",
        "feature_complete",
        TARGET,
        ENDPOINT,
        "return_20d",
        *V5_FEATURE_COLUMNS,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V5 Phase 2 panel is missing columns: " + ", ".join(missing))
    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        raise ValueError("V5 Phase 2 requires unique timestamp_utc/symbol rows")
    if not folds:
        raise ValueError("V5 Phase 2 requires at least one frozen fold")


def make_model(model_id):
    if model_id == "hist_gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("model", HistGradientBoostingRegressor(**HGB_PARAMS)),
            ]
        )
    if model_id == "ridge":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=RIDGE_ALPHA)),
            ]
        )
    raise KeyError(f"No fitted estimator for baseline model: {model_id}")


def _fold_masks(panel, fold):
    timestamp = panel["timestamp_utc"]
    endpoint = panel[ENDPOINT]
    validation_start = _utc(fold["validation_start_utc"])
    validation_end = _utc(fold["validation_end_exclusive_utc"])

    usable = (
        panel["feature_complete"].fillna(False).astype(bool)
        & panel[TARGET].notna()
        & endpoint.notna()
    )
    train = usable & (timestamp < validation_start) & (endpoint < validation_start)
    validation = (
        usable
        & (timestamp >= validation_start)
        & (timestamp < validation_end)
        & (timestamp < FUTURE_HOLDOUT_START_UTC)
        & (endpoint < FUTURE_HOLDOUT_START_UTC)
    )
    return train, validation


def generate_predictions(panel, folds):
    x = panel.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x[ENDPOINT] = pd.to_datetime(x[ENDPOINT], utc=True)
    validate_inputs(x, folds)

    outputs = []
    rng = np.random.default_rng(RANDOM_SEED)
    feature_cols = list(V5_FEATURE_COLUMNS)

    for fold in folds:
        train_mask, validation_mask = _fold_masks(x, fold)
        train = x.loc[train_mask]
        validation = x.loc[validation_mask]
        if train.empty or validation.empty:
            raise ValueError(f"Empty train/validation data for {fold['fold_id']}")

        max_train_endpoint = train[ENDPOINT].max()
        validation_start = _utc(fold["validation_start_utc"])
        if max_train_endpoint >= validation_start:
            raise AssertionError(
                f"{fold['fold_id']} training endpoint overlaps validation"
            )

        base = validation[
            ["timestamp_utc", "symbol", "sector", TARGET, "return_20d"]
        ].copy()
        base = base.rename(columns={TARGET: "actual_relative_return_5d"})

        for model_id in MODEL_IDS:
            pred = base.copy()
            if model_id in {"hist_gradient_boosting", "ridge"}:
                estimator = make_model(model_id)
                estimator.fit(train[feature_cols], train[TARGET])
                scores = estimator.predict(validation[feature_cols])
            elif model_id == "momentum_20d":
                scores = validation["return_20d"].to_numpy(dtype=float)
            elif model_id == "equal_score":
                scores = np.zeros(len(validation), dtype=float)
            elif model_id == "random_score":
                scores = rng.standard_normal(len(validation))
            else:
                raise KeyError(model_id)

            pred["predicted_score"] = np.asarray(scores, dtype=float)
            pred["fold_id"] = fold["fold_id"]
            pred["split"] = "development"
            pred["model_id"] = model_id
            pred["horizon_days"] = PRIMARY_HORIZON_DAYS
            outputs.append(pred)

    predictions = pd.concat(outputs, ignore_index=True)
    predictions["actual_cross_sectional_rank"] = predictions.groupby(
        ["model_id", "timestamp_utc"], observed=True
    )["actual_relative_return_5d"].rank(method="average", pct=True, ascending=True)
    predictions["predicted_cross_sectional_rank"] = predictions.groupby(
        ["model_id", "timestamp_utc"], observed=True
    )["predicted_score"].rank(method="average", pct=True, ascending=True)
    return predictions


def _daily_metric(group):
    actual = group["actual_relative_return_5d"]
    predicted = group["predicted_score"]
    order = group.sort_values("predicted_score", ascending=False)
    bucket = max(1, len(order) // 5)

    ic = predicted.corr(actual, method="spearman") if predicted.nunique() > 1 else np.nan
    return pd.Series(
        {
            "asset_count": int(len(group)),
            "ic": ic,
            "top_5_relative_return": order.head(5)["actual_relative_return_5d"].mean(),
            "top_quintile_relative_return": order.head(bucket)["actual_relative_return_5d"].mean(),
            "bottom_quintile_relative_return": order.tail(bucket)["actual_relative_return_5d"].mean(),
            "top_minus_bottom_spread": (
                order.head(bucket)["actual_relative_return_5d"].mean()
                - order.tail(bucket)["actual_relative_return_5d"].mean()
            ),
        }
    )


def compute_daily_metrics(predictions):
    return (
        predictions.groupby(
            ["horizon_days", "model_id", "split", "fold_id", "timestamp_utc"],
            observed=True,
        )
        .apply(_daily_metric, include_groups=False)
        .reset_index()
    )


def summarize_predictions(predictions, daily_metrics):
    rows = []
    keys = ["horizon_days", "model_id", "split"]
    for key, group in predictions.groupby(keys, observed=True):
        horizon_days, model_id, split = key
        daily = daily_metrics[
            (daily_metrics["horizon_days"] == horizon_days)
            & (daily_metrics["model_id"] == model_id)
            & (daily_metrics["split"] == split)
        ]
        actual = group["actual_relative_return_5d"]
        score = group["predicted_score"]
        error = score - actual
        rows.append(
            {
                "horizon_days": int(horizon_days),
                "model_id": model_id,
                "split": split,
                "observation_count": int(len(group)),
                "day_count": int(group["timestamp_utc"].nunique()),
                "fold_count": int(group["fold_id"].nunique()),
                "mean_ic": daily["ic"].mean(),
                "median_ic": daily["ic"].median(),
                "ic_hit_rate": daily["ic"].gt(0).mean(),
                "top_5_relative_return": daily["top_5_relative_return"].mean(),
                "top_quintile_relative_return": daily["top_quintile_relative_return"].mean(),
                "bottom_quintile_relative_return": daily["bottom_quintile_relative_return"].mean(),
                "top_minus_bottom_spread": daily["top_minus_bottom_spread"].mean(),
                "mae": error.abs().mean(),
                "rmse": float(np.sqrt(np.mean(np.square(error)))),
                "directional_sign_accuracy": (np.sign(score) == np.sign(actual)).mean(),
            }
        )
    return pd.DataFrame(rows)


def build_manifest(predictions, metrics):
    return {
        "research_version": "v5",
        "phase": PHASE,
        "stage": "frozen_walk_forward_baseline_cross_sectional_ranking",
        "primary_target": TARGET,
        "horizon_days": PRIMARY_HORIZON_DAYS,
        "models": list(MODEL_IDS),
        "model_contract": {
            "hist_gradient_boosting": HGB_PARAMS,
            "ridge_alpha": RIDGE_ALPHA,
            "momentum_baseline": "return_20d",
            "equal_score": 0.0,
            "random_seed": RANDOM_SEED,
        },
        "primary_diagnostics": [
            "daily_spearman_rank_ic",
            "median_daily_ic",
            "ic_hit_rate",
            "top_5_spy_relative_return",
            "top_minus_bottom_quintile_spread",
        ],
        "secondary_diagnostics": ["mae", "rmse", "directional_sign_accuracy"],
        "prediction_rows": int(len(predictions)),
        "metric_rows": int(len(metrics)),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": (
            "Development-only evaluation on frozen Phase 1 folds. No random split, "
            "hyperparameter search, threshold tuning, portfolio optimization, live "
            "execution, or future-holdout evaluation."
        ),
        "outputs": {
            "predictions": str(PREDICTIONS_PATH),
            "daily_rank_metrics": str(DAILY_METRICS_PATH),
            "metrics_summary": str(METRICS_SUMMARY_PATH),
        },
        "next_step": (
            "Review development-only rank diagnostics across all frozen baselines. "
            "Do not simulate the 60% SPY / 40% Top-5 portfolio until ranking evidence "
            "has been reviewed without tuning on the future holdout."
        ),
    }


def main():
    if not RESEARCH_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"V5 research panel not found: {RESEARCH_PANEL_PATH}. Run ml.v5.prepare_dataset first."
        )

    panel = pd.read_parquet(RESEARCH_PANEL_PATH)
    folds = load_folds()
    predictions = generate_predictions(panel, folds)
    daily_metrics = compute_daily_metrics(predictions)
    metrics = summarize_predictions(predictions, daily_metrics)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS_PATH, index=False)
    daily_metrics.to_csv(DAILY_METRICS_PATH, index=False)
    metrics.to_csv(METRICS_SUMMARY_PATH, index=False)

    manifest = build_manifest(predictions, metrics)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
