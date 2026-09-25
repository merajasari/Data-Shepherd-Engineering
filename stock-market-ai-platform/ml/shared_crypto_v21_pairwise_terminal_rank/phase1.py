"""Shared Crypto V21 Pairwise Terminal Rank Phase 1.

OFFLINE RESEARCH ONLY.
No brokerage orders, no paper-state mutation, and no automatic promotion.

V21 is a separately preregistered successor after V20 was rejected before
portfolio simulation.

V20 showed a useful cross-sectional ordering signal but failed to concentrate
enough BTC-relative return in its predicted top three. V21 changes the learning
objective materially: instead of regressing one scalar rank target per asset,
it learns pairwise ordering directly.

For every decision date and every canonical unordered asset pair:
* left/right are assigned by ascending product_id;
* the binary target is 1 when the left asset's exact seven-day BTC-relative
  net terminal return exceeds the right asset's;
* exact ties within 1e-12 are dropped and counted;
* model inputs contain only transformations of the same 22 causal V15/V20
  asset features available at the decision time.

For each base feature V21 preregisters:
* signed pair difference: left - right;
* pair mean: (left + right) / 2.

This yields 44 pairwise model features. The signed differences encode relative
state while pair means retain common/regime context that would otherwise cancel.

The Phase 2 model is preregistered as a balanced
HistGradientBoostingClassifier. Validation will aggregate pairwise win
probabilities into an asset score by mean expected win probability against all
other eligible assets. No probability threshold is used for ranking and no
threshold is searched.

Phase 1 builds and preregisters the pairwise dataset only. It fits no V21 model,
runs no portfolio simulation, and leaves the September 1, 2026 future holdout
untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v21_pairwise_terminal_rank"
SOURCE_VERSION = "shared_crypto_v20_btc_relative_terminal_rank"

SOURCE_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase1"
)
SOURCE_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase3"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v21_pairwise_terminal_rank/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

RAW_RELATIVE_TARGET = (
    "btc_relative_net_terminal_return_7d_25bps"
)
PAIR_MARGIN = (
    "left_minus_right_btc_relative_terminal_return_7d_25bps"
)
PAIR_LABEL = (
    "left_beats_right_7d"
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
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 8
MIN_CROSS_SECTION_ASSETS = 10
PAIR_TIE_ATOL = 1e-12

EXPECTED_PREDICTIVE_GATES = {
    "median_fold_pairwise_balanced_accuracy_gt": 0.55,
    "median_fold_daily_spearman_ic_gt": 0.05,
    "median_fold_positive_ic_day_fraction_gt": 0.52,
    "median_fold_top3_btc_relative_terminal_excess_gt": 0.0,
    "positive_fold_top3_btc_relative_terminal_excess_fraction_gte": 0.75,
    "median_fold_top3_daily_btc_win_fraction_gt": 0.50,
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


def pair_feature_columns(
    base_features: list[str],
) -> tuple[
    list[str],
    list[str],
    list[str],
]:
    difference = [
        f"diff__{feature}"
        for feature in base_features
    ]

    means = [
        f"mean__{feature}"
        for feature in base_features
    ]

    return (
        difference,
        means,
        difference + means,
    )


def _validate_source(
    source_contract: dict,
    source_adjudication: dict,
) -> list[str]:
    if (
        source_contract.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V21 source contract is not Shared Crypto V20 Phase 1"
        )

    if (
        source_contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V21 source holdout differs from V20"
        )

    base_features = list(
        source_contract[
            "model_feature_columns"
        ]
    )

    if len(
        base_features
    ) != 22:
        raise RuntimeError(
            "V21 requires exactly the 22 frozen V20 base features"
        )

    target = source_contract.get(
        "learning_target",
        {},
    )

    if (
        target.get(
            "raw_economic_target"
        )
        != RAW_RELATIVE_TARGET
    ):
        raise RuntimeError(
            "V21 requires the V20 BTC-relative terminal economic target"
        )

    source_constraints = source_contract.get(
        "research_constraints",
        {},
    )

    if (
        source_constraints.get(
            "offline_research_only"
        )
        is not True
        or source_constraints.get(
            "future_holdout_must_remain_untouched_until_candidate_freeze"
        )
        is not True
    ):
        raise RuntimeError(
            "V21 requires the frozen offline V20 source constraints"
        )

    if (
        source_adjudication.get(
            "research_version"
        )
        != SOURCE_VERSION
        or source_adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V20_BTC_RELATIVE_TERMINAL_RANK_HYPOTHESIS"
        or source_adjudication.get(
            "offline_portfolio_simulation_allowed"
        )
        is not False
    ):
        raise RuntimeError(
            "V21 requires the immutable rejected V20 adjudication"
        )

    return base_features


def build_pairwise_dataset(
    source: pd.DataFrame,
    source_contract: dict,
    source_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    base_features = _validate_source(
        source_contract,
        source_adjudication,
    )

    (
        difference_features,
        mean_features,
        model_features,
    ) = pair_feature_columns(
        base_features
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

    frame[
        "target_endpoint_utc_7d"
    ] = pd.to_datetime(
        frame[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    validate_pre_holdout(
        frame,
        "V21 V20 source dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        RAW_RELATIVE_TARGET,
        "target_endpoint_utc_7d",
        *base_features,
    }

    missing = required - set(
        frame.columns
    )

    if missing:
        raise RuntimeError(
            "V21 source dataset missing columns: "
            f"{sorted(missing)}"
        )

    if (
        frame[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V21 source target path reaches the future holdout"
        )

    finite = frame[
        [
            *base_features,
            RAW_RELATIVE_TARGET,
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
            "V21 source contains non-finite features or target values"
        )

    daily_counts = (
        frame.groupby(
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
            "V21 source violates minimum cross-section breadth"
        )

    pair_frames = []
    dropped_ties = 0

    for timestamp, day in frame.groupby(
        "timestamp_utc",
        sort=True,
    ):
        day = day.sort_values(
            "product_id"
        ).reset_index(
            drop=True
        )

        if (
            day[
                "product_id"
            ].duplicated().any()
        ):
            raise RuntimeError(
                f"V21 source contains duplicate assets at {timestamp}"
            )

        endpoints = (
            day[
                "target_endpoint_utc_7d"
            ]
            .drop_duplicates()
        )

        if len(
            endpoints
        ) != 1:
            raise RuntimeError(
                f"V21 source target endpoint is inconsistent at {timestamp}"
            )

        products = day[
            "product_id"
        ].astype(
            str
        ).to_numpy()

        values = day[
            base_features
        ].to_numpy(
            dtype=float
        )

        targets = pd.to_numeric(
            day[
                RAW_RELATIVE_TARGET
            ],
            errors="raise",
        ).to_numpy(
            dtype=float
        )

        left_index, right_index = (
            np.triu_indices(
                len(
                    day
                ),
                k=1,
            )
        )

        margins = (
            targets[
                left_index
            ]
            - targets[
                right_index
            ]
        )

        keep = ~np.isclose(
            margins,
            0.0,
            rtol=0.0,
            atol=PAIR_TIE_ATOL,
        )

        dropped_ties += int(
            (
                ~keep
            ).sum()
        )

        left_index = (
            left_index[
                keep
            ]
        )

        right_index = (
            right_index[
                keep
            ]
        )

        margins = margins[
            keep
        ]

        differences = (
            values[
                left_index
            ]
            - values[
                right_index
            ]
        )

        means = (
            values[
                left_index
            ]
            + values[
                right_index
            ]
        ) / 2.0

        pair = pd.DataFrame(
            np.concatenate(
                [
                    differences,
                    means,
                ],
                axis=1,
            ),
            columns=model_features,
        )

        pair.insert(
            0,
            "timestamp_utc",
            timestamp,
        )

        pair.insert(
            1,
            "left_product_id",
            products[
                left_index
            ],
        )

        pair.insert(
            2,
            "right_product_id",
            products[
                right_index
            ],
        )

        pair[
            "target_endpoint_utc_7d"
        ] = (
            endpoints.iloc[
                0
            ]
        )

        pair[
            "left_btc_relative_terminal_return_7d_25bps"
        ] = (
            targets[
                left_index
            ]
        )

        pair[
            "right_btc_relative_terminal_return_7d_25bps"
        ] = (
            targets[
                right_index
            ]
        )

        pair[
            PAIR_MARGIN
        ] = (
            margins
        )

        pair[
            PAIR_LABEL
        ] = (
            margins
            > 0.0
        ).astype(
            int
        )

        pair[
            "eligible_asset_count"
        ] = int(
            len(
                day
            )
        )

        pair_frames.append(
            pair
        )

    if not pair_frames:
        raise RuntimeError(
            "V21 pairwise dataset is empty"
        )

    pairwise = pd.concat(
        pair_frames,
        ignore_index=True,
    )

    labels = pd.to_numeric(
        pairwise[
            PAIR_LABEL
        ],
        errors="raise",
    ).astype(
        int
    )

    if set(
        labels.unique()
    ) != {
        0,
        1,
    }:
        raise RuntimeError(
            "V21 pairwise target requires both ordering classes"
        )

    expected_labels = (
        pd.to_numeric(
            pairwise[
                PAIR_MARGIN
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
            "V21 pair label no longer matches the frozen pair margin"
        )

    pairwise = pairwise.sort_values(
        [
            "timestamp_utc",
            "left_product_id",
            "right_product_id",
        ]
    ).reset_index(
        drop=True
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_pairwise_btc_relative_terminal_order_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "lineage": {
            "source_version": (
                SOURCE_VERSION
            ),
            "source_dataset": (
                "shared_crypto_v20_btc_relative_terminal_rank Phase 1 "
                "asset_btc_relative_terminal_rank_dataset.parquet"
            ),
            "source_status": (
                "REJECT_CURRENT_V20_BTC_RELATIVE_TERMINAL_RANK_HYPOTHESIS"
            ),
            "source_predictions_used_as_features": False,
            "source_portfolio_results_used_as_target": False,
        },
        "hypothesis": (
            "V20 demonstrated useful cross-sectional ordering but weak "
            "top-three economic concentration. Direct pairwise learning may "
            "sharpen the upper tail by fitting relative ordering decisions "
            "rather than a scalar percentile target. Aggregating expected "
            "pairwise wins can then produce an asset ranking without a "
            "day-level timing gate."
        ),
        "pair_target": {
            "binary": (
                PAIR_LABEL
            ),
            "binary_definition": (
                "1 when canonical left asset has strictly higher exact 7-day "
                "BTC-relative net terminal return than canonical right asset"
            ),
            "continuous_audit_margin": (
                PAIR_MARGIN
            ),
            "canonical_pair_order": (
                "ascending product_id; each unordered pair appears once per day"
            ),
            "tie_rule": (
                "drop pair when absolute target margin <= 1e-12"
            ),
            "target_path_must_finish_before_holdout": True,
        },
        "base_feature_columns": (
            base_features
        ),
        "difference_feature_columns": (
            difference_features
        ),
        "pair_mean_feature_columns": (
            mean_features
        ),
        "model_feature_columns": (
            model_features
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
            "class_weight_method": (
                CLASS_WEIGHT_METHOD
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
        "asset_score_aggregation": {
            "method": (
                "mean expected pairwise win probability against all other "
                "eligible assets on the same validation day"
            ),
            "probability_source": (
                "classifier predict_proba class 1"
            ),
            "probability_threshold_used_for_ranking": False,
            "tie_break": (
                "product_id ascending after aggregated score descending"
            ),
        },
        "predictive_quality_gates": dict(
            EXPECTED_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": {
            "research_mode": (
                "offline_paper_simulation_only"
            ),
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "selection_rule": (
                "rank eligible assets by V21 aggregated expected pairwise win "
                "score and select exactly top 3"
            ),
            "asset_weight": 0.20,
            "selected_asset_count": 3,
            "cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "maximum_turnover_per_7d_decision": 0.60,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
            "real_orders": False,
        },
        "research_constraints": {
            "offline_research_only": True,
            "materially_different_pairwise_objective": True,
            "same_22_source_features_as_v20": True,
            "pair_features_are_deterministic_transformations_only": True,
            "one_canonical_unordered_pair_per_asset_pair": True,
            "pair_target_fixed_before_fit": True,
            "pair_tie_rule_fixed_before_fit": True,
            "asset_score_aggregation_fixed_before_fit": True,
            "model_fixed_before_fit": True,
            "balanced_sample_weight_fixed_before_fit": True,
            "predictive_gates_fixed_before_fit": True,
            "no_probability_threshold_for_ranking": True,
            "no_probability_threshold_search": True,
            "no_model_family_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "no_top_k_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V21 is motivated by V20's observed development result on the same "
            "pre-holdout history. Pair construction, 44 deterministic features, "
            "classifier specification, pairwise aggregation, six predictive "
            "gates, and later paper-only policy are fixed before any V21 fit. "
            "This carries substantial researcher-selection risk."
        ),
        "dataset": {
            "pair_row_count": int(
                len(
                    pairwise
                )
            ),
            "decision_day_count": int(
                pairwise[
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
            "left_beats_right_count": int(
                labels.sum()
            ),
            "right_beats_left_count": int(
                (
                    labels
                    == 0
                ).sum()
            ),
            "left_beats_right_fraction": float(
                labels.mean()
            ),
            "dropped_tie_pair_count": int(
                dropped_ties
            ),
            "base_feature_count": int(
                len(
                    base_features
                )
            ),
            "model_feature_count": int(
                len(
                    model_features
                )
            ),
            "start_utc": (
                pairwise[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                pairwise[
                    "timestamp_utc"
                ].max().isoformat()
            ),
        },
    }

    return (
        pairwise,
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
        / "asset_btc_relative_terminal_rank_dataset.parquet"
    )

    source_adjudication = json.loads(
        (
            source_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    pairwise, contract = (
        build_pairwise_dataset(
            source,
            source_contract,
            source_adjudication,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "pairwise_terminal_order_dataset.parquet"
    )

    contract_path = (
        output_root
        / "preregistered_contract.json"
    )

    pairwise.to_parquet(
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

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_pairwise_btc_relative_terminal_order_dataset"
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
        "base_feature_count": int(
            len(
                contract[
                    "base_feature_columns"
                ]
            )
        ),
        "model_feature_count": int(
            len(
                contract[
                    "model_feature_columns"
                ]
            )
        ),
        "predictive_gate_count": int(
            len(
                contract[
                    "predictive_quality_gates"
                ]
            )
            - 1
        ),
        "outputs": {
            "dataset": str(
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
            "dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "offline_research_only": True,
            "shared_crypto_v20_modified": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "feature_search_performed": False,
            "model_family_searched": False,
            "hyperparameters_tuned": False,
            "threshold_search_performed": False,
            "top_k_search_performed": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Fit only the preregistered V21 balanced HGB pairwise classifier "
            "using the frozen pair construction, 44 features, purged "
            "walk-forward protocol, and fixed asset-score aggregation. Require "
            "all six predictive gates before any offline portfolio simulation."
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
