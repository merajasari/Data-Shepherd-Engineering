"""Shared Crypto V15 Cross-Sectional Rank Target Phase 1.

V15 is a separately preregistered successor to rejected V14.

V14 changed the research family from sleeve classification to asset-level
cross-sectional ranking and showed positive economic ranking evidence, but it
missed one of four frozen predictive gates:

    median fold daily Spearman IC = 0.0477822083690975
    required > 0.05

V15 does not lower that gate, retune the model, add features, change the
seven-day path-utility definition, or inspect the future holdout.

Instead, V15 changes only the learning target. The model now fits each asset's
within-day percentile rank of the exact same seven-day path utility:

    target_path_utility_percentile_rank_7d

The rationale is objective alignment: the evaluation gates are rank-based, so
the supervised target should emphasize within-day ordering rather than the
highly heteroskedastic raw utility magnitude.

All 22 V14 features, the exact HistGradientBoostingRegressor specification,
seven-day purge, fold protocol, September 1, 2026 holdout, and all four
predictive ranking gates remain unchanged.

This phase builds and preregisters the V15 dataset only. No model is fit and no
portfolio is simulated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v15_cross_sectional_rank"
SOURCE_VERSION = "shared_crypto_v14_path_utility_rank"

SOURCE_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v14_path_utility_rank/phase1"
)
SOURCE_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v14_path_utility_rank/phase3"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

RAW_TARGET = "path_utility_net25_7d"
RANK_TARGET = "target_path_utility_percentile_rank_7d"

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

EXPECTED_PREDICTIVE_GATES = {
    "median_fold_daily_spearman_ic_gt": 0.05,
    "median_fold_positive_ic_day_fraction_gt": 0.52,
    "median_fold_top3_target_utility_excess_vs_universe_gt": 0.0,
    "positive_fold_top3_target_utility_excess_fraction_gte": 0.75,
    "all_gates_required_before_portfolio_simulation": True,
}


def _sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with Path(path).open(
        "rb"
    ) as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


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


def _validate_source_contract(
    source_contract: dict,
) -> list[str]:
    if (
        source_contract.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V15 source contract is not Shared Crypto V14 Phase 1"
        )

    if (
        source_contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V15 source holdout boundary differs from preregistration"
        )

    target = source_contract.get(
        "target",
        {},
    )

    if (
        target.get(
            "primary"
        )
        != RAW_TARGET
    ):
        raise RuntimeError(
            "V15 requires the V14 raw path-utility target"
        )

    if float(
        target.get(
            "primary_round_trip_cost_bps"
        )
    ) != 25.0:
        raise RuntimeError(
            "V15 requires the V14 25-bps target cost"
        )

    expected_model = {
        "primary": PRIMARY_MODEL,
        "learning_rate": MODEL_LEARNING_RATE,
        "max_iter": MODEL_MAX_ITER,
        "max_leaf_nodes": MODEL_MAX_LEAF_NODES,
        "max_depth": None,
        "min_samples_leaf": MODEL_MIN_SAMPLES_LEAF,
        "l2_regularization": MODEL_L2_REGULARIZATION,
        "random_state": RANDOM_STATE,
        "secondary_models": [],
    }

    if (
        source_contract.get(
            "model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V15 requires the exact V14 model specification"
        )

    expected_walk = {
        "purge_days": PURGE_DAYS,
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "minimum_cross_section_assets": MIN_CROSS_SECTION_ASSETS,
    }

    if (
        source_contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V15 requires the exact V14 walk-forward protocol"
        )

    if (
        source_contract.get(
            "predictive_quality_gates"
        )
        != EXPECTED_PREDICTIVE_GATES
    ):
        raise RuntimeError(
            "V15 requires the exact V14 predictive gates"
        )

    features = list(
        source_contract[
            "model_feature_columns"
        ]
    )

    if len(
        features
    ) != 22:
        raise RuntimeError(
            "V15 expected exactly 22 carried-forward features"
        )

    return features


def _validate_v14_rejection(
    adjudication: dict,
) -> None:
    if (
        adjudication.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V15 requires the V14 Phase 3 adjudication"
        )

    if (
        adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V14_PREDICTIVE_HYPOTHESIS"
    ):
        raise RuntimeError(
            "V15 may start only after V14 is immutably rejected"
        )

    if (
        adjudication.get(
            "portfolio_simulation_allowed"
        )
        is not False
    ):
        raise RuntimeError(
            "V14 portfolio simulation must remain blocked"
        )

    if int(
        adjudication.get(
            "passed_predictive_gate_count",
            -1,
        )
    ) != 3:
        raise RuntimeError(
            "Unexpected V14 passed-gate count"
        )

    failed = adjudication.get(
        "failed_gates",
        []
    )

    if failed != [
        "gate_median_fold_daily_spearman_ic_gt_005"
    ]:
        raise RuntimeError(
            "Unexpected V14 failed-gate disposition"
        )


def build_dataset(
    source: pd.DataFrame,
    source_contract: dict,
    v14_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    features = _validate_source_contract(
        source_contract
    )

    _validate_v14_rejection(
        v14_adjudication
    )

    frame = source.copy()

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
        "V15 source dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        RAW_TARGET,
        RANK_TARGET,
        "eligible_asset_count",
        "net_terminal_return_7d_25bps",
        "maximum_adverse_close_return_7d",
        "maximum_favorable_close_return_7d",
        "target_endpoint_utc_7d",
        *features,
    }

    missing = (
        required
        - set(
            frame.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V15 source dataset missing columns: "
            f"{sorted(missing)}"
        )

    expected_rank = (
        frame.groupby(
            "timestamp_utc"
        )[
            RAW_TARGET
        ]
        .rank(
            pct=True
        )
    )

    actual_rank = pd.to_numeric(
        frame[
            RANK_TARGET
        ],
        errors="raise",
    )

    if not np.allclose(
        expected_rank.to_numpy(
            dtype=float
        ),
        actual_rank.to_numpy(
            dtype=float
        ),
        rtol=0.0,
        atol=1e-12,
        equal_nan=False,
    ):
        raise RuntimeError(
            "V15 source rank target does not equal within-day V14 utility percentile rank"
        )

    if (
        (
            actual_rank
            <= 0.0
        ).any()
        or (
            actual_rank
            > 1.0
        ).any()
    ):
        raise RuntimeError(
            "V15 rank target must lie in (0, 1]"
        )

    endpoint = pd.to_datetime(
        frame[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    if (
        endpoint
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V15 source target path reaches the future holdout"
        )

    model_frame = frame[
        [
            "timestamp_utc",
            "product_id",
            *features,
            RANK_TARGET,
            RAW_TARGET,
            "net_terminal_return_7d_25bps",
            "maximum_adverse_close_return_7d",
            "maximum_favorable_close_return_7d",
            "target_top3_path_utility_7d",
            "eligible_asset_count",
            "target_endpoint_utc_7d",
        ]
    ].copy()

    model_frame = model_frame.replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    ).dropna(
        subset=[
            *features,
            RANK_TARGET,
            RAW_TARGET,
        ]
    ).sort_values(
        [
            "timestamp_utc",
            "product_id",
        ]
    ).reset_index(
        drop=True
    )

    daily_counts = (
        model_frame.groupby(
            "timestamp_utc"
        )[
            "product_id"
        ]
        .nunique()
    )

    if (
        daily_counts.min()
        < MIN_CROSS_SECTION_ASSETS
    ):
        raise RuntimeError(
            "V15 dataset violates minimum cross-section breadth"
        )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_exact_7d_cross_sectional_rank_target_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "source": {
            "research_version": (
                SOURCE_VERSION
            ),
            "phase": 1,
            "source_dataset": (
                "asset_path_utility_dataset.parquet"
            ),
            "source_raw_target_preserved_for_evaluation": True,
            "source_model_predictions_used": False,
            "source_portfolio_results_used": False,
        },
        "successor_after_rejection": {
            "rejected_parent": (
                SOURCE_VERSION
            ),
            "parent_disposition": (
                "REJECT_CURRENT_V14_PREDICTIVE_HYPOTHESIS"
            ),
            "observed_v14_predictive_metrics": {
                "median_fold_daily_spearman_ic": (
                    0.0477822083690975
                ),
                "mean_fold_daily_spearman_ic": (
                    0.0441741372942577
                ),
                "median_fold_positive_ic_day_fraction": (
                    0.5731329690346083
                ),
                "median_fold_top3_target_utility_excess_vs_universe": (
                    0.0059205188228512
                ),
                "mean_fold_top3_target_utility_excess_vs_universe": (
                    0.0042185890855693
                ),
                "positive_fold_top3_target_utility_excess_fraction": (
                    0.75
                ),
            },
            "v14_gate_lowered": False,
            "v14_model_retuned": False,
            "v14_portfolio_simulated": False,
        },
        "hypothesis": (
            "Because V14 was evaluated primarily on cross-sectional ordering, "
            "training directly on the within-day percentile rank of the same "
            "seven-day path utility may align the regression objective with "
            "the frozen ranking metrics better than fitting raw utility "
            "magnitudes whose scale varies substantially across crypto regimes."
        ),
        "learning_target": {
            "primary": (
                RANK_TARGET
            ),
            "definition": (
                "within-timestamp percentile rank of V14 path_utility_net25_7d; "
                "higher is better and the best asset has rank 1.0"
            ),
            "raw_economic_target_retained_for_evaluation": (
                RAW_TARGET
            ),
            "rank_method": (
                "pandas rank(pct=True), default average tie handling"
            ),
            "target_uses_only_same_timestamp_cross_section": True,
            "target_path_must_finish_before_holdout": True,
        },
        "model_feature_columns": (
            features
        ),
        "model": {
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
        },
        "walk_forward": {
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
        },
        "predictive_quality_gates": dict(
            EXPECTED_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "selection_rule": (
                "rank eligible assets by predicted cross-sectional percentile; "
                "select exactly the top 3 eligible assets when at least three "
                "assets are available; no prediction threshold is applied"
            ),
            "asset_weight": (
                0.20
            ),
            "selected_asset_count": (
                3
            ),
            "cash_weight": (
                0.40
            ),
            "maximum_gross_crypto_exposure": (
                0.60
            ),
            "primary_round_trip_cost_bps": (
                25.0
            ),
            "stress_round_trip_cost_bps": (
                50.0
            ),
            "maximum_turnover_per_7d_decision": (
                0.60
            ),
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": dict(
            source_contract[
                "selection_gates"
            ]
        ),
        "research_constraints": {
            "only_learning_target_changed_from_v14": True,
            "same_22_features_as_v14": True,
            "same_model_specification_as_v14": True,
            "same_walk_forward_protocol_as_v14": True,
            "same_predictive_gates_as_v14": True,
            "rank_target_fixed_before_fit": True,
            "no_model_family_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "no_post_result_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V15 is another development iteration on the same pre-holdout "
            "history. It is motivated by V14's near-miss and therefore carries "
            "additional researcher-selection risk. Passing development gates "
            "would justify only frozen portfolio evaluation, not deployment or "
            "a holdout-performance claim."
        ),
        "dataset": {
            "row_count": int(
                len(
                    model_frame
                )
            ),
            "product_count": int(
                model_frame[
                    "product_id"
                ].nunique()
            ),
            "decision_day_count": int(
                model_frame[
                    "timestamp_utc"
                ].nunique()
            ),
            "minimum_daily_assets": int(
                daily_counts.min()
            ),
            "median_daily_assets": float(
                daily_counts.median()
            ),
            "maximum_daily_assets": int(
                daily_counts.max()
            ),
            "start_utc": (
                model_frame[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                model_frame[
                    "timestamp_utc"
                ].max().isoformat()
            ),
        },
    }

    return (
        model_frame,
        contract,
    )


def run(
    source_phase1_root: Path = SOURCE_PHASE1_ROOT,
    source_phase3_root: Path = SOURCE_PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_phase1_root = Path(
        source_phase1_root
    )
    source_phase3_root = Path(
        source_phase3_root
    )
    output_root = Path(
        output_root
    )

    source_contract = json.loads(
        (
            source_phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    source = pd.read_parquet(
        source_phase1_root
        / "asset_path_utility_dataset.parquet"
    )

    v14_adjudication = json.loads(
        (
            source_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    dataset, contract = (
        build_dataset(
            source,
            source_contract,
            v14_adjudication,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "asset_cross_sectional_rank_dataset.parquet"
    )

    contract_path = (
        output_root
        / "preregistered_contract.json"
    )

    dataset.to_parquet(
        dataset_path,
        index=False,
    )

    contract_path.write_text(
        json.dumps(
            contract,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    rank_target = pd.to_numeric(
        dataset[
            RANK_TARGET
        ],
        errors="raise",
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_exact_7d_cross_sectional_rank_target_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "dataset": (
            contract[
                "dataset"
            ]
        ),
        "learning_target": {
            "name": (
                RANK_TARGET
            ),
            "mean": float(
                rank_target.mean()
            ),
            "median": float(
                rank_target.median()
            ),
            "minimum": float(
                rank_target.min()
            ),
            "maximum": float(
                rank_target.max()
            ),
        },
        "raw_target_for_evaluation": (
            RAW_TARGET
        ),
        "model_feature_count": int(
            len(
                contract[
                    "model_feature_columns"
                ]
            )
        ),
        "outputs": {
            "asset_cross_sectional_rank_dataset": str(
                dataset_path
            ),
            "contract": str(
                contract_path
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "hashes": {
            "asset_cross_sectional_rank_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
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
            "model_fitted": False,
            "portfolio_simulated": False,
            "predictive_gate_lowered": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit only the preregistered V15 HGB regressor to the within-day "
            "path-utility percentile target using the unchanged V14 features, "
            "purge, fold protocol, and four predictive gates. No portfolio "
            "simulation is allowed unless all four gates pass."
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
        "--source-phase1-root",
        type=Path,
        default=SOURCE_PHASE1_ROOT,
    )

    parser.add_argument(
        "--source-phase3-root",
        type=Path,
        default=SOURCE_PHASE3_ROOT,
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
                args.source_phase1_root,
                args.source_phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
