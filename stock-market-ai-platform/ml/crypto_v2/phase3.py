"""Crypto V2 Phase 3: pre-registered walk-forward cross-sectional modeling.

Consumes only frozen Phase 2 horizon datasets. Modeling dates require a
minimum contemporaneous eligible universe size. Validation uses expanding
chronological folds with an h-day purge so every training target endpoint is
strictly before validation. A genuinely future holdout beginning 2026-09-01 is
reserved and is not evaluated by this phase while current data ends before it.
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

from ml.crypto_v2.config import FORWARD_HORIZONS_DAYS, MODEL_ROOT, RESEARCH_VERSION
from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES

PHASE3_ROOT = MODEL_ROOT / "phase3"
RANDOM_SEED = 1729
MIN_CROSS_SECTION_ASSETS = 10
DEVELOPMENT_VALIDATION_START_UTC = pd.Timestamp("2021-07-01", tz="UTC")
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01", tz="UTC")
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
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, pd.Timestamp):
                out[key] = value.isoformat()
        return out


def _month_end(ts):
    return ts + pd.offsets.MonthEnd(0)


def enforce_cross_section_breadth(frame, minimum=MIN_CROSS_SECTION_ASSETS):
    """Keep only dates with at least the pre-registered eligible asset count."""
    counts = frame.groupby("timestamp_utc")["product_id"].transform("nunique")
    out = frame.loc[counts >= int(minimum)].copy()
    out["eligible_asset_count"] = out.groupby("timestamp_utc")["product_id"].transform("nunique")
    return out.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def make_folds(timestamps, horizon_days,
               validation_start=DEVELOPMENT_VALIDATION_START_UTC,
               future_holdout_start=FUTURE_HOLDOUT_START_UTC):
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(), utc=True)).sort_values()
    if dates.empty:
        raise ValueError("Cannot create folds without timestamps")
    validation_start = pd.Timestamp(validation_start)
    validation_start = validation_start.tz_localize("UTC") if validation_start.tzinfo is None else validation_start.tz_convert("UTC")
    holdout_start = pd.Timestamp(future_holdout_start)
    holdout_start = holdout_start.tz_localize("UTC") if holdout_start.tzinfo is None else holdout_start.tz_convert("UTC")
    development_end = min(dates.max(), holdout_start - pd.Timedelta(days=1))
    folds = []
    number = 1
    while validation_start <= development_end:
        validation_end = min(
            _month_end(validation_start + pd.DateOffset(months=VALIDATION_MONTHS - 1)),
            development_end,
        )
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
    validation = frame[frame["timestamp_utc"].between(fold.validation_start_utc, fold.validation_end_utc)]
    if train.empty or validation.empty:
        raise ValueError(f"Empty train or validation partition in {fold.fold_id}")
    endpoint = f"target_endpoint_utc_{fold.horizon_days}d"
    if pd.to_datetime(train[endpoint], utc=True).max() >= validation["timestamp_utc"].min():
        raise ValueError(f"Target leakage across {fold.fold_id} boundary")
    if set(train.index) & set(validation.index):
        raise ValueError(f"Train/validation overlap in {fold.fold_id}")
    return train, validation


def model_definitions(seed=RANDOM_SEED):
    linear = [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
    return {
        "ridge": Pipeline(linear + [("model", Ridge(alpha=10.0))]),
        "elastic_net": Pipeline(linear + [("model", ElasticNet(
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
    values = []
    for row in frame[["timestamp_utc", "product_id"]].itertuples(index=False):
        key = f"{seed}|{horizon}|{fold_id}|{row.timestamp_utc.isoformat()}|{row.product_id}"
        values.append(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") / 2**64)
    return np.asarray(values)


def baseline_scores(frame, horizon, fold_id):
    return {
        "momentum": frame[f"btc_relative_return_{horizon}d"].to_numpy(dtype=float),
        "random": _stable_random_scores(frame, horizon, fold_id),
        "equal_score": np.zeros(len(frame), dtype=float),
    }


def prediction_frame(validation, scores, horizon, fold, model_id):
    target = f"forward_return_relative_to_btc_{horizon}d"
    cols = ["timestamp_utc", "product_id", target, "btc_regime", "eligible_asset_count"]
    out = validation[cols].copy().rename(columns={target: "actual_btc_relative_forward_return"})
    out["predicted_score"] = np.asarray(scores, dtype=float)
    out["fold_id"] = fold.fold_id
    out["split"] = fold.split
    out["model_id"] = model_id
    out["horizon_days"] = horizon
    grouped = out.groupby("timestamp_utc", sort=False)
    out["actual_cross_sectional_rank"] = grouped["actual_btc_relative_forward_return"].rank(method="average", ascending=False)
    out["predicted_cross_sectional_rank"] = grouped["predicted_score"].rank(method="average", ascending=False)
    return out


def daily_metrics(predictions):
    rows = []
    keys = ["horizon_days", "model_id", "fold_id", "split", "timestamp_utc", "btc_regime"]
    for key, day in predictions.groupby(keys, sort=True, dropna=False):
        actual = day["actual_btc_relative_forward_return"]
        predicted = day["predicted_score"]
        order = day.sort_values(["predicted_score", "product_id"], ascending=[False, True])
        bucket = max(1, len(order) // 5)
        has_signal = predicted.nunique() > 1
        rows.append(dict(zip(keys, key)) | {
            "asset_count": len(day),
            "ic": predicted.corr(actual, method="spearman") if has_signal else np.nan,
            "top_minus_bottom_spread": (
                order.head(bucket)["actual_btc_relative_forward_return"].mean()
                - order.tail(bucket)["actual_btc_relative_forward_return"].mean()
                if has_signal else 0.0
            ),
            "top_3_realized_return": order.head(3)["actual_btc_relative_forward_return"].mean() if has_signal else actual.mean(),
            "top_5_realized_return": order.head(5)["actual_btc_relative_forward_return"].mean() if has_signal else actual.mean(),
        })
    return pd.DataFrame(rows)


def summarize_metrics(predictions, daily):
    rows = []
    for (horizon, model_id, split), subset in predictions.groupby(["horizon_days", "model_id", "split"], sort=True):
        days = daily[(daily["horizon_days"] == horizon) & (daily["model_id"] == model_id) & (daily["split"] == split)]
        actual = subset["actual_btc_relative_forward_return"]
        predicted = subset["predicted_score"]
        rows.append({
            "horizon_days": horizon,
            "model_id": model_id,
            "split": split,
            "observation_count": len(subset),
            "day_count": len(days),
            "mean_ic": days["ic"].mean(),
            "median_ic": days["ic"].median(),
            "ic_hit_rate": days["ic"].gt(0).mean(),
            "top_minus_bottom_spread": days["top_minus_bottom_spread"].mean(),
            "top_3_realized_return": days["top_3_realized_return"].mean(),
            "top_5_realized_return": days["top_5_realized_return"].mean(),
            "mae": mean_absolute_error(actual, predicted),
            "rmse": mean_squared_error(actual, predicted) ** 0.5,
            "directional_sign_accuracy": float(np.mean(np.sign(actual) == np.sign(predicted))),
        })
    return pd.DataFrame(rows)


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_phase3(input_root=MODEL_ROOT, output_root=PHASE3_ROOT):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    all_predictions, fold_manifest, inputs = [], {}, {}
    definitions = model_definitions()

    for horizon in FORWARD_HORIZONS_DAYS:
        input_path = Path(input_root) / f"research_panel_{horizon}d.parquet"
        frame = pd.read_parquet(input_path).sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        before_rows = len(frame)
        frame = enforce_cross_section_breadth(frame)
        if frame.empty:
            raise ValueError(f"No {horizon}d rows survive minimum cross-section policy")
        inputs[f"{horizon}d"] = {
            "path": str(input_path), "sha256": _sha256(input_path),
            "source_rows": before_rows, "modeling_rows": len(frame),
            "modeling_start_utc": frame["timestamp_utc"].min().isoformat(),
            "modeling_end_utc": frame["timestamp_utc"].max().isoformat(),
        }
        folds = make_folds(frame["timestamp_utc"], horizon)
        fold_manifest[f"{horizon}d"] = [f.as_json() for f in folds]
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

    predictions = pd.concat(all_predictions, ignore_index=True).sort_values(
        ["horizon_days", "split", "fold_id", "model_id", "timestamp_utc", "product_id"]
    )
    if predictions.duplicated(["timestamp_utc", "product_id", "fold_id", "model_id", "horizon_days"]).any():
        raise ValueError("Duplicate Phase 3 prediction keys")
    daily = daily_metrics(predictions)
    summary = summarize_metrics(predictions, daily)
    predictions.to_parquet(output_root / "predictions.parquet", index=False)
    daily.to_csv(output_root / "daily_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)

    manifest = {
        "phase": 3,
        "research_version": RESEARCH_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "random_seed": RANDOM_SEED,
        "objective": "development-only out-of-sample cross-sectional ranking of BTC-relative forward returns",
        "features": list(MODEL_FEATURES),
        "minimum_cross_section_assets": MIN_CROSS_SECTION_ASSETS,
        "development_validation_start_utc": DEVELOPMENT_VALIDATION_START_UTC.isoformat(),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "Data at or after 2026-09-01 is reserved for genuinely future validation and is not evaluated by current Phase 3 runs.",
        "inputs": inputs,
        "folds": fold_manifest,
        "purge_embargo": "h decision days removed before every validation start; every training target endpoint is strictly before validation.",
        "models": {key: value.named_steps["model"].get_params(deep=False) for key, value in definitions.items()},
        "baselines": ["momentum", "random", "equal_score"],
        "outputs": {"predictions": "predictions.parquet", "daily_metrics": "daily_metrics.csv", "summary": "metrics_summary.csv", "artifacts": "artifacts/"},
        "next_step": "Review development-fold diagnostics only. Do not promote or tune on future holdout until genuinely new data at or after 2026-09-01 exists.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest, predictions, daily, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE3_ROOT)
    args = parser.parse_args(argv)
    manifest, _, _, _ = run_phase3(args.input_root, args.output_root)
    print(json.dumps({
        "phase": manifest["phase"],
        "minimum_cross_section_assets": manifest["minimum_cross_section_assets"],
        "development_validation_start_utc": manifest["development_validation_start_utc"],
        "future_holdout_start_utc": manifest["future_holdout_start_utc"],
        "future_holdout_policy": manifest["future_holdout_policy"],
        "inputs": manifest["inputs"],
        "next_step": manifest["next_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
