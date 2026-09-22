"""Shared Crypto V6 Durable Edge Phase 2: purged daily classifiers.

Fits the preregistered primary HistGradientBoosting classifier and the linear
diagnostic on expanding chronological folds.  Each training window is purged
by the full exact 24-hour label horizon before validation.  This phase measures
classification quality only; it does not simulate the persistent policy,
inspect the future holdout, freeze a model, write paper state, or place orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    log_loss,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v6_durable_edge"
PHASE1_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
TARGET = "best_sleeve_net25_24h"
CLASSES = ("BTC", "ALT", "CASH")
PURGE = timedelta(hours=24)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6
RANDOM_STATE = 1729


def model_candidates() -> dict[str, Pipeline]:
    return {
        "hist_gradient_boosting_classifier": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.04,
                max_iter=160,
                max_leaf_nodes=15,
                min_samples_leaf=40,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        "multinomial_logistic_regression_diagnostic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=0.25,
                max_iter=5000,
                solver="lbfgs",
                class_weight="balanced",
                random_state=RANDOM_STATE,
            )),
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
    unique = pd.Series(
        pd.to_datetime(timestamps, utc=True).drop_duplicates()
    ).sort_values().reset_index(drop=True)
    if unique.empty:
        raise RuntimeError("Cannot construct V6 folds from empty timestamps")
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
        raise RuntimeError("No valid purged V6 folds were constructed")
    return folds


def _ordered_probabilities(model, features: pd.DataFrame) -> np.ndarray:
    raw = np.asarray(model.predict_proba(features), dtype=float)
    model_classes = list(model.classes_)
    missing = set(CLASSES) - set(model_classes)
    if missing:
        raise RuntimeError(f"V6 model was fit without classes: {sorted(missing)}")
    return np.column_stack([raw[:, model_classes.index(label)] for label in CLASSES])


def _multiclass_brier(actual: pd.Series, probabilities: np.ndarray) -> float:
    index = {label: position for position, label in enumerate(CLASSES)}
    one_hot = np.zeros_like(probabilities)
    for row, label in enumerate(actual.astype(str)):
        one_hot[row, index[label]] = 1.0
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


def walk_forward(
    data: pd.DataFrame, features: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = []
    metrics = []
    base_columns = [
        "timestamp_utc", "btc_forward_return_24h", "alt_forward_return_24h",
        "alt_basket_assets", TARGET,
    ]
    for fold in make_folds(data["timestamp_utc"]):
        train = data.loc[fold["train"]]
        validation = data.loc[fold["validation"]]
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold['fold_id']} violates the 24-hour purge")
        missing_classes = set(CLASSES) - set(train[TARGET].astype(str))
        if missing_classes:
            raise RuntimeError(
                f"{fold['fold_id']} training data lacks classes: {sorted(missing_classes)}"
            )
        actual = validation[TARGET].astype(str)
        out = validation[base_columns].copy()
        out["fold_id"] = fold["fold_id"]
        baseline_label = str(train[TARGET].value_counts().idxmax())
        baseline_accuracy = float((actual == baseline_label).mean())
        for model_id, template in model_candidates().items():
            model = clone(template).fit(train[features], train[TARGET].astype(str))
            probabilities = _ordered_probabilities(model, validation[features])
            predicted_indices = probabilities.argmax(axis=1)
            predicted = np.asarray(CLASSES, dtype=object)[predicted_indices]
            ordered = np.sort(probabilities, axis=1)
            confidence = ordered[:, -1]
            margin = ordered[:, -1] - ordered[:, -2]
            out[f"predicted_label_{model_id}"] = predicted
            out[f"confidence_{model_id}"] = confidence
            out[f"margin_{model_id}"] = margin
            for position, label in enumerate(CLASSES):
                out[f"probability_{label.lower()}_{model_id}"] = probabilities[:, position]
            recalls = recall_score(
                actual, predicted, labels=list(CLASSES), average=None, zero_division=0
            )
            metrics.append({
                "fold_id": fold["fold_id"],
                "model_id": model_id,
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "validation_start_utc": fold["start"].isoformat(),
                "validation_end_utc": fold["end"].isoformat(),
                "accuracy": float(accuracy_score(actual, predicted)),
                "balanced_accuracy": float(
                    balanced_accuracy_score(actual, predicted)
                ),
                "macro_f1": float(f1_score(
                    actual, predicted, labels=list(CLASSES),
                    average="macro", zero_division=0,
                )),
                "log_loss": float(log_loss(
                    actual, probabilities, labels=list(CLASSES)
                )),
                "multiclass_brier": _multiclass_brier(actual, probabilities),
                "baseline_label": baseline_label,
                "baseline_accuracy": baseline_accuracy,
                "accuracy_edge_vs_majority": float(
                    accuracy_score(actual, predicted) - baseline_accuracy
                ),
                "mean_confidence": float(confidence.mean()),
                "mean_probability_margin": float(margin.mean()),
                **{
                    f"recall_{label.lower()}": float(recalls[position])
                    for position, label in enumerate(CLASSES)
                },
                **{
                    f"prediction_fraction_{label.lower()}": float(
                        (predicted == label).mean()
                    )
                    for label in CLASSES
                },
            })
        predictions.append(out)
        print(
            f"[SUCCESS] {fold['fold_id']} train={len(train):,} "
            f"validation={len(validation):,} purge=24h"
        )
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(metrics)


def _summary(metrics: pd.DataFrame) -> pd.DataFrame:
    identity = {
        "fold_id", "model_id", "validation_start_utc", "validation_end_utc",
        "baseline_label",
    }
    numeric = [column for column in metrics.columns if column not in identity]
    rows = []
    for model_id, group in metrics.groupby("model_id", sort=True):
        row = {
            "model_id": model_id,
            "fold_count": int(group["fold_id"].nunique()),
        }
        for column in numeric:
            row[f"mean_{column}"] = float(pd.to_numeric(
                group[column], errors="coerce"
            ).mean())
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
        raise RuntimeError("Unexpected V6 Phase 1 research version")
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V6 Phase 1 holdout boundary differs from Phase 2")
    data = _read(
        phase1_root / "daily_regime_dataset.parquet",
        "V6 daily regime dataset",
    )
    features = list(contract["regime_feature_columns"])
    missing = set(features + [TARGET]) - set(data.columns)
    if missing:
        raise RuntimeError(f"V6 Phase 1 dataset missing columns: {sorted(missing)}")
    predictions, metrics = walk_forward(data, features)
    summary = _summary(metrics)

    output_root.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output_root / "daily_predictions.parquet", index=False)
    metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "purged_daily_walk_forward_classifiers",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "target": TARGET,
        "purge_hours": int(PURGE.total_seconds() // 3600),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "primary_model": "hist_gradient_boosting_classifier",
        "diagnostic_model": "multinomial_logistic_regression_diagnostic",
        "input_rows": int(len(data)),
        "prediction_rows": int(len(predictions)),
        "outputs": {
            "daily_predictions": str(output_root / "daily_predictions.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "metrics_summary": str(output_root / "metrics_summary.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Review fold stability and probability quality before running the "
            "single preregistered persistent daily portfolio policy."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
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

