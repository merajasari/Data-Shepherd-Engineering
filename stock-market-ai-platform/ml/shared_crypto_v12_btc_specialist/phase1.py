"""Shared Crypto V12 BTC Specialist Phase 1.

V12 is a separately preregistered successor to rejected V11.

Observed V11 evidence isolated the weak link:
* Stage 1 BTC-vs-DEVIATE failed balanced accuracy.
* Stage 2 ALT-vs-CASH passed both preregistered gates.

V12 therefore changes only Stage 1's model family, from a linear separator to a
fixed nonlinear HistGradientBoosting classifier. Stage 2 retains the exact V11
balanced LinearSVC specification. The combined BTC/ALT/CASH predictive gates
remain unchanged.

No V12 model is fit in this phase. No portfolio is simulated. The September 1,
2026 future holdout remains untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v12_btc_specialist"
SOURCE_VERSION = "shared_crypto_v11_hierarchical_selector"
SOURCE_ROOT = Path(
    "data/model/shared_crypto_v11_hierarchical_selector/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v12_btc_specialist/phase1"
)
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

SOURCE_TARGET = "best_sleeve_net25_72h"
STAGE1_TARGET = "btc_vs_deviate_72h"
STAGE2_TARGET = "alt_vs_cash_when_deviate_72h"

STAGE1_MODEL = "hist_gradient_boosting_classifier"
STAGE1_LEARNING_RATE = 0.05
STAGE1_MAX_ITER = 200
STAGE1_MAX_LEAF_NODES = 15
STAGE1_MIN_SAMPLES_LEAF = 30
STAGE1_L2_REGULARIZATION = 1.0
STAGE1_CLASS_WEIGHT = "balanced"

STAGE2_MODEL = "linear_svc"
STAGE2_C = 0.25
STAGE2_CLASS_WEIGHT = "balanced"

PURGE_HOURS = 72
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6


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


def build_dataset(
    source: pd.DataFrame,
    source_contract: dict,
) -> tuple[pd.DataFrame, dict]:
    frame = source.copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    validate_pre_holdout(
        frame,
        "V12 source hierarchical dataset",
    )

    if (
        source_contract.get("research_version")
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V12 source contract is not Shared Crypto V11 Phase 1"
        )
    if (
        source_contract.get("future_holdout_start_utc")
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V12 source holdout boundary differs from preregistration"
        )

    features = list(
        source_contract["regime_feature_columns"]
    )

    required = {
        "timestamp_utc",
        SOURCE_TARGET,
        STAGE1_TARGET,
        STAGE2_TARGET,
        "alt_basket_assets",
        *features,
    }
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(
            f"V12 source dataset missing columns: {sorted(missing)}"
        )

    frame = frame.replace(
        [np.inf, -np.inf],
        np.nan,
    ).dropna(
        subset=[
            SOURCE_TARGET,
            STAGE1_TARGET,
            *features,
        ]
    ).copy()

    if set(
        frame[SOURCE_TARGET].astype(str).unique()
    ) != {"BTC", "ALT", "CASH"}:
        raise RuntimeError(
            "V12 source best-sleeve target must contain BTC, ALT, and CASH"
        )

    if set(
        frame[STAGE1_TARGET].astype(str).unique()
    ) != {"BTC", "DEVIATE"}:
        raise RuntimeError(
            "V12 Stage 1 target must contain BTC and DEVIATE"
        )

    stage2 = frame[
        frame[STAGE2_TARGET].notna()
    ].copy()
    if set(
        stage2[STAGE2_TARGET].astype(str).unique()
    ) != {"ALT", "CASH"}:
        raise RuntimeError(
            "V12 Stage 2 target must contain ALT and CASH"
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
    leaked = forbidden & set(features)
    if leaked:
        raise RuntimeError(
            f"V12 future information leaked into model features: {sorted(leaked)}"
        )

    keep = [
        "timestamp_utc",
        *features,
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
        if optional in frame.columns:
            keep.append(optional)

    dataset = frame[keep].sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": (
            "preregistered_72h_btc_specialist_hierarchical_dataset"
        ),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source": {
            "research_version": SOURCE_VERSION,
            "phase": 1,
            "reused_point_in_time_features": True,
            "source_model_predictions_used": False,
            "source_portfolio_results_used": False,
        },
        "new_hypothesis_after_rejection": {
            "rejected_parent": SOURCE_VERSION,
            "parent_disposition": (
                "REJECT_CURRENT_V11_PREDICTIVE_HYPOTHESIS"
            ),
            "observed_v11_failure": {
                "passed_predictive_gate_count": 5,
                "total_predictive_gate_count": 9,
                "stage1_median_balanced_accuracy": (
                    0.5084982989052875
                ),
                "stage1_median_mcc": (
                    0.0151596618023331
                ),
                "stage2_median_balanced_accuracy": (
                    0.5553788867145031
                ),
                "stage2_median_mcc": (
                    0.1274398857269659
                ),
                "combined_median_balanced_accuracy": (
                    0.3537859117154133
                ),
                "combined_median_macro_f1": (
                    0.3424491768702149
                ),
                "combined_median_accuracy_improvement_vs_train_majority": (
                    -0.0210538605230386
                ),
            },
            "v11_stage1_retuned": False,
            "v11_stage2_retuned": False,
            "v11_portfolio_simulated": False,
        },
        "hypothesis": (
            "BTC-versus-DEVIATE may depend on nonlinear interactions among "
            "momentum, volatility, drawdown, and cross-sectional ALT state. "
            "A fixed shallow HistGradientBoosting classifier may capture those "
            "interactions better than V11's linear Stage 1 while retaining the "
            "already-preregistered V11 Stage 2 specification."
        ),
        "targets": {
            STAGE1_TARGET: {
                "classes": ["BTC", "DEVIATE"],
                "definition": (
                    "BTC iff the cost-aware best sleeve is BTC; "
                    "else DEVIATE"
                ),
            },
            STAGE2_TARGET: {
                "classes": ["ALT", "CASH"],
                "definition": (
                    "Defined only when the cost-aware best sleeve is not BTC; "
                    "equals ALT or CASH according to the source best-sleeve label"
                ),
            },
        },
        "regime_feature_columns": features,
        "models": {
            "stage1": {
                "primary": STAGE1_MODEL,
                "learning_rate": STAGE1_LEARNING_RATE,
                "max_iter": STAGE1_MAX_ITER,
                "max_leaf_nodes": STAGE1_MAX_LEAF_NODES,
                "max_depth": None,
                "min_samples_leaf": STAGE1_MIN_SAMPLES_LEAF,
                "l2_regularization": STAGE1_L2_REGULARIZATION,
                "class_weight": STAGE1_CLASS_WEIGHT,
                "random_state": 1729,
                "secondary_models": [],
                "probability_calibration": None,
            },
            "stage2": {
                "primary": STAGE2_MODEL,
                "C": STAGE2_C,
                "loss": "squared_hinge",
                "penalty": "l2",
                "class_weight": STAGE2_CLASS_WEIGHT,
                "dual": "auto",
                "max_iter": 10000,
                "standardize_features": True,
                "random_state": 1729,
                "secondary_models": [],
                "probability_calibration": None,
            },
        },
        "walk_forward": {
            "purge_hours": PURGE_HOURS,
            "minimum_train_days": MIN_TRAIN_DAYS,
            "validation_days": VALIDATION_DAYS,
            "max_folds": MAX_FOLDS,
        },
        "predictive_quality_gates": {
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
        },
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 72-hour blocks inside each validation fold"
            ),
            "selection_rule": (
                "Stage 1 predicted BTC -> BTC. Stage 1 predicted DEVIATE -> "
                "use Stage 2 predicted ALT or CASH. No confidence threshold "
                "or override."
            ),
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "target_weights": {
                "BTC": {
                    "BTC": 1.0,
                    "CASH": 0.0,
                },
                "ALT": {
                    "top5_alt_each": 0.20,
                    "CASH": 0.0,
                },
                "CASH": {
                    "CASH": 1.0,
                },
            },
            "maximum_turnover_per_72h_decision": 0.50,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": {
            "median_fold_net_return_gt": 0.0,
            "positive_fold_fraction_gte": 0.80,
            "median_excess_vs_always_btc_gt": 0.0,
            "median_excess_vs_shared_crypto_v3_gt": 0.0,
            "positive_excess_vs_shared_crypto_v3_fraction_gte": 0.80,
            "worst_maximum_drawdown_gte": -0.20,
            "single_fold_profit_concentration_lte": 0.40,
            "survives_stress_cost_bps": 50.0,
        },
        "research_constraints": {
            "stage1_model_family_fixed_before_fit": True,
            "stage2_specification_carried_forward_unchanged": True,
            "no_model_family_search": True,
            "no_secondary_model_search": True,
            "no_probability_calibration": True,
            "no_confidence_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "combined_gates_not_weakened_from_v11": True,
            "nonoverlapping_72h_evaluation_required": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V12 is another iteration on the same pre-holdout research history. "
            "Passing these development gates would justify only the next frozen "
            "portfolio-evaluation stage, not deployment or holdout claims."
        ),
    }

    return dataset, contract


def run(
    source_root: Path = SOURCE_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_root = Path(source_root)
    output_root = Path(output_root)

    source_contract = json.loads(
        (source_root / "preregistered_contract.json").read_text(
            encoding="utf-8"
        )
    )
    source = pd.read_parquet(
        source_root / "daily_hierarchical_dataset.parquet"
    )

    dataset, contract = build_dataset(
        source,
        source_contract,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "daily_specialist_dataset.parquet"
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
        dataset[STAGE1_TARGET]
        .value_counts()
    )
    stage2 = dataset[
        dataset[STAGE2_TARGET].notna()
    ].copy()
    stage2_counts = (
        stage2[STAGE2_TARGET]
        .value_counts()
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": (
            "preregistered_72h_btc_specialist_hierarchical_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "dataset_rows": int(
            len(dataset)
        ),
        "stage2_rows": int(
            len(stage2)
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
            "daily_specialist_dataset": str(
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
            "daily_specialist_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
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
            "Fit only the preregistered purged walk-forward V12 hierarchy: "
            "nonlinear Stage 1 HistGradientBoosting plus unchanged V11 Stage 2 "
            "balanced LinearSVC. Require all nine predictive gates before any "
            "portfolio simulation."
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
