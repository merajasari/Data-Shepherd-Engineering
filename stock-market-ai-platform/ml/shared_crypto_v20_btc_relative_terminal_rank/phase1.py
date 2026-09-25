"""Shared Crypto V20 BTC-Relative Terminal Rank Phase 1.

OFFLINE RESEARCH ONLY.
No brokerage orders, no paper-state mutation, and no automatic promotion.

V20 is a separately preregistered successor after:
* V15 demonstrated strong cross-sectional ranking quality but its frozen
  always-deployed portfolio failed key BTC-relative and risk gates;
* V16/V17 broad market timing failed;
* V18 selected-basket deploy/cash timing failed; and
* V19 relative TOP3-vs-BTC binary routing reached 3/4 predictive gates but
  still failed minimum-class recall and was rejected before simulation.

V20 changes the research question materially by returning to asset-level
cross-sectional learning.

For every eligible asset on each decision date:
    raw_relative_target
        = asset net_terminal_return_7d_25bps
        - same-day BTC net_terminal_return_7d_25bps

The supervised target is the within-day percentile rank of that raw
BTC-relative terminal return.

This directly aligns the cross-sectional target with the economic weakness
seen in V15: outperforming BTC, rather than predicting broad market timing or
a day-level binary route.

V20 carries forward exactly the 22 V15 causal asset features, exact HGB
regressor specification, seven-day purge, 730-day minimum training history,
180-day validation windows, maximum eight folds, minimum 10-asset cross
section, and September 1, 2026 future holdout.

This phase builds and preregisters the dataset only. It fits no V20 model and
runs no portfolio simulation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v20_btc_relative_terminal_rank"

V15_VERSION = "shared_crypto_v15_cross_sectional_rank"
V19_VERSION = "shared_crypto_v19_relative_sleeve_router"

V15_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase1"
)
V15_PHASE2_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase2"
)
V15_PHASE4_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase4"
)
V19_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v19_relative_sleeve_router/phase3"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

BTC = "BTC-USD"
NET_TERMINAL = "net_terminal_return_7d_25bps"
BTC_NET_TERMINAL = "btc_net_terminal_return_7d_25bps"
RAW_RELATIVE_TARGET = (
    "btc_relative_net_terminal_return_7d_25bps"
)
RANK_TARGET = (
    "target_btc_relative_terminal_percentile_rank_7d"
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
MIN_CROSS_SECTION_ASSETS = 10

EXPECTED_PREDICTIVE_GATES = {
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


def _validate_lineage(
    v15_contract: dict,
    v15_phase2_manifest: dict,
    v15_adjudication: dict,
    v19_adjudication: dict,
) -> list[str]:
    if (
        v15_contract.get(
            "research_version"
        )
        != V15_VERSION
    ):
        raise RuntimeError(
            "V20 source contract is not Shared Crypto V15 Phase 1"
        )

    if (
        v15_contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V20 source holdout differs from V15"
        )

    features = list(
        v15_contract[
            "model_feature_columns"
        ]
    )

    if len(
        features
    ) != 22:
        raise RuntimeError(
            "V20 requires exactly the 22 frozen V15 asset features"
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
        v15_contract.get(
            "model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V20 requires the exact V15 HGB specification"
        )

    expected_walk = {
        "purge_days": PURGE_DAYS,
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "minimum_cross_section_assets": MIN_CROSS_SECTION_ASSETS,
    }

    if (
        v15_contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V20 requires the exact V15 walk-forward protocol"
        )

    if (
        v15_phase2_manifest.get(
            "research_version"
        )
        != V15_VERSION
        or v15_phase2_manifest.get(
            "predictive_gate_status"
        )
        != "ALLOW_POLICY_SIMULATION"
        or int(
            v15_phase2_manifest.get(
                "passed_predictive_gate_count",
                -1,
            )
        )
        != 4
    ):
        raise RuntimeError(
            "V20 requires the successful V15 predictive evidence"
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
            "V20 requires the immutable V15 portfolio rejection"
        )

    if (
        v19_adjudication.get(
            "research_version"
        )
        != V19_VERSION
        or v19_adjudication.get(
            "status"
        )
        != "REJECT_CURRENT_V19_RELATIVE_SLEEVE_ROUTER_HYPOTHESIS"
        or v19_adjudication.get(
            "offline_portfolio_simulation_allowed"
        )
        is not False
    ):
        raise RuntimeError(
            "V20 requires the immutable rejected V19 adjudication"
        )

    return features


def build_dataset(
    source: pd.DataFrame,
    v15_contract: dict,
    v15_phase2_manifest: dict,
    v15_adjudication: dict,
    v19_adjudication: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    features = _validate_lineage(
        v15_contract,
        v15_phase2_manifest,
        v15_adjudication,
        v19_adjudication,
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
        "V20 V15 source dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        NET_TERMINAL,
        "target_endpoint_utc_7d",
        "eligible_asset_count",
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
            "V20 source dataset missing columns: "
            f"{sorted(missing)}"
        )

    if (
        frame[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V20 source target path reaches the future holdout"
        )

    btc = frame[
        frame[
            "product_id"
        ]
        == BTC
    ][
        [
            "timestamp_utc",
            NET_TERMINAL,
        ]
    ].copy()

    counts = btc.groupby(
        "timestamp_utc"
    ).size()

    decision_days = (
        frame[
            "timestamp_utc"
        ]
        .drop_duplicates()
    )

    if (
        len(
            btc
        )
        != len(
            decision_days
        )
        or (
            counts
            != 1
        ).any()
    ):
        raise RuntimeError(
            "V20 requires exactly one BTC row on every decision day"
        )

    btc = btc.rename(
        columns={
            NET_TERMINAL: (
                BTC_NET_TERMINAL
            )
        }
    )

    frame = frame.merge(
        btc,
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )

    frame[
        RAW_RELATIVE_TARGET
    ] = (
        pd.to_numeric(
            frame[
                NET_TERMINAL
            ],
            errors="raise",
        )
        - pd.to_numeric(
            frame[
                BTC_NET_TERMINAL
            ],
            errors="raise",
        )
    )

    btc_relative = frame[
        frame[
            "product_id"
        ]
        == BTC
    ][
        RAW_RELATIVE_TARGET
    ].to_numpy(
        dtype=float
    )

    if not np.allclose(
        btc_relative,
        0.0,
        rtol=0.0,
        atol=1e-12,
    ):
        raise RuntimeError(
            "V20 BTC relative terminal target must equal zero"
        )

    frame[
        RANK_TARGET
    ] = (
        frame.groupby(
            "timestamp_utc"
        )[
            RAW_RELATIVE_TARGET
        ]
        .rank(
            pct=True
        )
    )

    finite = frame[
        [
            *features,
            NET_TERMINAL,
            BTC_NET_TERMINAL,
            RAW_RELATIVE_TARGET,
            RANK_TARGET,
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
            "V20 source contains non-finite features or targets"
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
            "V20 dataset violates minimum cross-section breadth"
        )

    model_frame = frame[
        [
            "timestamp_utc",
            "product_id",
            *features,
            RANK_TARGET,
            RAW_RELATIVE_TARGET,
            NET_TERMINAL,
            BTC_NET_TERMINAL,
            "eligible_asset_count",
            "target_endpoint_utc_7d",
        ]
    ].sort_values(
        [
            "timestamp_utc",
            "product_id",
        ]
    ).reset_index(
        drop=True
    )

    selection_gates = dict(
        v15_contract[
            "selection_gates"
        ]
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_exact_7d_btc_relative_terminal_rank_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "lineage": {
            "source_dataset": (
                "shared_crypto_v15_cross_sectional_rank Phase 1 "
                "asset_cross_sectional_rank_dataset.parquet"
            ),
            "v15_predictive_status": (
                "ALLOW_POLICY_SIMULATION"
            ),
            "v15_portfolio_status": (
                "REJECT_CURRENT_V15_POLICY_FAMILY"
            ),
            "v19_status": (
                "REJECT_CURRENT_V19_RELATIVE_SLEEVE_ROUTER_HYPOTHESIS"
            ),
            "source_model_predictions_used": False,
            "source_portfolio_results_used_as_target": False,
        },
        "hypothesis": (
            "V15 established that the frozen 22-feature HGB can learn useful "
            "cross-sectional ordering, but the path-utility rank target did "
            "not translate into stable BTC-relative portfolio performance. "
            "Training the same model directly on the within-day rank of exact "
            "seven-day net terminal return relative to BTC may align the "
            "learning objective with the missing economic property while "
            "avoiding day-level timing or binary routing."
        ),
        "learning_target": {
            "primary": (
                RANK_TARGET
            ),
            "definition": (
                "within-timestamp percentile rank of each asset's "
                "net_terminal_return_7d_25bps minus same-day BTC "
                "net_terminal_return_7d_25bps; higher is better"
            ),
            "raw_economic_target": (
                RAW_RELATIVE_TARGET
            ),
            "btc_reference_return": (
                BTC_NET_TERMINAL
            ),
            "btc_raw_relative_target_is_zero": True,
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
            "purge_days": PURGE_DAYS,
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
            "research_mode": (
                "offline_paper_simulation_only"
            ),
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "selection_rule": (
                "rank eligible assets by predicted V20 BTC-relative terminal "
                "percentile and select exactly the top 3; no prediction "
                "threshold or day-level market-timing gate"
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
        "selection_gates": (
            selection_gates
        ),
        "research_constraints": {
            "offline_research_only": True,
            "asset_level_cross_sectional_learning": True,
            "day_level_binary_gate": False,
            "same_22_features_as_v15": True,
            "same_model_specification_as_v15": True,
            "same_walk_forward_protocol_as_v15": True,
            "btc_relative_terminal_target_fixed_before_fit": True,
            "predictive_gates_fixed_before_fit": True,
            "no_model_family_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "no_probability_threshold": True,
            "no_post_result_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V20 is motivated by V15's observed BTC-relative portfolio "
            "failure and the subsequent V16-V19 gate failures on the same "
            "pre-holdout development history. The BTC-relative terminal-rank "
            "target, exact 22 features, model, walk-forward protocol, five "
            "predictive gates, and later paper-only policy are fixed before "
            "any V20 model fitting. This carries substantial "
            "researcher-selection risk."
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
            "raw_relative_target_mean": float(
                model_frame[
                    RAW_RELATIVE_TARGET
                ].mean()
            ),
            "raw_relative_target_median": float(
                model_frame[
                    RAW_RELATIVE_TARGET
                ].median()
            ),
            "raw_relative_target_positive_fraction": float(
                (
                    model_frame[
                        RAW_RELATIVE_TARGET
                    ]
                    > 0.0
                ).mean()
            ),
        },
    }

    return (
        model_frame,
        contract,
    )


def run(
    v15_phase1_root: Path = V15_PHASE1_ROOT,
    v15_phase2_root: Path = V15_PHASE2_ROOT,
    v15_phase4_root: Path = V15_PHASE4_ROOT,
    v19_phase3_root: Path = V19_PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    v15_phase1_root = Path(
        v15_phase1_root
    )
    v15_phase2_root = Path(
        v15_phase2_root
    )
    v15_phase4_root = Path(
        v15_phase4_root
    )
    v19_phase3_root = Path(
        v19_phase3_root
    )
    output_root = Path(
        output_root
    )

    v15_contract = json.loads(
        (
            v15_phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    source = pd.read_parquet(
        v15_phase1_root
        / "asset_cross_sectional_rank_dataset.parquet"
    )

    v15_phase2_manifest = json.loads(
        (
            v15_phase2_root
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    v15_adjudication = json.loads(
        (
            v15_phase4_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    v19_adjudication = json.loads(
        (
            v19_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    dataset, contract = build_dataset(
        source,
        v15_contract,
        v15_phase2_manifest,
        v15_adjudication,
        v19_adjudication,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "asset_btc_relative_terminal_rank_dataset.parquet"
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

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_exact_7d_btc_relative_terminal_rank_dataset"
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
            "shared_crypto_v15_modified": False,
            "shared_crypto_v19_modified": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "feature_search_performed": False,
            "model_family_searched": False,
            "hyperparameters_tuned": False,
            "threshold_search_performed": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Fit only the preregistered V20 HGB regressor on the BTC-relative "
            "terminal percentile-rank target using the frozen V15 22-feature "
            "walk-forward protocol. Require all five frozen predictive gates "
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
        "--v15-phase1-root",
        type=Path,
        default=V15_PHASE1_ROOT,
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
        "--v19-phase3-root",
        type=Path,
        default=V19_PHASE3_ROOT,
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
                args.v15_phase1_root,
                args.v15_phase2_root,
                args.v15_phase4_root,
                args.v19_phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
