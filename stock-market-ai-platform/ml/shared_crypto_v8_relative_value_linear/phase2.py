"""Shared Crypto V8 Relative Value Linear Phase 2.

Fits only the preregistered Ridge model family independently to the two exact
72-hour BTC-relative targets:
  * ALT excess return versus BTC after the 25 bps deviation hurdle.
  * CASH excess return versus BTC after the 25 bps deviation hurdle.

Training uses expanding chronological folds with a full 72-hour purge.  This
phase measures predictive quality only and adjudicates the predictive-quality
gates registered in Phase 1.  Portfolio simulation is prohibited unless every
predictive gate passes for both targets.

The future holdout remains untouched.  This phase cannot freeze a model, modify
paper state, promote a candidate automatically, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v8_relative_value_linear"
PHASE1_ROOT = Path("data/model/shared_crypto_v8_relative_value_linear/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v8_relative_value_linear/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
TARGETS = (
    "alt_excess_vs_btc_net25_72h",
    "cash_excess_vs_btc_net25_72h",
)
PRIMARY_MODEL = "ridge_regression"
PURGE = timedelta(hours=72)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6
RIDGE_ALPHA = 10.0


def model_template() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", Ridge(alpha=RIDGE_ALPHA)),
    ])


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
    timestamps = pd.to_datetime(timestamps, utc=True)
    unique = pd.Series(
        timestamps.drop_duplicates()
    ).sort_values().reset_index(drop=True)
    if unique.empty:
        raise RuntimeError("Cannot construct V8 folds from empty timestamps")

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
        end = min(
            start + timedelta(days=VALIDATION_DAYS),
            HOLDOUT,
        )
        train_end = start - PURGE
        train = timestamps < train_end
        validation = (
            (timestamps >= start)
            & (timestamps < end)
        )
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
        raise RuntimeError(
            "No valid purged V8 folds were constructed"
        )
    return folds


def _safe_pearson(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) < 2:
        return 0.0
    if (
        float(np.std(actual)) == 0.0
        or float(np.std(predicted)) == 0.0
    ):
        return 0.0
    return float(
        np.corrcoef(actual, predicted)[0, 1]
    )


def regression_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    baseline_prediction: float,
) -> dict[str, float]:
    actual_values = np.asarray(
        actual,
        dtype=float,
    )
    predicted_values = np.asarray(
        predicted,
        dtype=float,
    )
    baseline = np.full(
        len(actual_values),
        float(baseline_prediction),
        dtype=float,
    )

    mae = float(
        mean_absolute_error(
            actual_values,
            predicted_values,
        )
    )
    rmse = float(np.sqrt(
        mean_squared_error(
            actual_values,
            predicted_values,
        )
    ))
    baseline_mae = float(
        mean_absolute_error(
            actual_values,
            baseline,
        )
    )
    baseline_rmse = float(np.sqrt(
        mean_squared_error(
            actual_values,
            baseline,
        )
    ))

    actual_positive = actual_values > 0.0
    predicted_positive = predicted_values > 0.0
    predicted_positive_count = int(
        predicted_positive.sum()
    )

    return {
        "mae": mae,
        "rmse": rmse,
        "r2": float(
            r2_score(
                actual_values,
                predicted_values,
            )
        ),
        "pearson_correlation": _safe_pearson(
            actual_values,
            predicted_values,
        ),
        "sign_accuracy": float(
            (
                actual_positive
                == predicted_positive
            ).mean()
        ),
        "actual_positive_fraction": float(
            actual_positive.mean()
        ),
        "predicted_positive_fraction": float(
            predicted_positive.mean()
        ),
        "precision_when_predicted_positive": (
            float(
                actual_positive[
                    predicted_positive
                ].mean()
            )
            if predicted_positive_count
            else 0.0
        ),
        "mean_actual_excess_when_predicted_positive": (
            float(
                actual_values[
                    predicted_positive
                ].mean()
            )
            if predicted_positive_count
            else 0.0
        ),
        "mean_predicted_excess": float(
            predicted_values.mean()
        ),
        "mean_actual_excess": float(
            actual_values.mean()
        ),
        "baseline_train_mean_prediction": float(
            baseline_prediction
        ),
        "baseline_mae": baseline_mae,
        "baseline_rmse": baseline_rmse,
        "mae_improvement_vs_train_mean": float(
            baseline_mae - mae
        ),
        "rmse_improvement_vs_train_mean": float(
            baseline_rmse - rmse
        ),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prediction_frames = []
    metric_rows = []
    base_columns = [
        "timestamp_utc",
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        "alt_excess_vs_btc_net25_72h",
        "cash_excess_vs_btc_net25_72h",
        "alt_basket_assets",
        "oracle_best_deviation_net25_72h",
        "oracle_best_excess_vs_btc_net25_72h",
    ]

    for fold in make_folds(
        data["timestamp_utc"]
    ):
        train = data.loc[
            fold["train"]
        ].copy()
        validation = data.loc[
            fold["validation"]
        ].copy()

        if (
            train["timestamp_utc"].max()
            >= fold["train_end"]
        ):
            raise RuntimeError(
                f"{fold['fold_id']} violates the 72-hour purge"
            )
        if (
            validation["timestamp_utc"].max()
            >= HOLDOUT
        ):
            raise RuntimeError(
                f"{fold['fold_id']} reaches the future holdout"
            )

        out = validation[
            base_columns
        ].copy()
        out["fold_id"] = fold["fold_id"]

        for target in TARGETS:
            train_target = pd.to_numeric(
                train[target],
                errors="raise",
            )
            validation_target = pd.to_numeric(
                validation[target],
                errors="raise",
            )
            baseline_prediction = float(
                train_target.mean()
            )

            model = clone(
                model_template()
            ).fit(
                train[features],
                train_target,
            )
            predicted = np.asarray(
                model.predict(
                    validation[features]
                ),
                dtype=float,
            )
            if (
                len(predicted)
                != len(validation)
            ):
                raise RuntimeError(
                    f"{fold['fold_id']} Ridge returned wrong prediction count"
                )
            if not np.isfinite(
                predicted
            ).all():
                raise RuntimeError(
                    f"{fold['fold_id']} Ridge returned non-finite predictions"
                )

            out[
                f"predicted_{target}_{PRIMARY_MODEL}"
            ] = predicted

            metric_rows.append({
                "fold_id": fold["fold_id"],
                "target": target,
                "model_id": PRIMARY_MODEL,
                "train_rows": int(len(train)),
                "validation_rows": int(
                    len(validation)
                ),
                "train_end_exclusive_utc": (
                    fold["train_end"].isoformat()
                ),
                "validation_start_utc": (
                    fold["start"].isoformat()
                ),
                "validation_end_utc": (
                    fold["end"].isoformat()
                ),
                **regression_metrics(
                    validation_target,
                    predicted,
                    baseline_prediction,
                ),
            })

        prediction_frames.append(out)
        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            "purge=72h targets=2 ridge-only"
        )

    return (
        pd.concat(
            prediction_frames,
            ignore_index=True,
        ),
        pd.DataFrame(metric_rows),
    )


def summarize(
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    identity = {
        "fold_id",
        "target",
        "model_id",
        "train_end_exclusive_utc",
        "validation_start_utc",
        "validation_end_utc",
    }
    numeric = [
        column
        for column in metrics.columns
        if column not in identity
    ]

    rows = []
    for target, group in metrics.groupby(
        "target",
        sort=True,
    ):
        row = {
            "target": target,
            "model_id": PRIMARY_MODEL,
            "fold_count": int(
                group["fold_id"].nunique()
            ),
        }
        for column in numeric:
            values = pd.to_numeric(
                group[column],
                errors="coerce",
            )
            row[
                f"mean_{column}"
            ] = float(values.mean())
            row[
                f"median_{column}"
            ] = float(values.median())
        rows.append(row)

    return pd.DataFrame(rows)


def evaluate_predictive_gates(
    summary: pd.DataFrame,
    contract: dict,
) -> tuple[pd.DataFrame, dict]:
    registered = contract[
        "predictive_quality_gates"
    ]
    pearson_hurdle = float(
        registered[
            "median_pearson_correlation_each_target_gt"
        ]
    )
    mae_hurdle = float(
        registered[
            "median_mae_improvement_vs_train_mean_each_target_gt"
        ]
    )
    sign_hurdle = float(
        registered[
            "median_sign_accuracy_each_target_gt"
        ]
    )

    rows = []
    for target in TARGETS:
        match = summary[
            summary["target"] == target
        ]
        if len(match) != 1:
            raise RuntimeError(
                f"Missing unique V8 predictive summary for {target}"
            )
        row = match.iloc[0]

        pearson_pass = bool(
            row[
                "median_pearson_correlation"
            ] > pearson_hurdle
        )
        mae_pass = bool(
            row[
                "median_mae_improvement_vs_train_mean"
            ] > mae_hurdle
        )
        sign_pass = bool(
            row[
                "median_sign_accuracy"
            ] > sign_hurdle
        )

        rows.append({
            "target": target,
            "gate_median_pearson_correlation_gt_zero": pearson_pass,
            "gate_median_mae_improvement_vs_train_mean_gt_zero": mae_pass,
            "gate_median_sign_accuracy_gt_50pct": sign_pass,
            "passed_gate_count": int(
                pearson_pass
                + mae_pass
                + sign_pass
            ),
            "total_gate_count": 3,
            "median_pearson_correlation": float(
                row[
                    "median_pearson_correlation"
                ]
            ),
            "median_mae_improvement_vs_train_mean": float(
                row[
                    "median_mae_improvement_vs_train_mean"
                ]
            ),
            "median_sign_accuracy": float(
                row[
                    "median_sign_accuracy"
                ]
            ),
        })

    detail = pd.DataFrame(rows)
    passed = bool(
        (
            detail["passed_gate_count"]
            == detail["total_gate_count"]
        ).all()
    )

    result = {
        "target_count": int(len(detail)),
        "passed_target_count": int(
            (
                detail["passed_gate_count"]
                == detail["total_gate_count"]
            ).sum()
        ),
        "total_predictive_gate_count": int(
            detail["total_gate_count"].sum()
        ),
        "passed_predictive_gate_count": int(
            detail["passed_gate_count"].sum()
        ),
        "all_predictive_gates_pass": passed,
        "status": (
            "ALLOW_POLICY_SIMULATION"
            if passed
            else "STOP_BEFORE_PORTFOLIO_SIMULATION"
        ),
    }
    return detail, result


def run(
    phase1_root: Path = PHASE1_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root = Path(phase1_root)
    output_root = Path(output_root)

    contract = json.loads(
        (
            phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    if (
        contract.get("research_version")
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V8 Phase 1 research version"
        )
    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V8 Phase 1 holdout boundary differs from Phase 2"
        )

    registered_models = contract[
        "model_candidates"
    ]
    if (
        registered_models.get("primary")
        != PRIMARY_MODEL
    ):
        raise RuntimeError(
            "V8 Phase 1 primary model differs from Phase 2"
        )
    if (
        float(
            registered_models.get(
                "primary_regularization_alpha"
            )
        )
        != RIDGE_ALPHA
    ):
        raise RuntimeError(
            "V8 Phase 1 Ridge alpha differs from Phase 2"
        )
    if (
        registered_models.get(
            "secondary_models"
        )
        != []
    ):
        raise RuntimeError(
            "V8 Phase 2 forbids secondary model search"
        )
    if tuple(
        registered_models.get(
            "targets",
            [],
        )
    ) != TARGETS:
        raise RuntimeError(
            "V8 Phase 1 targets differ from Phase 2"
        )

    data = _read(
        (
            phase1_root
            / "daily_regime_dataset.parquet"
        ),
        "V8 daily regime dataset",
    )
    features = list(
        contract[
            "regime_feature_columns"
        ]
    )

    missing = (
        set(features)
        | set(TARGETS)
    ) - set(data.columns)
    if missing:
        raise RuntimeError(
            f"V8 Phase 1 dataset missing columns: {sorted(missing)}"
        )

    forbidden = (
        set(TARGETS)
        & set(features)
    )
    if forbidden:
        raise RuntimeError(
            f"V8 targets leaked into model features: {sorted(forbidden)}"
        )

    predictions, metrics = walk_forward(
        data,
        features,
    )
    summary = summarize(metrics)
    gate_detail, gate_result = evaluate_predictive_gates(
        summary,
        contract,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    prediction_path = (
        output_root
        / "daily_predictions.parquet"
    )
    metrics_path = (
        output_root
        / "fold_metrics.csv"
    )
    summary_path = (
        output_root
        / "metrics_summary.csv"
    )
    gate_detail_path = (
        output_root
        / "predictive_gate_detail.csv"
    )
    gate_result_path = (
        output_root
        / "predictive_gate_result.json"
    )

    predictions.to_parquet(
        prediction_path,
        index=False,
    )
    metrics.to_csv(
        metrics_path,
        index=False,
    )
    summary.to_csv(
        summary_path,
        index=False,
    )
    gate_detail.to_csv(
        gate_detail_path,
        index=False,
    )
    gate_result_path.write_text(
        json.dumps(
            gate_result,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": (
            "purged_72h_btc_relative_ridge_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "targets": list(TARGETS),
        "purge_hours": int(
            PURGE.total_seconds()
            // 3600
        ),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "primary_model": PRIMARY_MODEL,
        "ridge_alpha": RIDGE_ALPHA,
        "secondary_model_count": 0,
        "input_rows": int(len(data)),
        "prediction_rows": int(
            len(predictions)
        ),
        "fold_count": int(
            predictions[
                "fold_id"
            ].nunique()
        ),
        "predictive_gate_status": (
            gate_result["status"]
        ),
        "passed_predictive_gate_count": (
            gate_result[
                "passed_predictive_gate_count"
            ]
        ),
        "total_predictive_gate_count": (
            gate_result[
                "total_predictive_gate_count"
            ]
        ),
        "outputs": {
            "daily_predictions": str(
                prediction_path
            ),
            "fold_metrics": str(
                metrics_path
            ),
            "metrics_summary": str(
                summary_path
            ),
            "predictive_gate_detail": str(
                gate_detail_path
            ),
            "predictive_gate_result": str(
                gate_result_path
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "safety": {
            "shared_crypto_v7_modified": False,
            "shared_crypto_v6_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the single frozen non-overlapping 72-hour portfolio policy "
            "only if predictive_gate_status is ALLOW_POLICY_SIMULATION.  "
            "Otherwise preserve V8 as failed predictive evidence and do not "
            "simulate its portfolio policy."
        ),
    }

    (
        output_root
        / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument(
        "--phase1-root",
        type=Path,
        default=PHASE1_ROOT,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )
    args = parser.parse_args(argv)
    print(json.dumps(
        run(
            args.phase1_root,
            args.output_root,
        ),
        indent=2,
    ))


if __name__ == "__main__":
    main()
