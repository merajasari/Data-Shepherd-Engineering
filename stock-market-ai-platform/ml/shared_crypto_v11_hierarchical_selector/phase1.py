"""Shared Crypto V11 Hierarchical Selector Phase 1.

V11 is a separately preregistered successor to rejected V10.

V10's direct three-class LinearSVC under-selected BTC and failed macro-F1 and
minimum-class-recall gates. V11 changes structure rather than retuning V10:

  Stage 1: BTC versus DEVIATE.
  Stage 2: ALT versus CASH, trained only on rows where the best sleeve was not BTC.

Both stages use the same fixed standardized class-balanced LinearSVC with
C=0.25. No V11 model is fit here. No portfolio is simulated. The Sep 1, 2026
future holdout remains untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v11_hierarchical_selector"
SOURCE_VERSION = "shared_crypto_v10_regime_ranker"
SOURCE_ROOT = Path("data/model/shared_crypto_v10_regime_ranker/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v11_hierarchical_selector/phase1")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

SOURCE_TARGET = "best_sleeve_net25_72h"
STAGE1_TARGET = "btc_vs_deviate_72h"
STAGE2_TARGET = "alt_vs_cash_when_deviate_72h"

PRIMARY_MODEL = "linear_svc"
LINEAR_SVC_C = 0.25
CLASS_WEIGHT = "balanced"
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


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def build_dataset(
    source: pd.DataFrame,
    source_contract: dict,
) -> tuple[pd.DataFrame, dict]:
    frame = source.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, "V11 source rank dataset")

    if source_contract.get("research_version") != SOURCE_VERSION:
        raise RuntimeError("V11 source contract is not Shared Crypto V10 Phase 1")
    if source_contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V11 source holdout boundary differs from preregistration")

    features = list(source_contract["regime_feature_columns"])
    required = {"timestamp_utc", SOURCE_TARGET, "alt_basket_assets", *features}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V11 source dataset missing columns: {sorted(missing)}")

    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[SOURCE_TARGET, *features]
    ).copy()

    observed = set(frame[SOURCE_TARGET].astype(str).unique())
    if observed != {"BTC", "ALT", "CASH"}:
        raise RuntimeError("V11 source target must contain BTC, ALT, and CASH")

    frame[STAGE1_TARGET] = np.where(
        frame[SOURCE_TARGET].astype(str).eq("BTC"),
        "BTC",
        "DEVIATE",
    )
    frame[STAGE2_TARGET] = pd.Series(pd.NA, index=frame.index, dtype="object")
    deviate = frame[SOURCE_TARGET].astype(str).isin(["ALT", "CASH"])
    frame.loc[deviate, STAGE2_TARGET] = frame.loc[deviate, SOURCE_TARGET].astype(str)

    if set(frame[STAGE1_TARGET].unique()) != {"BTC", "DEVIATE"}:
        raise RuntimeError("V11 Stage 1 target lacks both classes")
    if set(frame.loc[deviate, STAGE2_TARGET].unique()) != {"ALT", "CASH"}:
        raise RuntimeError("V11 Stage 2 target lacks both classes")

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
            f"V11 future information leaked into model features: {sorted(leaked)}"
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

    dataset = frame[keep].sort_values("timestamp_utc").reset_index(drop=True)

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "preregistered_72h_hierarchical_sleeve_selection_dataset",
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
            "parent_disposition": "REJECT_CURRENT_V10_PREDICTIVE_HYPOTHESIS",
            "observed_v10_failure": {
                "passed_predictive_gate_count": 3,
                "total_predictive_gate_count": 5,
                "median_macro_f1": 0.3399287106962859,
                "median_minimum_class_recall": 0.0876027830487033,
                "median_btc_recall": 0.0876027830487033,
                "predicted_btc_count": 97,
                "predicted_alt_count": 311,
                "predicted_cash_count": 545,
            },
            "v10_class_weight_changed": False,
            "v10_linear_svc_c_changed": False,
            "v10_portfolio_simulated": False,
        },
        "hypothesis": (
            "Separating the BTC-versus-deviation decision from the ALT-versus-CASH "
            "decision may preserve BTC recognition while allowing the second stage "
            "to specialize only on deviation states."
        ),
        "targets": {
            STAGE1_TARGET: {
                "classes": ["BTC", "DEVIATE"],
                "definition": "BTC iff the cost-aware best sleeve is BTC; else DEVIATE",
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
        "model": {
            "primary": PRIMARY_MODEL,
            "C": LINEAR_SVC_C,
            "loss": "squared_hinge",
            "penalty": "l2",
            "class_weight": CLASS_WEIGHT,
            "dual": "auto",
            "max_iter": 10000,
            "standardize_features": True,
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
                "Stage 1 predicted BTC -> BTC. Stage 1 predicted DEVIATE -> use "
                "Stage 2 predicted ALT or CASH. No confidence threshold or override."
            ),
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "target_weights": {
                "BTC": {"BTC": 1.0, "CASH": 0.0},
                "ALT": {"top5_alt_each": 0.20, "CASH": 0.0},
                "CASH": {"CASH": 1.0},
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
            "two_stage_hierarchy_fixed_before_fit": True,
            "one_model_family": True,
            "same_fixed_C_both_stages": True,
            "class_weight_balanced_fixed_before_fit": True,
            "no_secondary_model_search": True,
            "no_probability_calibration": True,
            "no_confidence_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "combined_gates_not_weakened_from_v10": True,
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
    source_root = Path(source_root)
    output_root = Path(output_root)

    source_contract = json.loads(
        (source_root / "preregistered_contract.json").read_text(encoding="utf-8")
    )
    source = pd.read_parquet(source_root / "daily_rank_dataset.parquet")

    dataset, contract = build_dataset(source, source_contract)

    output_root.mkdir(parents=True, exist_ok=True)
    dataset_path = output_root / "daily_hierarchical_dataset.parquet"
    contract_path = output_root / "preregistered_contract.json"

    dataset.to_parquet(dataset_path, index=False)
    contract_path.write_text(
        json.dumps(contract, indent=2) + "\n",
        encoding="utf-8",
    )

    stage1_counts = dataset[STAGE1_TARGET].value_counts()
    stage2 = dataset[dataset[STAGE2_TARGET].notna()].copy()
    stage2_counts = stage2[STAGE2_TARGET].value_counts()

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "preregistered_72h_hierarchical_sleeve_selection_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "dataset_rows": int(len(dataset)),
        "stage2_rows": int(len(stage2)),
        "date_range": {
            "start": dataset["timestamp_utc"].min().isoformat(),
            "end": dataset["timestamp_utc"].max().isoformat(),
        },
        "stage1_class_balance": {
            label: {
                "count": int(stage1_counts.get(label, 0)),
                "fraction": float((dataset[STAGE1_TARGET] == label).mean()),
            }
            for label in ("BTC", "DEVIATE")
        },
        "stage2_class_balance": {
            label: {
                "count": int(stage2_counts.get(label, 0)),
                "fraction": float((stage2[STAGE2_TARGET] == label).mean()),
            }
            for label in ("ALT", "CASH")
        },
        "outputs": {
            "daily_hierarchical_dataset": str(dataset_path),
            "contract": str(contract_path),
            "manifest": str(output_root / "manifest.json"),
        },
        "hashes": {
            "daily_hierarchical_dataset": _sha256(dataset_path),
            "contract": _sha256(contract_path),
        },
        "safety": {
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
            "Fit only the preregistered purged walk-forward two-stage balanced "
            "LinearSVC hierarchy and require all stage-specific and combined "
            "predictive gates to pass before any V11 portfolio simulation."
        ),
    }

    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)

    print(json.dumps(run(args.source_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
