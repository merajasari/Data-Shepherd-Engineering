"""Shared Crypto V19 Relative Sleeve Router Phase 2.

OFFLINE RESEARCH ONLY.
No brokerage orders, no live allocation, and no automatic promotion.

Fits only the preregistered balanced V19 relative classifier.

Target:
    route_top3_over_btc_7d

Class 1 means the frozen V15-selected top-three basket had higher mean exact
seven-day net terminal return than BTC under the Phase 1 target definition.
Class 0 means BTC was at least as good.

Inputs:
* 11 frozen V15 rank-score diagnostics;
* 5 frozen BTC-relative score diagnostics;
* 18 frozen point-in-time market-context features.

Decision evaluation uses classifier.predict(...) directly. No probability
threshold is used or searched.

Validation uses the preregistered 360-day minimum training window, 180-day
validation windows, full seven-day purge, and at most six chronological folds.
Every training target path must end strictly before validation begins.

All four preregistered predictive gates must pass before any offline comparative
portfolio simulation:
1. median fold balanced accuracy > 0.55
2. median fold macro F1 > 0.55
3. median fold MCC > 0
4. median fold minimum class recall > 0.50

This phase performs no feature search, model-family search, secondary-model
fit, hyperparameter tuning, probability-threshold search, V15 refit, portfolio
simulation, future-holdout scoring, paper-state mutation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    balanced_accuracy_score,
    f1_score,
    matthews_corrcoef,
    recall_score,
)
from sklearn.utils.class_weight import compute_sample_weight


RESEARCH_VERSION = "shared_crypto_v19_relative_sleeve_router"

PHASE1_ROOT = Path(
    "data/model/shared_crypto_v19_relative_sleeve_router/phase1"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v19_relative_sleeve_router/phase2"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

RELATIVE_CONTINUOUS_TARGET = (
    "selected_top3_excess_vs_btc_net_terminal_7d_25bps"
)
RELATIVE_BINARY_TARGET = (
    "route_top3_over_btc_7d"
)

PRIMARY_MODEL = "hist_gradient_boosting_classifier"
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0
RANDOM_STATE = 1729
CLASS_WEIGHT_METHOD = "balanced_sample_weight"

PURGE_DAYS = 7
MIN_TRAIN_DAYS = 360
VALIDATION_DAYS = 180
MAX_FOLDS = 6

BTC_CLASS = 0
TOP3_CLASS = 1


def model_template() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=MODEL_LEARNING_RATE,
        max_iter=MODEL_MAX_ITER,
        max_leaf_nodes=MODEL_MAX_LEAF_NODES,
        max_depth=None,
        min_samples_leaf=MODEL_MIN_SAMPLES_LEAF,
        l2_regularization=MODEL_L2_REGULARIZATION,
        random_state=RANDOM_STATE,
    )


def balanced_sample_weights(
    labels: pd.Series,
) -> np.ndarray:
    values = np.asarray(
        pd.to_numeric(
            labels,
            errors="raise",
        ),
        dtype=int,
    )

    if set(
        np.unique(
            values
        )
    ) != {
        BTC_CLASS,
        TOP3_CLASS,
    }:
        raise RuntimeError(
            "V19 balanced weighting requires both BTC and TOP3 classes"
        )

    return np.asarray(
        compute_sample_weight(
            class_weight="balanced",
            y=values,
        ),
        dtype=float,
    )


def validate_pre_holdout(
    frame: pd.DataFrame,
    source: str,
) -> None:
    timestamps = pd.to_datetime(
        frame[
            "timestamp_utc"
        ],
        utc=True,
    )

    if (
        timestamps
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def make_folds(
    timestamps: pd.Series,
) -> list[dict]:
    timestamps = pd.to_datetime(
        timestamps,
        utc=True,
    )

    unique_dates = pd.Series(
        timestamps.drop_duplicates()
    ).sort_values().reset_index(
        drop=True
    )

    if unique_dates.empty:
        raise RuntimeError(
            "Cannot construct V19 folds from empty timestamps"
        )

    first = unique_dates.iloc[
        0
    ].floor(
        "D"
    )

    last = unique_dates.iloc[
        -1
    ]

    starts = []
    cursor = (
        first
        + pd.to_timedelta(
            MIN_TRAIN_DAYS,
            unit="D",
        )
    )

    while cursor <= last:
        starts.append(
            cursor
        )

        cursor += pd.to_timedelta(
            VALIDATION_DAYS,
            unit="D",
        )

    starts = starts[
        -MAX_FOLDS:
    ]

    folds = []

    for start in starts:
        end = min(
            start
            + pd.to_timedelta(
                VALIDATION_DAYS,
                unit="D",
            ),
            HOLDOUT,
        )

        train_end = (
            start
            - pd.to_timedelta(
                PURGE_DAYS,
                unit="D",
            )
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
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })

    if not folds:
        raise RuntimeError(
            "No valid purged V19 folds were constructed"
        )

    return folds


def classification_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
) -> dict[str, float]:
    actual_values = np.asarray(
        pd.to_numeric(
            actual,
            errors="raise",
        ),
        dtype=int,
    )

    predicted_values = np.asarray(
        predicted,
        dtype=int,
    )

    if set(
        np.unique(
            actual_values
        )
    ) != {
        BTC_CLASS,
        TOP3_CLASS,
    }:
        raise RuntimeError(
            "V19 validation metrics require both BTC and TOP3 classes"
        )

    if not set(
        np.unique(
            predicted_values
        )
    ).issubset({
        BTC_CLASS,
        TOP3_CLASS,
    }):
        raise RuntimeError(
            "V19 predicted route labels contain unexpected values"
        )

    recalls = recall_score(
        actual_values,
        predicted_values,
        labels=[
            BTC_CLASS,
            TOP3_CLASS,
        ],
        average=None,
        zero_division=0,
    )

    return {
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
                labels=[
                    BTC_CLASS,
                    TOP3_CLASS,
                ],
                average="macro",
                zero_division=0,
            )
        ),
        "mcc": float(
            matthews_corrcoef(
                actual_values,
                predicted_values,
            )
        ),
        "btc_recall": float(
            recalls[
                0
            ]
        ),
        "top3_recall": float(
            recalls[
                1
            ]
        ),
        "minimum_class_recall": float(
            np.min(
                recalls
            )
        ),
        "predicted_top3_fraction": float(
            np.mean(
                predicted_values
                == TOP3_CLASS
            )
        ),
        "actual_top3_fraction": float(
            np.mean(
                actual_values
                == TOP3_CLASS
            )
        ),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    prediction_frames = []
    metric_rows = []

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
            train.empty
            or validation.empty
        ):
            raise RuntimeError(
                f"{fold['fold_id']} contains an empty partition"
            )

        if (
            train[
                "timestamp_utc"
            ].max()
            >= fold[
                "train_end"
            ]
        ):
            raise RuntimeError(
                f"{fold['fold_id']} violates the seven-day purge"
            )

        train_endpoint = pd.to_datetime(
            train[
                "target_endpoint_utc_7d"
            ],
            utc=True,
        )

        if (
            train_endpoint.max()
            >= validation[
                "timestamp_utc"
            ].min()
        ):
            raise RuntimeError(
                f"{fold['fold_id']} target path leaks into validation"
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

        if (
            train[
                RELATIVE_BINARY_TARGET
            ].nunique()
            != 2
        ):
            raise RuntimeError(
                f"{fold['fold_id']} training lacks both BTC and TOP3 classes"
            )

        if (
            validation[
                RELATIVE_BINARY_TARGET
            ].nunique()
            != 2
        ):
            raise RuntimeError(
                f"{fold['fold_id']} validation lacks both BTC and TOP3 classes"
            )

        sample_weight = (
            balanced_sample_weights(
                train[
                    RELATIVE_BINARY_TARGET
                ]
            )
        )

        model = clone(
            model_template()
        )

        model.fit(
            train[
                features
            ],
            train[
                RELATIVE_BINARY_TARGET
            ].astype(
                int
            ),
            sample_weight=sample_weight,
        )

        predicted_label = np.asarray(
            model.predict(
                validation[
                    features
                ]
            ),
            dtype=int,
        )

        metrics = classification_metrics(
            validation[
                RELATIVE_BINARY_TARGET
            ],
            predicted_label,
        )

        out = validation[
            [
                "timestamp_utc",
                "source_v15_fold_id",
                "target_endpoint_utc_7d",
                "selected_assets",
                "btc_in_selected_top3",
                "selected_top3_mean_net_terminal_return_7d_25bps",
                "btc_net_terminal_return_7d_25bps",
                RELATIVE_CONTINUOUS_TARGET,
                RELATIVE_BINARY_TARGET,
            ]
        ].copy()

        out[
            "fold_id"
        ] = (
            fold[
                "fold_id"
            ]
        )

        out[
            "predicted_route_top3"
        ] = (
            predicted_label
        )

        out[
            "correct_relative_route"
        ] = (
            predicted_label
            == validation[
                RELATIVE_BINARY_TARGET
            ].to_numpy(
                dtype=int
            )
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
            "train_top3_fraction": float(
                train[
                    RELATIVE_BINARY_TARGET
                ].mean()
            ),
            "validation_top3_fraction": float(
                validation[
                    RELATIVE_BINARY_TARGET
                ].mean()
            ),
            "train_weight_sum": float(
                sample_weight.sum()
            ),
            "train_weight_btc_sum": float(
                sample_weight[
                    train[
                        RELATIVE_BINARY_TARGET
                    ].to_numpy(
                        dtype=int
                    )
                    == BTC_CLASS
                ].sum()
            ),
            "train_weight_top3_sum": float(
                sample_weight[
                    train[
                        RELATIVE_BINARY_TARGET
                    ].to_numpy(
                        dtype=int
                    )
                    == TOP3_CLASS
                ].sum()
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
            **metrics,
        })

        prediction_frames.append(
            out
        )

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            f"features={len(features)} "
            "purge=7d "
            "balanced-sample-weight "
            "target=frozen-v15-top3-relative-to-btc "
            "decision=direct-class "
            "research=offline-only"
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
    row = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "fold_count": int(
            metrics[
                "fold_id"
            ].nunique()
        ),
        "median_fold_balanced_accuracy": float(
            metrics[
                "balanced_accuracy"
            ].median()
        ),
        "mean_fold_balanced_accuracy": float(
            metrics[
                "balanced_accuracy"
            ].mean()
        ),
        "median_fold_macro_f1": float(
            metrics[
                "macro_f1"
            ].median()
        ),
        "mean_fold_macro_f1": float(
            metrics[
                "macro_f1"
            ].mean()
        ),
        "median_fold_mcc": float(
            metrics[
                "mcc"
            ].median()
        ),
        "mean_fold_mcc": float(
            metrics[
                "mcc"
            ].mean()
        ),
        "median_fold_minimum_class_recall": float(
            metrics[
                "minimum_class_recall"
            ].median()
        ),
        "median_fold_btc_recall": float(
            metrics[
                "btc_recall"
            ].median()
        ),
        "median_fold_top3_recall": float(
            metrics[
                "top3_recall"
            ].median()
        ),
        "median_fold_predicted_top3_fraction": float(
            metrics[
                "predicted_top3_fraction"
            ].median()
        ),
        "median_fold_actual_top3_fraction": float(
            metrics[
                "actual_top3_fraction"
            ].median()
        ),
    }

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
            "V19 predictive summary must contain exactly one row"
        )

    row = summary.iloc[
        0
    ]

    gates = contract[
        "predictive_quality_gates"
    ]

    checks = [
        (
            "gate_median_fold_balanced_accuracy_gt_55pct",
            float(
                row[
                    "median_fold_balanced_accuracy"
                ]
            )
            > float(
                gates[
                    "median_fold_balanced_accuracy_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_macro_f1_gt_55pct",
            float(
                row[
                    "median_fold_macro_f1"
                ]
            )
            > float(
                gates[
                    "median_fold_macro_f1_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_mcc_gt_zero",
            float(
                row[
                    "median_fold_mcc"
                ]
            )
            > float(
                gates[
                    "median_fold_mcc_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_minimum_class_recall_gt_50pct",
            float(
                row[
                    "median_fold_minimum_class_recall"
                ]
            )
            > float(
                gates[
                    "median_fold_minimum_class_recall_gt"
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

    detail = pd.DataFrame([
        {
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
            "median_fold_balanced_accuracy": float(
                row[
                    "median_fold_balanced_accuracy"
                ]
            ),
            "median_fold_macro_f1": float(
                row[
                    "median_fold_macro_f1"
                ]
            ),
            "median_fold_mcc": float(
                row[
                    "median_fold_mcc"
                ]
            ),
            "median_fold_minimum_class_recall": float(
                row[
                    "median_fold_minimum_class_recall"
                ]
            ),
            "median_fold_btc_recall": float(
                row[
                    "median_fold_btc_recall"
                ]
            ),
            "median_fold_top3_recall": float(
                row[
                    "median_fold_top3_recall"
                ]
            ),
        }
    ])

    result = {
        "target_count": 1,
        "class_count": 2,
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
            "ALLOW_OFFLINE_PORTFOLIO_SIMULATION"
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
            "Unexpected V19 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V19 Phase 1 holdout differs from Phase 2"
        )

    target = contract.get(
        "relative_target",
        {},
    )

    if (
        target.get(
            "continuous"
        )
        != RELATIVE_CONTINUOUS_TARGET
    ):
        raise RuntimeError(
            "Unexpected V19 continuous relative target"
        )

    if (
        target.get(
            "binary"
        )
        != RELATIVE_BINARY_TARGET
    ):
        raise RuntimeError(
            "Unexpected V19 binary relative target"
        )

    if (
        target.get(
            "binary_definition"
        )
        != (
            "1 when selected_top3_excess_vs_btc_net_terminal_7d_25bps > 0, else 0"
        )
    ):
        raise RuntimeError(
            "Unexpected V19 relative excess boundary"
        )

    expected_model = {
        "primary": (
            PRIMARY_MODEL
        ),
        "learning_rate": (
            MODEL_LEARNING_RATE
        ),
        "max_iter": (
            MODEL_MAX_ITER
        ),
        "max_leaf_nodes": (
            MODEL_MAX_LEAF_NODES
        ),
        "max_depth": None,
        "min_samples_leaf": (
            MODEL_MIN_SAMPLES_LEAF
        ),
        "l2_regularization": (
            MODEL_L2_REGULARIZATION
        ),
        "random_state": (
            RANDOM_STATE
        ),
        "class_weight_method": (
            CLASS_WEIGHT_METHOD
        ),
        "secondary_models": [],
    }

    if (
        contract.get(
            "router_model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V19 router model differs from preregistration"
        )

    expected_walk = {
        "purge_days": PURGE_DAYS,
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": MAX_FOLDS,
    }

    if (
        contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V19 walk-forward contract differs from preregistration"
        )

    expected_gates = {
        "median_fold_balanced_accuracy_gt": 0.55,
        "median_fold_macro_f1_gt": 0.55,
        "median_fold_mcc_gt": 0.0,
        "median_fold_minimum_class_recall_gt": 0.50,
        "all_gates_required_before_portfolio_simulation": True,
    }

    if (
        contract.get(
            "predictive_quality_gates"
        )
        != expected_gates
    ):
        raise RuntimeError(
            "V19 predictive gates differ from preregistration"
        )

    constraints = contract.get(
        "research_constraints",
        {},
    )

    for key in (
        "offline_research_only",
        "v15_oos_predictions_are_frozen_input",
        "gross_crypto_weight_fixed_at_60pct",
        "cash_weight_fixed_at_40pct",
        "relative_target_fixed_before_fit",
        "zero_relative_excess_boundary_fixed_before_fit",
        "score_diagnostics_fixed_before_fit",
        "same_18_point_in_time_market_features_as_v16",
        "router_model_fixed_before_fit",
        "balanced_sample_weight_fixed_before_fit",
        "no_probability_threshold",
        "no_probability_threshold_search",
        "no_feature_search",
        "no_secondary_model_search",
        "no_hyperparameter_search",
        "predictive_gates_required_before_portfolio_simulation",
        "portfolio_gates_fixed_before_simulation",
        "future_holdout_must_remain_untouched_until_candidate_freeze",
    ):
        if (
            constraints.get(
                key
            )
            is not True
        ):
            raise RuntimeError(
                "V19 Phase 1 research constraint failed: "
                f"{key}"
            )

    for key in (
        "v15_ranker_refit",
        "market_timing_or_cash_gate",
        "automatic_promotion",
        "brokerage_orders",
    ):
        if (
            constraints.get(
                key
            )
            is not False
        ):
            raise RuntimeError(
                "V19 Phase 1 negative research constraint failed: "
                f"{key}"
            )

    features = list(
        contract[
            "model_feature_columns"
        ]
    )

    if len(
        features
    ) != 34:
        raise RuntimeError(
            "V19 expected exactly 34 preregistered model features"
        )

    rank_features = list(
        contract[
            "v18_rank_diagnostic_feature_columns"
        ]
    )

    btc_features = list(
        contract[
            "btc_relative_feature_columns"
        ]
    )

    market_features = list(
        contract[
            "market_context_feature_columns"
        ]
    )

    if len(
        rank_features
    ) != 11:
        raise RuntimeError(
            "V19 expected exactly 11 rank diagnostics"
        )

    if len(
        btc_features
    ) != 5:
        raise RuntimeError(
            "V19 expected exactly 5 BTC-relative diagnostics"
        )

    if len(
        market_features
    ) != 18:
        raise RuntimeError(
            "V19 expected exactly 18 market context features"
        )

    if features != (
        rank_features
        + btc_features
        + market_features
    ):
        raise RuntimeError(
            "V19 model feature order differs from preregistration"
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

    features = _validate_contract(
        contract
    )

    data = pd.read_parquet(
        phase1_root
        / "relative_sleeve_router_dataset.parquet"
    ).copy()

    data[
        "timestamp_utc"
    ] = pd.to_datetime(
        data[
            "timestamp_utc"
        ],
        utc=True,
    )

    data[
        "target_endpoint_utc_7d"
    ] = pd.to_datetime(
        data[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    validate_pre_holdout(
        data,
        "V19 Phase 1 relative router dataset",
    )

    required = {
        "timestamp_utc",
        "source_v15_fold_id",
        "target_endpoint_utc_7d",
        "selected_assets",
        "btc_in_selected_top3",
        "selected_top3_mean_net_terminal_return_7d_25bps",
        "btc_net_terminal_return_7d_25bps",
        RELATIVE_CONTINUOUS_TARGET,
        RELATIVE_BINARY_TARGET,
        *features,
    }

    missing = required - set(
        data.columns
    )

    if missing:
        raise RuntimeError(
            "V19 Phase 1 dataset missing columns: "
            f"{sorted(missing)}"
        )

    finite = data[
        [
            *features,
            RELATIVE_CONTINUOUS_TARGET,
        ]
    ].replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    )

    if (
        finite
        .isna()
        .any()
        .any()
    ):
        raise RuntimeError(
            "V19 Phase 1 dataset contains non-finite model inputs"
        )

    labels = pd.to_numeric(
        data[
            RELATIVE_BINARY_TARGET
        ],
        errors="raise",
    ).astype(
        int
    )

    if set(
        labels.unique()
    ) != {
        BTC_CLASS,
        TOP3_CLASS,
    }:
        raise RuntimeError(
            "V19 Phase 1 dataset must contain both BTC and TOP3 classes"
        )

    expected_labels = (
        pd.to_numeric(
            data[
                RELATIVE_CONTINUOUS_TARGET
            ],
            errors="raise",
        )
        > 0.0
    ).astype(
        int
    )

    if not labels.equals(
        expected_labels
    ):
        raise RuntimeError(
            "V19 Phase 1 labels no longer match the frozen relative-return target"
        )

    predictions, fold_metrics = (
        walk_forward(
            data,
            features,
        )
    )

    summary = summarize(
        fold_metrics
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
        / "relative_router_predictions.parquet"
    )
    fold_path = (
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
    fold_metrics.to_csv(
        fold_path,
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
            "purged_relative_top3_vs_btc_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "binary_target": (
            RELATIVE_BINARY_TARGET
        ),
        "continuous_reference_target": (
            RELATIVE_CONTINUOUS_TARGET
        ),
        "decision_rule": (
            "direct_classifier_class_prediction"
        ),
        "probability_threshold": None,
        "model": PRIMARY_MODEL,
        "class_weight_method": (
            CLASS_WEIGHT_METHOD
        ),
        "model_feature_count": int(
            len(
                features
            )
        ),
        "purge_days": PURGE_DAYS,
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": MAX_FOLDS,
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
            fold_metrics[
                "fold_id"
            ].nunique()
        ),
        "predicted_top3_count": int(
            predictions[
                "predicted_route_top3"
            ].sum()
        ),
        "predicted_btc_count": int(
            (
                predictions[
                    "predicted_route_top3"
                ]
                == BTC_CLASS
            ).sum()
        ),
        "actual_top3_count": int(
            predictions[
                RELATIVE_BINARY_TARGET
            ].sum()
        ),
        "actual_btc_count": int(
            (
                predictions[
                    RELATIVE_BINARY_TARGET
                ]
                == BTC_CLASS
            ).sum()
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
            "relative_router_predictions": str(
                prediction_path
            ),
            "fold_metrics": str(
                fold_path
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
            "offline_research_only": True,
            "shared_crypto_v15_modified": False,
            "shared_crypto_v16_modified": False,
            "shared_crypto_v18_modified": False,
            "v15_ranker_refit": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "feature_search_performed": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "hyperparameters_tuned": False,
            "probability_threshold_used": False,
            "probability_threshold_searched": False,
            "predictive_gate_lowered": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the preregistered offline comparative portfolio simulation "
            "only if all four V19 predictive gates pass. Otherwise preserve "
            "V19 as failed predictive evidence and do not simulate the router."
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
