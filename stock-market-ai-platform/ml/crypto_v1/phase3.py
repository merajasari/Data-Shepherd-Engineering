"""Leakage-safe chronological modeling for Crypto V1 Phase 3.

This module only consumes the immutable Phase 2 horizon research panels.  It
does not construct portfolios, simulate trading, or select models on holdout
results.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_v1.config import FORWARD_HORIZONS_DAYS, MODEL_ROOT
from ml.crypto_v1.prepare_dataset import REQUIRED_FEATURES


PHASE3_ROOT = MODEL_ROOT / "phase3"
RANDOM_SEED = 1729
HOLDOUT_START_UTC = pd.Timestamp("2025-08-01", tz="UTC")
INITIAL_TRAIN_END_UTC = pd.Timestamp("2020-12-31", tz="UTC")
VALIDATION_MONTHS = 6
MODEL_FEATURES = tuple(REQUIRED_FEATURES)


@dataclass(frozen=True)
class Fold:
    fold_id: str
    horizon_days: int
    split: str
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp
    validation_start_utc: pd.Timestamp
    validation_end_utc: pd.Timestamp
    purge_days: int

    def as_json(self):
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, pd.Timestamp):
                result[key] = value.isoformat()
        return result


def _month_end(timestamp):
    return timestamp + pd.offsets.MonthEnd(0)


def make_folds(timestamps, horizon_days, holdout_start=HOLDOUT_START_UTC):
    """Create deterministic expanding folds plus one untouched final holdout.

    A training decision is admitted only when its target endpoint is strictly
    before validation.  Thus the final ``horizon_days`` decision dates before
    each validation start are purged.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(), utc=True)).sort_values()
    if dates.empty:
        raise ValueError("Cannot create folds without timestamps")
    holdout_start = pd.Timestamp(holdout_start)
    holdout_start = holdout_start.tz_localize("UTC") if holdout_start.tzinfo is None else holdout_start.tz_convert("UTC")
    development_end = min(holdout_start - pd.Timedelta(days=1), dates.max())
    validation_start = INITIAL_TRAIN_END_UTC + pd.Timedelta(days=1)
    folds = []
    number = 1
    while validation_start <= development_end:
        validation_end = min(_month_end(validation_start + pd.DateOffset(months=VALIDATION_MONTHS - 1)), development_end)
        train_end = validation_start - pd.Timedelta(days=horizon_days + 1)
        folds.append(Fold(
            f"dev_{number:02d}", horizon_days, "development", dates.min(), train_end,
            validation_start, validation_end, horizon_days,
        ))
        validation_start = validation_end + pd.Timedelta(days=1)
        number += 1
    if dates.max() >= holdout_start:
        folds.append(Fold(
            "holdout", horizon_days, "holdout", dates.min(),
            holdout_start - pd.Timedelta(days=horizon_days + 1), holdout_start,
            dates.max(), horizon_days,
        ))
    return folds


def validate_fold(fold, frame):
    train = frame[frame["timestamp_utc"].between(fold.train_start_utc, fold.train_end_utc)]
    validation = frame[frame["timestamp_utc"].between(
        fold.validation_start_utc, fold.validation_end_utc)]
    if train.empty or validation.empty:
        raise ValueError(f"Empty train or validation partition in {fold.fold_id}")
    endpoint = f"target_endpoint_utc_{fold.horizon_days}d"
    if train[endpoint].max() >= validation["timestamp_utc"].min():
        raise ValueError(f"Target leakage across {fold.fold_id} boundary")
    if set(train.index) & set(validation.index):
        raise ValueError(f"Train/validation overlap in {fold.fold_id}")
    return train, validation


def model_definitions(seed=RANDOM_SEED):
    linear_preprocessor = [
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
    return {
        "ridge": Pipeline(linear_preprocessor + [("model", Ridge(alpha=10.0))]),
        "elastic_net": Pipeline(linear_preprocessor + [("model", ElasticNet(
            alpha=0.001, l1_ratio=0.25, max_iter=10_000, random_state=seed,
        ))]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                learning_rate=0.05, max_iter=150, max_leaf_nodes=15,
                l2_regularization=1.0, random_state=seed,
            )),
        ]),
    }


def _stable_random_scores(frame, horizon, fold_id, seed=RANDOM_SEED):
    def score(row):
        value = f"{seed}|{horizon}|{fold_id}|{row.timestamp_utc.isoformat()}|{row.product_id}"
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big") / 2**64
    return np.array([score(row) for row in frame[["timestamp_utc", "product_id"]].itertuples(index=False)])


