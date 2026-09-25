"""Shared Crypto V16 Risk-Gated Rank Phase 2.

Fits only the preregistered V16 broad-market risk regressor.

Target:
    market_median_path_utility_net25_7d

Frozen risk decision:
    predicted market_median_path_utility_net25_7d > 0 -> RISK_ON
    otherwise -> RISK_OFF

Validation uses expanding chronological folds with a full seven-day purge, and
every training target path must end strictly before validation begins.

All four preregistered risk predictive gates must pass before V16 is allowed to
combine this gate with the frozen V15 ranking engine in any portfolio
simulation:
1. median fold Spearman IC > 0.10
2. median fold balanced accuracy > 0.55
3. median fold MCC > 0
4. median fold minimum class recall > 0.50

This phase performs no threshold search, no model-family search, no secondary
model fit, no V15 refit, no portfolio simulation, no future-holdout score, no
paper activation, and no brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import (
    balanced_accuracy_score,
    matthews_corrcoef,
    recall_score,
)


RESEARCH_VERSION = "shared_crypto_v16_risk_gated_rank"
PHASE1_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase2"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

MARKET_TARGET = "market_median_path_utility_net25_7d"
MARKET_LABEL = "market_risk_on_7d"

PRIMARY_MODEL = "hist_gradient_boosting_regressor"
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0
RANDOM_STATE = 1729

PURGE_DAYS = 7
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 8

RISK_OFF = 0
RISK_ON = 1


def model_template() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=MODEL_LEARNING_RATE,
        max_iter=MODEL_MAX_ITER,
        max_leaf_nodes=MODEL_MAX_LEAF_NODES,
        max_depth=None,
        min_samples_leaf=MODEL_MIN_SAMPLES_LEAF,
        l2_regularization=MODEL_L2_REGULARIZATION,
        random_state=RANDOM_STATE,
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
            "Cannot construct V16 folds from empty timestamps"
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
            "No valid purged V16 folds were constructed"
        )

    return folds


def classification_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
) -> dict[str, float]:
    actual_values = np.asarray(
        actual,
        dtype=int,
    )

    predicted_values = np.asarray(
        predicted,
        dtype=int,
    )

    if not set(
        np.unique(
            actual_values
        )
    ).issubset({
        RISK_OFF,
        RISK_ON,
    }):
        raise RuntimeError(
            "V16 actual risk labels contain unexpected values"
        )

    if not set(
        np.unique(
            predicted_values
        )
    ).issubset({
        RISK_OFF,
        RISK_ON,
    }):
        raise RuntimeError(
            "V16 predicted risk labels contain unexpected values"
        )

    recalls = recall_score(
        actual_values,
        predicted_values,
        labels=[
            RISK_OFF,
            RISK_ON,
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
        "mcc": float(
            matthews_corrcoef(
                actual_values,
                predicted_values,
            )
        ),
        "risk_off_recall": float(
            recalls[
                0
            ]
        ),
        "risk_on_recall": float(
            recalls[
                1
            ]
        ),
        "minimum_class_recall": float(
            np.min(
                recalls
            )
        ),
    }


def regression_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
) -> dict[str, float]:
    actual_values = pd.Series(
        pd.to_numeric(
            actual,
            errors="raise",
        ),
        dtype=float,
    )

    predicted_values = pd.Series(
        np.asarray(
            predicted,
            dtype=float,
        ),
        index=actual_values.index,
        dtype=float,
    )

    if not np.isfinite(
        predicted_values.to_numpy(
            dtype=float
        )
    ).all():
        raise RuntimeError(
            "V16 market-risk model produced non-finite predictions"
        )

    if (
        actual_values.nunique()
        <= 1
        or predicted_values.nunique()
        <= 1
    ):
        spearman = np.nan
    else:
        spearman = float(
            predicted_values.corr(
                actual_values,
                method="spearman",
            )
        )

    errors = (
        predicted_values
        - actual_values
    )

    return {
        "spearman_ic": float(
            spearman
        ),
        "mae": float(
            np.abs(
                errors
            ).mean()
        ),
        "rmse": float(
            np.sqrt(
                np.mean(
                    np.square(
                        errors
                    )
                )
            )
        ),
        "actual_mean": float(
            actual_values.mean()
        ),
        "predicted_mean": float(
            predicted_values.mean()
        ),
        "actual_positive_fraction": float(
            (
                actual_values
                > 0.0
            ).mean()
        ),
        "predicted_positive_fraction": float(
            (
                predicted_values
                > 0.0
            ).mean()
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
                MARKET_LABEL
            ].nunique()
            != 2
        ):
            raise RuntimeError(
                f"{fold['fold_id']} training lacks both risk classes"
            )

        if (
            validation[
                MARKET_LABEL
            ].nunique()
            != 2
        ):
            raise RuntimeError(
                f"{fold['fold_id']} validation lacks both risk classes"
            )

        model = clone(
            model_template()
        )

        model.fit(
            train[
                features
            ],
            train[
                MARKET_TARGET
            ],
        )

        predicted_utility = np.asarray(
            model.predict(
                validation[
                    features
                ]
            ),
            dtype=float,
        )

        predicted_label = (
            predicted_utility
            > 0.0
        ).astype(
            int
        )

        reg = regression_metrics(
            validation[
                MARKET_TARGET
            ],
            predicted_utility,
        )

        cls = classification_metrics(
            validation[
                MARKET_LABEL
            ],
            predicted_label,
        )

        out = validation[
            [
                "timestamp_utc",
                "target_endpoint_utc_7d",
                "eligible_asset_count",
                MARKET_TARGET,
                MARKET_LABEL,
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
            "predicted_market_utility"
        ] = (
            predicted_utility
        )

        out[
            "predicted_market_risk_on"
        ] = (
            predicted_label
        )

        out[
            "prediction_error"
        ] = (
            predicted_utility
            - pd.to_numeric(
                validation[
                    MARKET_TARGET
                ],
                errors="raise",
            ).to_numpy(
                dtype=float
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
            "train_risk_on_fraction": float(
                train[
                    MARKET_LABEL
                ].mean()
            ),
            "validation_risk_on_fraction": float(
                validation[
                    MARKET_LABEL
                ].mean()
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
            **{
                f"regression_{key}": (
                    value
                )
                for key, value
                in reg.items()
            },
            **{
                f"classification_{key}": (
                    value
                )
                for key, value
                in cls.items()
            },
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
            "threshold=0 "
            "model=frozen-hgb-market-risk"
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
        "median_fold_spearman_ic": float(
            metrics[
                "regression_spearman_ic"
            ].median()
        ),
        "mean_fold_spearman_ic": float(
            metrics[
                "regression_spearman_ic"
            ].mean()
        ),
        "median_fold_balanced_accuracy": float(
            metrics[
                "classification_balanced_accuracy"
            ].median()
        ),
        "mean_fold_balanced_accuracy": float(
            metrics[
                "classification_balanced_accuracy"
            ].mean()
        ),
        "median_fold_mcc": float(
            metrics[
                "classification_mcc"
            ].median()
        ),
        "mean_fold_mcc": float(
            metrics[
                "classification_mcc"
            ].mean()
        ),
        "median_fold_minimum_class_recall": float(
            metrics[
                "classification_minimum_class_recall"
            ].median()
        ),
        "median_fold_risk_off_recall": float(
            metrics[
                "classification_risk_off_recall"
            ].median()
        ),
        "median_fold_risk_on_recall": float(
            metrics[
                "classification_risk_on_recall"
            ].median()
        ),
        "median_fold_mae": float(
            metrics[
                "regression_mae"
            ].median()
        ),
        "median_fold_rmse": float(
            metrics[
                "regression_rmse"
            ].median()
        ),
        "median_fold_predicted_positive_fraction": float(
            metrics[
                "regression_predicted_positive_fraction"
            ].median()
        ),
        "median_fold_actual_positive_fraction": float(
            metrics[
                "regression_actual_positive_fraction"
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
            "V16 predictive summary must contain exactly one row"
        )

    row = summary.iloc[
        0
    ]

    gates = contract[
        "risk_predictive_quality_gates"
    ]

    checks = [
        (
            "gate_median_fold_spearman_ic_gt_010",
            float(
                row[
                    "median_fold_spearman_ic"
                ]
            )
            > float(
                gates[
                    "median_fold_spearman_ic_gt"
                ]
            ),
        ),
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
            "median_fold_spearman_ic": float(
                row[
                    "median_fold_spearman_ic"
                ]
            ),
            "median_fold_balanced_accuracy": float(
                row[
                    "median_fold_balanced_accuracy"
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
            "median_fold_risk_off_recall": float(
                row[
                    "median_fold_risk_off_recall"
                ]
            ),
            "median_fold_risk_on_recall": float(
                row[
                    "median_fold_risk_on_recall"
                ]
            ),
        }
    ])

    result = {
        "target_count": 1,
        "diagnostic_class_count": 2,
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
            "Unexpected V16 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V16 Phase 1 holdout differs from Phase 2"
        )

    target = contract.get(
        "market_risk_target",
        {},
    )

    if (
        target.get(
            "primary"
        )
        != MARKET_TARGET
    ):
        raise RuntimeError(
            "Unexpected V16 market-risk target"
        )

    if (
        target.get(
            "binary_diagnostic"
        )
        != MARKET_LABEL
    ):
        raise RuntimeError(
            "Unexpected V16 market-risk diagnostic label"
        )

    if (
        target.get(
            "risk_on_definition"
        )
        != (
            "market_median_path_utility_net25_7d > 0"
        )
    ):
        raise RuntimeError(
            "Unexpected V16 risk-on definition"
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
        "secondary_models": [],
    }

    if (
        contract.get(
            "market_risk_model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V16 risk model contract differs from preregistration"
        )

    expected_walk = {
        "purge_days": (
            PURGE_DAYS
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
    }

    if (
        contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V16 walk-forward contract differs from preregistration"
        )

    constraints = contract.get(
        "research_constraints",
        {},
    )

    for key in (
        "v15_ranker_is_frozen_input",
        "risk_gate_is_separate_model",
        "risk_gate_zero_threshold_fixed_before_fit",
        "no_manual_volatility_threshold",
        "no_manual_drawdown_threshold",
        "risk_features_fixed_before_fit",
        "risk_model_family_fixed_before_fit",
        "risk_predictive_gates_required_before_portfolio_simulation",
        "portfolio_gates_carried_forward_unchanged_from_v15",
        "no_post_result_threshold_search",
        "no_secondary_model_search",
        "no_hyperparameter_search",
        "future_holdout_must_remain_untouched_until_candidate_freeze",
    ):
        if (
            constraints.get(
                key
            )
            is not True
        ):
            raise RuntimeError(
                "V16 Phase 1 research constraint failed: "
                f"{key}"
            )

    if (
        constraints.get(
            "v15_ranker_refit_for_v16"
        )
        is not False
    ):
        raise RuntimeError(
            "V16 must not refit the V15 ranking engine"
        )

    features = list(
        contract[
            "risk_feature_columns"
        ]
    )

    if len(
        features
    ) != 18:
        raise RuntimeError(
            "V16 expected exactly 18 preregistered risk features"
        )

    if (
        int(
            contract[
                "risk_feature_design"
            ][
                "risk_feature_count"
            ]
        )
        != 18
    ):
        raise RuntimeError(
            "V16 risk feature count contract is inconsistent"
        )

    gates = contract.get(
        "risk_predictive_quality_gates",
        {},
    )

    expected_gates = {
        "median_fold_spearman_ic_gt": 0.10,
        "median_fold_balanced_accuracy_gt": 0.55,
        "median_fold_mcc_gt": 0.0,
        "median_fold_minimum_class_recall_gt": 0.50,
        "all_gates_required_before_portfolio_simulation": True,
    }

    if (
        gates
        != expected_gates
    ):
        raise RuntimeError(
            "V16 risk predictive gates differ from preregistration"
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

    data = pd.read_parquet(
        phase1_root
        / "market_risk_dataset.parquet"
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
        "V16 Phase 1 market-risk dataset",
    )

    required = {
        "timestamp_utc",
        "target_endpoint_utc_7d",
        "eligible_asset_count",
        MARKET_TARGET,
        MARKET_LABEL,
        *features,
    }

    missing = (
        required
        - set(
            data.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V16 Phase 1 dataset missing columns: "
            f"{sorted(missing)}"
        )

    finite_frame = data[
        [
            *features,
            MARKET_TARGET,
        ]
    ].replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    )

    if (
        finite_frame
        .isna()
        .any()
        .any()
    ):
        raise RuntimeError(
            "V16 Phase 1 dataset contains non-finite risk inputs or target"
        )

    if (
        data[
            MARKET_LABEL
        ].nunique()
        != 2
    ):
        raise RuntimeError(
            "V16 Phase 1 dataset must contain both risk classes"
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
        / "market_risk_predictions.parquet"
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
            "purged_7d_market_risk_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "market_target": (
            MARKET_TARGET
        ),
        "risk_label": (
            MARKET_LABEL
        ),
        "risk_threshold": 0.0,
        "model": (
            PRIMARY_MODEL
        ),
        "risk_feature_count": int(
            len(
                features
            )
        ),
        "purge_days": (
            PURGE_DAYS
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
        "predicted_risk_on_count": int(
            predictions[
                "predicted_market_risk_on"
            ].sum()
        ),
        "predicted_risk_off_count": int(
            (
                predictions[
                    "predicted_market_risk_on"
                ]
                == 0
            ).sum()
        ),
        "actual_risk_on_count": int(
            predictions[
                MARKET_LABEL
            ].sum()
        ),
        "actual_risk_off_count": int(
            (
                predictions[
                    MARKET_LABEL
                ]
                == 0
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
            "market_risk_predictions": str(
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
            "shared_crypto_v15_modified": False,
            "v15_ranker_refit": False,
            "v15_portfolio_resimulated": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "hyperparameters_tuned": False,
            "risk_threshold_changed": False,
            "threshold_search_performed": False,
            "predictive_gate_lowered": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Combine V16 risk predictions with the frozen V15 out-of-sample "
            "ranking predictions only if all four risk predictive gates pass. "
            "Otherwise preserve V16 as failed predictive evidence and do not "
            "simulate the risk-gated portfolio."
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
