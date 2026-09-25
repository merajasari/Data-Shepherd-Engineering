"""Shared Crypto V19 Relative Sleeve Router Phase 1.

OFFLINE RESEARCH ONLY.
No brokerage orders, no live allocation, and no automatic promotion.

V19 is a separately preregistered successor after V18 was rejected before
portfolio simulation.

Research reset:
V16, V17, and V18 all asked some version of whether crypto exposure should be
reduced to cash. V19 abandons that question. It holds the paper-only gross
crypto sleeve fixed at 60% and the cash reserve fixed at 40%. The learning
problem is only relative selection:

    Should the 60% crypto sleeve use the frozen V15 top-three basket or BTC?

For each frozen V15 out-of-sample prediction day:
1. rank assets by frozen V15 predicted_rank_score;
2. select the same top three assets;
3. compute their mean exact seven-day net terminal return at 25 bps;
4. compare that mean with BTC's exact seven-day net terminal return at 25 bps;
5. label TOP3 when the top-three excess over BTC is > 0, otherwise label BTC.

Features contain only decision-time information:
* the 11 V18 V15 score diagnostics;
* 5 additional BTC-relative score diagnostics;
* the same 18 point-in-time market-context features from V16.

No realized return, path utility, target, future endpoint, or V16/V17/V18
prediction is a model feature.

Phase 1 builds and preregisters the dataset only. It fits no V19 model, runs no
portfolio simulation, and leaves the September 1, 2026 future holdout untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v19_relative_sleeve_router"

V15_VERSION = "shared_crypto_v15_cross_sectional_rank"
V16_VERSION = "shared_crypto_v16_risk_gated_rank"
V18_VERSION = "shared_crypto_v18_ranker_meta_gate"

V15_PHASE2_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase2"
)
V15_PHASE4_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase4"
)
V16_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase1"
)
V18_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v18_ranker_meta_gate/phase3"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v19_relative_sleeve_router/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

BTC = "BTC-USD"
PREDICTED_SCORE = "predicted_rank_score"
NET_TERMINAL = "net_terminal_return_7d_25bps"

RELATIVE_CONTINUOUS_TARGET = (
    "selected_top3_excess_vs_btc_net_terminal_7d_25bps"
)
RELATIVE_BINARY_TARGET = (
    "route_top3_over_btc_7d"
)

TOP_K = 3
PRIMARY_COST_BPS = 25.0

V18_RANK_DIAGNOSTIC_FEATURES = (
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

BTC_RELATIVE_FEATURES = (
    "router_btc_predicted_rank_score",
    "router_btc_predicted_rank_fraction",
    "router_top3_mean_minus_btc_score",
    "router_top3_min_minus_btc_score",
    "router_btc_in_top3",
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

EXPECTED_PREDICTIVE_GATES = {
    "median_fold_balanced_accuracy_gt": 0.55,
    "median_fold_macro_f1_gt": 0.55,
    "median_fold_mcc_gt": 0.0,
    "median_fold_minimum_class_recall_gt": 0.50,
    "all_gates_required_before_portfolio_simulation": True,
}

FROZEN_PORTFOLIO_GATES = {
    "median_fold_net_return_gt": 0.0,
    "positive_fold_fraction_gte": 0.80,
    "median_excess_vs_fixed_btc_sleeve_gt": 0.0,
    "positive_excess_vs_fixed_btc_sleeve_fraction_gte": 0.80,
    "median_excess_vs_always_v15_top3_gt": 0.0,
    "positive_excess_vs_always_v15_top3_fraction_gte": 0.80,
    "worst_maximum_drawdown_gte": -0.20,
    "single_fold_profit_concentration_lte": 0.40,
    "survives_stress_cost_bps": 50.0,
}


def _sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pre_holdout(
    frame: pd.DataFrame,
    source: str,
) -> None:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"],
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
    v18_adjudication: dict,
) -> list[str]:
    if (
        v15_manifest.get("research_version")
        != V15_VERSION
        or v15_manifest.get("predictive_gate_status")
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
            "V19 requires the successful V15 predictive ranking evidence"
        )

    if (
        v15_adjudication.get("research_version")
        != V15_VERSION
        or v15_adjudication.get("status")
        != "REJECT_CURRENT_V15_POLICY_FAMILY"
    ):
        raise RuntimeError(
            "V19 requires the immutable V15 portfolio rejection"
        )

    if (
        v16_contract.get("research_version")
        != V16_VERSION
    ):
        raise RuntimeError(
            "V19 requires the frozen V16 market-context contract"
        )

    market_features = list(
        v16_contract["risk_feature_columns"]
    )

    if len(market_features) != 18:
        raise RuntimeError(
            "V19 requires exactly 18 frozen market-context features"
        )

    if (
        v18_adjudication.get("research_version")
        != V18_VERSION
        or v18_adjudication.get("status")
        != "REJECT_CURRENT_V18_RANKER_META_GATE_HYPOTHESIS"
        or v18_adjudication.get(
            "portfolio_simulation_allowed"
        )
        is not False
    ):
        raise RuntimeError(
            "V19 requires the immutable rejected V18 adjudication"
        )

    return market_features


def build_router_dataset(
    v15_predictions: pd.DataFrame,
    market_context: pd.DataFrame,
    v15_manifest: dict,
    v15_adjudication: dict,
    v16_contract: dict,
    v18_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    market_features = _validate_lineage(
        v15_manifest,
        v15_adjudication,
        v16_contract,
        v18_adjudication,
    )

    predictions = v15_predictions.copy()

    predictions["timestamp_utc"] = pd.to_datetime(
        predictions["timestamp_utc"],
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
        "V19 frozen V15 OOS predictions",
    )

    required = {
        "timestamp_utc",
        "product_id",
        "fold_id",
        PREDICTED_SCORE,
        NET_TERMINAL,
        "target_endpoint_utc_7d",
        "eligible_asset_count",
    }

    missing = required - set(
        predictions.columns
    )

    if missing:
        raise RuntimeError(
            "V19 V15 predictions missing columns: "
            f"{sorted(missing)}"
        )

    if (
        predictions[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V19 source target path reaches the future holdout"
        )

    context = market_context.copy()
    context["timestamp_utc"] = pd.to_datetime(
        context["timestamp_utc"],
        utc=True,
    )

    validate_pre_holdout(
        context,
        "V19 market context",
    )

    missing = {
        "timestamp_utc",
        *market_features,
    } - set(
        context.columns
    )

    if missing:
        raise RuntimeError(
            "V19 market context missing columns: "
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
            day["product_id"].nunique()
            < 4
        ):
            raise RuntimeError(
                "V19 requires at least four eligible assets"
            )

        btc = day[
            day["product_id"]
            == BTC
        ]

        if len(btc) != 1:
            raise RuntimeError(
                f"V19 requires exactly one BTC row at {timestamp}"
            )

        endpoints = (
            day[
                "target_endpoint_utc_7d"
            ]
            .drop_duplicates()
        )

        if len(endpoints) != 1:
            raise RuntimeError(
                f"V19 target endpoint is inconsistent at {timestamp}"
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

        btc_row = btc.iloc[0]
        btc_score = float(
            btc_row[
                PREDICTED_SCORE
            ]
        )

        btc_rank = int(
            ordered.index[
                ordered["product_id"]
                == BTC
            ][0]
        ) + 1

        asset_count = int(
            day[
                "product_id"
            ].nunique()
        )

        top3_terminal = float(
            pd.to_numeric(
                top3[
                    NET_TERMINAL
                ],
                errors="raise",
            ).mean()
        )

        btc_terminal = float(
            btc_row[
                NET_TERMINAL
            ]
        )

        relative_target = float(
            top3_terminal
            - btc_terminal
        )

        row = {
            "timestamp_utc": timestamp,
            "source_v15_fold_id": str(
                fold_id
            ),
            "target_endpoint_utc_7d": (
                endpoints.iloc[0]
            ),
            "selected_assets": "|".join(
                top3[
                    "product_id"
                ].astype(str)
            ),
            "btc_in_selected_top3": int(
                BTC
                in set(
                    top3[
                        "product_id"
                    ].astype(str)
                )
            ),
            "selected_top3_mean_net_terminal_return_7d_25bps": (
                top3_terminal
            ),
            "btc_net_terminal_return_7d_25bps": (
                btc_terminal
            ),
            RELATIVE_CONTINUOUS_TARGET: (
                relative_target
            ),
            RELATIVE_BINARY_TARGET: int(
                relative_target
                > 0.0
            ),
            "meta_top1_predicted_rank_score": float(
                top3_scores.iloc[0]
            ),
            "meta_top2_predicted_rank_score": float(
                top3_scores.iloc[1]
            ),
            "meta_top3_predicted_rank_score": float(
                top3_scores.iloc[2]
            ),
            "meta_top3_mean_predicted_rank_score": float(
                top3_scores.mean()
            ),
            "meta_top3_min_predicted_rank_score": float(
                top3_scores.min()
            ),
            "meta_top1_minus_top3_predicted_score": float(
                top3_scores.iloc[0]
                - top3_scores.iloc[2]
            ),
            "meta_top3_minus_fourth_predicted_score": float(
                top3_scores.iloc[2]
                - scores.iloc[3]
            ),
            "meta_top3_score_excess_vs_universe_mean": float(
                top3_scores.mean()
                - scores.mean()
            ),
            "meta_predicted_score_std": float(
                scores.std(ddof=0)
            ),
            "meta_predicted_score_range": float(
                scores.max()
                - scores.min()
            ),
            "meta_eligible_asset_count": float(
                asset_count
            ),
            "router_btc_predicted_rank_score": (
                btc_score
            ),
            "router_btc_predicted_rank_fraction": float(
                btc_rank
                / asset_count
            ),
            "router_top3_mean_minus_btc_score": float(
                top3_scores.mean()
                - btc_score
            ),
            "router_top3_min_minus_btc_score": float(
                top3_scores.min()
                - btc_score
            ),
            "router_btc_in_top3": float(
                BTC
                in set(
                    top3[
                        "product_id"
                    ].astype(str)
                )
            ),
        }

        rows.append(row)

    router = pd.DataFrame(
        rows
    )

    router = router.merge(
        context,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )

    model_features = [
        *V18_RANK_DIAGNOSTIC_FEATURES,
        *BTC_RELATIVE_FEATURES,
        *market_features,
    ]

    finite = router[
        [
            *model_features,
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
            "V19 router dataset contains missing or non-finite inputs"
        )

    labels = pd.to_numeric(
        router[
            RELATIVE_BINARY_TARGET
        ],
        errors="raise",
    ).astype(int)

    expected_labels = (
        pd.to_numeric(
            router[
                RELATIVE_CONTINUOUS_TARGET
            ],
            errors="raise",
        )
        > 0.0
    ).astype(int)

    if not labels.equals(
        expected_labels
    ):
        raise RuntimeError(
            "V19 route label no longer matches the frozen relative-return target"
        )

    if set(
        labels.unique()
    ) != {
        0,
        1,
    }:
        raise RuntimeError(
            "V19 route target requires both BTC and TOP3 examples"
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
            "V19 future or target information leaked into model features: "
            f"{sorted(leaked)}"
        )

    router = router.sort_values(
        "timestamp_utc"
    ).reset_index(
        drop=True
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_relative_top3_vs_btc_router_dataset"
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
            "v18_meta_gate_status": (
                "REJECT_CURRENT_V18_RANKER_META_GATE_HYPOTHESIS"
            ),
            "v15_ranker_refit_allowed": False,
        },
        "hypothesis": (
            "V15's cross-sectional ranking signal may be more useful for "
            "relative allocation than for market timing. Keeping paper-only "
            "gross crypto exposure fixed at 60%, a classifier conditioned on "
            "the frozen V15 score structure, BTC's relative score position, "
            "and point-in-time market context may distinguish when the frozen "
            "V15 top-three basket will outperform BTC over the next exact "
            "seven days."
        ),
        "relative_target": {
            "continuous": (
                RELATIVE_CONTINUOUS_TARGET
            ),
            "continuous_definition": (
                "mean frozen V15 top-3 net_terminal_return_7d_25bps minus "
                "BTC net_terminal_return_7d_25bps"
            ),
            "binary": (
                RELATIVE_BINARY_TARGET
            ),
            "binary_definition": (
                "1 when selected_top3_excess_vs_btc_net_terminal_7d_25bps > 0, else 0"
            ),
            "top3_label": 1,
            "btc_label": 0,
            "selection_count": TOP_K,
            "target_asset_level_cost_bps": (
                PRIMARY_COST_BPS
            ),
            "target_path_must_finish_before_holdout": True,
        },
        "v18_rank_diagnostic_feature_columns": list(
            V18_RANK_DIAGNOSTIC_FEATURES
        ),
        "btc_relative_feature_columns": list(
            BTC_RELATIVE_FEATURES
        ),
        "market_context_feature_columns": (
            market_features
        ),
        "model_feature_columns": (
            model_features
        ),
        "router_model": {
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
            "purge_days": PURGE_DAYS,
            "minimum_train_days": (
                MIN_TRAIN_DAYS
            ),
            "validation_days": (
                VALIDATION_DAYS
            ),
            "max_folds": MAX_FOLDS,
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
            "cash_weight_always": 0.40,
            "gross_crypto_weight_always": 0.60,
            "router_rule": (
                "if V19 predicts TOP3 class 1, simulate 20% each in the frozen "
                "V15 top three plus 40% cash; otherwise simulate 60% BTC plus "
                "40% cash"
            ),
            "top3_selected_asset_count": 3,
            "top3_asset_weight": 0.20,
            "btc_route_weight": 0.60,
            "maximum_gross_crypto_exposure": 0.60,
            "maximum_turnover_per_7d_decision": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
            "real_orders": False,
        },
        "portfolio_quality_gates": dict(
            FROZEN_PORTFOLIO_GATES
        ),
        "research_constraints": {
            "offline_research_only": True,
            "v15_oos_predictions_are_frozen_input": True,
            "v15_ranker_refit": False,
            "market_timing_or_cash_gate": False,
            "gross_crypto_weight_fixed_at_60pct": True,
            "cash_weight_fixed_at_40pct": True,
            "relative_target_fixed_before_fit": True,
            "zero_relative_excess_boundary_fixed_before_fit": True,
            "score_diagnostics_fixed_before_fit": True,
            "same_18_point_in_time_market_features_as_v16": True,
            "router_model_fixed_before_fit": True,
            "balanced_sample_weight_fixed_before_fit": True,
            "no_probability_threshold": True,
            "no_probability_threshold_search": True,
            "no_feature_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_gates_fixed_before_simulation": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
            "brokerage_orders": False,
        },
        "research_iteration_disclosure": (
            "V19 is motivated by the observed V15 portfolio failure and the "
            "V16/V17/V18 gating failures on the same pre-holdout development "
            "history. The relative top3-vs-BTC target, 34 features, model, "
            "walk-forward protocol, predictive gates, and later paper-only "
            "routing policy are fixed before any V19 fit. This carries "
            "substantial researcher-selection risk."
        ),
        "dataset": {
            "row_count": int(
                len(router)
            ),
            "start_utc": (
                router[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                router[
                    "timestamp_utc"
                ].max().isoformat()
            ),
            "route_top3_count": int(
                router[
                    RELATIVE_BINARY_TARGET
                ].sum()
            ),
            "route_btc_count": int(
                (
                    router[
                        RELATIVE_BINARY_TARGET
                    ]
                    == 0
                ).sum()
            ),
            "route_top3_fraction": float(
                router[
                    RELATIVE_BINARY_TARGET
                ].mean()
            ),
            "v18_rank_diagnostic_feature_count": int(
                len(
                    V18_RANK_DIAGNOSTIC_FEATURES
                )
            ),
            "btc_relative_feature_count": int(
                len(
                    BTC_RELATIVE_FEATURES
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

    return router, contract


def run(
    v15_phase2_root: Path = V15_PHASE2_ROOT,
    v15_phase4_root: Path = V15_PHASE4_ROOT,
    v16_phase1_root: Path = V16_PHASE1_ROOT,
    v18_phase3_root: Path = V18_PHASE3_ROOT,
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
    v18_phase3_root = Path(
        v18_phase3_root
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

    v18_adjudication = json.loads(
        (
            v18_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    router, contract = (
        build_router_dataset(
            v15_predictions,
            market_context,
            v15_manifest,
            v15_adjudication,
            v16_contract,
            v18_adjudication,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "relative_sleeve_router_dataset.parquet"
    )
    contract_path = (
        output_root
        / "preregistered_contract.json"
    )

    router.to_parquet(
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

    relative = pd.to_numeric(
        router[
            RELATIVE_CONTINUOUS_TARGET
        ],
        errors="raise",
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_relative_top3_vs_btc_router_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "dataset": contract[
            "dataset"
        ],
        "relative_target_distribution": {
            "mean": float(
                relative.mean()
            ),
            "median": float(
                relative.median()
            ),
            "minimum": float(
                relative.min()
            ),
            "maximum": float(
                relative.max()
            ),
        },
        "outputs": {
            "relative_sleeve_router_dataset": str(
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
            "relative_sleeve_router_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "offline_research_only": True,
            "shared_crypto_v15_modified": False,
            "shared_crypto_v16_modified": False,
            "shared_crypto_v18_modified": False,
            "v15_ranker_refit": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "probability_threshold_searched": False,
            "feature_search_performed": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Fit only the preregistered V19 balanced HGB relative router on "
            "the frozen TOP3-vs-BTC label with the fixed 34 features and "
            "purged walk-forward protocol. Require all four predictive gates "
            "before any offline portfolio simulation."
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
        "--v18-phase3-root",
        type=Path,
        default=V18_PHASE3_ROOT,
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
                args.v18_phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
