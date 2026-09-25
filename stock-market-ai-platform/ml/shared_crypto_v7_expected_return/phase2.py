"""Shared Crypto V7 Expected Return Phase 2: purged 72-hour regressors.

Fits the preregistered primary HistGradientBoosting regressor family and the
linear Ridge diagnostic independently for BTC and ALT 72-hour net-return
targets on expanding chronological folds.

Every training window is purged by the full exact 72-hour label horizon before
validation.  This phase measures out-of-sample regression quality and direction
only.  It does not simulate the frozen V7 portfolio policy, inspect the future
holdout, freeze a model, modify paper state, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v7_expected_return"
PHASE1_ROOT = Path("data/model/shared_crypto_v7_expected_return/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v7_expected_return/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
TARGETS = (
    "btc_net_entry_return_72h",
    "alt_net_entry_return_72h",
)
PRIMARY_MODEL = "hist_gradient_boosting_regressor"
DIAGNOSTIC_MODEL = "ridge_regression_diagnostic"
PURGE = timedelta(hours=72)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6
RANDOM_STATE = 1729


def model_candidates() -> dict[str, Pipeline]:
    """Return the frozen V7 Phase 2 model families and hyperparameters."""
    return {
        PRIMARY_MODEL: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                learning_rate=0.04,
                max_iter=200,
                max_leaf_nodes=15,
                min_samples_leaf=40,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        DIAGNOSTIC_MODEL: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
    }


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def _read(path: Path, source: str) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, source)
    return frame.sort_values("timestamp_utc").reset_index(drop=True)


def make_folds(timestamps: pd.Series) -> list[dict]:
    """Build expanding chronological folds with a full 72-hour label purge."""
    timestamps = pd.to_datetime(timestamps, utc=True)
    unique = pd.Series(timestamps.drop_duplicates()).sort_values().reset_index(drop=True)
    if unique.empty:
        raise RuntimeError("Cannot construct V7 folds from empty timestamps")

    first = unique.iloc[0].floor("D")
    last = unique.iloc[-1]
    starts = []
    cursor = first + timedelta(days=MIN_TRAIN_DAYS)
    while cursor <= last:
        starts.append(cursor)
        cursor += timedelta(days=VALIDATION_DAYS)
    starts = starts[-MAX_FOLDS:]

    folds = []
    for start in starts:
        end = min(start + timedelta(days=VALIDATION_DAYS), HOLDOUT)
        train_end = start - PURGE
        train = timestamps < train_end
        validation = (timestamps >= start) & (timestamps < end)
        if train.any() and validation.any():
            folds.append({
                "fold_id": f"fold_{len(folds) + 1:02d}",
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })

    if not folds:
        raise RuntimeError("No valid purged V7 folds were constructed")
    return folds


def _safe_pearson(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) < 2:
        return 0.0
    if float(np.std(actual)) == 0.0 or float(np.std(predicted)) == 0.0:
        return 0.0
    return float(np.corrcoef(actual, predicted)[0, 1])


def regression_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    baseline_prediction: float,
) -> dict[str, float]:
    """Compute fixed error and economic-direction diagnostics."""
    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    baseline = np.full(len(actual_values), float(baseline_prediction), dtype=float)

    mae = float(mean_absolute_error(actual_values, predicted_values))
    rmse = float(np.sqrt(mean_squared_error(actual_values, predicted_values)))
    baseline_mae = float(mean_absolute_error(actual_values, baseline))
    baseline_rmse = float(np.sqrt(mean_squared_error(actual_values, baseline)))

    actual_positive = actual_values > 0.0
    predicted_positive = predicted_values > 0.0
    predicted_positive_count = int(predicted_positive.sum())

    precision_positive = (
        float(actual_positive[predicted_positive].mean())
        if predicted_positive_count
        else 0.0
    )
    mean_actual_when_positive = (
        float(actual_values[predicted_positive].mean())
        if predicted_positive_count
        else 0.0
    )

    return {
        "mae": mae,
        "rmse": rmse,
        "r2": float(r2_score(actual_values, predicted_values)),
        "pearson_correlation": _safe_pearson(actual_values, predicted_values),
        "sign_accuracy": float(
            ((actual_values > 0.0) == (predicted_values > 0.0)).mean()
        ),
        "actual_positive_fraction": float(actual_positive.mean()),
        "predicted_positive_fraction": float(predicted_positive.mean()),
        "precision_when_predicted_positive": precision_positive,
        "mean_actual_return_when_predicted_positive": mean_actual_when_positive,
        "mean_predicted_return": float(predicted_values.mean()),
        "mean_actual_return": float(actual_values.mean()),
        "baseline_train_mean_prediction": float(baseline_prediction),
        "baseline_mae": baseline_mae,
        "baseline_rmse": baseline_rmse,
        "mae_improvement_vs_train_mean": float(baseline_mae - mae),
        "rmse_improvement_vs_train_mean": float(baseline_rmse - rmse),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit both target regressions independently inside each purged fold."""
    prediction_frames = []
    metric_rows = []
    base_columns = [
        "timestamp_utc",
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        "btc_net_entry_return_72h",
        "alt_net_entry_return_72h",
        "alt_basket_assets",
        "oracle_best_sleeve_net25_72h",
    ]

    for fold in make_folds(data["timestamp_utc"]):
        train = data.loc[fold["train"]].copy()
        validation = data.loc[fold["validation"]].copy()

        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold['fold_id']} violates the 72-hour purge")
        if validation["timestamp_utc"].min() < fold["start"]:
            raise RuntimeError(f"{fold['fold_id']} validation starts too early")
        if validation["timestamp_utc"].max() >= HOLDOUT:
            raise RuntimeError(f"{fold['fold_id']} reaches the future holdout")

        out = validation[base_columns].copy()
        out["fold_id"] = fold["fold_id"]

        for target in TARGETS:
            train_target = pd.to_numeric(train[target], errors="raise")
            validation_target = pd.to_numeric(validation[target], errors="raise")
            baseline_prediction = float(train_target.mean())

            for model_id, template in model_candidates().items():
                model = clone(template).fit(train[features], train_target)
                predicted = np.asarray(
                    model.predict(validation[features]),
                    dtype=float,
                )
                if len(predicted) != len(validation):
                    raise RuntimeError(
                        f"{fold['fold_id']} {model_id} returned wrong prediction count"
                    )
                if not np.isfinite(predicted).all():
                    raise RuntimeError(
                        f"{fold['fold_id']} {model_id} returned non-finite predictions"
                    )

                out[f"predicted_{target}_{model_id}"] = predicted
                metric_rows.append({
                    "fold_id": fold["fold_id"],
                    "target": target,
                    "model_id": model_id,
                    "train_rows": int(len(train)),
                    "validation_rows": int(len(validation)),
                    "train_end_exclusive_utc": fold["train_end"].isoformat(),
                    "validation_start_utc": fold["start"].isoformat(),
                    "validation_end_utc": fold["end"].isoformat(),
                    **regression_metrics(
                        validation_target,
                        predicted,
                        baseline_prediction,
                    ),
                })

        prediction_frames.append(out)
        print(
            f"[SUCCESS] {fold['fold_id']} train={len(train):,} "
            f"validation={len(validation):,} purge=72h targets=2 models=2"
        )

    return (
        pd.concat(prediction_frames, ignore_index=True),
        pd.DataFrame(metric_rows),
    )


