"""Shared Crypto V14 Path Utility Rank Phase 1.

Research-family reset after V8-V13.

V8-V13 repeatedly attempted to infer a BTC-versus-deviation boundary from the
same pre-holdout research history. V13 ended with Stage 1 median balanced
accuracy below 50% and a slightly negative MCC. V14 therefore changes the task
itself instead of changing another classifier.

V14 uses the frozen ten-year canonical DAILY OHLCV history and predicts a new
asset-level exact 7-day path-utility target for every eligible asset, including
BTC. CASH is not a model class. Later policy simulation, if predictive gates
are passed, may abstain to cash when no asset has positive predicted utility.

The path-utility target uses only observed exact daily closes t+1 through t+7:

    net_terminal_return_7d_25bps
        = close(t+7) / close(t) - 1 - 0.0025

    maximum_adverse_close_return_7d
        = min(0, close(t+1..t+7) / close(t) - 1)

    path_utility_net25_7d
        = net_terminal_return_7d_25bps
          - abs(maximum_adverse_close_return_7d)

Thus a path that reaches the same endpoint with a deeper adverse excursion gets
a lower target. The full seven-day target path must end strictly before the
2026-09-01 future holdout.

This phase builds and preregisters the dataset only. It fits no model, performs
no portfolio simulation, and does not score the future holdout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v2.prepare_dataset import (
    REQUIRED_FEATURES,
    add_features_and_eligibility,
    load_canonical_history,
)


RESEARCH_VERSION = "shared_crypto_v14_path_utility_rank"
CANONICAL_ROOT = Path(
    "data/research/crypto_ten_year/canonical"
)
CANONICAL_HISTORY = (
    CANONICAL_ROOT
    / "canonical_history.parquet"
)
CANONICAL_MANIFEST = (
    CANONICAL_ROOT
    / "canonical_manifest.json"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v14_path_utility_rank/phase1"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)
HORIZON_DAYS = 7
PRIMARY_COST_BPS = 25.0
STRESS_COST_BPS = 50.0
MIN_CROSS_SECTION_ASSETS = 10

TARGET = "path_utility_net25_7d"
TERMINAL_TARGET = "net_terminal_return_7d_25bps"
ADVERSE_TARGET = "maximum_adverse_close_return_7d"
FAVORABLE_TARGET = "maximum_favorable_close_return_7d"

PRIMARY_MODEL = "hist_gradient_boosting_regressor"
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0

MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 8
PURGE_DAYS = HORIZON_DAYS


def _sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with Path(
        path
    ).open(
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


def attach_exact_future_path(
    featured: pd.DataFrame,
) -> pd.DataFrame:
    result = featured.copy()

    result[
        "timestamp_utc"
    ] = pd.to_datetime(
        result[
            "timestamp_utc"
        ],
        utc=True,
    )

    validate_pre_holdout(
        result,
        "V14 featured source",
    )

    if result.duplicated(
        [
            "product_id",
            "timestamp_utc",
        ]
    ).any():
        raise RuntimeError(
            "V14 source contains duplicate product/timestamp rows"
        )

    price_lookup = result[
        [
            "product_id",
            "timestamp_utc",
            "close",
        ]
    ].copy()

    for day in range(
        1,
        HORIZON_DAYS + 1,
    ):
        endpoint_column = (
            f"target_endpoint_utc_{day}d"
        )
        future_close_column = (
            f"future_close_{day}d"
        )

        result[
            endpoint_column
        ] = (
            result[
                "timestamp_utc"
            ]
            + pd.Timedelta(
                days=day
            )
        )

        lookup = price_lookup.rename(
            columns={
                "timestamp_utc": (
                    endpoint_column
                ),
                "close": (
                    future_close_column
                ),
            }
        )

        result = result.merge(
            lookup,
            on=[
                "product_id",
                endpoint_column,
            ],
            how="left",
            validate="many_to_one",
        )

        result[
            f"future_close_return_{day}d"
        ] = (
            pd.to_numeric(
                result[
                    future_close_column
                ],
                errors="coerce",
            )
            / pd.to_numeric(
                result[
                    "close"
                ],
                errors="coerce",
            )
            - 1.0
        )

    return result


def build_path_utility_dataset(
    featured: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    frame = attach_exact_future_path(
        featured
    )

    feature_columns = list(
        REQUIRED_FEATURES
    )

    required = {
        "timestamp_utc",
        "product_id",
        "close",
        "source_provider",
        "source_granularity",
        "is_eligible",
        *feature_columns,
    }

    missing = (
        required
        - set(
            frame.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V14 featured source missing columns: "
            f"{sorted(missing)}"
        )

    path_return_columns = [
        f"future_close_return_{day}d"
        for day in range(
            1,
            HORIZON_DAYS + 1,
        )
    ]

    future_close_columns = [
        f"future_close_{day}d"
        for day in range(
            1,
            HORIZON_DAYS + 1,
        )
    ]

    last_endpoint = (
        f"target_endpoint_utc_{HORIZON_DAYS}d"
    )

    frame = frame[
        frame[
            "is_eligible"
        ].fillna(
            False
        ).astype(
            bool
        )
    ].copy()

    frame = frame[
        frame[
            last_endpoint
        ]
        < HOLDOUT
    ].copy()

    frame = frame.replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    ).dropna(
        subset=(
            feature_columns
            + future_close_columns
            + path_return_columns
        )
    ).copy()

    if frame.empty:
        raise RuntimeError(
            "V14 path-utility dataset is empty after exact-path requirements"
        )

    path_values = frame[
        path_return_columns
    ].to_numpy(
        dtype=float
    )

    terminal_return = (
        path_values[
            :,
            -1,
        ]
    )

    maximum_adverse = np.minimum(
        np.min(
            path_values,
            axis=1,
        ),
        0.0,
    )

    maximum_favorable = np.maximum(
        np.max(
            path_values,
            axis=1,
        ),
        0.0,
    )

    cost = (
        PRIMARY_COST_BPS
        / 10000.0
    )

    frame[
        TERMINAL_TARGET
    ] = (
        terminal_return
        - cost
    )

    frame[
        ADVERSE_TARGET
    ] = (
        maximum_adverse
    )

    frame[
        FAVORABLE_TARGET
    ] = (
        maximum_favorable
    )

    frame[
        TARGET
    ] = (
        frame[
            TERMINAL_TARGET
        ]
        - np.abs(
            frame[
                ADVERSE_TARGET
            ]
        )
    )

    daily_counts = (
        frame.groupby(
            "timestamp_utc"
        )[
            "product_id"
        ]
        .transform(
            "nunique"
        )
    )

    frame = frame[
        daily_counts
        >= MIN_CROSS_SECTION_ASSETS
    ].copy()

    frame[
        "eligible_asset_count"
    ] = (
        frame.groupby(
            "timestamp_utc"
        )[
            "product_id"
        ]
        .transform(
            "nunique"
        )
    )

    frame[
        "target_path_utility_percentile_rank_7d"
    ] = (
        frame.groupby(
            "timestamp_utc"
        )[
            TARGET
        ]
        .rank(
            pct=True
        )
    )

    descending = (
        frame.groupby(
            "timestamp_utc"
        )[
            TARGET
        ]
        .rank(
            method="first",
            ascending=False,
        )
    )

    frame[
        "target_top3_path_utility_7d"
    ] = (
        descending
        <= 3
    )

    forbidden_feature_tokens = (
        "future_",
        "target_",
        "forward_",
        "endpoint",
        "source_provider",
        "source_granularity",
        "path_utility",
        "maximum_adverse",
        "maximum_favorable",
        "net_terminal",
    )

    leaked = [
        column
        for column
        in feature_columns
        if any(
            token
            in column.lower()
            for token
            in forbidden_feature_tokens
        )
    ]

    if leaked:
        raise RuntimeError(
            "V14 future/provenance information leaked into model features: "
            f"{sorted(leaked)}"
        )

    if (
        frame[
            last_endpoint
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V14 target path reaches the future holdout"
        )

    frame = frame.sort_values(
        [
            "timestamp_utc",
            "product_id",
        ]
    ).reset_index(
        drop=True
    )

    daily_asset_counts = (
        frame.groupby(
            "timestamp_utc"
        )[
            "product_id"
        ]
        .nunique()
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_exact_7d_asset_path_utility_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "research_family_reset": {
            "exhausted_family": (
                "shared_crypto_v8_through_v13_btc_vs_deviate_and_sleeve_classification"
            ),
            "closed_versions": [
                "shared_crypto_v8_relative_value_linear",
                "shared_crypto_v9_deviation_classifier",
                "shared_crypto_v10_regime_ranker",
                "shared_crypto_v11_hierarchical_selector",
                "shared_crypto_v12_btc_specialist",
                "shared_crypto_v13_regime_transition",
            ],
            "prior_models_retuned": False,
            "prior_gates_weakened": False,
            "prior_portfolios_simulated_after_predictive_failure": False,
            "new_task": (
                "asset_level_regression_and_cross_sectional_ranking"
            ),
            "cash_representation": (
                "abstention_if_no_positive_predicted_utility"
            ),
        },
        "hypothesis": (
            "A direct asset-level target that rewards seven-day terminal return "
            "while penalizing adverse path excursion may be more learnable and "
            "more economically aligned than classifying which aggregate sleeve "
            "wins. Ranking all eligible assets, including BTC, also removes the "
            "repeated BTC-versus-DEVIATE boundary."
        ),
        "source": {
            "dataset": (
                "frozen ten-year canonical daily OHLCV history"
            ),
            "provider_provenance_retained": True,
            "provider_provenance_used_as_feature": False,
            "synthetic_rows_allowed": False,
            "interpolation_allowed": False,
            "calendar_gap_bridging_allowed": False,
        },
        "decision_cadence": (
            "daily research observations; later portfolio decisions use non-overlapping 7-day blocks"
        ),
        "economic_horizon": (
            "exact seven calendar days"
        ),
        "target": {
            "primary": (
                TARGET
            ),
            "definition": (
                "net_terminal_return_7d_25bps minus absolute maximum adverse "
                "close return from entry across exact t+1 through t+7 closes"
            ),
            "primary_round_trip_cost_bps": (
                PRIMARY_COST_BPS
            ),
            "path_requires_all_seven_exact_daily_closes": True,
            "target_path_must_finish_before_holdout": True,
        },
        "model_feature_columns": (
            feature_columns
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
            "random_state": 1729,
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
        "predictive_quality_gates": {
            "median_fold_daily_spearman_ic_gt": (
                0.05
            ),
            "median_fold_positive_ic_day_fraction_gt": (
                0.52
            ),
            "median_fold_top3_target_utility_excess_vs_universe_gt": (
                0.0
            ),
            "positive_fold_top3_target_utility_excess_fraction_gte": (
                0.75
            ),
            "all_gates_required_before_portfolio_simulation": True,
        },
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "selection_rule": (
                "rank eligible assets by predicted path utility; select up to "
                "top 3 assets whose predicted utility is strictly positive; "
                "unallocated weight remains CASH"
            ),
            "asset_weight": (
                0.20
            ),
            "maximum_selected_assets": (
                3
            ),
            "minimum_cash_weight": (
                0.40
            ),
            "maximum_gross_crypto_exposure": (
                0.60
            ),
            "primary_round_trip_cost_bps": (
                PRIMARY_COST_BPS
            ),
            "stress_round_trip_cost_bps": (
                STRESS_COST_BPS
            ),
            "maximum_turnover_per_7d_decision": (
                0.60
            ),
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": {
            "median_fold_net_return_gt": (
                0.0
            ),
            "positive_fold_fraction_gte": (
                0.80
            ),
            "median_excess_vs_always_btc_gt": (
                0.0
            ),
            "median_excess_vs_shared_crypto_v3_gt": (
                0.0
            ),
            "positive_excess_vs_shared_crypto_v3_fraction_gte": (
                0.80
            ),
            "worst_maximum_drawdown_gte": (
                -0.20
            ),
            "single_fold_profit_concentration_lte": (
                0.40
            ),
            "survives_stress_cost_bps": (
                STRESS_COST_BPS
            ),
        },
        "research_constraints": {
            "new_target_family_fixed_before_fit": True,
            "one_primary_model_family": True,
            "no_secondary_model_search": True,
            "no_post_result_threshold_search": True,
            "zero_predicted_utility_abstention_threshold_fixed_before_fit": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "dataset": {
            "row_count": int(
                len(
                    frame
                )
            ),
            "product_count": int(
                frame[
                    "product_id"
                ].nunique()
            ),
            "decision_day_count": int(
                frame[
                    "timestamp_utc"
                ].nunique()
            ),
            "minimum_daily_assets": int(
                daily_asset_counts.min()
            ),
            "median_daily_assets": float(
                daily_asset_counts.median()
            ),
            "maximum_daily_assets": int(
                daily_asset_counts.max()
            ),
            "start_utc": (
                frame[
                    "timestamp_utc"
                ].min().isoformat()
            ),
            "end_utc": (
                frame[
                    "timestamp_utc"
                ].max().isoformat()
            ),
        },
    }

    return (
        frame,
        contract,
    )


def run(
    canonical_history: Path = CANONICAL_HISTORY,
    canonical_manifest: Path = CANONICAL_MANIFEST,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    canonical_history = Path(
        canonical_history
    )
    canonical_manifest = Path(
        canonical_manifest
    )
    output_root = Path(
        output_root
    )

    if not canonical_history.exists():
        raise FileNotFoundError(
            canonical_history
        )

    if not canonical_manifest.exists():
        raise FileNotFoundError(
            canonical_manifest
        )

    canonical_hash_before = _sha256(
        canonical_history
    )
    manifest_hash_before = _sha256(
        canonical_manifest
    )

    canonical = load_canonical_history(
        canonical_history,
        completed_before_utc=HOLDOUT,
    )

    featured = (
        add_features_and_eligibility(
            canonical
        )
    )

    dataset, contract = (
        build_path_utility_dataset(
            featured
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "asset_path_utility_dataset.parquet"
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

    canonical_hash_after = _sha256(
        canonical_history
    )
    manifest_hash_after = _sha256(
        canonical_manifest
    )

    if (
        canonical_hash_before
        != canonical_hash_after
        or manifest_hash_before
        != manifest_hash_after
    ):
        raise RuntimeError(
            "V14 frozen canonical source changed during Phase 1"
        )

    target = dataset[
        TARGET
    ]

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_exact_7d_asset_path_utility_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "source": {
            "canonical_history": str(
                canonical_history
            ),
            "canonical_history_sha256": (
                canonical_hash_before
            ),
            "canonical_manifest": str(
                canonical_manifest
            ),
            "canonical_manifest_sha256": (
                manifest_hash_before
            ),
            "canonical_rows_loaded_pre_holdout": int(
                len(
                    canonical
                )
            ),
            "canonical_product_count": int(
                canonical[
                    "product_id"
                ].nunique()
            ),
        },
        "dataset": (
            contract[
                "dataset"
            ]
        ),
        "target_distribution": {
            "mean": float(
                target.mean()
            ),
            "median": float(
                target.median()
            ),
            "positive_fraction": float(
                (
                    target
                    > 0.0
                ).mean()
            ),
            "top3_label_fraction": float(
                dataset[
                    "target_top3_path_utility_7d"
                ].mean()
            ),
        },
        "model_feature_count": int(
            len(
                contract[
                    "model_feature_columns"
                ]
            )
        ),
        "outputs": {
            "asset_path_utility_dataset": str(
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
            "asset_path_utility_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "shared_crypto_v13_modified": False,
            "shared_crypto_v12_modified": False,
            "shared_crypto_v11_modified": False,
            "shared_crypto_v10_modified": False,
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Run the preregistered purged walk-forward V14 asset-level "
            "path-utility regressor. Require all predictive ranking gates before "
            "any non-overlapping 7-day portfolio simulation."
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
        "--canonical-history",
        type=Path,
        default=CANONICAL_HISTORY,
    )

    parser.add_argument(
        "--canonical-manifest",
        type=Path,
        default=CANONICAL_MANIFEST,
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
                args.canonical_history,
                args.canonical_manifest,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
