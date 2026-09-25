"""Shared Crypto V12 BTC Specialist Phase 2.

Fits only the preregistered V12 hierarchy:

* Stage 1 BTC-vs-DEVIATE: fixed HistGradientBoostingClassifier with balanced
  training weights.
* Stage 2 ALT-vs-CASH: unchanged V11 balanced LinearSVC(C=0.25).

Training uses expanding chronological folds with a full 72-hour purge.
Stage-specific and combined BTC/ALT/CASH predictive gates are adjudicated
before any portfolio simulation. The September 1, 2026 future holdout remains
untouched.

This phase cannot search model families, tune hyperparameters or confidence
thresholds, calibrate probabilities, freeze a model, modify paper state, or
place brokerage orders.
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
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    matthews_corrcoef,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.utils.class_weight import compute_sample_weight


RESEARCH_VERSION = "shared_crypto_v12_btc_specialist"
PHASE1_ROOT = Path(
    "data/model/shared_crypto_v12_btc_specialist/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v12_btc_specialist/phase2"
)
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

SOURCE_TARGET = "best_sleeve_net25_72h"
STAGE1_TARGET = "btc_vs_deviate_72h"
STAGE2_TARGET = "alt_vs_cash_when_deviate_72h"

STAGE1_MODEL = "hist_gradient_boosting_classifier"
STAGE1_LEARNING_RATE = 0.05
STAGE1_MAX_ITER = 200
STAGE1_MAX_LEAF_NODES = 15
STAGE1_MIN_SAMPLES_LEAF = 30
STAGE1_L2_REGULARIZATION = 1.0
STAGE1_CLASS_WEIGHT = "balanced"

STAGE2_MODEL = "linear_svc"
STAGE2_C = 0.25
STAGE2_CLASS_WEIGHT = "balanced"

PURGE = timedelta(hours=72)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6

STAGE1_CLASSES = ("BTC", "DEVIATE")
STAGE2_CLASSES = ("ALT", "CASH")
COMBINED_CLASSES = ("BTC", "ALT", "CASH")


def stage1_model_template() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=STAGE1_LEARNING_RATE,
        max_iter=STAGE1_MAX_ITER,
        max_leaf_nodes=STAGE1_MAX_LEAF_NODES,
        max_depth=None,
        min_samples_leaf=STAGE1_MIN_SAMPLES_LEAF,
        l2_regularization=STAGE1_L2_REGULARIZATION,
        random_state=1729,
    )


def stage2_model_template() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", LinearSVC(
            C=STAGE2_C,
            loss="squared_hinge",
            penalty="l2",
            class_weight=STAGE2_CLASS_WEIGHT,
            dual="auto",
            max_iter=10000,
            random_state=1729,
        )),
    ])


def validate_pre_holdout(
    frame: pd.DataFrame,
    source: str,
) -> None:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def _read(
    path: Path,
    source: str,
) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(path)

    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    validate_pre_holdout(
        frame,
        source,
    )

    return frame.sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)


def make_folds(
    timestamps: pd.Series,
) -> list[dict]:
    timestamps = pd.to_datetime(
        timestamps,
        utc=True,
    )
    unique = pd.Series(
        timestamps.drop_duplicates()
    ).sort_values().reset_index(drop=True)

    if unique.empty:
        raise RuntimeError(
            "Cannot construct V12 folds from empty timestamps"
        )

    first = unique.iloc[0].floor("D")
    last = unique.iloc[-1]
    starts = []

    cursor = first + timedelta(
        days=MIN_TRAIN_DAYS
    )
    while cursor <= last:
        starts.append(cursor)
        cursor += timedelta(
            days=VALIDATION_DAYS
        )

    starts = starts[-MAX_FOLDS:]
    folds = []

    for start in starts:
        end = min(
            start + timedelta(
                days=VALIDATION_DAYS
            ),
            HOLDOUT,
        )
        train_end = start - PURGE

        train = (
            timestamps
            < train_end
        )
        validation = (
            (timestamps >= start)
            & (timestamps < end)
        )

        if train.any() and validation.any():
            folds.append({
                "fold_id": (
                    f"fold_{len(folds) + 1:02d}"
                ),
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })

    if not folds:
        raise RuntimeError(
            "No valid purged V12 folds were constructed"
        )

    return folds


def binary_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    classes: tuple[str, str],
) -> dict[str, float]:
    actual_values = np.asarray(
        actual,
        dtype=object,
    )
    predicted_values = np.asarray(
        predicted,
        dtype=object,
    )

    unexpected_actual = (
        set(np.unique(actual_values))
        - set(classes)
    )
    unexpected_predicted = (
        set(np.unique(predicted_values))
        - set(classes)
    )
    if unexpected_actual:
        raise RuntimeError(
            f"Unexpected V12 binary actual class: {sorted(unexpected_actual)}"
        )
    if unexpected_predicted:
        raise RuntimeError(
            f"Unexpected V12 binary predicted class: {sorted(unexpected_predicted)}"
        )

    return {
        "balanced_accuracy": float(
            balanced_accuracy_score(
                actual_values,
                predicted_values,
            )
        ),
        "mcc": float(
            matthews_corrcoef(
                actual_values,
                predicted_values,
            )
        ),
        "accuracy": float(
            accuracy_score(
                actual_values,
                predicted_values,
            )
        ),
    }


def combined_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    train_actual: pd.Series,
) -> dict[str, float | str]:
    actual_values = np.asarray(
        actual,
        dtype=object,
    )
    predicted_values = np.asarray(
        predicted,
        dtype=object,
    )
    train_values = np.asarray(
        train_actual,
        dtype=object,
    )

    if (
        set(np.unique(actual_values))
        - set(COMBINED_CLASSES)
    ):
        raise RuntimeError(
            "Unexpected V12 combined actual class"
        )
    if (
        set(np.unique(predicted_values))
        - set(COMBINED_CLASSES)
    ):
        raise RuntimeError(
            "Unexpected V12 combined predicted class"
        )

    train_counts = (
        pd.Series(train_values)
        .value_counts()
    )
    train_majority = str(
        train_counts.index[0]
    )
    baseline_prediction = np.full(
        len(actual_values),
        train_majority,
        dtype=object,
    )

    recalls = recall_score(
        actual_values,
        predicted_values,
        labels=list(
            COMBINED_CLASSES
        ),
        average=None,
        zero_division=0,
    )

    accuracy = float(
        accuracy_score(
            actual_values,
            predicted_values,
        )
    )
    baseline_accuracy = float(
        accuracy_score(
            actual_values,
            baseline_prediction,
        )
    )

    return {
        "accuracy": accuracy,
        "balanced_accuracy": float(
            balanced_accuracy_score(
                actual_values,
                predicted_values,
            )
        ),
        "macro_f1": float(
            f1_score(
                actual_values,
                predicted_values,
                labels=list(
                    COMBINED_CLASSES
                ),
                average="macro",
                zero_division=0,
            )
        ),
        "multiclass_mcc": float(
            matthews_corrcoef(
                actual_values,
                predicted_values,
            )
        ),
        "minimum_class_recall": float(
            np.min(recalls)
        ),
        "btc_recall": float(
            recalls[0]
        ),
        "alt_recall": float(
            recalls[1]
        ),
        "cash_recall": float(
            recalls[2]
        ),
        "baseline_train_majority_class": (
            train_majority
        ),
        "baseline_train_majority_accuracy": (
            baseline_accuracy
        ),
        "accuracy_improvement_vs_train_majority": float(
            accuracy
            - baseline_accuracy
        ),
        "actual_btc_fraction": float(
            (
                actual_values
                == "BTC"
            ).mean()
        ),
        "actual_alt_fraction": float(
            (
                actual_values
                == "ALT"
            ).mean()
        ),
        "actual_cash_fraction": float(
            (
                actual_values
                == "CASH"
            ).mean()
        ),
        "predicted_btc_fraction": float(
            (
                predicted_values
                == "BTC"
            ).mean()
        ),
        "predicted_alt_fraction": float(
            (
                predicted_values
                == "ALT"
            ).mean()
        ),
        "predicted_cash_fraction": float(
            (
                predicted_values
                == "CASH"
            ).mean()
        ),
    }


def _binary_margin(
    fitted_pipeline: Pipeline,
    features: pd.DataFrame,
    positive_class: str,
) -> np.ndarray:
    model = fitted_pipeline.named_steps[
        "model"
    ]
    classes = list(
        model.classes_
    )

    if positive_class not in classes:
        raise RuntimeError(
            f"V12 Stage 2 model missing class {positive_class}"
        )

    raw = np.asarray(
        fitted_pipeline.decision_function(
            features
        ),
        dtype=float,
    )

    if raw.ndim != 1:
        raise RuntimeError(
            "V12 expected one-dimensional Stage 2 decision margins"
        )

    if classes[1] == positive_class:
        return raw
    if classes[0] == positive_class:
        return -raw

    raise RuntimeError(
        f"V12 cannot orient Stage 2 margin for {positive_class}"
    )


def _class_probability(
    fitted_model: HistGradientBoostingClassifier,
    features: pd.DataFrame,
    class_name: str,
) -> np.ndarray:
    classes = list(
        fitted_model.classes_
    )
    if class_name not in classes:
        raise RuntimeError(
            f"V12 Stage 1 model missing class {class_name}"
        )

    probabilities = np.asarray(
        fitted_model.predict_proba(
            features
        ),
        dtype=float,
    )
    if probabilities.shape != (
        len(features),
        len(classes),
    ):
        raise RuntimeError(
            "V12 Stage 1 returned unexpected probability shape"
        )

    result = probabilities[
        :,
        classes.index(
            class_name
        ),
    ]
    if (
        (result < 0.0).any()
        or (result > 1.0).any()
        or not np.isfinite(
            result
        ).all()
    ):
        raise RuntimeError(
            "V12 Stage 1 returned invalid probabilities"
        )

    return result


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prediction_frames = []
    metric_rows = []

    base_columns = [
        "timestamp_utc",
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
        "alt_basket_assets",
    ]

    for optional in (
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        "alt_excess_vs_btc_net25_72h",
        "cash_excess_vs_btc_net25_72h",
        "oracle_best_deviation_net25_72h",
    ):
        if optional in data.columns:
            base_columns.append(
                optional
            )

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
            train[
                "timestamp_utc"
            ].max()
            >= fold["train_end"]
        ):
            raise RuntimeError(
                f"{fold['fold_id']} violates the 72-hour purge"
            )
        if (
            validation[
                "timestamp_utc"
            ].max()
            >= HOLDOUT
        ):
            raise RuntimeError(
                f"{fold['fold_id']} reaches the future holdout"
            )

        stage1_train_target = train[
            STAGE1_TARGET
        ].astype(str)
        stage1_validation_target = validation[
            STAGE1_TARGET
        ].astype(str)

        if set(
            stage1_train_target.unique()
        ) != set(
            STAGE1_CLASSES
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 1 training lacks both classes"
            )

        stage1_model = clone(
            stage1_model_template()
        )
        stage1_weights = (
            compute_sample_weight(
                class_weight="balanced",
                y=stage1_train_target,
            )
        )
        stage1_model.fit(
            train[features],
            stage1_train_target,
            sample_weight=stage1_weights,
        )

        stage1_predicted = np.asarray(
            stage1_model.predict(
                validation[features]
            ),
            dtype=object,
        )
        stage1_probability_deviate = (
            _class_probability(
                stage1_model,
                validation[features],
                "DEVIATE",
            )
        )

        stage2_train = train[
            train[
                STAGE2_TARGET
            ].notna()
        ].copy()
        stage2_validation = validation[
            validation[
                STAGE2_TARGET
            ].notna()
        ].copy()

        stage2_train_target = stage2_train[
            STAGE2_TARGET
        ].astype(str)
        stage2_validation_target = stage2_validation[
            STAGE2_TARGET
        ].astype(str)

        if set(
            stage2_train_target.unique()
        ) != set(
            STAGE2_CLASSES
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 training lacks both classes"
            )
        if stage2_validation.empty:
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 validation is empty"
            )
        if set(
            stage2_validation_target.unique()
        ) != set(
            STAGE2_CLASSES
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 validation lacks both classes"
            )

        stage2_model = clone(
            stage2_model_template()
        ).fit(
            stage2_train[features],
            stage2_train_target,
        )

        stage2_predicted_all = np.asarray(
            stage2_model.predict(
                validation[features]
            ),
            dtype=object,
        )
        stage2_margin_cash_all = (
            _binary_margin(
                stage2_model,
                validation[features],
                "CASH",
            )
        )

        stage2_predicted_intrinsic = np.asarray(
            stage2_model.predict(
                stage2_validation[
                    features
                ]
            ),
            dtype=object,
        )

        combined_predicted = np.where(
            stage1_predicted
            == "BTC",
            "BTC",
            stage2_predicted_all,
        ).astype(
            object
        )

        stage1_stats = binary_metrics(
            stage1_validation_target,
            stage1_predicted,
            STAGE1_CLASSES,
        )
        stage2_stats = binary_metrics(
            stage2_validation_target,
            stage2_predicted_intrinsic,
            STAGE2_CLASSES,
        )
        combined_stats = combined_metrics(
            validation[
                SOURCE_TARGET
            ].astype(str),
            combined_predicted,
            train[
                SOURCE_TARGET
            ].astype(str),
        )

        out = validation[
            base_columns
        ].copy()
        out["fold_id"] = (
            fold["fold_id"]
        )
        out[
            "stage1_predicted"
        ] = stage1_predicted
        out[
            "stage1_probability_deviate"
        ] = (
            stage1_probability_deviate
        )
        out[
            "stage2_predicted"
        ] = stage2_predicted_all
        out[
            "stage2_margin_cash"
        ] = stage2_margin_cash_all
        out[
            "predicted_sleeve"
        ] = combined_predicted

        metric_rows.append({
            "fold_id": (
                fold["fold_id"]
            ),
            "train_rows": int(
                len(train)
            ),
            "validation_rows": int(
                len(validation)
            ),
            "stage2_train_rows": int(
                len(stage2_train)
            ),
            "stage2_validation_rows": int(
                len(stage2_validation)
            ),
            "train_end_exclusive_utc": (
                fold[
                    "train_end"
                ].isoformat()
            ),
            "validation_start_utc": (
                fold[
                    "start"
                ].isoformat()
            ),
            "validation_end_utc": (
                fold[
                    "end"
                ].isoformat()
            ),
            "stage1_balanced_accuracy": (
                stage1_stats[
                    "balanced_accuracy"
                ]
            ),
            "stage1_mcc": (
                stage1_stats[
                    "mcc"
                ]
            ),
            "stage1_accuracy": (
                stage1_stats[
                    "accuracy"
                ]
            ),
            "stage2_balanced_accuracy": (
                stage2_stats[
                    "balanced_accuracy"
                ]
            ),
            "stage2_mcc": (
                stage2_stats[
                    "mcc"
                ]
            ),
            "stage2_accuracy": (
                stage2_stats[
                    "accuracy"
                ]
            ),
            **{
                f"combined_{key}": value
                for key, value
                in combined_stats.items()
            },
        })

        prediction_frames.append(
            out
        )

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            f"stage2_train={len(stage2_train):,} "
            f"stage2_validation={len(stage2_validation):,} "
            "purge=72h "
            "stage1=hist-gradient-boosting "
            "stage2=balanced-linear-svc"
        )

    return (
        pd.concat(
            prediction_frames,
            ignore_index=True,
        ),
        pd.DataFrame(
            metric_rows
        ),
    )


def summarize(
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    identity = {
        "fold_id",
        "train_end_exclusive_utc",
        "validation_start_utc",
        "validation_end_utc",
        "combined_baseline_train_majority_class",
    }

    numeric = [
        column
        for column in metrics.columns
        if column not in identity
    ]

    row = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "fold_count": int(
            metrics[
                "fold_id"
            ].nunique()
        ),
    }

    for column in numeric:
        values = pd.to_numeric(
            metrics[column],
            errors="coerce",
        )
        row[
            f"mean_{column}"
        ] = float(
            values.mean()
        )
        row[
            f"median_{column}"
        ] = float(
            values.median()
        )

    return pd.DataFrame([
        row
    ])


def evaluate_predictive_gates(
    summary: pd.DataFrame,
    contract: dict,
) -> tuple[pd.DataFrame, dict]:
    if len(summary) != 1:
        raise RuntimeError(
            "V12 predictive summary must contain exactly one row"
        )

    row = summary.iloc[0]
    gates = contract[
        "predictive_quality_gates"
    ]

    checks = [
        (
            "gate_stage1_median_balanced_accuracy_gt_52pct",
            float(
                row[
                    "median_stage1_balanced_accuracy"
                ]
            )
            > float(
                gates[
                    "stage1_median_balanced_accuracy_gt"
                ]
            ),
        ),
        (
            "gate_stage1_median_mcc_gt_zero",
            float(
                row[
                    "median_stage1_mcc"
                ]
            )
            > float(
                gates[
                    "stage1_median_mcc_gt"
                ]
            ),
        ),
        (
            "gate_stage2_median_balanced_accuracy_gt_52pct",
            float(
                row[
                    "median_stage2_balanced_accuracy"
                ]
            )
            > float(
                gates[
                    "stage2_median_balanced_accuracy_gt"
                ]
            ),
        ),
        (
            "gate_stage2_median_mcc_gt_zero",
            float(
                row[
                    "median_stage2_mcc"
                ]
            )
            > float(
                gates[
                    "stage2_median_mcc_gt"
                ]
            ),
        ),
        (
            "gate_combined_median_balanced_accuracy_gt_36pct",
            float(
                row[
                    "median_combined_balanced_accuracy"
                ]
            )
            > float(
                gates[
                    "combined_median_balanced_accuracy_gt"
                ]
            ),
        ),
        (
            "gate_combined_median_macro_f1_gt_36pct",
            float(
                row[
                    "median_combined_macro_f1"
                ]
            )
            > float(
                gates[
                    "combined_median_macro_f1_gt"
                ]
            ),
        ),
        (
            "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero",
            float(
                row[
                    "median_combined_accuracy_improvement_vs_train_majority"
                ]
            )
            > float(
                gates[
                    "combined_median_accuracy_improvement_vs_train_majority_gt"
                ]
            ),
        ),
        (
            "gate_combined_median_multiclass_mcc_gt_zero",
            float(
                row[
                    "median_combined_multiclass_mcc"
                ]
            )
            > float(
                gates[
                    "combined_median_multiclass_mcc_gt"
                ]
            ),
        ),
        (
            "gate_combined_median_minimum_class_recall_gt_20pct",
            float(
                row[
                    "median_combined_minimum_class_recall"
                ]
            )
            > float(
                gates[
                    "combined_median_minimum_class_recall_gt"
                ]
            ),
        ),
    ]

    passed = int(
        sum(
            bool(value)
            for _, value
            in checks
        )
    )
    total = len(
        checks
    )
    all_pass = bool(
        passed
        == total
    )

    detail = pd.DataFrame([{
        "research_version": (
            RESEARCH_VERSION
        ),
        **{
            name: bool(value)
            for name, value
            in checks
        },
        "passed_gate_count": (
            passed
        ),
        "total_gate_count": (
            total
        ),
        "median_stage1_balanced_accuracy": float(
            row[
                "median_stage1_balanced_accuracy"
            ]
        ),
        "median_stage1_mcc": float(
            row[
                "median_stage1_mcc"
            ]
        ),
        "median_stage2_balanced_accuracy": float(
            row[
                "median_stage2_balanced_accuracy"
            ]
        ),
        "median_stage2_mcc": float(
            row[
                "median_stage2_mcc"
            ]
        ),
        "median_combined_balanced_accuracy": float(
            row[
                "median_combined_balanced_accuracy"
            ]
        ),
        "median_combined_macro_f1": float(
            row[
                "median_combined_macro_f1"
            ]
        ),
        "median_combined_accuracy_improvement_vs_train_majority": float(
            row[
                "median_combined_accuracy_improvement_vs_train_majority"
            ]
        ),
        "median_combined_multiclass_mcc": float(
            row[
                "median_combined_multiclass_mcc"
            ]
        ),
        "median_combined_minimum_class_recall": float(
            row[
                "median_combined_minimum_class_recall"
            ]
        ),
    }])

    result = {
        "target_count": 3,
        "stage_count": 2,
        "total_predictive_gate_count": (
            total
        ),
        "passed_predictive_gate_count": (
            passed
        ),
        "all_predictive_gates_pass": (
            all_pass
        ),
        "status": (
            "ALLOW_POLICY_SIMULATION"
            if all_pass
            else "STOP_BEFORE_PORTFOLIO_SIMULATION"
        ),
    }

    return detail, result


def run(
    phase1_root: Path = PHASE1_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root = Path(
        phase1_root
    )
    output_root = Path(
        output_root
    )

    contract = json.loads(
        (
            phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    if (
        contract.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V12 Phase 1 research version"
        )
    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V12 Phase 1 holdout boundary differs from Phase 2"
        )

    stage1 = contract[
        "models"
    ]["stage1"]
    stage2 = contract[
        "models"
    ]["stage2"]

    if (
        stage1.get(
            "primary"
        )
        != STAGE1_MODEL
    ):
        raise RuntimeError(
            "V12 Stage 1 model differs from preregistration"
        )
    if float(
        stage1.get(
            "learning_rate"
        )
    ) != STAGE1_LEARNING_RATE:
        raise RuntimeError(
            "V12 Stage 1 learning rate differs from preregistration"
        )
    if int(
        stage1.get(
            "max_iter"
        )
    ) != STAGE1_MAX_ITER:
        raise RuntimeError(
            "V12 Stage 1 max_iter differs from preregistration"
        )
    if int(
        stage1.get(
            "max_leaf_nodes"
        )
    ) != STAGE1_MAX_LEAF_NODES:
        raise RuntimeError(
            "V12 Stage 1 leaf count differs from preregistration"
        )
    if int(
        stage1.get(
            "min_samples_leaf"
        )
    ) != STAGE1_MIN_SAMPLES_LEAF:
        raise RuntimeError(
            "V12 Stage 1 min_samples_leaf differs from preregistration"
        )
    if float(
        stage1.get(
            "l2_regularization"
        )
    ) != STAGE1_L2_REGULARIZATION:
        raise RuntimeError(
            "V12 Stage 1 L2 differs from preregistration"
        )
    if (
        stage1.get(
            "class_weight"
        )
        != STAGE1_CLASS_WEIGHT
    ):
        raise RuntimeError(
            "V12 Stage 1 class weighting differs from preregistration"
        )

    if (
        stage2.get(
            "primary"
        )
        != STAGE2_MODEL
    ):
        raise RuntimeError(
            "V12 Stage 2 model differs from preregistration"
        )
    if float(
        stage2.get(
            "C"
        )
    ) != STAGE2_C:
        raise RuntimeError(
            "V12 Stage 2 C differs from preregistration"
        )
    if (
        stage2.get(
            "class_weight"
        )
        != STAGE2_CLASS_WEIGHT
    ):
        raise RuntimeError(
            "V12 Stage 2 class weighting differs from preregistration"
        )

    for model_contract in (
        stage1,
        stage2,
    ):
        if (
            model_contract.get(
                "secondary_models"
            )
            != []
        ):
            raise RuntimeError(
                "V12 Phase 2 forbids secondary model search"
            )
        if (
            model_contract.get(
                "probability_calibration"
            )
            is not None
        ):
            raise RuntimeError(
                "V12 Phase 2 forbids probability calibration"
            )

    data = _read(
        (
            phase1_root
            / "daily_specialist_dataset.parquet"
        ),
        "V12 specialist dataset",
    )
    features = list(
        contract[
            "regime_feature_columns"
        ]
    )

    missing = (
        set(features)
        | {
            SOURCE_TARGET,
            STAGE1_TARGET,
            STAGE2_TARGET,
        }
    ) - set(
        data.columns
    )
    if missing:
        raise RuntimeError(
            f"V12 Phase 1 dataset missing columns: {sorted(missing)}"
        )

    forbidden = {
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
    } & set(
        features
    )
    if forbidden:
        raise RuntimeError(
            f"V12 targets leaked into model features: {sorted(forbidden)}"
        )

    predictions, metrics = (
        walk_forward(
            data,
            features,
        )
    )
    summary = summarize(
        metrics
    )
    gate_detail, gate_result = (
        evaluate_predictive_gates(
            summary,
            contract,
        )
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
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 2,
        "stage": (
            "purged_72h_btc_specialist_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "stage1_target": (
            STAGE1_TARGET
        ),
        "stage2_target": (
            STAGE2_TARGET
        ),
        "combined_target": (
            SOURCE_TARGET
        ),
        "purge_hours": int(
            PURGE.total_seconds()
            // 3600
        ),
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": (
            MAX_FOLDS
        ),
        "stage1_model": (
            STAGE1_MODEL
        ),
        "stage1_learning_rate": (
            STAGE1_LEARNING_RATE
        ),
        "stage1_max_iter": (
            STAGE1_MAX_ITER
        ),
        "stage1_max_leaf_nodes": (
            STAGE1_MAX_LEAF_NODES
        ),
        "stage1_min_samples_leaf": (
            STAGE1_MIN_SAMPLES_LEAF
        ),
        "stage1_l2_regularization": (
            STAGE1_L2_REGULARIZATION
        ),
        "stage1_class_weight": (
            STAGE1_CLASS_WEIGHT
        ),
        "stage1_balancing_implementation": (
            "compute_sample_weight"
        ),
        "stage2_model": (
            STAGE2_MODEL
        ),
        "stage2_C": (
            STAGE2_C
        ),
        "stage2_class_weight": (
            STAGE2_CLASS_WEIGHT
        ),
        "secondary_model_count": 0,
        "probability_calibration": False,
        "confidence_threshold_search": False,
        "input_rows": int(
            len(data)
        ),
        "prediction_rows": int(
            len(predictions)
        ),
        "fold_count": int(
            predictions[
                "fold_id"
            ].nunique()
        ),
        "predictive_gate_status": (
            gate_result[
                "status"
            ]
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
            "shared_crypto_v11_modified": False,
            "shared_crypto_v10_modified": False,
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "hyperparameters_tuned": False,
            "class_weight_tuned": False,
            "probability_calibrated": False,
            "confidence_threshold_tuned": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the frozen non-overlapping 72-hour portfolio policy only if "
            "predictive_gate_status is ALLOW_POLICY_SIMULATION. Otherwise "
            "preserve V12 as failed predictive evidence and do not simulate "
            "its portfolio policy."
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
