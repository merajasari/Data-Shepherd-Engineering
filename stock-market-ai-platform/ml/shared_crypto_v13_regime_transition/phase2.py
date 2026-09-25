"""Shared Crypto V13 Regime Transition Phase 2.

Fits the exact V12 hierarchy on the preregistered V13 information set.

The only experimental change from V12 is the addition of exact 24-hour and
72-hour regime-transition features created in V13 Phase 1. Model families,
hyperparameters, class weighting, walk-forward protocol, predictive gates, and
the frozen later portfolio policy remain unchanged.

Stage 1 BTC-vs-DEVIATE:
    HistGradientBoostingClassifier with fixed balanced training weights.

Stage 2 ALT-vs-CASH:
    standardized balanced LinearSVC(C=0.25), trained only on true historical
    deviation rows.

Training uses expanding chronological folds with a full 72-hour purge. All
nine unchanged predictive gates must pass before any portfolio simulation.
The September 1, 2026 future holdout remains untouched.
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


RESEARCH_VERSION = "shared_crypto_v13_regime_transition"
PHASE1_ROOT = Path(
    "data/model/shared_crypto_v13_regime_transition/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v13_regime_transition/phase2"
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
        (
            "imputer",
            SimpleImputer(
                strategy="median"
            ),
        ),
        (
            "scaler",
            StandardScaler(),
        ),
        (
            "model",
            LinearSVC(
                C=STAGE2_C,
                loss="squared_hinge",
                penalty="l2",
                class_weight=STAGE2_CLASS_WEIGHT,
                dual="auto",
                max_iter=10000,
                random_state=1729,
            ),
        ),
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
    if not Path(
        path
    ).exists():
        raise FileNotFoundError(
            path
        )

    frame = pd.read_parquet(
        path
    ).copy()
    frame[
        "timestamp_utc"
    ] = pd.to_datetime(
        frame[
            "timestamp_utc"
        ],
        utc=True,
    )

    validate_pre_holdout(
        frame,
        source,
    )

    return frame.sort_values(
        "timestamp_utc"
    ).reset_index(
        drop=True
    )


def make_folds(
    timestamps: pd.Series,
) -> list[dict]:
    timestamps = pd.to_datetime(
        timestamps,
        utc=True,
    )

    unique = pd.Series(
        timestamps.drop_duplicates()
    ).sort_values().reset_index(
        drop=True
    )

    if unique.empty:
        raise RuntimeError(
            "Cannot construct V13 folds from empty timestamps"
        )

    first = unique.iloc[
        0
    ].floor(
        "D"
    )
    last = unique.iloc[
        -1
    ]
    starts = []

    cursor = (
        first
        + timedelta(
            days=MIN_TRAIN_DAYS
        )
    )

    while cursor <= last:
        starts.append(
            cursor
        )
        cursor += timedelta(
            days=VALIDATION_DAYS
        )

    starts = starts[
        -MAX_FOLDS:
    ]
    folds = []

    for start in starts:
        end = min(
            start
            + timedelta(
                days=VALIDATION_DAYS
            ),
            HOLDOUT,
        )
        train_end = (
            start
            - PURGE
        )

        train = (
            timestamps
            < train_end
        )
        validation = (
            (
                timestamps
                >= start
            )
            & (
                timestamps
                < end
            )
        )

        if (
            train.any()
            and validation.any()
        ):
            folds.append({
                "fold_id": (
                    f"fold_{len(folds) + 1:02d}"
                ),
                "start": (
                    start
                ),
                "end": (
                    end
                ),
                "train_end": (
                    train_end
                ),
                "train": (
                    train
                ),
                "validation": (
                    validation
                ),
            })

    if not folds:
        raise RuntimeError(
            "No valid purged V13 folds were constructed"
        )

    return folds


def binary_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    classes: tuple[
        str,
        str,
    ],
) -> dict[
    str,
    float,
]:
    actual_values = np.asarray(
        actual,
        dtype=object,
    )
    predicted_values = np.asarray(
        predicted,
        dtype=object,
    )

    unexpected_actual = (
        set(
            np.unique(
                actual_values
            )
        )
        - set(
            classes
        )
    )
    unexpected_predicted = (
        set(
            np.unique(
                predicted_values
            )
        )
        - set(
            classes
        )
    )

    if unexpected_actual:
        raise RuntimeError(
            "Unexpected V13 binary actual class: "
            f"{sorted(unexpected_actual)}"
        )

    if unexpected_predicted:
        raise RuntimeError(
            "Unexpected V13 binary predicted class: "
            f"{sorted(unexpected_predicted)}"
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
) -> dict[
    str,
    float | str,
]:
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
        set(
            np.unique(
                actual_values
            )
        )
        - set(
            COMBINED_CLASSES
        )
    ):
        raise RuntimeError(
            "Unexpected V13 combined actual class"
        )

    if (
        set(
            np.unique(
                predicted_values
            )
        )
        - set(
            COMBINED_CLASSES
        )
    ):
        raise RuntimeError(
            "Unexpected V13 combined predicted class"
        )

    train_counts = (
        pd.Series(
            train_values
        )
        .value_counts()
    )
    train_majority = str(
        train_counts.index[
            0
        ]
    )
    baseline_prediction = np.full(
        len(
            actual_values
        ),
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
        "accuracy": (
            accuracy
        ),
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
            np.min(
                recalls
            )
        ),
        "btc_recall": float(
            recalls[
                0
            ]
        ),
        "alt_recall": float(
            recalls[
                1
            ]
        ),
        "cash_recall": float(
            recalls[
                2
            ]
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
    model = (
        fitted_pipeline
        .named_steps[
            "model"
        ]
    )

    classes = list(
        model.classes_
    )

    if (
        positive_class
        not in classes
    ):
        raise RuntimeError(
            "V13 Stage 2 model missing class "
            f"{positive_class}"
        )

    raw = np.asarray(
        fitted_pipeline.decision_function(
            features
        ),
        dtype=float,
    )

    if raw.ndim != 1:
        raise RuntimeError(
            "V13 expected one-dimensional Stage 2 decision margins"
        )

    if (
        classes[
            1
        ]
        == positive_class
    ):
        return raw

    if (
        classes[
            0
        ]
        == positive_class
    ):
        return -raw

    raise RuntimeError(
        "V13 cannot orient Stage 2 margin for "
        f"{positive_class}"
    )


def _class_probability(
    fitted_model: HistGradientBoostingClassifier,
    features: pd.DataFrame,
    class_name: str,
) -> np.ndarray:
    classes = list(
        fitted_model.classes_
    )

    if (
        class_name
        not in classes
    ):
        raise RuntimeError(
            "V13 Stage 1 model missing class "
            f"{class_name}"
        )

    probabilities = np.asarray(
        fitted_model.predict_proba(
            features
        ),
        dtype=float,
    )

    if (
        probabilities.shape
        != (
            len(
                features
            ),
            len(
                classes
            ),
        )
    ):
        raise RuntimeError(
            "V13 Stage 1 returned unexpected probability shape"
        )

    result = probabilities[
        :,
        classes.index(
            class_name
        ),
    ]

    if (
        (
            result
            < 0.0
        ).any()
        or (
            result
            > 1.0
        ).any()
        or not np.isfinite(
            result
        ).all()
    ):
        raise RuntimeError(
            "V13 Stage 1 returned invalid probabilities"
        )

    return result


def walk_forward(
    data: pd.DataFrame,
    features: list[
        str
    ],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
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
        if (
            optional
            in data.columns
        ):
            base_columns.append(
                optional
            )

    for fold in make_folds(
        data[
            "timestamp_utc"
        ]
    ):
        train = data.loc[
            fold[
                "train"
            ]
        ].copy()

        validation = data.loc[
            fold[
                "validation"
            ]
        ].copy()

        if (
            train[
                "timestamp_utc"
            ].max()
            >= fold[
                "train_end"
            ]
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

        stage1_train_target = (
            train[
                STAGE1_TARGET
            ].astype(
                str
            )
        )
        stage1_validation_target = (
            validation[
                STAGE1_TARGET
            ].astype(
                str
            )
        )

        if (
            set(
                stage1_train_target.unique()
            )
            != set(
                STAGE1_CLASSES
            )
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
            train[
                features
            ],
            stage1_train_target,
            sample_weight=stage1_weights,
        )

        stage1_predicted = np.asarray(
            stage1_model.predict(
                validation[
                    features
                ]
            ),
            dtype=object,
        )

        stage1_probability_deviate = (
            _class_probability(
                stage1_model,
                validation[
                    features
                ],
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

        stage2_train_target = (
            stage2_train[
                STAGE2_TARGET
            ].astype(
                str
            )
        )
        stage2_validation_target = (
            stage2_validation[
                STAGE2_TARGET
            ].astype(
                str
            )
        )

        if (
            set(
                stage2_train_target.unique()
            )
            != set(
                STAGE2_CLASSES
            )
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 training lacks both classes"
            )

        if (
            stage2_validation.empty
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 validation is empty"
            )

        if (
            set(
                stage2_validation_target.unique()
            )
            != set(
                STAGE2_CLASSES
            )
        ):
            raise RuntimeError(
                f"{fold['fold_id']} Stage 2 validation lacks both classes"
            )

        stage2_model = clone(
            stage2_model_template()
        ).fit(
            stage2_train[
                features
            ],
            stage2_train_target,
        )

        stage2_predicted_all = np.asarray(
            stage2_model.predict(
                validation[
                    features
                ]
            ),
            dtype=object,
        )

        stage2_margin_cash_all = (
            _binary_margin(
                stage2_model,
                validation[
                    features
                ],
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
            ].astype(
                str
            ),
            combined_predicted,
            train[
                SOURCE_TARGET
            ].astype(
                str
            ),
        )

        out = validation[
            base_columns
        ].copy()

        out[
            "fold_id"
        ] = (
            fold[
                "fold_id"
            ]
        )
        out[
            "stage1_predicted"
        ] = (
            stage1_predicted
        )
        out[
            "stage1_probability_deviate"
        ] = (
            stage1_probability_deviate
        )
        out[
            "stage2_predicted"
        ] = (
            stage2_predicted_all
        )
        out[
            "stage2_margin_cash"
        ] = (
            stage2_margin_cash_all
        )
        out[
            "predicted_sleeve"
        ] = (
            combined_predicted
        )

        metric_rows.append({
            "fold_id": (
                fold[
                    "fold_id"
                ]
            ),
            "train_rows": int(
                len(
                    train
                )
            ),
            "validation_rows": int(
                len(
                    validation
                )
            ),
            "stage2_train_rows": int(
                len(
                    stage2_train
                )
            ),
            "stage2_validation_rows": int(
                len(
                    stage2_validation
                )
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
                f"combined_{key}": (
                    value
                )
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
            f"features={len(features)} "
            "purge=72h "
            "models=frozen-v12-hierarchy"
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
        for column
        in metrics.columns
        if column
        not in identity
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
            metrics[
                column
            ],
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
) -> tuple[
    pd.DataFrame,
    dict,
]:
    if len(
        summary
    ) != 1:
        raise RuntimeError(
            "V13 predictive summary must contain exactly one row"
        )

    row = summary.iloc[
        0
    ]
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
            bool(
                value
            )
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
            name: bool(
                value
            )
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

    return (
        detail,
        result,
    )


def _validate_contract(
    contract: dict,
) -> list[str]:
    if (
        contract.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V13 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V13 Phase 1 holdout boundary differs from Phase 2"
        )

    constraints = contract.get(
        "research_constraints",
        {},
    )

    for key in (
        "models_carried_forward_unchanged_from_v12",
        "predictive_gates_carried_forward_unchanged_from_v12",
        "portfolio_gates_carried_forward_unchanged_from_v12",
        "only_information_set_changed",
        "transition_features_fixed_before_fit",
        "exact_timestamp_lags_only",
        "no_model_family_search",
        "no_secondary_model_search",
        "no_probability_calibration",
        "no_confidence_threshold_search",
        "predictive_gates_required_before_portfolio_simulation",
        "nonoverlapping_72h_evaluation_required",
        "future_holdout_must_remain_untouched_until_candidate_freeze",
    ):
        if (
            constraints.get(
                key
            )
            is not True
        ):
            raise RuntimeError(
                "V13 Phase 1 research constraint failed: "
                f"{key}"
            )

    models = contract.get(
        "models",
        {},
    )

    stage1 = models.get(
        "stage1",
        {},
    )
    stage2 = models.get(
        "stage2",
        {},
    )

    expected_stage1 = {
        "primary": (
            STAGE1_MODEL
        ),
        "learning_rate": (
            STAGE1_LEARNING_RATE
        ),
        "max_iter": (
            STAGE1_MAX_ITER
        ),
        "max_leaf_nodes": (
            STAGE1_MAX_LEAF_NODES
        ),
        "max_depth": None,
        "min_samples_leaf": (
            STAGE1_MIN_SAMPLES_LEAF
        ),
        "l2_regularization": (
            STAGE1_L2_REGULARIZATION
        ),
        "class_weight": (
            STAGE1_CLASS_WEIGHT
        ),
        "random_state": 1729,
        "secondary_models": [],
        "probability_calibration": None,
    }

    expected_stage2 = {
        "primary": (
            STAGE2_MODEL
        ),
        "C": (
            STAGE2_C
        ),
        "loss": "squared_hinge",
        "penalty": "l2",
        "class_weight": (
            STAGE2_CLASS_WEIGHT
        ),
        "dual": "auto",
        "max_iter": 10000,
        "standardize_features": True,
        "random_state": 1729,
        "secondary_models": [],
        "probability_calibration": None,
    }

    if (
        stage1
        != expected_stage1
    ):
        raise RuntimeError(
            "V13 Stage 1 model contract differs from frozen V12 specification"
        )

    if (
        stage2
        != expected_stage2
    ):
        raise RuntimeError(
            "V13 Stage 2 model contract differs from frozen V12 specification"
        )

    walk_forward_contract = contract.get(
        "walk_forward",
        {},
    )

    expected_walk_forward = {
        "purge_hours": 72,
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": (
            MAX_FOLDS
        ),
    }

    if (
        walk_forward_contract
        != expected_walk_forward
    ):
        raise RuntimeError(
            "V13 walk-forward contract differs from frozen V12 protocol"
        )

    features = list(
        contract[
            "regime_feature_columns"
        ]
    )

    feature_engineering = contract.get(
        "feature_engineering",
        {},
    )

    if (
        int(
            feature_engineering.get(
                "base_regime_feature_count",
                -1,
            )
        )
        != 52
    ):
        raise RuntimeError(
            "V13 expected 52 carried-forward base features"
        )

    if (
        int(
            feature_engineering.get(
                "transition_feature_count",
                -1,
            )
        )
        != 24
    ):
        raise RuntimeError(
            "V13 expected exactly 24 transition features"
        )

    if (
        len(
            features
        )
        != 76
    ):
        raise RuntimeError(
            "V13 expected exactly 76 model features"
        )

    return features


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

    features = (
        _validate_contract(
            contract
        )
    )

    data = _read(
        (
            phase1_root
            / "daily_regime_transition_dataset.parquet"
        ),
        "V13 regime transition dataset",
    )

    missing = (
        set(
            features
        )
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
            "V13 Phase 1 dataset missing columns: "
            f"{sorted(missing)}"
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
            "V13 targets leaked into model features: "
            f"{sorted(forbidden)}"
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
            "purged_72h_regime_transition_predictive_adjudication"
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
        "model_feature_count": int(
            len(
                features
            )
        ),
        "base_feature_count": int(
            contract[
                "feature_engineering"
            ][
                "base_regime_feature_count"
            ]
        ),
        "transition_feature_count": int(
            contract[
                "feature_engineering"
            ][
                "transition_feature_count"
            ]
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
            len(
                data
            )
        ),
        "prediction_rows": int(
            len(
                predictions
            )
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
            "shared_crypto_v12_modified": False,
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
            "preserve V13 as failed predictive evidence and do not simulate "
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


def main(
    argv=None,
) -> None:
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

    args = parser.parse_args(
        argv
    )

    print(
        json.dumps(
            run(
                args.phase1_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
