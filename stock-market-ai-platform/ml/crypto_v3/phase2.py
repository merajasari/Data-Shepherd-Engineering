"""Crypto V3 Phase 2: pre-registered dual-target walk-forward modeling.

Consumes only the frozen Crypto V3 Phase 1 dataset. Two separate 7-day tasks are
modeled without portfolio construction:

1) positive_probability: estimate P(forward_return_7d > 0).
2) risk_adjusted_return: estimate the Phase 1 ex-ante-volatility-normalized target.

Validation uses expanding six-month development folds with a 7-day purge so
all training target endpoints precede validation. BTC remains excluded from the
investable universe, BTC context features remain inputs, no BTC V1 signal is
used, and data at or after 2026-09-01 remains an untouched future holdout.
No threshold search, portfolio simulation, hyperparameter tuning, leverage,
shorting, derivatives, or live execution occurs in this phase.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_v3.phase1 import (
    DATASET_PATH,
    FUTURE_HOLDOUT_START_UTC,
    HORIZON_DAYS,
    MODEL_FEATURES,
    PHASE1_ROOT,
    RESEARCH_VERSION,
    TARGET_POSITIVE,
    TARGET_RISK_ADJUSTED,
)

PHASE2_ROOT = Path("data/model/crypto_v3/phase2")
DEVELOPMENT_VALIDATION_START_UTC = pd.Timestamp("2021-07-01", tz="UTC")
VALIDATION_MONTHS = 6
RANDOM_SEED = 1729
TARGET_ENDPOINT = "target_endpoint_utc_7d"
CLASSIFIER_MODEL_ID = "hist_gradient_boosting_classifier"
CLASSIFIER_LINEAR_ID = "logistic_regression"
CLASSIFIER_BASELINE_ID = "train_prevalence"
REGRESSOR_MODEL_ID = "hist_gradient_boosting_regressor"
REGRESSOR_LINEAR_ID = "ridge"
REGRESSOR_BASELINE_ID = "zero_score"


@dataclass(frozen=True)
class Fold:
    fold_id: str
    split: str
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp
    validation_start_utc: pd.Timestamp
    validation_end_utc: pd.Timestamp
    purge_days: int

    def as_json(self):
        out = asdict(self)
        return {
            k: (v.isoformat() if isinstance(v, pd.Timestamp) else v)
            for k, v in out.items()
        }


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _month_end(ts):
    return ts + pd.offsets.MonthEnd(0)


def make_folds(
    timestamps,
    validation_start=DEVELOPMENT_VALIDATION_START_UTC,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
):
    dates = pd.DatetimeIndex(
        pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)
    ).sort_values()
    if dates.empty:
        raise ValueError("Cannot create Crypto V3 Phase 2 folds without timestamps")
    validation_start = pd.Timestamp(validation_start)
    validation_start = (
        validation_start.tz_localize("UTC")
        if validation_start.tzinfo is None
        else validation_start.tz_convert("UTC")
    )
    holdout_start = pd.Timestamp(holdout_start)
    holdout_start = (
        holdout_start.tz_localize("UTC")
        if holdout_start.tzinfo is None
        else holdout_start.tz_convert("UTC")
    )
    development_end = min(dates.max(), holdout_start - pd.Timedelta(days=1))
    folds = []
    n = 1
    while validation_start <= development_end:
        validation_end = min(
            _month_end(validation_start + pd.DateOffset(months=VALIDATION_MONTHS - 1)),
            development_end,
        )
        train_end = validation_start - pd.Timedelta(days=HORIZON_DAYS + 1)
        folds.append(Fold(
            fold_id=f"dev_{n:02d}",
            split="development",
            train_start_utc=dates.min(),
            train_end_utc=train_end,
            validation_start_utc=validation_start,
            validation_end_utc=validation_end,
            purge_days=HORIZON_DAYS,
        ))
        validation_start = validation_end + pd.Timedelta(days=1)
        n += 1
    if dates.max() >= holdout_start:
        folds.append(Fold(
            fold_id="holdout",
            split="holdout",
            train_start_utc=dates.min(),
            train_end_utc=holdout_start - pd.Timedelta(days=HORIZON_DAYS + 1),
            validation_start_utc=holdout_start,
            validation_end_utc=dates.max(),
            purge_days=HORIZON_DAYS,
        ))
    return folds


def load_dataset(path=DATASET_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path).copy()
    required = set(MODEL_FEATURES) | {
        "timestamp_utc", "product_id", TARGET_POSITIVE, TARGET_RISK_ADJUSTED,
        TARGET_ENDPOINT,
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError("Crypto V3 Phase 1 dataset missing columns: " + ", ".join(sorted(missing)))
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df[TARGET_ENDPOINT] = pd.to_datetime(df[TARGET_ENDPOINT], utc=True)
    if df.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate Crypto V3 Phase 1 dataset keys")
    if (df["product_id"] == "BTC-USD").any():
        raise ValueError("BTC-USD must not appear in Crypto V3 investable dataset")
    return df.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def validate_fold(fold, df):
    train = df[df["timestamp_utc"].between(fold.train_start_utc, fold.train_end_utc)].copy()
    validation = df[df["timestamp_utc"].between(fold.validation_start_utc, fold.validation_end_utc)].copy()
    train = train[
        train[TARGET_POSITIVE].notna()
        & train[TARGET_RISK_ADJUSTED].notna()
        & train[list(MODEL_FEATURES)].notna().all(axis=1)
    ]
    validation = validation[
        validation[TARGET_POSITIVE].notna()
        & validation[TARGET_RISK_ADJUSTED].notna()
        & validation[list(MODEL_FEATURES)].notna().all(axis=1)
    ]
    if train.empty or validation.empty:
        raise ValueError(f"Empty train or validation partition in {fold.fold_id}")
    if pd.to_datetime(train[TARGET_ENDPOINT], utc=True).max() >= validation["timestamp_utc"].min():
        raise ValueError(f"Target leakage across {fold.fold_id}")
    return train, validation


def classifier_definitions(seed=RANDOM_SEED):
    return {
        CLASSIFIER_MODEL_ID: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=15,
                l2_regularization=1.0,
                random_state=seed,
            )),
        ]),
        CLASSIFIER_LINEAR_ID: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=1.0,
                max_iter=2000,
                random_state=seed,
            )),
        ]),
    }


def regressor_definitions(seed=RANDOM_SEED):
    return {
        REGRESSOR_MODEL_ID: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=15,
                l2_regularization=1.0,
                random_state=seed,
            )),
        ]),
        REGRESSOR_LINEAR_ID: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
    }


def _classifier_prediction_frame(validation, probability, model_id, fold):
    out = validation[["timestamp_utc", "product_id", TARGET_POSITIVE]].copy()
    out = out.rename(columns={TARGET_POSITIVE: "actual_positive_absolute_7d"})
    out["actual_positive_absolute_7d"] = out["actual_positive_absolute_7d"].astype(bool)
    out["predicted_positive_probability"] = np.asarray(probability, dtype=float)
    out["model_id"] = model_id
    out["task"] = "positive_probability"
    out["fold_id"] = fold.fold_id
    out["split"] = fold.split
    return out


def _regressor_prediction_frame(validation, score, model_id, fold):
    out = validation[["timestamp_utc", "product_id", TARGET_RISK_ADJUSTED]].copy()
    out = out.rename(columns={TARGET_RISK_ADJUSTED: "actual_risk_adjusted_return_7d"})
    out["predicted_risk_adjusted_return_7d"] = np.asarray(score, dtype=float)
    out["model_id"] = model_id
    out["task"] = "risk_adjusted_return"
    out["fold_id"] = fold.fold_id
    out["split"] = fold.split
    return out


def build_predictions(df):
    classifier_rows = []
    regressor_rows = []
    fold_rows = []
    for fold in make_folds(df["timestamp_utc"]):
        if fold.split != "development":
            continue
        train, validation = validate_fold(fold, df)
        X_train = train[list(MODEL_FEATURES)]
        X_val = validation[list(MODEL_FEATURES)]
        y_class = train[TARGET_POSITIVE].astype(int)
        y_reg = train[TARGET_RISK_ADJUSTED].astype(float)

        for model_id, definition in classifier_definitions().items():
            model = clone(definition).fit(X_train, y_class)
            probability = model.predict_proba(X_val)[:, 1]
            classifier_rows.append(
                _classifier_prediction_frame(validation, probability, model_id, fold)
            )
        prevalence = float(y_class.mean())
        classifier_rows.append(
            _classifier_prediction_frame(
                validation,
                np.full(len(validation), prevalence, dtype=float),
                CLASSIFIER_BASELINE_ID,
                fold,
            )
        )

        for model_id, definition in regressor_definitions().items():
            model = clone(definition).fit(X_train, y_reg)
            score = model.predict(X_val)
            regressor_rows.append(
                _regressor_prediction_frame(validation, score, model_id, fold)
            )
        regressor_rows.append(
            _regressor_prediction_frame(
                validation,
                np.zeros(len(validation), dtype=float),
                REGRESSOR_BASELINE_ID,
                fold,
            )
        )
        fold_rows.append(fold.as_json())

    classifier = pd.concat(classifier_rows, ignore_index=True).sort_values(
        ["timestamp_utc", "model_id", "product_id"]
    ).reset_index(drop=True)
    regressor = pd.concat(regressor_rows, ignore_index=True).sort_values(
        ["timestamp_utc", "model_id", "product_id"]
    ).reset_index(drop=True)
    return classifier, regressor, fold_rows


def summarize_classifier(predictions):
    rows = []
    for (model_id, split), g in predictions.groupby(["model_id", "split"], sort=True):
        y = g["actual_positive_absolute_7d"].astype(int).to_numpy()
        p = g["predicted_positive_probability"].astype(float).to_numpy()
        hard = p >= 0.5
        auc = roc_auc_score(y, p) if len(np.unique(y)) > 1 and np.std(p) > 0 else np.nan
        rows.append({
            "task": "positive_probability",
            "model_id": model_id,
            "split": split,
            "observation_count": int(len(g)),
            "roc_auc": float(auc) if pd.notna(auc) else np.nan,
            "brier_score": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, np.clip(p, 1e-9, 1 - 1e-9))),
            "accuracy_at_0_5": float(accuracy_score(y, hard)),
            "predicted_positive_rate_at_0_5": float(hard.mean()),
            "actual_positive_rate": float(y.mean()),
        })
    return pd.DataFrame(rows)


def summarize_regressor(predictions):
    rows = []
    for (model_id, split), g in predictions.groupby(["model_id", "split"], sort=True):
        y = g["actual_risk_adjusted_return_7d"].astype(float)
        p = g["predicted_risk_adjusted_return_7d"].astype(float)
        pearson = p.corr(y) if p.nunique() > 1 else np.nan
        spearman = p.corr(y, method="spearman") if p.nunique() > 1 else np.nan
        rows.append({
            "task": "risk_adjusted_return",
            "model_id": model_id,
            "split": split,
            "observation_count": int(len(g)),
            "mae": float(mean_absolute_error(y, p)),
            "rmse": float(mean_squared_error(y, p) ** 0.5),
            "pearson_correlation": float(pearson) if pd.notna(pearson) else np.nan,
            "spearman_correlation": float(spearman) if pd.notna(spearman) else np.nan,
            "directional_sign_accuracy": float((np.sign(y) == np.sign(p)).mean()),
        })
    return pd.DataFrame(rows)


def run_phase2(dataset_path=DATASET_PATH, output_root=PHASE2_ROOT):
    dataset_path = Path(dataset_path)
    before = _sha256(dataset_path)
    df = load_dataset(dataset_path)
    classifier, regressor, folds = build_predictions(df)
    classifier_metrics = summarize_classifier(classifier)
    regressor_metrics = summarize_regressor(regressor)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    classifier_path = output_root / "classifier_predictions.parquet"
    regressor_path = output_root / "regressor_predictions.parquet"
    classifier_metrics_path = output_root / "classifier_metrics.csv"
    regressor_metrics_path = output_root / "regressor_metrics.csv"
    folds_path = output_root / "folds.json"
    classifier.to_parquet(classifier_path, index=False)
    regressor.to_parquet(regressor_path, index=False)
    classifier_metrics.to_csv(classifier_metrics_path, index=False)
    regressor_metrics.to_csv(regressor_metrics_path, index=False)
    folds_path.write_text(json.dumps(folds, indent=2) + "\n", encoding="utf-8")

    after = _sha256(dataset_path)
    if after != before:
        raise RuntimeError("Frozen Crypto V3 Phase 1 dataset changed during Phase 2")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "dual_target_walk_forward_modeling",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "horizon_days": HORIZON_DAYS,
        "development_validation_start_utc": DEVELOPMENT_VALIDATION_START_UTC.isoformat(),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "validation_months": VALIDATION_MONTHS,
        "purge_days": HORIZON_DAYS,
        "tasks": {
            "positive_probability": {
                "target": TARGET_POSITIVE,
                "models": list(classifier_definitions().keys()) + [CLASSIFIER_BASELINE_ID],
                "decision_threshold_reserved_for_diagnostics_only": 0.5,
            },
            "risk_adjusted_return": {
                "target": TARGET_RISK_ADJUSTED,
                "models": list(regressor_definitions().keys()) + [REGRESSOR_BASELINE_ID],
            },
        },
        "policy": (
            "development-only dual-target modeling from frozen Crypto V3 Phase 1 data; "
            "no threshold search, portfolio simulation, BTC V1 signal, hyperparameter tuning, "
            "leverage, shorting, derivatives, live execution, or future-holdout evaluation"
        ),
        "input": {
            "path": str(dataset_path),
            "sha256": before,
            "rows": int(len(df)),
        },
        "outputs": {
            "classifier_predictions": str(classifier_path),
            "regressor_predictions": str(regressor_path),
            "classifier_metrics": str(classifier_metrics_path),
            "regressor_metrics": str(regressor_metrics_path),
            "folds": str(folds_path),
        },
        "next_step": (
            "Review development-only discrimination/calibration for positive-return probability "
            "and predictive quality for risk-adjusted return. Do not combine targets into a "
            "portfolio rule or tune thresholds until these frozen diagnostics are reviewed."
        ),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE2_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase2(args.dataset, args.output_root), indent=2))


if __name__ == "__main__":
    main()