def _summary(metrics: pd.DataFrame) -> pd.DataFrame:
    identity = {
        "fold_id",
        "target",
        "model_id",
        "train_end_exclusive_utc",
        "validation_start_utc",
        "validation_end_utc",
    }
    numeric = [column for column in metrics.columns if column not in identity]
    rows = []
    for (target, model_id), group in metrics.groupby(
        ["target", "model_id"],
        sort=True,
    ):
        row = {
            "target": target,
            "model_id": model_id,
            "fold_count": int(group["fold_id"].nunique()),
        }
        for column in numeric:
            row[f"mean_{column}"] = float(
                pd.to_numeric(group[column], errors="coerce").mean()
            )
            row[f"median_{column}"] = float(
                pd.to_numeric(group[column], errors="coerce").median()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def run(
    phase1_root: Path = PHASE1_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root = Path(phase1_root)
    output_root = Path(output_root)

    contract = json.loads(
        (phase1_root / "preregistered_contract.json").read_text(encoding="utf-8")
    )
    if contract.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError("Unexpected V7 Phase 1 research version")
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V7 Phase 1 holdout boundary differs from Phase 2")

    registered_models = contract.get("model_candidates", {})
    if registered_models.get("primary") != PRIMARY_MODEL:
        raise RuntimeError("V7 Phase 1 primary model differs from Phase 2")
    if registered_models.get("diagnostic_only") != "ridge_regression":
        raise RuntimeError("V7 Phase 1 diagnostic model differs from Phase 2")
    if tuple(registered_models.get("targets", [])) != TARGETS:
        raise RuntimeError("V7 Phase 1 regression targets differ from Phase 2")

    data = _read(
        phase1_root / "daily_regime_dataset.parquet",
        "V7 daily regime dataset",
    )
    features = list(contract["regime_feature_columns"])
    missing = set(features + list(TARGETS)) - set(data.columns)
    if missing:
        raise RuntimeError(
            f"V7 Phase 1 dataset missing columns: {sorted(missing)}"
        )
    forbidden = set(TARGETS) & set(features)
    if forbidden:
        raise RuntimeError(
            f"V7 targets leaked into model features: {sorted(forbidden)}"
        )

    predictions, metrics = walk_forward(data, features)
    summary = _summary(metrics)

    output_root.mkdir(parents=True, exist_ok=True)
    prediction_path = output_root / "daily_predictions.parquet"
    metrics_path = output_root / "fold_metrics.csv"
    summary_path = output_root / "metrics_summary.csv"

    predictions.to_parquet(prediction_path, index=False)
    metrics.to_csv(metrics_path, index=False)
    summary.to_csv(summary_path, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "purged_72h_walk_forward_expected_return_regressors",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "targets": list(TARGETS),
        "purge_hours": int(PURGE.total_seconds() // 3600),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "primary_model": PRIMARY_MODEL,
        "diagnostic_model": DIAGNOSTIC_MODEL,
        "input_rows": int(len(data)),
        "prediction_rows": int(len(predictions)),
        "fold_count": int(predictions["fold_id"].nunique()),
        "outputs": {
            "daily_predictions": str(prediction_path),
            "fold_metrics": str(metrics_path),
            "metrics_summary": str(summary_path),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "shared_crypto_v6_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Review primary-model fold stability and economic-direction diagnostics, "
            "then evaluate exactly one frozen 72-hour V7 portfolio policy at 25 bps "
            "and stress it at 50 bps without changing thresholds."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase1_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
