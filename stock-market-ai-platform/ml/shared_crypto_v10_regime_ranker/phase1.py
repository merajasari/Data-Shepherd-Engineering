"""Shared Crypto V10 Regime Ranker Phase 1.

V10 is a new preregistered hypothesis created only after V9 was immutably
rejected before portfolio simulation.

V8 tried exact excess-return regression and failed baseline MAE gates.
V9 tried two calibrated binary deviation classifiers and failed probability-
quality gates. V10 changes the learning target itself: one direct multiclass
decision label identifying which sleeve -- BTC, ALT, or CASH -- is best over
the next exact 72 hours after the fixed 25 bps deviation hurdle.

The primary model family is a fixed standardized LinearSVC. It produces
decision margins, not calibrated probabilities. No V10 model is fit in this
phase, no portfolio is simulated, and the September 1, 2026 holdout remains
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


RESEARCH_VERSION = "shared_crypto_v10_regime_ranker"
SOURCE_VERSION = "shared_crypto_v8_relative_value_linear"
SOURCE_ROOT = Path(
    "data/model/shared_crypto_v8_relative_value_linear/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v10_regime_ranker/phase1"
)
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

ALT_EXCESS = "alt_excess_vs_btc_net25_72h"
CASH_EXCESS = "cash_excess_vs_btc_net25_72h"
TARGET = "best_sleeve_net25_72h"
CLASSES = ("BTC", "ALT", "CASH")

PRIMARY_MODEL = "linear_svc"
LINEAR_SVC_C = 0.25
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


def derive_best_sleeve(frame: pd.DataFrame) -> pd.Series:
    alt = pd.to_numeric(
        frame[ALT_EXCESS],
        errors="raise",
    ).to_numpy(float)
    cash = pd.to_numeric(
        frame[CASH_EXCESS],
        errors="raise",
    ).to_numpy(float)

    result = np.full(
        len(frame),
        "BTC",
        dtype=object,
    )
    alt_mask = (
        (alt > 0.0)
        & (alt >= cash)
    )
    cash_mask = (
        (cash > 0.0)
        & (cash > alt)
    )
    result[alt_mask] = "ALT"
    result[cash_mask] = "CASH"

    return pd.Series(
        result,
        index=frame.index,
        name=TARGET,
        dtype="object",
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
        "V10 source regime dataset",
    )

    if (
        source_contract.get("research_version")
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V10 source contract is not Shared Crypto V8 Phase 1"
        )
    if (
        source_contract.get("future_holdout_start_utc")
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V10 source holdout boundary differs from preregistration"
        )

    features = list(
        source_contract["regime_feature_columns"]
    )

    required = {
        "timestamp_utc",
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        ALT_EXCESS,
        CASH_EXCESS,
        "alt_basket_assets",
        *features,
    }
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(
            f"V10 source dataset missing columns: {sorted(missing)}"
        )

    frame = frame.replace(
        [np.inf, -np.inf],
        np.nan,
    ).dropna(
        subset=[
            ALT_EXCESS,
            CASH_EXCESS,
            *features,
        ]
    ).copy()

    frame[TARGET] = derive_best_sleeve(
        frame
    )

    if (
        "oracle_best_deviation_net25_72h"
        in frame.columns
    ):
        mismatch = (
            frame[
                "oracle_best_deviation_net25_72h"
            ].astype(str)
            != frame[TARGET].astype(str)
        )
        if mismatch.any():
            raise RuntimeError(
                "V10 derived sleeve target disagrees with V8 oracle diagnostic"
            )

    forbidden = {
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        ALT_EXCESS,
        CASH_EXCESS,
        TARGET,
        "oracle_best_deviation_net25_72h",
        "oracle_best_excess_vs_btc_net25_72h",
        "alt_basket_assets",
    }
    leaked = forbidden & set(features)
    if leaked:
        raise RuntimeError(
            f"V10 future information leaked into model features: {sorted(leaked)}"
        )

    keep = [
        "timestamp_utc",
        *features,
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        ALT_EXCESS,
        CASH_EXCESS,
        TARGET,
        "alt_basket_assets",
    ]
    if (
        "oracle_best_deviation_net25_72h"
        in frame.columns
    ):
        keep.append(
            "oracle_best_deviation_net25_72h"
        )

    dataset = frame[keep].sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)

    observed_classes = set(
        dataset[TARGET].unique()
    )
    if observed_classes != set(CLASSES):
        raise RuntimeError(
            "V10 target must contain BTC, ALT, and CASH classes"
        )

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "preregistered_72h_direct_sleeve_ranking_dataset",
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source": {
            "research_version": SOURCE_VERSION,
            "phase": 1,
            "reused_point_in_time_features": True,
            "source_model_predictions_used": False,
            "source_portfolio_results_used": False,
        },
        "new_hypothesis_after_rejection": {
            "rejected_parent": "shared_crypto_v9_deviation_classifier",
            "parent_disposition": "REJECT_CURRENT_V9_PREDICTIVE_HYPOTHESIS",
            "observed_v9_failure": {
                "passed_predictive_gate_count": 2,
                "total_predictive_gate_count": 8,
                "passed_target_count": 0,
                "portfolio_simulation_allowed": False,
                "alt_median_roc_auc": 0.517528864897286,
                "alt_median_balanced_accuracy": 0.5289556391543447,
                "alt_median_brier_improvement_vs_train_prevalence": -0.0029358378008731,
                "alt_median_log_loss_improvement_vs_train_prevalence": -0.0061073613925921,
                "cash_median_roc_auc": 0.5389569705726172,
                "cash_median_balanced_accuracy": 0.4945875611190147,
                "cash_median_brier_improvement_vs_train_prevalence": -0.0008505790612263,
                "cash_median_log_loss_improvement_vs_train_prevalence": -0.002332774452503,
            },
            "v9_threshold_retuned": False,
            "v9_logistic_model_reused": False,
            "v9_portfolio_simulated": False,
        },
        "hypothesis": (
            "The portfolio decision is fundamentally a three-way ranking "
            "problem rather than a return-regression or calibrated-probability "
            "problem. A fixed margin-based multiclass classifier may identify "
            "the best cost-aware sleeve directly even when magnitude and "
            "probability calibration are unstable."
        ),
        "target": {
            "name": TARGET,
            "classes": list(CLASSES),
            "definition": {
                "BTC": (
                    "baseline class when neither ALT nor CASH beats BTC after "
                    "the 25 bps deviation hurdle"
                ),
                "ALT": (
                    "ALT excess versus BTC after 25 bps is positive and at "
                    "least as large as CASH excess"
                ),
                "CASH": (
                    "CASH excess versus BTC after 25 bps is positive and "
                    "strictly larger than ALT excess"
                ),
            },
        },
        "regime_feature_columns": features,
        "model": {
            "primary": PRIMARY_MODEL,
            "C": LINEAR_SVC_C,
            "loss": "squared_hinge",
            "penalty": "l2",
            "class_weight": None,
            "dual": "auto",
            "max_iter": 10000,
            "standardize_features": True,
            "multiclass_strategy": "one_vs_rest",
            "secondary_models": [],
            "probability_calibration": None,
        },
        "walk_forward": {
            "purge_hours": PURGE_HOURS,
            "minimum_train_days": MIN_TRAIN_DAYS,
            "validation_days": VALIDATION_DAYS,
            "max_folds": MAX_FOLDS,
        },
        "predictive_quality_gates": {
            "median_balanced_accuracy_gt": 0.36,
            "median_macro_f1_gt": 0.36,
            "median_accuracy_improvement_vs_train_majority_gt": 0.0,
            "median_multiclass_mcc_gt": 0.0,
            "median_minimum_class_recall_gt": 0.20,
            "all_gates_required_before_portfolio_simulation": True,
        },
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 72-hour blocks inside each validation fold"
            ),
            "selection_rule": (
                "Use the single V10 predicted sleeve class directly. No "
                "confidence threshold, probability threshold, or post-result "
                "override is permitted."
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
            "one_primary_model_family": True,
            "single_multiclass_target": True,
            "no_secondary_model_search": True,
            "no_probability_calibration": True,
            "no_confidence_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_selection_gates_weakened_from_v9": False,
            "nonoverlapping_72h_evaluation_required": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
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
        / "daily_regime_dataset.parquet"
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
        / "daily_rank_dataset.parquet"
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

    counts = dataset[
        TARGET
    ].value_counts()

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "preregistered_72h_direct_sleeve_ranking_dataset",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source_root": str(
            source_root
        ),
        "dataset_rows": int(
            len(dataset)
        ),
        "date_range": {
            "start": dataset[
                "timestamp_utc"
            ].min().isoformat(),
            "end": dataset[
                "timestamp_utc"
            ].max().isoformat(),
        },
        "class_balance": {
            label: {
                "count": int(
                    counts.get(
                        label,
                        0,
                    )
                ),
                "fraction": float(
                    (
                        dataset[TARGET]
                        == label
                    ).mean()
                ),
            }
            for label in CLASSES
        },
        "outputs": {
            "daily_rank_dataset": str(
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
            "daily_rank_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v7_modified": False,
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
            "Fit only the preregistered purged walk-forward standardized "
            "LinearSVC multiclass ranker and require all predictive gates to "
            "pass before any V10 portfolio simulation."
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
