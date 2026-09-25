"""Shared Crypto V15 Cross-Sectional Rank Target Phase 2.

Fits only the preregistered V15 HistGradientBoostingRegressor to the within-day
percentile rank of exact seven-day path utility.

Only the supervised target differs from V14. The 22 features, model family,
hyperparameters, seven-day purge, walk-forward folds, September 1, 2026
holdout, and all four predictive ranking gates remain unchanged.

Predictive evaluation remains economically grounded:
* Spearman IC compares predicted rank score with raw path utility.
* top-3 excess compares the raw path utility of predicted top-3 assets with the
  contemporaneous eligible-universe mean.

All four gates must pass before any portfolio simulation.
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


RESEARCH_VERSION = "shared_crypto_v15_cross_sectional_rank"
PHASE1_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase2"
)

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

RANK_TARGET = "target_path_utility_percentile_rank_7d"
RAW_TARGET = "path_utility_net25_7d"
TERMINAL_TARGET = "net_terminal_return_7d_25bps"
ADVERSE_TARGET = "maximum_adverse_close_return_7d"
FAVORABLE_TARGET = "maximum_favorable_close_return_7d"

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
MIN_CROSS_SECTION_ASSETS = 10


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
        frame["timestamp_utc"],
        utc=True,
    )
    if (timestamps >= HOLDOUT).any():
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
            "Cannot construct V15 folds from empty timestamps"
        )

    first = unique_dates.iloc[0].floor("D")
    last = unique_dates.iloc[-1]

    starts = []
    cursor = first + pd.to_timedelta(
        MIN_TRAIN_DAYS,
        unit="D",
    )

    while cursor <= last:
        starts.append(cursor)
        cursor += pd.to_timedelta(
            VALIDATION_DAYS,
            unit="D",
        )

    starts = starts[-MAX_FOLDS:]
    folds = []

    for start in starts:
        end = min(
            start + pd.to_timedelta(
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
            "No valid purged V15 folds were constructed"
        )

    return folds


def daily_ranking_metrics(
    validation: pd.DataFrame,
    predicted: np.ndarray,
) -> pd.DataFrame:
    scored = validation[
        [
            "timestamp_utc",
            "product_id",
            RAW_TARGET,
            RANK_TARGET,
        ]
    ].copy()

    scored[
        "predicted_rank_score"
    ] = np.asarray(
        predicted,
        dtype=float,
    )

    rows = []

    for timestamp, day in scored.groupby(
        "timestamp_utc",
        sort=True,
    ):
        if (
            day["product_id"].nunique()
            < MIN_CROSS_SECTION_ASSETS
        ):
            raise RuntimeError(
                "V15 validation day violates minimum cross-section breadth"
            )

        actual_raw = pd.to_numeric(
            day[RAW_TARGET],
            errors="raise",
        )
        predicted_day = pd.to_numeric(
            day["predicted_rank_score"],
            errors="raise",
        )

        if (
            actual_raw.nunique() > 1
            and predicted_day.nunique() > 1
        ):
            ic = float(
                predicted_day.corr(
                    actual_raw,
                    method="spearman",
                )
            )
        else:
            ic = np.nan

        ordered = day.sort_values(
            [
                "predicted_rank_score",
                "product_id",
            ],
            ascending=[
                False,
                True,
            ],
        )

        top3 = ordered.head(3)

        universe_mean = float(
            actual_raw.mean()
        )
        top3_mean = float(
            pd.to_numeric(
                top3[RAW_TARGET],
                errors="raise",
            ).mean()
        )

        rows.append({
            "timestamp_utc": timestamp,
            "asset_count": int(
                len(day)
            ),
            "spearman_ic": ic,
            "top3_actual_path_utility": top3_mean,
            "universe_actual_path_utility": universe_mean,
            "top3_target_utility_excess_vs_universe": float(
                top3_mean - universe_mean
            ),
            "mean_predicted_rank_score": float(
                predicted_day.mean()
            ),
            "maximum_predicted_rank_score": float(
                predicted_day.max()
            ),
        })

    return pd.DataFrame(
        rows
    )


def fold_ranking_metrics(
    daily: pd.DataFrame,
) -> dict:
    valid_ic = pd.to_numeric(
        daily["spearman_ic"],
        errors="coerce",
    ).dropna()

    if valid_ic.empty:
        raise RuntimeError(
            "V15 fold has no valid daily Spearman IC observations"
        )

    excess = pd.to_numeric(
        daily[
            "top3_target_utility_excess_vs_universe"
        ],
        errors="raise",
    )

    return {
        "daily_metric_days": int(
            len(daily)
        ),
        "valid_ic_days": int(
            len(valid_ic)
        ),
        "median_daily_spearman_ic": float(
            valid_ic.median()
        ),
        "mean_daily_spearman_ic": float(
            valid_ic.mean()
        ),
        "positive_ic_day_fraction": float(
            (
                valid_ic > 0.0
            ).mean()
        ),
        "mean_top3_target_utility_excess_vs_universe": float(
            excess.mean()
        ),
        "median_top3_target_utility_excess_vs_universe": float(
            excess.median()
        ),
        "positive_top3_excess_day_fraction": float(
            (
                excess > 0.0
            ).mean()
        ),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    prediction_frames = []
    daily_frames = []
    fold_rows = []

    for fold in make_folds(
        data["timestamp_utc"]
    ):
        train = data.loc[
            fold["train"]
        ].copy()
        validation = data.loc[
            fold["validation"]
        ].copy()

        if train.empty or validation.empty:
            raise RuntimeError(
                f"{fold['fold_id']} contains an empty partition"
            )

        if (
            train["timestamp_utc"].max()
            >= fold["train_end"]
        ):
            raise RuntimeError(
                f"{fold['fold_id']} violates the seven-day purge"
            )

        endpoint = pd.to_datetime(
            train[
                "target_endpoint_utc_7d"
            ],
            utc=True,
        )

        if (
            endpoint.max()
            >= validation[
                "timestamp_utc"
            ].min()
        ):
            raise RuntimeError(
                f"{fold['fold_id']} target path leaks into validation"
            )

        if (
            validation["timestamp_utc"].max()
            >= HOLDOUT
        ):
            raise RuntimeError(
                f"{fold['fold_id']} reaches the future holdout"
            )

        model = clone(
            model_template()
        )

        model.fit(
            train[features],
            train[RANK_TARGET],
        )

        predicted = np.asarray(
            model.predict(
                validation[features]
            ),
            dtype=float,
        )

        if not np.isfinite(
            predicted
        ).all():
            raise RuntimeError(
                f"{fold['fold_id']} produced non-finite predictions"
            )

        out = validation[
            [
                "timestamp_utc",
                "product_id",
                RANK_TARGET,
                RAW_TARGET,
                TERMINAL_TARGET,
                ADVERSE_TARGET,
                FAVORABLE_TARGET,
                "eligible_asset_count",
                "target_endpoint_utc_7d",
            ]
        ].copy()

        out["fold_id"] = (
            fold["fold_id"]
        )
        out[
            "predicted_rank_score"
        ] = predicted
        out[
            "predicted_cross_sectional_rank"
        ] = (
            out.groupby(
                "timestamp_utc"
            )[
                "predicted_rank_score"
            ]
            .rank(
                method="first",
                ascending=False,
            )
        )
        out[
            "actual_cross_sectional_rank"
        ] = (
            out.groupby(
                "timestamp_utc"
            )[
                RAW_TARGET
            ]
            .rank(
                method="average",
                ascending=False,
            )
        )

        daily = daily_ranking_metrics(
            validation,
            predicted,
        )
        daily["fold_id"] = (
            fold["fold_id"]
        )

        metrics = fold_ranking_metrics(
            daily
        )

        fold_rows.append({
            "fold_id": (
                fold["fold_id"]
            ),
            "train_rows": int(
                len(train)
            ),
            "validation_rows": int(
                len(validation)
            ),
            "train_days": int(
                train[
                    "timestamp_utc"
                ].nunique()
            ),
            "validation_days": int(
                validation[
                    "timestamp_utc"
                ].nunique()
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
            **metrics,
        })

        prediction_frames.append(
            out
        )
        daily_frames.append(
            daily
        )

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train_rows={len(train):,} "
            f"validation_rows={len(validation):,} "
            f"validation_days={validation['timestamp_utc'].nunique():,} "
            f"features={len(features)} "
            "purge=7d "
            "target=within-day-percentile-rank "
            "model=frozen-hgb"
        )

    return (
        pd.concat(
            prediction_frames,
            ignore_index=True,
        ),
        pd.concat(
            daily_frames,
            ignore_index=True,
        ),
        pd.DataFrame(
            fold_rows
        ),
    )


def summarize(
    fold_metrics: pd.DataFrame,
) -> pd.DataFrame:
    row = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "fold_count": int(
            fold_metrics[
                "fold_id"
            ].nunique()
        ),
        "median_fold_daily_spearman_ic": float(
            fold_metrics[
                "median_daily_spearman_ic"
            ].median()
        ),
        "mean_fold_daily_spearman_ic": float(
            fold_metrics[
                "median_daily_spearman_ic"
            ].mean()
        ),
        "median_fold_positive_ic_day_fraction": float(
            fold_metrics[
                "positive_ic_day_fraction"
            ].median()
        ),
        "median_fold_top3_target_utility_excess_vs_universe": float(
            fold_metrics[
                "mean_top3_target_utility_excess_vs_universe"
            ].median()
        ),
        "mean_fold_top3_target_utility_excess_vs_universe": float(
            fold_metrics[
                "mean_top3_target_utility_excess_vs_universe"
            ].mean()
        ),
        "positive_fold_top3_target_utility_excess_fraction": float(
            (
                fold_metrics[
                    "mean_top3_target_utility_excess_vs_universe"
                ]
                > 0.0
            ).mean()
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
    if len(summary) != 1:
        raise RuntimeError(
            "V15 predictive summary must contain exactly one row"
        )

    row = summary.iloc[0]
    gates = contract[
        "predictive_quality_gates"
    ]

    checks = [
        (
            "gate_median_fold_daily_spearman_ic_gt_005",
            float(
                row[
                    "median_fold_daily_spearman_ic"
                ]
            )
            > float(
                gates[
                    "median_fold_daily_spearman_ic_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_positive_ic_day_fraction_gt_52pct",
            float(
                row[
                    "median_fold_positive_ic_day_fraction"
                ]
            )
            > float(
                gates[
                    "median_fold_positive_ic_day_fraction_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_top3_target_utility_excess_vs_universe_gt_zero",
            float(
                row[
                    "median_fold_top3_target_utility_excess_vs_universe"
                ]
            )
            > float(
                gates[
                    "median_fold_top3_target_utility_excess_vs_universe_gt"
                ]
            ),
        ),
        (
            "gate_positive_fold_top3_target_utility_excess_fraction_gte_75pct",
            float(
                row[
                    "positive_fold_top3_target_utility_excess_fraction"
                ]
            )
            >= float(
                gates[
                    "positive_fold_top3_target_utility_excess_fraction_gte"
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
        passed == total
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
        "median_fold_daily_spearman_ic": float(
            row[
                "median_fold_daily_spearman_ic"
            ]
        ),
        "median_fold_positive_ic_day_fraction": float(
            row[
                "median_fold_positive_ic_day_fraction"
            ]
        ),
        "median_fold_top3_target_utility_excess_vs_universe": float(
            row[
                "median_fold_top3_target_utility_excess_vs_universe"
            ]
        ),
        "positive_fold_top3_target_utility_excess_fraction": float(
            row[
                "positive_fold_top3_target_utility_excess_fraction"
            ]
        ),
    }])

    result = {
        "target_count": 1,
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
            "Unexpected V15 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V15 Phase 1 holdout differs from Phase 2"
        )

    learning_target = contract.get(
        "learning_target",
        {},
    )

    if (
        learning_target.get(
            "primary"
        )
        != RANK_TARGET
    ):
        raise RuntimeError(
            "Unexpected V15 learning target"
        )

    if (
        learning_target.get(
            "raw_economic_target_retained_for_evaluation"
        )
        != RAW_TARGET
    ):
        raise RuntimeError(
            "Unexpected V15 economic evaluation target"
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
            "model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V15 model contract differs from frozen V14 specification"
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
        "minimum_cross_section_assets": (
            MIN_CROSS_SECTION_ASSETS
        ),
    }

    if (
        contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V15 walk-forward contract differs from V14"
        )

    constraints = contract.get(
        "research_constraints",
        {},
    )

    for key in (
        "only_learning_target_changed_from_v14",
        "same_22_features_as_v14",
        "same_model_specification_as_v14",
        "same_walk_forward_protocol_as_v14",
        "same_predictive_gates_as_v14",
        "rank_target_fixed_before_fit",
        "no_model_family_search",
        "no_secondary_model_search",
        "no_hyperparameter_search",
        "no_post_result_threshold_search",
        "predictive_gates_required_before_portfolio_simulation",
        "future_holdout_must_remain_untouched_until_candidate_freeze",
    ):
        if constraints.get(
            key
        ) is not True:
            raise RuntimeError(
                "V15 Phase 1 research constraint failed: "
                f"{key}"
            )

    features = list(
        contract[
            "model_feature_columns"
        ]
    )

    if len(features) != 22:
        raise RuntimeError(
            "V15 expected exactly 22 model features"
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
        / "asset_cross_sectional_rank_dataset.parquet"
    ).copy()

    data["timestamp_utc"] = pd.to_datetime(
        data["timestamp_utc"],
        utc=True,
    )

    validate_pre_holdout(
        data,
        "V15 Phase 1 dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        RANK_TARGET,
        RAW_TARGET,
        TERMINAL_TARGET,
        ADVERSE_TARGET,
        FAVORABLE_TARGET,
        "eligible_asset_count",
        "target_endpoint_utc_7d",
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
            "V15 Phase 1 dataset missing columns: "
            f"{sorted(missing)}"
        )

    if (
        data[
            features
            + [
                RANK_TARGET,
                RAW_TARGET,
            ]
        ].replace(
            [
                np.inf,
                -np.inf,
            ],
            np.nan,
        ).isna().any().any()
    ):
        raise RuntimeError(
            "V15 Phase 1 dataset contains non-finite inputs or targets"
        )

    rank_target = pd.to_numeric(
        data[RANK_TARGET],
        errors="raise",
    )

    if (
        (rank_target <= 0.0).any()
        or (rank_target > 1.0).any()
    ):
        raise RuntimeError(
            "V15 rank target must remain in (0, 1]"
        )

    predictions, daily, fold_metrics = (
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
        / "asset_predictions.parquet"
    )
    daily_path = (
        output_root
        / "daily_ranking_metrics.csv"
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
    daily.to_csv(
        daily_path,
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
            "purged_7d_cross_sectional_rank_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "learning_target": (
            RANK_TARGET
        ),
        "economic_evaluation_target": (
            RAW_TARGET
        ),
        "model": (
            PRIMARY_MODEL
        ),
        "model_feature_count": int(
            len(features)
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
            len(data)
        ),
        "input_products": int(
            data[
                "product_id"
            ].nunique()
        ),
        "input_days": int(
            data[
                "timestamp_utc"
            ].nunique()
        ),
        "prediction_rows": int(
            len(predictions)
        ),
        "prediction_days": int(
            predictions[
                "timestamp_utc"
            ].nunique()
        ),
        "fold_count": int(
            fold_metrics[
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
            "asset_predictions": str(
                prediction_path
            ),
            "daily_ranking_metrics": str(
                daily_path
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
            "shared_crypto_v14_modified": False,
            "shared_crypto_v13_modified": False,
            "shared_crypto_v12_modified": False,
            "shared_crypto_v11_modified": False,
            "shared_crypto_v10_modified": False,
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "hyperparameters_tuned": False,
            "predictive_gate_lowered": False,
            "threshold_search_performed": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the frozen non-overlapping seven-day V15 portfolio policy only "
            "if predictive_gate_status is ALLOW_POLICY_SIMULATION. Otherwise "
            "preserve V15 as failed predictive evidence and do not simulate "
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
