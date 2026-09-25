"""Shared Crypto V9 Deviation Classifier Phase 2.

Fits only the preregistered logistic-regression model independently to the two
exact 72-hour binary targets:

  * ALT beats BTC after the fixed 25 bps deviation hurdle.
  * CASH beats BTC after the fixed 25 bps deviation hurdle.

Training uses expanding chronological folds with a full 72-hour purge.  This
phase evaluates predictive quality only.  Portfolio simulation is prohibited
unless every preregistered predictive gate passes for both targets.

The future holdout remains untouched.  This phase cannot search model families,
tune thresholds, freeze a model, modify paper state, or place brokerage orders.
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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v9_deviation_classifier"
PHASE1_ROOT = Path("data/model/shared_crypto_v9_deviation_classifier/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v9_deviation_classifier/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

TARGETS = (
    "alt_beats_btc_net25_72h",
    "cash_beats_btc_net25_72h",
)
PRIMARY_MODEL = "logistic_regression"
LOGISTIC_C = 0.5
PROBABILITY_THRESHOLD = 0.50
PURGE = timedelta(hours=72)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6


def model_template() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(
            penalty="l2",
            C=LOGISTIC_C,
            solver="lbfgs",
            max_iter=2000,
            class_weight=None,
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


def _read(path: Path, source: str) -> pd.DataFrame:
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
            "Cannot construct V9 folds from empty timestamps"
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
        train = timestamps < train_end
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
            "No valid purged V9 folds were constructed"
        )
    return folds


def classification_metrics(
    actual: pd.Series,
    probability: np.ndarray,
    train_prevalence: float,
) -> dict[str, float]:
    actual_values = np.asarray(
        actual,
        dtype=int,
    )
    probability_values = np.asarray(
        probability,
        dtype=float,
    )

    if not (
        (probability_values >= 0.0).all()
        and (probability_values <= 1.0).all()
    ):
        raise RuntimeError(
            "Classifier returned invalid probabilities"
        )

    predicted = (
        probability_values
        >= PROBABILITY_THRESHOLD
    ).astype(int)

    baseline_probability = np.full(
        len(actual_values),
        float(train_prevalence),
        dtype=float,
    )
    baseline_prediction = np.full(
        len(actual_values),
        int(
            float(train_prevalence)
            >= PROBABILITY_THRESHOLD
        ),
        dtype=int,
    )

    brier = float(
        brier_score_loss(
            actual_values,
            probability_values,
        )
    )
    baseline_brier = float(
        brier_score_loss(
            actual_values,
            baseline_probability,
        )
    )

    model_log_loss = float(
        log_loss(
            actual_values,
            probability_values,
            labels=[0, 1],
        )
    )
    baseline_log_loss = float(
        log_loss(
            actual_values,
            baseline_probability,
            labels=[0, 1],
        )
    )

    roc_auc = (
        float(
            roc_auc_score(
                actual_values,
                probability_values,
            )
        )
        if len(
            np.unique(actual_values)
        ) == 2
        else 0.5
    )

    balanced_accuracy = float(
        balanced_accuracy_score(
            actual_values,
            predicted,
        )
    )
    baseline_balanced_accuracy = float(
        balanced_accuracy_score(
            actual_values,
            baseline_prediction,
        )
    )

    positive_mask = predicted == 1
    actual_positive = actual_values == 1

    return {
        "roc_auc": roc_auc,
        "balanced_accuracy": balanced_accuracy,
        "baseline_balanced_accuracy": (
            baseline_balanced_accuracy
        ),
        "brier_score": brier,
        "baseline_brier_score": (
            baseline_brier
        ),
        "brier_improvement_vs_train_prevalence": float(
            baseline_brier - brier
        ),
        "log_loss": model_log_loss,
        "baseline_log_loss": (
            baseline_log_loss
        ),
        "log_loss_improvement_vs_train_prevalence": float(
            baseline_log_loss - model_log_loss
        ),
        "actual_positive_fraction": float(
            actual_positive.mean()
        ),
        "predicted_positive_fraction": float(
            positive_mask.mean()
        ),
        "precision_when_predicted_positive": (
            float(
                actual_positive[
                    positive_mask
                ].mean()
            )
            if positive_mask.any()
            else 0.0
        ),
        "mean_predicted_probability": float(
            probability_values.mean()
        ),
        "train_prevalence": float(
            train_prevalence
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
        "alt_beats_btc_net25_72h",
        "cash_beats_btc_net25_72h",
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

        out = validation[
            base_columns
        ].copy()
        out["fold_id"] = fold["fold_id"]

        for target in TARGETS:
            train_target = pd.to_numeric(
                train[target],
                errors="raise",
            ).astype(int)
            validation_target = pd.to_numeric(
                validation[target],
                errors="raise",
            ).astype(int)

            if set(
                train_target.unique()
            ) != {0, 1}:
                raise RuntimeError(
                    f"{fold['fold_id']} {target} training data lacks both classes"
                )

            model = clone(
                model_template()
            ).fit(
                train[features],
                train_target,
            )

            probabilities = np.asarray(
                model.predict_proba(
                    validation[features]
                )[:, 1],
                dtype=float,
            )

            if (
                len(probabilities)
                != len(validation)
            ):
                raise RuntimeError(
                    f"{fold['fold_id']} {target} returned wrong probability count"
                )
            if not np.isfinite(
                probabilities
            ).all():
                raise RuntimeError(
                    f"{fold['fold_id']} {target} returned non-finite probabilities"
                )

            out[
                f"probability_{target}_{PRIMARY_MODEL}"
            ] = probabilities

            train_prevalence = float(
                train_target.mean()
            )

            metric_rows.append({
                "fold_id": fold["fold_id"],
                "target": target,
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
                    probabilities,
                    train_prevalence,
                ),
            })

        prediction_frames.append(out)

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            "purge=72h targets=2 logistic-only"
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
            ] = float(
                values.mean()
            )
            row[
                f"median_{column}"
            ] = float(
                values.median()
            )
        rows.append(row)

    return pd.DataFrame(rows)


def evaluate_predictive_gates(
    summary: pd.DataFrame,
    contract: dict,
) -> tuple[pd.DataFrame, dict]:
    registered = contract[
        "predictive_quality_gates"
    ]

    auc_hurdle = float(
        registered[
            "median_roc_auc_each_target_gt"
        ]
    )
    balanced_hurdle = float(
        registered[
            "median_balanced_accuracy_each_target_gt"
        ]
    )
    brier_hurdle = float(
        registered[
            "median_brier_improvement_vs_train_prevalence_each_target_gt"
        ]
    )
    log_loss_hurdle = float(
        registered[
            "median_log_loss_improvement_vs_train_prevalence_each_target_gt"
        ]
    )

    rows = []

    for target in TARGETS:
        match = summary[
            summary["target"] == target
        ]
        if len(match) != 1:
            raise RuntimeError(
                f"Missing unique V9 predictive summary for {target}"
            )

        row = match.iloc[0]

        auc_pass = bool(
            row[
                "median_roc_auc"
            ] > auc_hurdle
        )
        balanced_pass = bool(
            row[
                "median_balanced_accuracy"
            ] > balanced_hurdle
        )
        brier_pass = bool(
            row[
                "median_brier_improvement_vs_train_prevalence"
            ] > brier_hurdle
        )
        log_loss_pass = bool(
            row[
                "median_log_loss_improvement_vs_train_prevalence"
            ] > log_loss_hurdle
        )

        rows.append({
            "target": target,
            "gate_median_roc_auc_gt_52pct": auc_pass,
            "gate_median_balanced_accuracy_gt_52pct": balanced_pass,
            "gate_median_brier_improvement_gt_zero": brier_pass,
            "gate_median_log_loss_improvement_gt_zero": log_loss_pass,
            "passed_gate_count": int(
                auc_pass
                + balanced_pass
                + brier_pass
                + log_loss_pass
            ),
            "total_gate_count": 4,
            "median_roc_auc": float(
                row["median_roc_auc"]
            ),
            "median_balanced_accuracy": float(
                row[
                    "median_balanced_accuracy"
                ]
            ),
            "median_brier_improvement_vs_train_prevalence": float(
                row[
                    "median_brier_improvement_vs_train_prevalence"
                ]
            ),
            "median_log_loss_improvement_vs_train_prevalence": float(
                row[
                    "median_log_loss_improvement_vs_train_prevalence"
                ]
            ),
        })

    detail = pd.DataFrame(rows)

    all_pass = bool(
        (
            detail["passed_gate_count"]
            == detail["total_gate_count"]
        ).all()
    )

    result = {
        "target_count": int(
            len(detail)
        ),
        "passed_target_count": int(
            (
                detail["passed_gate_count"]
                == detail["total_gate_count"]
            ).sum()
        ),
        "total_predictive_gate_count": int(
            detail[
                "total_gate_count"
            ].sum()
        ),
        "passed_predictive_gate_count": int(
            detail[
                "passed_gate_count"
            ].sum()
        ),
        "all_predictive_gates_pass": all_pass,
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
            "Unexpected V9 Phase 1 research version"
        )
    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V9 Phase 1 holdout boundary differs from Phase 2"
        )

    model = contract["model"]
    if (
        model.get("primary")
        != PRIMARY_MODEL
    ):
        raise RuntimeError(
            "V9 Phase 1 primary model differs from Phase 2"
        )
    if (
        float(model.get("C"))
        != LOGISTIC_C
    ):
        raise RuntimeError(
            "V9 Phase 1 logistic C differs from Phase 2"
        )
    if (
        model.get("secondary_models")
        != []
    ):
        raise RuntimeError(
            "V9 Phase 2 forbids secondary model search"
        )

    predictive_policy = contract[
        "predictive_policy"
    ]
    if (
        float(
            predictive_policy[
                "fixed_probability_threshold"
            ]
        )
        != PROBABILITY_THRESHOLD
    ):
        raise RuntimeError(
            "V9 Phase 1 probability threshold differs from Phase 2"
        )
    if bool(
        predictive_policy[
            "threshold_search"
        ]
    ):
        raise RuntimeError(
            "V9 Phase 2 forbids threshold search"
        )

    data = _read(
        (
            phase1_root
            / "daily_classification_dataset.parquet"
        ),
        "V9 daily classification dataset",
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
            f"V9 Phase 1 dataset missing columns: {sorted(missing)}"
        )

    forbidden = (
        set(TARGETS)
        & set(features)
    )
    if forbidden:
        raise RuntimeError(
            f"V9 labels leaked into model features: {sorted(forbidden)}"
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
            "purged_72h_btc_deviation_logistic_predictive_adjudication"
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
        "logistic_C": LOGISTIC_C,
        "probability_threshold": (
            PROBABILITY_THRESHOLD
        ),
        "secondary_model_count": 0,
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
            "shared_crypto_v8_modified": False,
            "shared_crypto_v7_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "probability_threshold_tuned": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the single frozen non-overlapping 72-hour portfolio policy "
            "only if predictive_gate_status is ALLOW_POLICY_SIMULATION.  "
            "Otherwise preserve V9 as failed predictive evidence and do not "
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
