"""Shared Crypto V18 Ranker Meta-Gate Phase 1.

V18 is a separately preregistered successor after:
* V15 proved that cross-sectional rank learning can clear all predictive gates
  but its always-deployed 60%-crypto top-3 portfolio failed portfolio gates;
* V16 and V17 both failed to learn a sufficiently reliable broad market-state
  gate.

V18 changes the deployment question.

Rather than predict whether the entire eligible crypto universe is RISK_ON,
V18 asks whether the exact basket selected by the frozen V15 ranker is itself
likely to have a positive exact seven-day terminal return after the existing
25-bps asset-level target cost.

For each V15 out-of-sample prediction day:
1. rank assets by frozen V15 predicted_rank_score;
2. select the same top 3 assets;
3. define the continuous meta target as their mean
   net_terminal_return_7d_25bps;
4. define the binary deployment target as 1 when that mean is > 0.

The meta model may use only:
* frozen V15 prediction-score diagnostics available at the decision time; and
* the same 18 point-in-time market-context features preregistered in V16.

No V15 model is refit. No V16/V17 prediction is used as a feature. No target or
future-return column is used as a feature.

Because V15 out-of-sample predictions begin later than the underlying history,
V18 preregisters a 360-day minimum meta-training window, 180-day validation
windows, a full 7-day purge, and at most 6 folds.

This phase builds and preregisters the V18 meta dataset only. It fits no model,
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


RESEARCH_VERSION = "shared_crypto_v18_ranker_meta_gate"

V15_VERSION = "shared_crypto_v15_cross_sectional_rank"
V16_VERSION = "shared_crypto_v16_risk_gated_rank"
V17_VERSION = "shared_crypto_v17_direct_market_state"

V15_PHASE2_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase2"
)
V15_PHASE4_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase4"
)
V16_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase1"
)
V17_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v17_direct_market_state/phase3"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v18_ranker_meta_gate/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

PREDICTED_SCORE = "predicted_rank_score"
RAW_PATH_UTILITY = "path_utility_net25_7d"
NET_TERMINAL = "net_terminal_return_7d_25bps"

META_CONTINUOUS_TARGET = (
    "selected_top3_mean_net_terminal_return_7d_25bps"
)
META_BINARY_TARGET = (
    "selected_top3_profitable_7d"
)

TOP_K = 3
PRIMARY_COST_BPS = 25.0

RANK_DIAGNOSTIC_FEATURES = (
    "meta_top1_predicted_rank_score",
    "meta_top2_predicted_rank_score",
    "meta_top3_predicted_rank_score",
    "meta_top3_mean_predicted_rank_score",
    "meta_top3_min_predicted_rank_score",
    "meta_top1_minus_top3_predicted_score",
    "meta_top3_minus_fourth_predicted_score",
    "meta_top3_score_excess_vs_universe_mean",
    "meta_predicted_score_std",
    "meta_predicted_score_range",
    "meta_eligible_asset_count",
)

PRIMARY_MODEL = (
    "hist_gradient_boosting_classifier"
)
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0
RANDOM_STATE = 1729
CLASS_WEIGHT_METHOD = (
    "balanced_sample_weight"
)

PURGE_DAYS = 7
MIN_TRAIN_DAYS = 360
VALIDATION_DAYS = 180
MAX_FOLDS = 6

EXPECTED_PREDICTIVE_GATES = {
    "median_fold_balanced_accuracy_gt": 0.55,
    "median_fold_macro_f1_gt": 0.55,
    "median_fold_mcc_gt": 0.0,
    "median_fold_minimum_class_recall_gt": 0.50,
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


def _validate_lineage(
    v15_manifest: dict,
    v15_adjudication: dict,
    v16_contract: dict,
    v17_adjudication: dict,
) -> list[str]:
    if (
        v15_manifest.get(
            "research_version"
        )
        != V15_VERSION
        or v15_manifest.get(
            "predictive_gate_status"
        )
        != "ALLOW_POLICY_SIMULATION"
        or int(
            v15_manifest.get(
                "passed_predictive_gate_count",
                -1,
            )
        )
        != 4
    ):
        raise RuntimeError(
            "V18 requires the successful frozen V15 predictive ranker evidence"
        )

    if (
        v15_adjudication.get(
            "research_version"
        )
        != V15_VERSION
        or v15_adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V15_POLICY_FAMILY"
    ):
        raise RuntimeError(
            "V18 requires the immutable rejected V15 portfolio adjudication"
        )

    if (
        v16_contract.get(
            "research_version"
        )
        != V16_VERSION
    ):
        raise RuntimeError(
            "V18 requires the V16 point-in-time market-context contract"
        )

    market_features = list(
        v16_contract[
            "risk_feature_columns"
        ]
    )

    if len(
        market_features
    ) != 18:
        raise RuntimeError(
            "V18 requires exactly the 18 frozen V16 market-context features"
        )

    if (
        v17_adjudication.get(
            "research_version"
        )
        != V17_VERSION
        or v17_adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V17_DIRECT_MARKET_STATE_HYPOTHESIS"
        or v17_adjudication.get(
            "portfolio_simulation_allowed"
        )
        is not False
    ):
        raise RuntimeError(
            "V18 requires the immutable rejected V17 market-state adjudication"
        )

    return market_features


def build_meta_dataset(
    v15_predictions: pd.DataFrame,
    market_context: pd.DataFrame,
    v15_manifest: dict,
    v15_adjudication: dict,
    v16_contract: dict,
    v17_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    market_features = _validate_lineage(
        v15_manifest,
        v15_adjudication,
        v16_contract,
        v17_adjudication,
    )

    predictions = (
        v15_predictions.copy()
    )

    predictions[
        "timestamp_utc"
    ] = pd.to_datetime(
        predictions[
            "timestamp_utc"
        ],
        utc=True,
    )

    predictions[
        "target_endpoint_utc_7d"
    ] = pd.to_datetime(
        predictions[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    validate_pre_holdout(
        predictions,
        "V18 frozen V15 OOS predictions",
    )

    required_prediction_columns = {
        "timestamp_utc",
        "product_id",
        "fold_id",
        PREDICTED_SCORE,
        RAW_PATH_UTILITY,
        NET_TERMINAL,
        "target_endpoint_utc_7d",
        "eligible_asset_count",
    }

    missing = (
        required_prediction_columns
        - set(
            predictions.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V18 V15 predictions missing columns: "
            f"{sorted(missing)}"
        )

    if (
        predictions[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V18 source target path reaches the future holdout"
        )

    context = (
        market_context.copy()
    )

    context[
        "timestamp_utc"
    ] = pd.to_datetime(
        context[
            "timestamp_utc"
        ],
        utc=True,
    )

    validate_pre_holdout(
        context,
        "V18 market context",
    )

    missing = (
        {
            "timestamp_utc",
            *market_features,
        }
        - set(
            context.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V18 market context missing columns: "
            f"{sorted(missing)}"
        )

    context = (
        context[
            [
                "timestamp_utc",
                *market_features,
            ]
        ]
        .drop_duplicates(
            "timestamp_utc"
        )
    )

    rows = []

    for (
        fold_id,
        timestamp,
    ), day in predictions.groupby(
        [
            "fold_id",
            "timestamp_utc",
        ],
        sort=True,
    ):
        if (
            day[
                "product_id"
            ].nunique()
            < 4
        ):
            raise RuntimeError(
                "V18 requires at least four eligible assets for rank diagnostics"
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
                f"V18 target endpoint is inconsistent at {timestamp}"
            )

        ordered = day.sort_values(
            [
                PREDICTED_SCORE,
                "product_id",
            ],
            ascending=[
                False,
                True,
            ],
        ).reset_index(
            drop=True
        )

        top3 = ordered.head(
            TOP_K
        )

        scores = pd.to_numeric(
            ordered[
                PREDICTED_SCORE
            ],
            errors="raise",
        )

        top3_scores = pd.to_numeric(
            top3[
                PREDICTED_SCORE
            ],
            errors="raise",
        )

        selected_terminal = pd.to_numeric(
            top3[
                NET_TERMINAL
            ],
            errors="raise",
        )

        selected_path_utility = pd.to_numeric(
            top3[
                RAW_PATH_UTILITY
            ],
            errors="raise",
        )

        continuous_target = float(
            selected_terminal.mean()
        )

        universe_path_utility = float(
            pd.to_numeric(
                day[
                    RAW_PATH_UTILITY
                ],
                errors="raise",
            ).mean()
        )

        row = {
            "timestamp_utc": (
                timestamp
            ),
            "source_v15_fold_id": (
                str(
                    fold_id
                )
            ),
            "target_endpoint_utc_7d": (
                endpoints.iloc[
                    0
                ]
            ),
            "selected_assets": (
                "|".join(
                    top3[
                        "product_id"
                    ].astype(
                        str
                    )
                )
            ),
            META_CONTINUOUS_TARGET: (
                continuous_target
            ),
            META_BINARY_TARGET: int(
                continuous_target
                > 0.0
            ),
            "selected_top3_mean_path_utility_net25_7d": float(
                selected_path_utility.mean()
            ),
            "selected_top3_path_utility_excess_vs_universe": float(
                selected_path_utility.mean()
                - universe_path_utility
            ),
            "meta_top1_predicted_rank_score": float(
                top3_scores.iloc[
                    0
                ]
            ),
            "meta_top2_predicted_rank_score": float(
                top3_scores.iloc[
                    1
                ]
            ),
            "meta_top3_predicted_rank_score": float(
                top3_scores.iloc[
                    2
                ]
            ),
            "meta_top3_mean_predicted_rank_score": float(
                top3_scores.mean()
            ),
            "meta_top3_min_predicted_rank_score": float(
                top3_scores.min()
            ),
            "meta_top1_minus_top3_predicted_score": float(
                top3_scores.iloc[
                    0
                ]
                - top3_scores.iloc[
                    2
                ]
            ),
            "meta_top3_minus_fourth_predicted_score": float(
                top3_scores.iloc[
                    2
                ]
                - scores.iloc[
                    3
                ]
            ),
            "meta_top3_score_excess_vs_universe_mean": float(
                top3_scores.mean()
                - scores.mean()
            ),
            "meta_predicted_score_std": float(
                scores.std(
                    ddof=0
                )
            ),
            "meta_predicted_score_range": float(
                scores.max()
                - scores.min()
            ),
            "meta_eligible_asset_count": float(
                day[
                    "product_id"
                ].nunique()
            ),
        }

        rows.append(
            row
        )

    meta = pd.DataFrame(
        rows
    )

    meta = meta.merge(
        context,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )

    model_features = [
        *RANK_DIAGNOSTIC_FEATURES,
        *market_features,
    ]

    finite = meta[
        [
            *model_features,
            META_CONTINUOUS_TARGET,
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
            "V18 meta dataset contains missing or non-finite model inputs"
        )

    labels = pd.to_numeric(
        meta[
            META_BINARY_TARGET
        ],
        errors="raise",
    ).astype(
        int
    )

    expected_labels = (
        pd.to_numeric(
            meta[
                META_CONTINUOUS_TARGET
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
            "V18 binary deployment label no longer matches the frozen zero definition"
        )

    if set(
        labels.unique()
    ) != {
        0,
        1,
    }:
        raise RuntimeError(
            "V18 meta target requires both DEPLOY and CASH examples"
        )

    forbidden_tokens = (
        "target",
        "terminal_return",
        "path_utility",
        "future",
        "endpoint",
        "selected_assets",
        "correct",
    )

    leaked = [
        feature
        for feature
        in model_features
        if any(
            token
            in feature.lower()
            for token
            in forbidden_tokens
        )
    ]

    if leaked:
        raise RuntimeError(
            "V18 future or target information leaked into model features: "
            f"{sorted(leaked)}"
        )

    meta = meta.sort_values(
        "timestamp_utc"
    ).reset_index(
        drop=True
    )

    v15_policy = dict(
        v16_contract[
            "frozen_policy_for_later_simulation"
        ]
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_frozen_v15_ranker_meta_gate_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "lineage": {
            "frozen_ranking_engine": (
                "shared_crypto_v15_cross_sectional_rank Phase 2 OOS predictions"
            ),
            "v15_ranker_predictive_status": (
                "ALLOW_POLICY_SIMULATION"
            ),
            "v15_portfolio_status": (
                "REJECT_CURRENT_V15_POLICY_FAMILY"
            ),
            "v16_market_gate_status": (
                "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS"
            ),
            "v17_market_gate_status": (
                "REJECT_CURRENT_V17_DIRECT_MARKET_STATE_HYPOTHESIS"
            ),
            "v15_ranker_refit_allowed": False,
        },
        "hypothesis": (
            "Broad market-state timing was not learnable enough in V16/V17, "
            "but V15 ranking itself was predictive. A meta-model conditioned "
            "on the frozen V15 top-3 score structure plus point-in-time market "
            "context may identify whether the selected V15 basket itself will "
            "finish the next exact seven days positive, which is more directly "
            "aligned to the deployment decision than broad market RISK_ON."
        ),
        "deployment_target": {
            "continuous": (
                META_CONTINUOUS_TARGET
            ),
            "continuous_definition": (
                "mean V15-selected top-3 net_terminal_return_7d_25bps"
            ),
            "binary": (
                META_BINARY_TARGET
            ),
            "binary_definition": (
                "1 when selected_top3_mean_net_terminal_return_7d_25bps > 0, else 0"
            ),
            "deploy_label": 1,
            "cash_label": 0,
            "selection_count": (
                TOP_K
            ),
            "target_asset_level_cost_bps": (
                PRIMARY_COST_BPS
            ),
            "target_path_must_finish_before_holdout": True,
        },
        "rank_diagnostic_feature_columns": list(
            RANK_DIAGNOSTIC_FEATURES
        ),
        "market_context_feature_columns": (
            market_features
        ),
        "model_feature_columns": (
            model_features
        ),
        "meta_model": {
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
        },
        "predictive_quality_gates": dict(
            EXPECTED_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "meta_gate_rule": (
                "deploy frozen V15 top-3 ranker only when V18 direct meta "
                "classifier predicts DEPLOY class 1; otherwise hold 100% cash"
            ),
            "probability_threshold": None,
            "cash_when_blocked": 1.0,
            "risk_on_selection_engine": (
                "frozen V15 Phase 2 out-of-sample predicted_rank_score"
            ),
            "risk_on_selected_asset_count": int(
                v15_policy[
                    "risk_on_selected_asset_count"
                ]
            ),
            "risk_on_asset_weight": float(
                v15_policy[
                    "risk_on_asset_weight"
                ]
            ),
            "risk_on_cash_weight": float(
                v15_policy[
                    "risk_on_cash_weight"
                ]
            ),
            "maximum_gross_crypto_exposure": float(
                v15_policy[
                    "maximum_gross_crypto_exposure"
                ]
            ),
            "maximum_turnover_per_7d_decision": float(
                v15_policy[
                    "maximum_turnover_per_7d_decision"
                ]
            ),
            "primary_round_trip_cost_bps": float(
                v15_policy[
                    "primary_round_trip_cost_bps"
                ]
            ),
            "stress_round_trip_cost_bps": float(
                v15_policy[
                    "stress_round_trip_cost_bps"
                ]
            ),
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": dict(
            v16_contract[
                "selection_gates"
            ]
        ),
        "research_constraints": {
            "v15_oos_predictions_are_frozen_input": True,
            "v15_ranker_refit": False,
            "v16_or_v17_predictions_used_as_features": False,
            "broad_market_state_label_reused": False,
            "deployment_target_fixed_before_fit": True,
            "zero_profitability_boundary_fixed_before_fit": True,
            "rank_diagnostics_fixed_before_fit": True,
            "same_18_point_in_time_market_features_as_v16": True,
            "meta_model_fixed_before_fit": True,
            "balanced_sample_weight_fixed_before_fit": True,
            "no_probability_threshold": True,
            "no_probability_threshold_search": True,
            "no_feature_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_gates_carried_forward_unchanged": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V18 is motivated by the observed V15 portfolio failure and V16/V17 "
            "market-gate failures on the same pre-holdout development history. "
            "The new selected-basket deployment target, score diagnostics, "
            "market features, classifier, fold protocol, gates, and later "
            "policy are fixed before V18 fitting. This carries substantial "
            "researcher-selection risk and any development pass would not by "
            "itself establish future performance."
        ),
        "dataset": {
            "row_count": int(
                len(
                    meta
                )
            ),
            "start_utc": (
                meta[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                meta[
                    "timestamp_utc"
                ].max().isoformat()
            ),
            "deploy_count": int(
                meta[
                    META_BINARY_TARGET
                ].sum()
            ),
            "cash_count": int(
                (
                    meta[
                        META_BINARY_TARGET
                    ]
                    == 0
                ).sum()
            ),
            "deploy_fraction": float(
                meta[
                    META_BINARY_TARGET
                ].mean()
            ),
            "rank_diagnostic_feature_count": int(
                len(
                    RANK_DIAGNOSTIC_FEATURES
                )
            ),
            "market_context_feature_count": int(
                len(
                    market_features
                )
            ),
            "total_model_feature_count": int(
                len(
                    model_features
                )
            ),
        },
    }

    return (
        meta,
        contract,
    )


def run(
    v15_phase2_root: Path = V15_PHASE2_ROOT,
    v15_phase4_root: Path = V15_PHASE4_ROOT,
    v16_phase1_root: Path = V16_PHASE1_ROOT,
    v17_phase3_root: Path = V17_PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    v15_phase2_root = Path(
        v15_phase2_root
    )
    v15_phase4_root = Path(
        v15_phase4_root
    )
    v16_phase1_root = Path(
        v16_phase1_root
    )
    v17_phase3_root = Path(
        v17_phase3_root
    )
    output_root = Path(
        output_root
    )

    v15_manifest = json.loads(
        (
            v15_phase2_root
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    v15_predictions = pd.read_parquet(
        v15_phase2_root
        / "asset_predictions.parquet"
    )

    v15_adjudication = json.loads(
        (
            v15_phase4_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    v16_contract = json.loads(
        (
            v16_phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    market_context = pd.read_parquet(
        v16_phase1_root
        / "market_risk_dataset.parquet"
    )

    v17_adjudication = json.loads(
        (
            v17_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    meta, contract = (
        build_meta_dataset(
            v15_predictions,
            market_context,
            v15_manifest,
            v15_adjudication,
            v16_contract,
            v17_adjudication,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "ranker_meta_gate_dataset.parquet"
    )

    contract_path = (
        output_root
        / "preregistered_contract.json"
    )

    meta.to_parquet(
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

    continuous = pd.to_numeric(
        meta[
            META_CONTINUOUS_TARGET
        ],
        errors="raise",
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_frozen_v15_ranker_meta_gate_dataset"
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
        "continuous_target_distribution": {
            "mean": float(
                continuous.mean()
            ),
            "median": float(
                continuous.median()
            ),
            "minimum": float(
                continuous.min()
            ),
            "maximum": float(
                continuous.max()
            ),
        },
        "outputs": {
            "ranker_meta_gate_dataset": str(
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
            "ranker_meta_gate_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "shared_crypto_v15_modified": False,
            "shared_crypto_v16_modified": False,
            "shared_crypto_v17_modified": False,
            "v15_ranker_refit": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "probability_threshold_searched": False,
            "feature_search_performed": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit only the preregistered V18 balanced HGB meta-classifier on "
            "the selected-basket profitability label with the fixed 29 "
            "features and purged meta walk-forward protocol. Require all four "
            "predictive gates before any portfolio simulation."
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
        "--v15-phase2-root",
        type=Path,
        default=V15_PHASE2_ROOT,
    )

    parser.add_argument(
        "--v15-phase4-root",
        type=Path,
        default=V15_PHASE4_ROOT,
    )

    parser.add_argument(
        "--v16-phase1-root",
        type=Path,
        default=V16_PHASE1_ROOT,
    )

    parser.add_argument(
        "--v17-phase3-root",
        type=Path,
        default=V17_PHASE3_ROOT,
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
                args.v15_phase2_root,
                args.v15_phase4_root,
                args.v16_phase1_root,
                args.v17_phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
