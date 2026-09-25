"""Shared Crypto V16 Risk-Gated Rank Phase 1.

V16 is a separately preregistered successor to rejected V15.

V15 established two distinct facts on development data:
1. the cross-sectional percentile ranker passed all four predictive ranking
   gates; and
2. the fixed always-deployed 60%-crypto top-3 portfolio failed five of eight
   portfolio gates.

V16 therefore preserves V15's ranking engine and changes only deployment. It
adds an independent daily market-risk model whose continuous target is the
cross-sectional median of the exact same seven-day net path-utility target:

    market_median_path_utility_net25_7d

The risk-on rule is fixed before fitting:

    predicted market_median_path_utility_net25_7d > 0

When risk-on, later portfolio simulation may deploy the frozen V15 top-3
ranking at 20% per asset plus 40% cash. When risk-off, it holds 100% cash.

No hand-tuned volatility or drawdown threshold is introduced. Risk features are
limited to preregistered BTC trend/volatility/drawdown state plus broad-market
cross-sectional medians and breadth computed from point-in-time V15 features.

This phase builds the risk dataset and contract only. No model is fit, V15 is
not refit, no portfolio is simulated, and the September 1, 2026 holdout remains
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


RESEARCH_VERSION = "shared_crypto_v16_risk_gated_rank"
SOURCE_VERSION = "shared_crypto_v15_cross_sectional_rank"

SOURCE_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase1"
)
SOURCE_PHASE4_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase4"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

RAW_TARGET = "path_utility_net25_7d"
MARKET_TARGET = "market_median_path_utility_net25_7d"
MARKET_LABEL = "market_risk_on_7d"

BTC = "BTC-USD"

BTC_BASE_FEATURES = (
    "return_1d",
    "return_3d",
    "return_7d",
    "return_14d",
    "return_30d",
    "realized_volatility_7d",
    "realized_volatility_14d",
    "realized_volatility_30d",
    "close_to_sma_7",
    "close_to_sma_14",
    "close_to_sma_30",
    "drawdown_from_high_30d",
)

CROSS_MEDIAN_FEATURES = (
    "return_7d",
    "return_30d",
    "realized_volatility_14d",
    "drawdown_from_high_30d",
)

BREADTH_DEFINITIONS = (
    (
        "breadth_return_7d_positive_fraction",
        "return_7d",
        0.0,
    ),
    (
        "breadth_above_sma30_fraction",
        "close_to_sma_30",
        0.0,
    ),
)

RISK_FEATURE_COLUMNS = (
    tuple(
        f"btc_{feature}"
        for feature
        in BTC_BASE_FEATURES
    )
    + tuple(
        f"market_median_{feature}"
        for feature
        in CROSS_MEDIAN_FEATURES
    )
    + tuple(
        definition[0]
        for definition
        in BREADTH_DEFINITIONS
    )
)

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

EXPECTED_RISK_PREDICTIVE_GATES = {
    "median_fold_spearman_ic_gt": 0.10,
    "median_fold_balanced_accuracy_gt": 0.55,
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


def _validate_v15_contract(
    contract: dict,
) -> list[str]:
    if (
        contract.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V16 source contract is not Shared Crypto V15 Phase 1"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V16 source holdout boundary differs from preregistration"
        )

    features = list(
        contract[
            "model_feature_columns"
        ]
    )

    if len(
        features
    ) != 22:
        raise RuntimeError(
            "V16 requires the exact 22-feature V15 ranking input set"
        )

    return features


def _validate_v15_rejection(
    adjudication: dict,
) -> None:
    if (
        adjudication.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V16 requires the V15 Phase 4 adjudication"
        )

    if (
        adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V15_POLICY_FAMILY"
    ):
        raise RuntimeError(
            "V16 may start only after V15 is immutably rejected"
        )

    if int(
        adjudication.get(
            "qualifying_candidate_count",
            -1,
        )
    ) != 0:
        raise RuntimeError(
            "V16 expected no qualifying V15 portfolio candidate"
        )

    policy = adjudication.get(
        "single_preregistered_policy",
        {},
    )

    if int(
        policy.get(
            "passed_gate_count",
            -1,
        )
    ) != 3:
        raise RuntimeError(
            "Unexpected V15 portfolio passed-gate count"
        )

    if int(
        policy.get(
            "total_gate_count",
            -1,
        )
    ) != 8:
        raise RuntimeError(
            "Unexpected V15 portfolio total-gate count"
        )


def build_risk_dataset(
    source: pd.DataFrame,
    source_contract: dict,
    v15_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    ranking_features = (
        _validate_v15_contract(
            source_contract
        )
    )

    _validate_v15_rejection(
        v15_adjudication
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
        "V16 V15 source dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        RAW_TARGET,
        "target_endpoint_utc_7d",
        *ranking_features,
        *BTC_BASE_FEATURES,
        *CROSS_MEDIAN_FEATURES,
        *[
            definition[1]
            for definition
            in BREADTH_DEFINITIONS
        ],
    }

    missing = (
        required
        - set(
            frame.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V16 source dataset missing columns: "
            f"{sorted(missing)}"
        )

    if (
        frame[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V16 source target path reaches the future holdout"
        )

    rows = []

    for timestamp, day in frame.groupby(
        "timestamp_utc",
        sort=True,
    ):
        btc = day[
            day[
                "product_id"
            ]
            == BTC
        ]

        if len(
            btc
        ) != 1:
            raise RuntimeError(
                f"V16 requires exactly one BTC row at {timestamp}"
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
                f"V16 target endpoint is inconsistent at {timestamp}"
            )

        row = {
            "timestamp_utc": (
                timestamp
            ),
            "target_endpoint_utc_7d": (
                endpoints.iloc[
                    0
                ]
            ),
            "eligible_asset_count": int(
                day[
                    "product_id"
                ].nunique()
            ),
            MARKET_TARGET: float(
                pd.to_numeric(
                    day[
                        RAW_TARGET
                    ],
                    errors="raise",
                ).median()
            ),
        }

        row[
            MARKET_LABEL
        ] = int(
            row[
                MARKET_TARGET
            ]
            > 0.0
        )

        btc_row = btc.iloc[
            0
        ]

        for feature in (
            BTC_BASE_FEATURES
        ):
            row[
                f"btc_{feature}"
            ] = float(
                btc_row[
                    feature
                ]
            )

        for feature in (
            CROSS_MEDIAN_FEATURES
        ):
            row[
                f"market_median_{feature}"
            ] = float(
                pd.to_numeric(
                    day[
                        feature
                    ],
                    errors="raise",
                ).median()
            )

        for (
            output_name,
            source_name,
            threshold,
        ) in BREADTH_DEFINITIONS:
            values = pd.to_numeric(
                day[
                    source_name
                ],
                errors="raise",
            )

            row[
                output_name
            ] = float(
                (
                    values
                    > float(
                        threshold
                    )
                ).mean()
            )

        rows.append(
            row
        )

    risk = pd.DataFrame(
        rows
    ).replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    ).dropna(
        subset=[
            *RISK_FEATURE_COLUMNS,
            MARKET_TARGET,
            MARKET_LABEL,
        ]
    ).sort_values(
        "timestamp_utc"
    ).reset_index(
        drop=True
    )

    if risk.empty:
        raise RuntimeError(
            "V16 market-risk dataset is empty"
        )

    if (
        risk[
            "eligible_asset_count"
        ].min()
        < 10
    ):
        raise RuntimeError(
            "V16 market-risk dataset violates V15 minimum universe breadth"
        )

    if (
        risk[
            MARKET_LABEL
        ].nunique()
        != 2
    ):
        raise RuntimeError(
            "V16 market-risk target must contain both RISK_ON and RISK_OFF examples"
        )

    forbidden_tokens = (
        "target_",
        "future_",
        "path_utility",
        "forward_",
        "endpoint",
    )

    leaked = [
        feature
        for feature
        in RISK_FEATURE_COLUMNS
        if any(
            token
            in feature.lower()
            for token
            in forbidden_tokens
        )
    ]

    if leaked:
        raise RuntimeError(
            "V16 future information leaked into risk features: "
            f"{sorted(leaked)}"
        )

    v15_policy = (
        source_contract[
            "frozen_policy_for_later_simulation"
        ]
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_7d_market_risk_gate_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "source": {
            "ranking_engine_research_version": (
                SOURCE_VERSION
            ),
            "ranking_engine_phase": 2,
            "ranking_engine_oos_predictions": (
                "data/model/shared_crypto_v15_cross_sectional_rank/phase2/asset_predictions.parquet"
            ),
            "ranking_engine_refit_allowed": False,
            "v15_portfolio_result_used_as_training_target": False,
        },
        "successor_after_rejection": {
            "rejected_parent": (
                SOURCE_VERSION
            ),
            "parent_disposition": (
                "REJECT_CURRENT_V15_POLICY_FAMILY"
            ),
            "v15_predictive_ranker_passed_all_gates": True,
            "v15_portfolio_passed_gate_count": 3,
            "v15_portfolio_total_gate_count": 8,
            "v15_failed_portfolio_gates": list(
                v15_adjudication[
                    "single_preregistered_policy"
                ][
                    "failed_gates"
                ]
            ),
            "v15_ranker_retuned": False,
            "v15_policy_modified": False,
        },
        "hypothesis": (
            "V15's rank model contains durable cross-sectional selection "
            "information, but deploying it during broad negative market states "
            "causes unstable returns and deep drawdowns. A separately trained "
            "daily market-risk regressor may identify whether the median "
            "eligible asset has positive seven-day path utility. Deploying the "
            "unchanged V15 ranker only when predicted broad-market median "
            "utility is positive may improve stability without changing asset "
            "selection."
        ),
        "market_risk_target": {
            "primary": (
                MARKET_TARGET
            ),
            "definition": (
                "cross-sectional median of V15 path_utility_net25_7d across "
                "eligible assets at the decision timestamp"
            ),
            "binary_diagnostic": (
                MARKET_LABEL
            ),
            "risk_on_definition": (
                "market_median_path_utility_net25_7d > 0"
            ),
            "future_path_horizon_days": 7,
            "target_path_must_finish_before_holdout": True,
        },
        "risk_feature_columns": list(
            RISK_FEATURE_COLUMNS
        ),
        "risk_feature_design": {
            "btc_point_in_time_features": list(
                BTC_BASE_FEATURES
            ),
            "cross_sectional_median_features": list(
                CROSS_MEDIAN_FEATURES
            ),
            "breadth_features": [
                {
                    "output": output,
                    "source": source,
                    "threshold": float(
                        threshold
                    ),
                }
                for (
                    output,
                    source,
                    threshold,
                )
                in BREADTH_DEFINITIONS
            ],
            "risk_feature_count": int(
                len(
                    RISK_FEATURE_COLUMNS
                )
            ),
        },
        "market_risk_model": {
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
        },
        "risk_predictive_quality_gates": dict(
            EXPECTED_RISK_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "risk_gate_rule": (
                "deploy frozen V15 top-3 ranker only when predicted "
                "market_median_path_utility_net25_7d is strictly greater than 0"
            ),
            "risk_off_allocation": {
                "cash_weight": 1.0,
                "crypto_weight": 0.0,
            },
            "risk_on_selection_engine": (
                "frozen V15 Phase 2 out-of-sample predicted_rank_score"
            ),
            "risk_on_selected_asset_count": int(
                v15_policy[
                    "selected_asset_count"
                ]
            ),
            "risk_on_asset_weight": float(
                v15_policy[
                    "asset_weight"
                ]
            ),
            "risk_on_cash_weight": float(
                v15_policy[
                    "cash_weight"
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
            source_contract[
                "selection_gates"
            ]
        ),
        "research_constraints": {
            "v15_ranker_is_frozen_input": True,
            "v15_ranker_refit_for_v16": False,
            "risk_gate_is_separate_model": True,
            "risk_gate_zero_threshold_fixed_before_fit": True,
            "no_manual_volatility_threshold": True,
            "no_manual_drawdown_threshold": True,
            "risk_features_fixed_before_fit": True,
            "risk_model_family_fixed_before_fit": True,
            "risk_predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_gates_carried_forward_unchanged_from_v15": True,
            "no_post_result_threshold_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V16 is motivated by observing V15's portfolio failure on the same "
            "pre-holdout development history and therefore carries substantial "
            "researcher-selection risk. Its risk target, risk features, zero "
            "activation threshold, model specification, predictive gates, and "
            "later portfolio policy are fixed before any V16 model is fit. A "
            "development pass would not itself establish future performance."
        ),
        "dataset": {
            "row_count": int(
                len(
                    risk
                )
            ),
            "start_utc": (
                risk[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                risk[
                    "timestamp_utc"
                ].max().isoformat()
            ),
            "risk_on_count": int(
                risk[
                    MARKET_LABEL
                ].sum()
            ),
            "risk_off_count": int(
                (
                    risk[
                        MARKET_LABEL
                    ]
                    == 0
                ).sum()
            ),
            "risk_on_fraction": float(
                risk[
                    MARKET_LABEL
                ].mean()
            ),
            "minimum_eligible_assets": int(
                risk[
                    "eligible_asset_count"
                ].min()
            ),
            "median_eligible_assets": float(
                risk[
                    "eligible_asset_count"
                ].median()
            ),
            "maximum_eligible_assets": int(
                risk[
                    "eligible_asset_count"
                ].max()
            ),
        },
    }

    return (
        risk,
        contract,
    )


def run(
    source_phase1_root: Path = SOURCE_PHASE1_ROOT,
    source_phase4_root: Path = SOURCE_PHASE4_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_phase1_root = Path(
        source_phase1_root
    )
    source_phase4_root = Path(
        source_phase4_root
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
        / "asset_cross_sectional_rank_dataset.parquet"
    )

    v15_adjudication = json.loads(
        (
            source_phase4_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    risk, contract = (
        build_risk_dataset(
            source,
            source_contract,
            v15_adjudication,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    risk_path = (
        output_root
        / "market_risk_dataset.parquet"
    )

    contract_path = (
        output_root
        / "preregistered_contract.json"
    )

    risk.to_parquet(
        risk_path,
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

    target = pd.to_numeric(
        risk[
            MARKET_TARGET
        ],
        errors="raise",
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_7d_market_risk_gate_dataset"
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
        "risk_feature_count": int(
            len(
                RISK_FEATURE_COLUMNS
            )
        ),
        "market_target_distribution": {
            "mean": float(
                target.mean()
            ),
            "median": float(
                target.median()
            ),
            "minimum": float(
                target.min()
            ),
            "maximum": float(
                target.max()
            ),
            "risk_on_fraction": float(
                risk[
                    MARKET_LABEL
                ].mean()
            ),
        },
        "outputs": {
            "market_risk_dataset": str(
                risk_path
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
            "market_risk_dataset": _sha256(
                risk_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "shared_crypto_v15_modified": False,
            "v15_ranker_refit": False,
            "v15_portfolio_resimulated": False,
            "future_holdout_scored": False,
            "risk_model_fitted": False,
            "portfolio_simulated": False,
            "threshold_search_performed": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit only the preregistered V16 market-risk HGB regressor using "
            "purged walk-forward development folds. Require all four frozen "
            "risk predictive gates before combining it with the frozen V15 "
            "ranking predictions in any portfolio simulation."
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
        "--source-phase4-root",
        type=Path,
        default=SOURCE_PHASE4_ROOT,
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
                args.source_phase4_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