def baseline_scores(frame, horizon, fold_id):
    momentum = f"btc_relative_return_{horizon}d"
    return {
        "momentum": frame[momentum].to_numpy(dtype=float),
        "random": _stable_random_scores(frame, horizon, fold_id),
        "equal_score": np.zeros(len(frame), dtype=float),
    }


def add_ranks(predictions):
    result = predictions.copy()
    grouped = result.groupby("timestamp_utc", sort=False)
    result["actual_cross_sectional_rank"] = grouped[
        "actual_btc_relative_forward_return"].rank(method="average", ascending=False)
    result["predicted_cross_sectional_rank"] = grouped[
        "predicted_score"].rank(method="average", ascending=False)
    return result


def prediction_frame(validation, scores, horizon, fold, model_id):
    target = f"forward_return_relative_to_btc_{horizon}d"
    result = validation[["timestamp_utc", "product_id", target, "btc_regime"]].copy()
    result = result.rename(columns={target: "actual_btc_relative_forward_return"})
    result["predicted_score"] = np.asarray(scores, dtype=float)
    result["fold_id"] = fold.fold_id
    result["split"] = fold.split
    result["model_id"] = model_id
    result["horizon_days"] = horizon
    return add_ranks(result)


def daily_metrics(predictions):
    rows = []
    keys = ["horizon_days", "model_id", "fold_id", "split", "timestamp_utc", "btc_regime"]
    for key, day in predictions.groupby(keys, sort=True, dropna=False):
        actual = day["actual_btc_relative_forward_return"]
        predicted = day["predicted_score"]
        order = day.sort_values(["predicted_score", "product_id"], ascending=[False, True])
        bucket = max(1, len(order) // 5)
        has_signal = predicted.nunique() > 1
        top_bottom = (order.head(bucket)["actual_btc_relative_forward_return"].mean()
                      - order.tail(bucket)["actual_btc_relative_forward_return"].mean()
                      if has_signal else 0.0)
        top_3 = (order.head(3)["actual_btc_relative_forward_return"].mean()
                 if has_signal else actual.mean())
        top_5 = (order.head(5)["actual_btc_relative_forward_return"].mean()
                 if has_signal else actual.mean())
        rows.append(dict(zip(keys, key)) | {
            "asset_count": len(day),
            "ic": predicted.corr(actual, method="spearman") if has_signal else np.nan,
            "top_minus_bottom_spread": top_bottom,
            "top_3_realized_return": top_3,
            "top_5_realized_return": top_5,
        })
    return pd.DataFrame(rows)


def _summary_row(predictions, daily, dimensions, values):
    mask = pd.Series(True, index=predictions.index)
    day_mask = pd.Series(True, index=daily.index)
    for dimension, value in zip(dimensions, values):
        mask &= predictions[dimension].eq(value)
        day_mask &= daily[dimension].eq(value)
    subset, days = predictions[mask], daily[day_mask]
    actual = subset["actual_btc_relative_forward_return"]
    predicted = subset["predicted_score"]
    row = {dimension: value for dimension, value in zip(dimensions, values)}
    row.update({
        "observation_count": len(subset), "day_count": len(days),
        "mean_ic": days["ic"].mean(), "median_ic": days["ic"].median(),
        "ic_std": days["ic"].std(), "ic_hit_rate": days["ic"].gt(0).mean(),
        "top_minus_bottom_spread": days["top_minus_bottom_spread"].mean(),
        "top_3_realized_return": days["top_3_realized_return"].mean(),
        "top_5_realized_return": days["top_5_realized_return"].mean(),
        "mae": mean_absolute_error(actual, predicted),
        "rmse": mean_squared_error(actual, predicted) ** 0.5,
        "directional_sign_accuracy": np.mean(np.sign(actual) == np.sign(predicted)),
    })
    return row


def summarize_metrics(predictions, daily):
    base = ["horizon_days", "model_id", "split"]
    specs = [
        ("overall", base), ("fold", base + ["fold_id"]),
        ("year", base + ["calendar_year"]), ("btc_regime", base + ["btc_regime"]),
    ]
    predictions = predictions.copy()
    daily = daily.copy()
    predictions["calendar_year"] = predictions["timestamp_utc"].dt.year
    daily["calendar_year"] = daily["timestamp_utc"].dt.year
    rows = []
    for breakdown, dimensions in specs:
        groups = predictions[dimensions].drop_duplicates().itertuples(index=False, name=None)
        for values in groups:
            rows.append({"breakdown": breakdown} | _summary_row(
                predictions, daily, dimensions, values))
    return pd.DataFrame(rows)


def preprocessing_metadata(fitted_pipeline, train, fold, model_id):
    imputer = fitted_pipeline.named_steps["imputer"]
    scaler = fitted_pipeline.named_steps.get("scaler")
    metadata = {
        "model_id": model_id, "fold": fold.as_json(),
        "features": list(MODEL_FEATURES), "imputation": "training-fold median",
        "imputer_statistics": dict(zip(MODEL_FEATURES, imputer.statistics_.tolist())),
        "standardization": scaler is not None,
        "clipping_or_winsorization": None,
        "training_row_count": len(train),
    }
    if scaler is not None:
        metadata["scaler_mean"] = dict(zip(MODEL_FEATURES, scaler.mean_.tolist()))
        metadata["scaler_scale"] = dict(zip(MODEL_FEATURES, scaler.scale_.tolist()))
    return metadata


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_hash():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_phase3(input_root=MODEL_ROOT, output_root=PHASE3_ROOT):
    """Run the frozen model set on development folds, then the holdout."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    all_predictions, fold_manifest, inputs = [], {}, {}
    definitions = model_definitions()
    for horizon in FORWARD_HORIZONS_DAYS:
        input_path = Path(input_root) / f"research_panel_{horizon}d.parquet"
        frame = pd.read_parquet(input_path).sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        inputs[f"{horizon}d"] = {"path": str(input_path), "sha256": _sha256(input_path), "rows": len(frame)}
        folds = make_folds(frame["timestamp_utc"], horizon)
        fold_manifest[f"{horizon}d"] = [fold.as_json() for fold in folds]
        for fold in folds:
            train, validation = validate_fold(fold, frame)
            for model_id, scores in baseline_scores(validation, horizon, fold.fold_id).items():
                all_predictions.append(prediction_frame(validation, scores, horizon, fold, model_id))
            target = f"forward_return_relative_to_btc_{horizon}d"
            for model_id, definition in definitions.items():
                fitted = clone(definition).fit(train[list(MODEL_FEATURES)], train[target])
                scores = fitted.predict(validation[list(MODEL_FEATURES)])
                all_predictions.append(prediction_frame(validation, scores, horizon, fold, model_id))
                artifact_dir = output_root / "artifacts" / f"{horizon}d" / fold.fold_id / model_id
                artifact_dir.mkdir(parents=True, exist_ok=True)
                joblib.dump(fitted, artifact_dir / "model.joblib")
                metadata = preprocessing_metadata(fitted, train, fold, model_id)
                metadata["model_parameters"] = fitted.named_steps["model"].get_params(deep=False)
                (artifact_dir / "metadata.json").write_text(
                    json.dumps(metadata, indent=2, default=_json_default) + "\n", encoding="utf-8")
    predictions = pd.concat(all_predictions, ignore_index=True).sort_values(
        ["horizon_days", "split", "fold_id", "model_id", "timestamp_utc", "product_id"])
    if predictions.duplicated(["timestamp_utc", "product_id", "fold_id", "model_id", "horizon_days"]).any():
        raise ValueError("Duplicate Phase 3 prediction keys")
    daily = daily_metrics(predictions)
    summary = summarize_metrics(predictions, daily)
    predictions.to_parquet(output_root / "predictions.parquet", index=False)
    daily.to_csv(output_root / "daily_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "phase": 3, "research_version": "crypto_v1", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(), "random_seed": RANDOM_SEED,
        "objective": "out-of-sample cross-sectional ranking of BTC-relative forward returns",
        "features": list(MODEL_FEATURES), "inputs": inputs, "folds": fold_manifest,
        "holdout_policy": "Frozen start 2025-08-01; no holdout result used for selection or tuning",
        "purge_embargo": "h decision days removed before each validation; every training target endpoint is strictly before validation start",
        "models": {key: value.named_steps["model"].get_params(deep=False) for key, value in definitions.items()},
        "baselines": ["momentum", "random", "equal_score"],
        "outputs": {"predictions": "predictions.parquet", "daily_metrics": "daily_metrics.csv", "summary": "metrics_summary.csv", "artifacts": "artifacts/"},
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return manifest, predictions, daily, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE3_ROOT)
    args = parser.parse_args()
    manifest, predictions, _, summary = run_phase3(args.input_root, args.output_root)
    print(json.dumps({"manifest": manifest, "prediction_rows": len(predictions),
                      "summary_rows": len(summary)}, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
