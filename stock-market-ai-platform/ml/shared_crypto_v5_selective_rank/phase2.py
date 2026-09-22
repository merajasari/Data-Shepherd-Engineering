"""Shared Crypto V5 Selective Rank Phase 2: purged walk-forward models.

Fits the preregistered market-risk classifier, ALT excess-return regressor, and
ALT downside classifier on expanding chronological folds.  A separate trailing
calibration window produces one-sided conformal lower bounds for predicted ALT
excess return.  The untouched future holdout is rejected on input.

This phase measures signal quality only.  It does not simulate a portfolio,
select a paper candidate, modify an existing model, or place orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v5_selective_rank"
PHASE1_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
PURGE = timedelta(hours=1)
MIN_TRAIN_DAYS = 730
CALIBRATION_DAYS = 90
VALIDATION_DAYS = 90
MAX_FOLDS = 6
CONFORMAL_COVERAGE = 0.90
RANDOM_STATE = 1729


def risk_models() -> dict[str, Pipeline]:
    return {
        "hist_gradient_boosting_classifier": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=120,
                max_leaf_nodes=15,
                min_samples_leaf=50,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        "logistic_regression_diagnostic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=0.25,
                max_iter=3000,
                solver="lbfgs",
                random_state=RANDOM_STATE,
            )),
        ]),
    }


def excess_models() -> dict[str, Pipeline]:
    return {
        "hist_gradient_boosting_regressor": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_iter=120,
                max_leaf_nodes=15,
                min_samples_leaf=200,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        "ridge_diagnostic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
    }


def downside_models() -> dict[str, Pipeline]:
    return {
        "hist_gradient_boosting_classifier": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=120,
                max_leaf_nodes=15,
                min_samples_leaf=200,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        "logistic_regression_diagnostic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                C=0.25,
                max_iter=3000,
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
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, source)
    return frame.sort_values("timestamp_utc").reset_index(drop=True)


def make_folds(timestamps: pd.Series) -> list[dict]:
    unique = pd.Series(pd.to_datetime(timestamps, utc=True).drop_duplicates()).sort_values()
    if unique.empty:
        raise RuntimeError("Cannot construct folds from empty timestamps")
    first = unique.iloc[0].floor("D")
    last = unique.iloc[-1]
    starts = list(pd.date_range(
        first + timedelta(days=MIN_TRAIN_DAYS + CALIBRATION_DAYS),
        last,
        freq=f"{VALIDATION_DAYS}D",
    ))[-MAX_FOLDS:]
    folds = []
    for start in starts:
        end = min(start + timedelta(days=VALIDATION_DAYS), HOLDOUT)
        train_end = start - PURGE
        calibration_start = train_end - timedelta(days=CALIBRATION_DAYS)
        fit_end = calibration_start - PURGE
        fit = timestamps < fit_end
        calibration = (timestamps >= calibration_start) & (timestamps < train_end)
        validation = (timestamps >= start) & (timestamps < end)
        if fit.any() and calibration.any() and validation.any():
            folds.append({
                "fold_id": f"fold_{len(folds) + 1:02d}",
                "start": start,
                "end": end,
                "fit_end": fit_end,
                "calibration_start": calibration_start,
                "train_end": train_end,
                "fit": fit,
                "calibration": calibration,
                "validation": validation,
            })
    if not folds:
        raise RuntimeError("No valid purged V5 folds were constructed")
    return folds


def one_sided_conformal_adjustment(actual, predicted, coverage=CONFORMAL_COVERAGE) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) == 0 or len(actual) != len(predicted):
        raise RuntimeError("Invalid conformal calibration arrays")
    nonconformity = predicted - actual
    try:
        quantile = np.quantile(nonconformity, coverage, method="higher")
    except TypeError:  # NumPy compatibility.
        quantile = np.quantile(nonconformity, coverage, interpolation="higher")
    return float(max(0.0, quantile))


def _safe_auc(actual, probability) -> float:
    actual = np.asarray(actual)
    if len(np.unique(actual)) < 2:
        return np.nan
    return float(roc_auc_score(actual, probability))


def _safe_average_precision(actual, probability) -> float:
    actual = np.asarray(actual)
    if len(np.unique(actual)) < 2:
        return np.nan
    return float(average_precision_score(actual, probability))


def _risk_walk_forward(data: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = []
    metrics = []
    for fold in make_folds(data["timestamp_utc"]):
        fit = data.loc[fold["fit"]]
        validation = data.loc[fold["validation"]]
        if fit["timestamp_utc"].max() >= fold["fit_end"]:
            raise RuntimeError(f"{fold['fold_id']} risk fit violates purge")
        actual = validation["btc_positive_1h"].to_numpy(int)
        out = validation[[
            "timestamp_utc", "btc_forward_return_1h", "alt_forward_return_1h",
            "btc_positive_1h",
        ]].copy()
        out["fold_id"] = fold["fold_id"]
        for model_id, template in risk_models().items():
            model = clone(template).fit(fit[features], fit["btc_positive_1h"])
            probability = model.predict_proba(validation[features])[:, 1]
            predicted = (probability >= 0.50).astype(int)
            out[f"probability_{model_id}"] = probability
            metrics.append({
                "task": "market_risk", "fold_id": fold["fold_id"],
                "model_id": model_id,
                "fit_rows": int(len(fit)), "validation_rows": int(len(validation)),
                "validation_start_utc": fold["start"].isoformat(),
                "validation_end_utc": fold["end"].isoformat(),
                "accuracy": float(accuracy_score(actual, predicted)),
                "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
                "brier_score": float(brier_score_loss(actual, probability)),
                "log_loss": float(log_loss(actual, np.column_stack([1-probability, probability]), labels=[0, 1])),
                "roc_auc": _safe_auc(actual, probability),
                "positive_prediction_fraction": float(predicted.mean()),
            })
        predictions.append(out)
        print(f"[SUCCESS] market-risk {fold['fold_id']} fit={len(fit):,} validation={len(validation):,}")
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(metrics)


def _rank_ic(group: pd.DataFrame, prediction_column: str) -> float:
    if (len(group) < 2
            or group[prediction_column].nunique(dropna=True) < 2
            or group["alt_excess_vs_btc_1h"].nunique(dropna=True) < 2):
        return np.nan
    return float(group[prediction_column].corr(
        group["alt_excess_vs_btc_1h"], method="spearman"
    ))


def _selection_walk_forward(data: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = []
    metrics = []
    for fold in make_folds(data["timestamp_utc"]):
        fit = data.loc[fold["fit"]]
        calibration = data.loc[fold["calibration"]]
        validation = data.loc[fold["validation"]]
        if fit["timestamp_utc"].max() >= fold["fit_end"]:
            raise RuntimeError(f"{fold['fold_id']} selection fit violates purge")
        out = validation[[
            "timestamp_utc", "product_id", "forward_return_1h",
            "btc_forward_return_1h", "alt_excess_vs_btc_1h", "alt_loss_1pct_1h",
        ]].copy()
        out["fold_id"] = fold["fold_id"]

        for model_id, template in excess_models().items():
            model = clone(template).fit(fit[features], fit["alt_excess_vs_btc_1h"])
            calibration_prediction = model.predict(calibration[features])
            adjustment = one_sided_conformal_adjustment(
                calibration["alt_excess_vs_btc_1h"], calibration_prediction
            )
            prediction = model.predict(validation[features])
            column = f"predicted_excess_{model_id}"
            out[column] = prediction
            out[f"lower_bound_{model_id}"] = prediction - adjustment
            rank_ic = out.groupby("timestamp_utc", sort=True).apply(
                lambda group: _rank_ic(group, column), include_groups=False
            )
            ordered = out.sort_values(["timestamp_utc", column], ascending=[True, False])
            top5 = ordered.groupby("timestamp_utc", sort=False).head(5)
            top5_excess = top5.groupby("timestamp_utc")["alt_excess_vs_btc_1h"].mean()
            metrics.append({
                "task": "alt_excess", "fold_id": fold["fold_id"],
                "model_id": model_id,
                "fit_rows": int(len(fit)), "calibration_rows": int(len(calibration)),
                "validation_rows": int(len(validation)),
                "validation_start_utc": fold["start"].isoformat(),
                "validation_end_utc": fold["end"].isoformat(),
                "mae": float(np.mean(np.abs(
                    prediction - validation["alt_excess_vs_btc_1h"].to_numpy(float)
                ))),
                "correlation": float(pd.Series(prediction).corr(
                    pd.Series(validation["alt_excess_vs_btc_1h"].to_numpy(float))
                )),
                "mean_rank_ic": float(rank_ic.mean()),
                "positive_rank_ic_fraction": float((rank_ic > 0).mean()),
                "top5_mean_excess_vs_btc": float(top5_excess.mean()),
                "conformal_adjustment": adjustment,
            })

        actual_downside = validation["alt_loss_1pct_1h"].to_numpy(int)
        for model_id, template in downside_models().items():
            model = clone(template).fit(fit[features], fit["alt_loss_1pct_1h"])
            probability = model.predict_proba(validation[features])[:, 1]
            out[f"downside_probability_{model_id}"] = probability
            metrics.append({
                "task": "alt_downside", "fold_id": fold["fold_id"],
                "model_id": model_id,
                "fit_rows": int(len(fit)), "calibration_rows": int(len(calibration)),
                "validation_rows": int(len(validation)),
                "validation_start_utc": fold["start"].isoformat(),
                "validation_end_utc": fold["end"].isoformat(),
                "event_rate": float(actual_downside.mean()),
                "brier_score": float(brier_score_loss(actual_downside, probability)),
                "roc_auc": _safe_auc(actual_downside, probability),
                "average_precision": _safe_average_precision(actual_downside, probability),
            })
        predictions.append(out)
        print(
            f"[SUCCESS] selection {fold['fold_id']} fit={len(fit):,} "
            f"calibration={len(calibration):,} validation={len(validation):,}"
        )
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(metrics)


def _summary(metrics: pd.DataFrame) -> pd.DataFrame:
    identity = {
        "task", "fold_id", "model_id", "validation_start_utc", "validation_end_utc"
    }
    numeric = [column for column in metrics.columns if column not in identity]
    rows = []
    for keys, group in metrics.groupby(["task", "model_id"], sort=True):
        row = {
            "task": keys[0], "model_id": keys[1],
            "fold_count": int(group["fold_id"].nunique()),
        }
        for column in numeric:
            row[f"mean_{column}"] = float(pd.to_numeric(
                group[column], errors="coerce"
            ).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def run(phase1_root: Path = PHASE1_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    phase1_root = Path(phase1_root)
    output_root = Path(output_root)
    contract = json.loads(
        (phase1_root / "preregistered_contract.json").read_text(encoding="utf-8")
    )
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V5 Phase 1 holdout boundary differs from Phase 2")
    risk = _read(phase1_root / "market_risk_dataset.parquet", "market-risk dataset")
    selection = _read(phase1_root / "alt_selection_dataset.parquet", "ALT-selection dataset")
    risk_predictions, risk_metrics = _risk_walk_forward(
        risk, list(contract["risk_feature_columns"])
    )
    selection_predictions, selection_metrics = _selection_walk_forward(
        selection, list(contract["selection_feature_columns"])
    )
    metrics = pd.concat([risk_metrics, selection_metrics], ignore_index=True, sort=False)
    summary = _summary(metrics)

    output_root.mkdir(parents=True, exist_ok=True)
    risk_predictions.to_parquet(output_root / "market_risk_predictions.parquet", index=False)
    selection_predictions.to_parquet(output_root / "alt_selection_predictions.parquet", index=False)
    metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "purged_walk_forward_selective_rank_models",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "purge_hours": int(PURGE.total_seconds() // 3600),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "calibration_days": CALIBRATION_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "conformal_coverage": CONFORMAL_COVERAGE,
        "market_risk_rows": int(len(risk)),
        "alt_selection_rows": int(len(selection)),
        "outputs": {
            "market_risk_predictions": str(output_root / "market_risk_predictions.parquet"),
            "alt_selection_predictions": str(output_root / "alt_selection_predictions.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "metrics_summary": str(output_root / "metrics_summary.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "shared_crypto_v3_modified": False,
            "rejected_v4_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": "Review fold stability before running the single preregistered V5 portfolio policy.",
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
