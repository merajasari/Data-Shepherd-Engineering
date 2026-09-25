"""Shared Crypto V10 Regime Ranker Phase 2.

Fits only the preregistered standardized LinearSVC multiclass model to the
single exact 72-hour target identifying the best cost-aware sleeve among BTC,
ALT, and CASH.

Training uses expanding chronological folds with a full 72-hour purge.
Predictive quality is adjudicated before any portfolio simulation.  The future
holdout remains untouched.  This phase cannot search model families, tune
confidence thresholds, calibrate probabilities, freeze a model, modify paper
state, or place brokerage orders.
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


RESEARCH_VERSION = "shared_crypto_v10_regime_ranker"
PHASE1_ROOT = Path(
    "data/model/shared_crypto_v10_regime_ranker/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v10_regime_ranker/phase2"
)
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

TARGET = "best_sleeve_net25_72h"
CLASSES = ("BTC", "ALT", "CASH")
PRIMARY_MODEL = "linear_svc"
LINEAR_SVC_C = 0.25
PURGE = timedelta(hours=72)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6


def model_template() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", LinearSVC(
            C=LINEAR_SVC_C,
            loss="squared_hinge",
            penalty="l2",
            class_weight=None,
            dual="auto",
            max_iter=10000,
            multi_class="ovr",
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

    frame = pd.read_parquet(
        path
    ).copy()
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
            "Cannot construct V10 folds from empty timestamps"
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
            "No valid purged V10 folds were constructed"
        )

    return folds


def classification_metrics(
    actual: pd.Series,
    predicted: np.ndarray,
    train_target: pd.Series,
) -> dict[str, float]:
    actual_values = np.asarray(
        actual,
        dtype=object,
    )
    predicted_values = np.asarray(
        predicted,
        dtype=object,
    )
    train_values = np.asarray(
        train_target,
        dtype=object,
    )

    if set(
        np.unique(actual_values)
    ) - set(CLASSES):
        raise RuntimeError(
            "Unexpected V10 validation class"
        )
    if set(
        np.unique(predicted_values)
    ) - set(CLASSES):
        raise RuntimeError(
            "Unexpected V10 predicted class"
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
        labels=list(CLASSES),
        average=None,
        zero_division=0,
    )

    return {
        "accuracy": float(
            accuracy_score(
                actual_values,
                predicted_values,
            )
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
                labels=list(CLASSES),
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
            recalls[
                list(CLASSES).index(
                    "BTC"
                )
            ]
        ),
        "alt_recall": float(
            recalls[
                list(CLASSES).index(
                    "ALT"
                )
            ]
        ),
        "cash_recall": float(
            recalls[
                list(CLASSES).index(
                    "CASH"
                )
            ]
        ),
        "baseline_train_majority_class": (
            train_majority
        ),
        "baseline_train_majority_accuracy": float(
            accuracy_score(
                actual_values,
                baseline_prediction,
            )
        ),
        "accuracy_improvement_vs_train_majority": float(
            accuracy_score(
                actual_values,
                predicted_values,
            )
            - accuracy_score(
                actual_values,
                baseline_prediction,
            )
        ),
        "actual_btc_fraction": float(
            (
                actual_values == "BTC"
            ).mean()
        ),
        "actual_alt_fraction": float(
            (
                actual_values == "ALT"
            ).mean()
        ),
        "actual_cash_fraction": float(
            (
                actual_values == "CASH"
            ).mean()
        ),
        "predicted_btc_fraction": float(
            (
                predicted_values == "BTC"
            ).mean()
        ),
        "predicted_alt_fraction": float(
            (
                predicted_values == "ALT"
            ).mean()
        ),
        "predicted_cash_fraction": float(
            (
                predicted_values == "CASH"
            ).mean()
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
        TARGET,
        "alt_basket_assets",
    ]

    if (
        "oracle_best_deviation_net25_72h"
        in data.columns
    ):
        base_columns.append(
            "oracle_best_deviation_net25_72h"
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

        train_target = train[
            TARGET
        ].astype(str)
        validation_target = validation[
            TARGET
        ].astype(str)

        if set(
            train_target.unique()
        ) != set(CLASSES):
            raise RuntimeError(
                f"{fold['fold_id']} V10 training data lacks all three classes"
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
            dtype=object,
        )

        if (
            len(predicted)
            != len(validation)
        ):
            raise RuntimeError(
                f"{fold['fold_id']} V10 returned wrong prediction count"
            )

        margins = np.asarray(
            model.decision_function(
                validation[features]
            ),
            dtype=float,
        )

        if margins.shape != (
            len(validation),
            len(CLASSES),
        ):
            raise RuntimeError(
                f"{fold['fold_id']} V10 returned unexpected decision-margin shape"
            )

        classes = list(
            model.named_steps[
                "model"
            ].classes_
        )

        out = validation[
            base_columns
        ].copy()
        out["fold_id"] = (
            fold["fold_id"]
        )
        out["predicted_sleeve"] = (
            predicted
        )

        for class_name in CLASSES:
            if class_name not in classes:
                raise RuntimeError(
                    f"{fold['fold_id']} V10 model missing class {class_name}"
                )
            index = classes.index(
                class_name
            )
            out[
                f"decision_margin_{class_name.lower()}"
            ] = margins[:, index]

        metric_rows.append({
            "fold_id": fold["fold_id"],
            "target": TARGET,
            "model_id": PRIMARY_MODEL,
            "train_rows": int(
                len(train)
            ),
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
            **classification_metrics(
                validation_target,
                predicted,
                train_target,
            ),
        })

        prediction_frames.append(
            out
        )

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            "purge=72h classes=3 linear-svc-only"
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
        "target",
        "model_id",
        "train_end_exclusive_utc",
        "validation_start_utc",
        "validation_end_utc",
        "baseline_train_majority_class",
    }

    numeric = [
        column
        for column in metrics.columns
        if column not in identity
    ]

    row = {
        "target": TARGET,
        "model_id": PRIMARY_MODEL,
        "fold_count": int(
            metrics["fold_id"].nunique()
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
            "V10 predictive summary must contain exactly one target row"
        )

    row = summary.iloc[0]
    gates = contract[
        "predictive_quality_gates"
    ]

    balanced_pass = bool(
        row[
            "median_balanced_accuracy"
        ] > float(
            gates[
                "median_balanced_accuracy_gt"
            ]
        )
    )
    macro_f1_pass = bool(
        row[
            "median_macro_f1"
        ] > float(
            gates[
                "median_macro_f1_gt"
            ]
        )
    )
    accuracy_improvement_pass = bool(
        row[
            "median_accuracy_improvement_vs_train_majority"
        ] > float(
            gates[
                "median_accuracy_improvement_vs_train_majority_gt"
            ]
        )
    )
    mcc_pass = bool(
        row[
            "median_multiclass_mcc"
        ] > float(
            gates[
                "median_multiclass_mcc_gt"
            ]
        )
    )
    minimum_recall_pass = bool(
        row[
            "median_minimum_class_recall"
        ] > float(
            gates[
                "median_minimum_class_recall_gt"
            ]
        )
    )

    detail = pd.DataFrame([{
        "target": TARGET,
        "gate_median_balanced_accuracy_gt_36pct": (
            balanced_pass
        ),
        "gate_median_macro_f1_gt_36pct": (
            macro_f1_pass
        ),
        "gate_median_accuracy_improvement_vs_train_majority_gt_zero": (
            accuracy_improvement_pass
        ),
        "gate_median_multiclass_mcc_gt_zero": (
            mcc_pass
        ),
        "gate_median_minimum_class_recall_gt_20pct": (
            minimum_recall_pass
        ),
        "passed_gate_count": int(
            balanced_pass
            + macro_f1_pass
            + accuracy_improvement_pass
            + mcc_pass
            + minimum_recall_pass
        ),
        "total_gate_count": 5,
        "median_balanced_accuracy": float(
            row[
                "median_balanced_accuracy"
            ]
        ),
        "median_macro_f1": float(
            row[
                "median_macro_f1"
            ]
        ),
        "median_accuracy_improvement_vs_train_majority": float(
            row[
                "median_accuracy_improvement_vs_train_majority"
            ]
        ),
        "median_multiclass_mcc": float(
            row[
                "median_multiclass_mcc"
            ]
        ),
        "median_minimum_class_recall": float(
            row[
                "median_minimum_class_recall"
            ]
        ),
    }])

    passed = int(
        detail.iloc[0][
            "passed_gate_count"
        ]
    )
    total = int(
        detail.iloc[0][
            "total_gate_count"
        ]
    )
    all_pass = bool(
        passed == total
    )

    result = {
        "target_count": 1,
        "passed_target_count": int(
            all_pass
        ),
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
        contract.get("research_version")
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V10 Phase 1 research version"
        )
    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V10 Phase 1 holdout boundary differs from Phase 2"
        )

    model = contract[
        "model"
    ]

    if (
        model.get("primary")
        != PRIMARY_MODEL
    ):
        raise RuntimeError(
            "V10 Phase 1 primary model differs from Phase 2"
        )
    if (
        float(
            model.get("C")
        )
        != LINEAR_SVC_C
    ):
        raise RuntimeError(
            "V10 Phase 1 LinearSVC C differs from Phase 2"
        )
    if (
        model.get(
            "secondary_models"
        )
        != []
    ):
        raise RuntimeError(
            "V10 Phase 2 forbids secondary model search"
        )
    if (
        model.get(
            "probability_calibration"
        )
        is not None
    ):
        raise RuntimeError(
            "V10 Phase 2 forbids probability calibration"
        )

    data = _read(
        (
            phase1_root
            / "daily_rank_dataset.parquet"
        ),
        "V10 daily rank dataset",
    )

    features = list(
        contract[
            "regime_feature_columns"
        ]
    )

    missing = (
        set(features)
        | {TARGET}
    ) - set(
        data.columns
    )
    if missing:
        raise RuntimeError(
            f"V10 Phase 1 dataset missing columns: {sorted(missing)}"
        )

    if TARGET in set(features):
        raise RuntimeError(
            "V10 target leaked into model features"
        )

    predictions, metrics = walk_forward(
        data,
        features,
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
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": (
            "purged_72h_direct_sleeve_linear_svc_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "target": TARGET,
        "classes": list(
            CLASSES
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
        "primary_model": (
            PRIMARY_MODEL
        ),
        "linear_svc_C": (
            LINEAR_SVC_C
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
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v7_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "probability_calibrated": False,
            "confidence_threshold_tuned": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the single frozen non-overlapping 72-hour portfolio policy "
            "only if predictive_gate_status is ALLOW_POLICY_SIMULATION. "
            "Otherwise preserve V10 as failed predictive evidence and do not "
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
