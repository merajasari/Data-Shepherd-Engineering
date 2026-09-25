"""Shared Crypto V13 Regime Transition Phase 1.

V13 is a separately preregistered successor to rejected V12.

V10, V11, and V12 changed decision structure and model family while keeping
essentially the same contemporaneous information set. V12 passed seven of nine
predictive gates but Stage 1 BTC-vs-DEVIATE remained near chance.

V13 changes only the information set. It keeps V12's exact Stage 1
HistGradientBoosting specification, exact Stage 2 balanced LinearSVC
specification, exact 72-hour walk-forward protocol, and exact nine predictive
gates. It adds point-in-time regime-transition features using exact 24-hour and
72-hour lags of a small preregistered set of BTC and ALT state variables.

No V13 model is fit in this phase. No portfolio is simulated. The September 1,
2026 future holdout remains untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v13_regime_transition"
SOURCE_VERSION = "shared_crypto_v12_btc_specialist"
SOURCE_ROOT = Path(
    "data/model/shared_crypto_v12_btc_specialist/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v13_regime_transition/phase1"
)
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

SOURCE_TARGET = "best_sleeve_net25_72h"
STAGE1_TARGET = "btc_vs_deviate_72h"
STAGE2_TARGET = "alt_vs_cash_when_deviate_72h"

TRANSITION_BASE_FEATURES = (
    "btc_return_96bar",
    "btc_realized_volatility_96bar",
    "btc_drawdown_from_high_96bar",
    "alt_outperforming_btc_4bar_fraction",
    "alt_mean_btc_relative_return_16bar",
    "alt_volatility_dispersion",
)
TRANSITION_LAG_HOURS = (
    24,
    72,
)

EXPECTED_STAGE1_MODEL = {
    "primary": "hist_gradient_boosting_classifier",
    "learning_rate": 0.05,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "max_depth": None,
    "min_samples_leaf": 30,
    "l2_regularization": 1.0,
    "class_weight": "balanced",
    "random_state": 1729,
    "secondary_models": [],
    "probability_calibration": None,
}

EXPECTED_STAGE2_MODEL = {
    "primary": "linear_svc",
    "C": 0.25,
    "loss": "squared_hinge",
    "penalty": "l2",
    "class_weight": "balanced",
    "dual": "auto",
    "max_iter": 10000,
    "standardize_features": True,
    "random_state": 1729,
    "secondary_models": [],
    "probability_calibration": None,
}

EXPECTED_PREDICTIVE_GATES = {
    "stage1_median_balanced_accuracy_gt": 0.52,
    "stage1_median_mcc_gt": 0.0,
    "stage2_median_balanced_accuracy_gt": 0.52,
    "stage2_median_mcc_gt": 0.0,
    "combined_median_balanced_accuracy_gt": 0.36,
    "combined_median_macro_f1_gt": 0.36,
    "combined_median_accuracy_improvement_vs_train_majority_gt": 0.0,
    "combined_median_multiclass_mcc_gt": 0.0,
    "combined_median_minimum_class_recall_gt": 0.20,
    "all_gates_required_before_portfolio_simulation": True,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def _validate_source_contract(
    source_contract: dict,
) -> None:
    if (
        source_contract.get(
            "research_version"
        )
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V13 source contract is not Shared Crypto V12 Phase 1"
        )

    if (
        source_contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V13 source holdout boundary differs from preregistration"
        )

    models = source_contract.get(
        "models",
        {},
    )
    if (
        models.get("stage1")
        != EXPECTED_STAGE1_MODEL
    ):
        raise RuntimeError(
            "V13 requires the exact frozen V12 Stage 1 specification"
        )
    if (
        models.get("stage2")
        != EXPECTED_STAGE2_MODEL
    ):
        raise RuntimeError(
            "V13 requires the exact frozen V12 Stage 2 specification"
        )

    if (
        source_contract.get(
            "predictive_quality_gates"
        )
        != EXPECTED_PREDICTIVE_GATES
    ):
        raise RuntimeError(
            "V13 requires the exact V12 predictive gates"
        )


def _attach_exact_transition_features(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    result = frame.copy()
    result["timestamp_utc"] = pd.to_datetime(
        result["timestamp_utc"],
        utc=True,
    )

    missing = (
        set(
            TRANSITION_BASE_FEATURES
        )
        - set(
            result.columns
        )
    )
    if missing:
        raise RuntimeError(
            f"V13 source dataset missing transition bases: {sorted(missing)}"
        )

    new_features: list[str] = []

    for lag_hours in TRANSITION_LAG_HOURS:
        lag_source = result[
            [
                "timestamp_utc",
                *TRANSITION_BASE_FEATURES,
            ]
        ].copy()
        lag_source[
            "timestamp_utc"
        ] = (
            lag_source[
                "timestamp_utc"
            ]
            + timedelta(
                hours=int(
                    lag_hours
                )
            )
        )

        rename = {
            feature: (
                f"{feature}_lag_{lag_hours}h"
            )
            for feature
            in TRANSITION_BASE_FEATURES
        }
        lag_source = (
            lag_source.rename(
                columns=rename
            )
        )

        result = result.merge(
            lag_source,
            on="timestamp_utc",
            how="left",
            validate="one_to_one",
        )

        for feature in (
            TRANSITION_BASE_FEATURES
        ):
            lag_name = (
                f"{feature}_lag_{lag_hours}h"
            )
            delta_name = (
                f"{feature}_delta_{lag_hours}h"
            )

            result[
                delta_name
            ] = (
                pd.to_numeric(
                    result[
                        feature
                    ],
                    errors="coerce",
                )
                - pd.to_numeric(
                    result[
                        lag_name
                    ],
                    errors="coerce",
                )
            )

            new_features.extend([
                lag_name,
                delta_name,
            ])

    return result, new_features


def build_dataset(
    source: pd.DataFrame,
    source_contract: dict,
) -> tuple[pd.DataFrame, dict]:
    _validate_source_contract(
        source_contract
    )

    frame = source.copy()
    frame["timestamp_utc"] = (
        pd.to_datetime(
            frame[
                "timestamp_utc"
            ],
            utc=True,
        )
    )

    validate_pre_holdout(
        frame,
        "V13 source specialist dataset",
    )

    base_features = list(
        source_contract[
            "regime_feature_columns"
        ]
    )

    required = {
        "timestamp_utc",
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
        "alt_basket_assets",
        *base_features,
        *TRANSITION_BASE_FEATURES,
    }
    missing = (
        required
        - set(
            frame.columns
        )
    )
    if missing:
        raise RuntimeError(
            f"V13 source dataset missing columns: {sorted(missing)}"
        )

    frame, transition_features = (
        _attach_exact_transition_features(
            frame
        )
    )

    model_features = (
        base_features
        + transition_features
    )

    forbidden = {
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        "alt_excess_vs_btc_net25_72h",
        "cash_excess_vs_btc_net25_72h",
        "oracle_best_deviation_net25_72h",
        "oracle_best_excess_vs_btc_net25_72h",
        "alt_basket_assets",
    }

    leaked = (
        forbidden
        & set(
            model_features
        )
    )
    if leaked:
        raise RuntimeError(
            f"V13 future information leaked into model features: {sorted(leaked)}"
        )

    frame = frame.replace(
        [np.inf, -np.inf],
        np.nan,
    ).dropna(
        subset=[
            SOURCE_TARGET,
            STAGE1_TARGET,
            *model_features,
        ]
    ).copy()

    if set(
        frame[
            SOURCE_TARGET
        ].astype(str).unique()
    ) != {
        "BTC",
        "ALT",
        "CASH",
    }:
        raise RuntimeError(
            "V13 source best-sleeve target must contain BTC, ALT, and CASH"
        )

    if set(
        frame[
            STAGE1_TARGET
        ].astype(str).unique()
    ) != {
        "BTC",
        "DEVIATE",
    }:
        raise RuntimeError(
            "V13 Stage 1 target must contain BTC and DEVIATE"
        )

    stage2 = frame[
        frame[
            STAGE2_TARGET
        ].notna()
    ].copy()

    if set(
        stage2[
            STAGE2_TARGET
        ].astype(str).unique()
    ) != {
        "ALT",
        "CASH",
    }:
        raise RuntimeError(
            "V13 Stage 2 target must contain ALT and CASH"
        )

    keep = [
        "timestamp_utc",
        *model_features,
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
        "alt_basket_assets",
    ]

    for optional in (
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        "alt_excess_vs_btc_net25_72h",
        "cash_excess_vs_btc_net25_72h",
        "oracle_best_deviation_net25_72h",
    ):
        if optional in (
            frame.columns
        ):
            keep.append(
                optional
            )

    dataset = (
        frame[
            list(
                dict.fromkeys(
                    keep
                )
            )
        ]
        .sort_values(
            "timestamp_utc"
        )
        .reset_index(
            drop=True
        )
    )

    contract = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "stage": (
            "preregistered_72h_regime_transition_hierarchical_dataset"
        ),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "source": {
            "research_version": (
                SOURCE_VERSION
            ),
            "phase": 1,
            "reused_point_in_time_features": True,
            "source_model_predictions_used": False,
            "source_portfolio_results_used": False,
        },
        "new_hypothesis_after_rejection": {
            "rejected_parent": (
                SOURCE_VERSION
            ),
            "parent_disposition": (
                "REJECT_CURRENT_V12_PREDICTIVE_HYPOTHESIS"
            ),
            "observed_v12_failure": {
                "passed_predictive_gate_count": 7,
                "total_predictive_gate_count": 9,
                "stage1_median_balanced_accuracy": (
                    0.5096965903472823
                ),
                "stage1_median_mcc": (
                    0.0187458422777551
                ),
                "stage2_median_balanced_accuracy": (
                    0.5553788867145031
                ),
                "stage2_median_mcc": (
                    0.1274398857269659
                ),
                "combined_median_balanced_accuracy": (
                    0.3769141085010856
                ),
                "combined_median_macro_f1": (
                    0.3628112800930041
                ),
                "combined_median_accuracy_improvement_vs_train_majority": (
                    -0.0113636363636363
                ),
            },
            "v12_models_retuned": False,
            "v12_gates_changed": False,
            "v12_portfolio_simulated": False,
        },
        "hypothesis": (
            "BTC-versus-DEVIATE may depend less on the contemporaneous level "
            "of market-state variables than on whether those variables are "
            "improving or deteriorating. Exact 24-hour and 72-hour lag and "
            "delta features may expose regime transition and persistence "
            "information that was absent from V12."
        ),
        "feature_engineering": {
            "base_regime_feature_count": int(
                len(
                    base_features
                )
            ),
            "transition_base_features": list(
                TRANSITION_BASE_FEATURES
            ),
            "exact_lag_hours": list(
                TRANSITION_LAG_HOURS
            ),
            "per_base_feature_outputs": [
                "exact_lag",
                "current_minus_exact_lag",
            ],
            "transition_feature_count": int(
                len(
                    transition_features
                )
            ),
            "row_shift_used": False,
            "future_data_used": False,
            "timestamps_joined_exactly": True,
        },
        "regime_feature_columns": (
            model_features
        ),
        "models": {
            "stage1": dict(
                EXPECTED_STAGE1_MODEL
            ),
            "stage2": dict(
                EXPECTED_STAGE2_MODEL
            ),
        },
        "walk_forward": dict(
            source_contract[
                "walk_forward"
            ]
        ),
        "predictive_quality_gates": dict(
            EXPECTED_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": dict(
            source_contract[
                "frozen_policy_for_later_simulation"
            ]
        ),
        "selection_gates": dict(
            source_contract[
                "selection_gates"
            ]
        ),
        "research_constraints": {
            "models_carried_forward_unchanged_from_v12": True,
            "predictive_gates_carried_forward_unchanged_from_v12": True,
            "portfolio_gates_carried_forward_unchanged_from_v12": True,
            "only_information_set_changed": True,
            "transition_features_fixed_before_fit": True,
            "exact_timestamp_lags_only": True,
            "no_model_family_search": True,
            "no_secondary_model_search": True,
            "no_probability_calibration": True,
            "no_confidence_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "nonoverlapping_72h_evaluation_required": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V13 is another development iteration on the same pre-holdout "
            "history. Its new feature family is preregistered before fitting. "
            "A predictive pass would justify only the next frozen portfolio-"
            "evaluation stage, not deployment or a holdout-performance claim."
        ),
    }

    return dataset, contract


def run(
    source_root: Path = SOURCE_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_root = Path(
        source_root
    )
    output_root = Path(
        output_root
    )

    source_contract = json.loads(
        (
            source_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    source = pd.read_parquet(
        source_root
        / "daily_specialist_dataset.parquet"
    )

    dataset, contract = (
        build_dataset(
            source,
            source_contract,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "daily_regime_transition_dataset.parquet"
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

    stage1_counts = (
        dataset[
            STAGE1_TARGET
        ].value_counts()
    )
    stage2 = dataset[
        dataset[
            STAGE2_TARGET
        ].notna()
    ].copy()
    stage2_counts = (
        stage2[
            STAGE2_TARGET
        ].value_counts()
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 1,
        "stage": (
            "preregistered_72h_regime_transition_hierarchical_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "source_rows": int(
            len(
                source
            )
        ),
        "dataset_rows": int(
            len(
                dataset
            )
        ),
        "stage2_rows": int(
            len(
                stage2
            )
        ),
        "base_feature_count": int(
            len(
                source_contract[
                    "regime_feature_columns"
                ]
            )
        ),
        "transition_feature_count": int(
            contract[
                "feature_engineering"
            ][
                "transition_feature_count"
            ]
        ),
        "model_feature_count": int(
            len(
                contract[
                    "regime_feature_columns"
                ]
            )
        ),
        "date_range": {
            "start": dataset[
                "timestamp_utc"
            ].min().isoformat(),
            "end": dataset[
                "timestamp_utc"
            ].max().isoformat(),
        },
        "stage1_class_balance": {
            label: {
                "count": int(
                    stage1_counts.get(
                        label,
                        0,
                    )
                ),
                "fraction": float(
                    (
                        dataset[
                            STAGE1_TARGET
                        ]
                        == label
                    ).mean()
                ),
            }
            for label in (
                "BTC",
                "DEVIATE",
            )
        },
        "stage2_class_balance": {
            label: {
                "count": int(
                    stage2_counts.get(
                        label,
                        0,
                    )
                ),
                "fraction": float(
                    (
                        stage2[
                            STAGE2_TARGET
                        ]
                        == label
                    ).mean()
                ),
            }
            for label in (
                "ALT",
                "CASH",
            )
        },
        "outputs": {
            "daily_regime_transition_dataset": str(
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
            "daily_regime_transition_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
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
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit only the frozen V12 model hierarchy on the preregistered V13 "
            "expanded information set. Require all nine unchanged predictive "
            "gates before any portfolio simulation."
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
        "--source-root",
        type=Path,
        default=SOURCE_ROOT,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )
    args = parser.parse_args(argv)

    print(json.dumps(
        run(
            args.source_root,
            args.output_root,
        ),
        indent=2,
    ))


if __name__ == "__main__":
    main()
