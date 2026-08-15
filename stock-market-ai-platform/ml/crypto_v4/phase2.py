"""Crypto V4 Phase 2: pre-registered market-allocation model validation.

Consumes only the frozen Phase 1 BTC/ALT/CASH dataset and evaluates fixed,
pre-registered model candidates with chronological expanding validation.
The untouched future holdout begins 2026-09-01 UTC and is not evaluated here.
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_v4.phase1 import FUTURE_HOLDOUT_START_UTC

RESEARCH_VERSION = "crypto_v4"
PHASE = 2
PHASE1_ROOT = Path("data/model/crypto_v4/phase1")
DATASET_PATH = PHASE1_ROOT / "market_allocation_dataset.parquet"
PHASE1_MANIFEST_PATH = PHASE1_ROOT / "manifest.json"
OUTPUT_ROOT = Path("data/model/crypto_v4/phase2")
RANDOM_SEED = 1729
VALIDATION_MONTHS = 6
INITIAL_TRAIN_END_UTC = pd.Timestamp("2021-12-31T00:00:00Z")
PURGE_DAYS = 7
LABELS = ("BTC", "ALT", "CASH")


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp
    validation_start_utc: pd.Timestamp
    validation_end_utc: pd.Timestamp
    purge_days: int

    def as_json(self):
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, pd.Timestamp):
                d[k] = v.isoformat()
        return d


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _month_end(ts: pd.Timestamp) -> pd.Timestamp:
    return ts + pd.offsets.MonthEnd(0)


def make_folds(timestamps) -> list[Fold]:
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(), utc=True)).sort_values()
    if dates.empty:
        raise ValueError("No timestamps available for Crypto V4 Phase 2")
    development_end = min(FUTURE_HOLDOUT_START_UTC - pd.Timedelta(days=1), dates.max())
    validation_start = INITIAL_TRAIN_END_UTC + pd.Timedelta(days=1)
    folds = []
    number = 1
    while validation_start <= development_end:
        validation_end = min(
            _month_end(validation_start + pd.DateOffset(months=VALIDATION_MONTHS - 1)),
            development_end,
        )
        train_end = validation_start - pd.Timedelta(days=PURGE_DAYS + 1)
        folds.append(Fold(
            fold_id=f"dev_{number:02d}",
            train_start_utc=dates.min(),
            train_end_utc=train_end,
            validation_start_utc=validation_start,
            validation_end_utc=validation_end,
            purge_days=PURGE_DAYS,
        ))
        validation_start = validation_end + pd.Timedelta(days=1)
        number += 1
    if not folds:
        raise ValueError("No development folds were created")
    return folds


def model_definitions(seed=RANDOM_SEED):
    return {
        "multinomial_logistic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=1.0,
                max_iter=5000,
                multi_class="auto",
                random_state=seed,
            )),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=15,
                l2_regularization=1.0,
                random_state=seed,
            )),
        ]),
    }


def _majority_class(train: pd.DataFrame) -> str:
    counts = train["allocation_target"].value_counts()
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], LABELS.index(kv[0])))
    return ordered[0][0]


def _return_columns(frame: pd.DataFrame):
    return {
        "BTC": frame["btc_forward_return_7d"].to_numpy(dtype=float),
        "ALT": frame["alt_forward_return_7d"].to_numpy(dtype=float),
        "CASH": frame["cash_forward_return_7d"].to_numpy(dtype=float),
    }


def _decision_returns(validation: pd.DataFrame, predicted_labels: np.ndarray) -> np.ndarray:
    returns = _return_columns(validation)
    return np.array([returns[label][i] for i, label in enumerate(predicted_labels)], dtype=float)


def _oracle_returns(validation: pd.DataFrame) -> np.ndarray:
    return validation["best_forward_return_7d"].to_numpy(dtype=float)


def _btc_returns(validation: pd.DataFrame) -> np.ndarray:
    return validation["btc_forward_return_7d"].to_numpy(dtype=float)


def _alt_returns(validation: pd.DataFrame) -> np.ndarray:
    return validation["alt_forward_return_7d"].to_numpy(dtype=float)


def _safe_log_loss(y_true, proba, classes):
    try:
        return float(log_loss(y_true, proba, labels=list(classes)))
    except ValueError:
        return np.nan


def _metric_row(fold, model_id, validation, predicted, probabilities=None, classes=None):
    actual = validation["allocation_target"].to_numpy(dtype=object)
    strategy = _decision_returns(validation, predicted)
    oracle = _oracle_returns(validation)
    btc = _btc_returns(validation)
    alt = _alt_returns(validation)
    cash = np.zeros(len(validation), dtype=float)
    counts = pd.Series(predicted).value_counts()
    row = {
        "fold_id": fold.fold_id,
        "model_id": model_id,
        "observation_count": int(len(validation)),
        "accuracy": float(accuracy_score(actual, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "mean_selected_forward_return_7d": float(np.mean(strategy)),
        "median_selected_forward_return_7d": float(np.median(strategy)),
        "positive_selected_return_rate": float(np.mean(strategy > 0)),
        "mean_btc_forward_return_7d": float(np.mean(btc)),
        "mean_alt_forward_return_7d": float(np.mean(alt)),
        "mean_cash_forward_return_7d": float(np.mean(cash)),
        "mean_oracle_forward_return_7d": float(np.mean(oracle)),
        "mean_excess_vs_btc": float(np.mean(strategy - btc)),
        "mean_excess_vs_alt": float(np.mean(strategy - alt)),
        "oracle_capture_ratio": float(np.mean(strategy) / np.mean(oracle)) if np.mean(oracle) != 0 else np.nan,
        "btc_prediction_fraction": float(counts.get("BTC", 0) / len(validation)),
        "alt_prediction_fraction": float(counts.get("ALT", 0) / len(validation)),
        "cash_prediction_fraction": float(counts.get("CASH", 0) / len(validation)),
        "log_loss": np.nan,
    }
    if probabilities is not None and classes is not None:
        row["log_loss"] = _safe_log_loss(actual, probabilities, classes)
    return row


def load_inputs(dataset_path=DATASET_PATH, manifest_path=PHASE1_MANIFEST_PATH):
    dataset_path = Path(dataset_path)
    manifest_path = Path(manifest_path)
    for path in (dataset_path, manifest_path):
        if not path.exists():
            raise FileNotFoundError(path)
    phase1_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hash = phase1_manifest.get("dataset_sha256")
    actual_hash = _sha256(dataset_path)
    if expected_hash and expected_hash != actual_hash:
        raise RuntimeError("Crypto V4 Phase 1 dataset hash does not match manifest")
    frame = pd.read_parquet(dataset_path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (frame["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
        raise RuntimeError("Future holdout rows present in Phase 1 dataset")
    features = list(phase1_manifest["feature_columns"])
    required = set(features) | {
        "timestamp_utc", "allocation_target", "btc_forward_return_7d",
        "alt_forward_return_7d", "cash_forward_return_7d", "best_forward_return_7d",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Phase 1 dataset missing columns: " + ", ".join(missing))
    return dataset_path, manifest_path, phase1_manifest, frame, features


def run_phase2(dataset_path=DATASET_PATH, manifest_path=PHASE1_MANIFEST_PATH, output_root=OUTPUT_ROOT):
    dataset_path, manifest_path, phase1_manifest, frame, features = load_inputs(dataset_path, manifest_path)
    input_hashes_before = {
        "phase1_dataset": _sha256(dataset_path),
        "phase1_manifest": _sha256(manifest_path),
    }
    folds = make_folds(frame["timestamp_utc"])
    models = model_definitions()
    predictions = []
    metrics = []
    fitted_artifacts = []

    for fold in folds:
        train = frame[frame["timestamp_utc"].between(fold.train_start_utc, fold.train_end_utc)].copy()
        validation = frame[frame["timestamp_utc"].between(
            fold.validation_start_utc, fold.validation_end_utc
        )].copy()
        if train.empty or validation.empty:
            raise ValueError(f"Empty train/validation split in {fold.fold_id}")
        if train["timestamp_utc"].max() >= validation["timestamp_utc"].min() - pd.Timedelta(days=PURGE_DAYS):
            raise RuntimeError(f"Purge violation in {fold.fold_id}")

        majority = _majority_class(train)
        majority_pred = np.repeat(majority, len(validation)).astype(object)
        metrics.append(_metric_row(fold, "majority_class", validation, majority_pred))
        for i, row in validation.reset_index(drop=True).iterrows():
            predictions.append({
                "timestamp_utc": row["timestamp_utc"],
                "fold_id": fold.fold_id,
                "model_id": "majority_class",
                "actual_label": row["allocation_target"],
                "predicted_label": majority,
                "selected_forward_return_7d": _decision_returns(validation.iloc[[i]], np.array([majority]))[0],
            })

        for model_id, template in models.items():
            model = template
            X_train = train[features]
            y_train = train["allocation_target"]
            X_val = validation[features]
            model.fit(X_train, y_train)
            pred = model.predict(X_val)
            proba = model.predict_proba(X_val)
            classes = model.named_steps["model"].classes_
            metrics.append(_metric_row(fold, model_id, validation, pred, proba, classes))

            artifact_dir = Path(output_root) / "artifacts" / fold.fold_id / model_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "model.joblib"
            joblib.dump(model, artifact_path)
            fitted_artifacts.append(str(artifact_path))

            selected_returns = _decision_returns(validation, pred)
            class_index = {c: i for i, c in enumerate(classes)}
            for i, (_, row) in enumerate(validation.reset_index(drop=True).iterrows()):
                record = {
                    "timestamp_utc": row["timestamp_utc"],
                    "fold_id": fold.fold_id,
                    "model_id": model_id,
                    "actual_label": row["allocation_target"],
                    "predicted_label": pred[i],
                    "selected_forward_return_7d": float(selected_returns[i]),
                }
                for label in LABELS:
                    record[f"prob_{label.lower()}"] = float(proba[i, class_index[label]]) if label in class_index else np.nan
                predictions.append(record)

    predictions_df = pd.DataFrame(predictions).sort_values(["model_id", "timestamp_utc", "fold_id"])
    metrics_df = pd.DataFrame(metrics).sort_values(["model_id", "fold_id"])
    summary_rows = []
    for model_id, g in metrics_df.groupby("model_id", sort=True):
        weights = g["observation_count"].to_numpy(dtype=float)
        def wavg(col):
            vals = pd.to_numeric(g[col], errors="coerce").to_numpy(dtype=float)
            mask = np.isfinite(vals)
            return float(np.average(vals[mask], weights=weights[mask])) if mask.any() else np.nan
        summary_rows.append({
            "model_id": model_id,
            "fold_count": int(len(g)),
            "observation_count": int(g["observation_count"].sum()),
            "weighted_accuracy": wavg("accuracy"),
            "weighted_balanced_accuracy": wavg("balanced_accuracy"),
            "weighted_log_loss": wavg("log_loss"),
            "mean_selected_forward_return_7d": wavg("mean_selected_forward_return_7d"),
            "mean_excess_vs_btc": wavg("mean_excess_vs_btc"),
            "mean_excess_vs_alt": wavg("mean_excess_vs_alt"),
            "oracle_capture_ratio": wavg("oracle_capture_ratio"),
            "btc_prediction_fraction": wavg("btc_prediction_fraction"),
            "alt_prediction_fraction": wavg("alt_prediction_fraction"),
            "cash_prediction_fraction": wavg("cash_prediction_fraction"),
        })
    summary_df = pd.DataFrame(summary_rows).sort_values("model_id")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    predictions_path = output_root / "predictions.parquet"
    metrics_path = output_root / "fold_metrics.csv"
    summary_path = output_root / "metrics_summary.csv"
    predictions_df.to_parquet(predictions_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    input_hashes_after = {
        "phase1_dataset": _sha256(dataset_path),
        "phase1_manifest": _sha256(manifest_path),
    }
    if input_hashes_before != input_hashes_after:
        raise RuntimeError("Frozen Crypto V4 Phase 1 inputs changed during Phase 2")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "market_allocation_model_validation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "objective": "predict BTC vs ALT vs CASH winner over the next 7 days using only completed-close BTC state features",
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "No rows at or after 2026-09-01 UTC are present or evaluated.",
        "validation": {
            "type": "expanding chronological six-month folds",
            "initial_train_end_utc": INITIAL_TRAIN_END_UTC.isoformat(),
            "validation_months": VALIDATION_MONTHS,
            "purge_days": PURGE_DAYS,
            "folds": [fold.as_json() for fold in folds],
        },
        "features": features,
        "models": {
            "majority_class": "training-fold majority class baseline",
            "multinomial_logistic": "median imputation + standardization + multinomial logistic regression, fixed C=1.0",
            "hist_gradient_boosting": "median imputation + HistGradientBoostingClassifier, lr=.05 max_iter=150 max_leaf_nodes=15 l2=1",
        },
        "selection_policy": (
            "Phase 2 reports development-only evidence. No candidate is promoted, retuned, or selected "
            "for future holdout based on these outputs without a separate governance decision."
        ),
        "input": {
            "phase1_dataset": str(dataset_path),
            "phase1_manifest": str(manifest_path),
            "hashes": input_hashes_before,
        },
        "outputs": {
            "predictions": str(predictions_path),
            "fold_metrics": str(metrics_path),
            "metrics_summary": str(summary_path),
            "artifacts": fitted_artifacts,
        },
        "next_step": "Review development-only model quality and allocation economics; do not touch the September 2026 future holdout.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, summary_df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--phase1-manifest", type=Path, default=PHASE1_MANIFEST_PATH)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    manifest, summary = run_phase2(args.dataset, args.phase1_manifest, args.output_root)
    print("CRYPTO V4 PHASE 2")
    print("=" * 72)
    print(f"Folds: {len(manifest['validation']['folds'])}")
    print(summary.to_string(index=False))
    print(f"Output: {manifest['outputs']['metrics_summary']}")
    print("Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
