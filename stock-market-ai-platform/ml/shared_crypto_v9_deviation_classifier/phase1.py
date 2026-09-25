"""Shared Crypto V9 Deviation Classifier Phase 1.

V9 is a new preregistered hypothesis created only after V8 was immutably
rejected before portfolio simulation.  V8 showed weak but positive directional
signal on both BTC-relative targets while failing to beat the training-mean
baseline on median MAE.  V9 therefore changes the learning objective rather
than tuning V8: it predicts the binary decision-relevant events

  * ALT beats BTC after the 25 bps deviation hurdle over exactly 72 hours.
  * CASH beats BTC after the 25 bps deviation hurdle over exactly 72 hours.

V9 reuses the already point-in-time V8 Phase 1 regime features and labels only
to construct a separately named classification dataset.  No V9 model is fit in
this phase.  The future holdout is not inspected, no portfolio is simulated,
and paper/brokerage state cannot be modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v9_deviation_classifier"
SOURCE_VERSION = "shared_crypto_v8_relative_value_linear"
SOURCE_ROOT = Path("data/model/shared_crypto_v8_relative_value_linear/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v9_deviation_classifier/phase1")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

ALT_EXCESS = "alt_excess_vs_btc_net25_72h"
CASH_EXCESS = "cash_excess_vs_btc_net25_72h"
ALT_LABEL = "alt_beats_btc_net25_72h"
CASH_LABEL = "cash_beats_btc_net25_72h"

PRIMARY_MODEL = "logistic_regression"
LOGISTIC_C = 0.5
PROBABILITY_THRESHOLD = 0.50
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
        "V9 source regime dataset",
    )

    if (
        source_contract.get("research_version")
        != SOURCE_VERSION
    ):
        raise RuntimeError(
            "V9 source contract is not Shared Crypto V8"
        )
    if (
        source_contract.get("future_holdout_start_utc")
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V9 source holdout boundary differs from V8"
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
            f"V9 source dataset missing columns: {sorted(missing)}"
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

    frame[ALT_LABEL] = (
        pd.to_numeric(
            frame[ALT_EXCESS],
            errors="raise",
        )
        > 0.0
    ).astype("int8")
    frame[CASH_LABEL] = (
        pd.to_numeric(
            frame[CASH_EXCESS],
            errors="raise",
        )
        > 0.0
    ).astype("int8")

    forbidden = {
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        ALT_EXCESS,
        CASH_EXCESS,
        ALT_LABEL,
        CASH_LABEL,
        "oracle_best_deviation_net25_72h",
        "oracle_best_excess_vs_btc_net25_72h",
        "alt_basket_assets",
    }
    leaked = forbidden & set(features)
    if leaked:
        raise RuntimeError(
            f"V9 future information leaked into model features: {sorted(leaked)}"
        )

    keep = [
        "timestamp_utc",
        *features,
        "btc_forward_return_72h",
        "alt_forward_return_72h",
        ALT_EXCESS,
        CASH_EXCESS,
        ALT_LABEL,
        CASH_LABEL,
        "alt_basket_assets",
    ]
    if "oracle_best_deviation_net25_72h" in frame.columns:
        keep.append(
            "oracle_best_deviation_net25_72h"
        )

    dataset = frame[keep].sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)

    if dataset.empty:
        raise RuntimeError(
            "Shared Crypto V9 Phase 1 produced an empty dataset"
        )
    for label in (ALT_LABEL, CASH_LABEL):
        values = set(dataset[label].unique())
        if values != {0, 1}:
            raise RuntimeError(
                f"V9 target {label} does not contain both classes"
            )

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "preregistered_72h_btc_deviation_classification_dataset",
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
            "parent_disposition": "REJECT_CURRENT_V8_PREDICTIVE_HYPOTHESIS",
            "observed_v8_failure": {
                "passed_predictive_gate_count": 4,
                "total_predictive_gate_count": 6,
                "portfolio_simulation_allowed": False,
                "alt_median_pearson_correlation": 0.0662084721038134,
                "alt_median_sign_accuracy": 0.5523816936488168,
                "alt_median_mae_improvement_vs_train_mean": -0.0003643725155748,
                "cash_median_pearson_correlation": 0.0291826931456478,
                "cash_median_sign_accuracy": 0.5367424242424242,
                "cash_median_mae_improvement_vs_train_mean": -0.0007093629013821,
            },
            "v8_thresholds_retuned": False,
            "v8_ridge_reused": False,
            "v8_portfolio_simulated": False,
        },
        "hypothesis": (
            "The economically relevant 72-hour question is classification, "
            "not precise return magnitude.  A regularized logistic model may "
            "identify whether ALT or CASH will beat BTC after the fixed 25 bps "
            "deviation hurdle even when absolute excess-return regression does "
            "not improve MAE."
        ),
        "targets": {
            ALT_LABEL: (
                "1 iff ALT 72-hour forward return minus BTC 72-hour forward "
                "return minus 25 bps is greater than zero"
            ),
            CASH_LABEL: (
                "1 iff negative BTC 72-hour forward return minus 25 bps is "
                "greater than zero"
            ),
        },
        "regime_feature_columns": features,
        "model": {
            "primary": PRIMARY_MODEL,
            "penalty": "l2",
            "C": LOGISTIC_C,
            "solver": "lbfgs",
            "max_iter": 2000,
            "class_weight": None,
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
        "predictive_policy": {
            "fixed_probability_threshold": PROBABILITY_THRESHOLD,
            "threshold_search": False,
            "targets_fit_independently": True,
        },
        "predictive_quality_gates": {
            "median_roc_auc_each_target_gt": 0.52,
            "median_balanced_accuracy_each_target_gt": 0.52,
            "median_brier_improvement_vs_train_prevalence_each_target_gt": 0.0,
            "median_log_loss_improvement_vs_train_prevalence_each_target_gt": 0.0,
            "all_gates_required_before_portfolio_simulation": True,
        },
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 72-hour blocks inside each validation fold"
            ),
            "default_state": "BTC",
            "selection_rule": (
                "At each eligible block, compare the fixed-threshold ALT and "
                "CASH probabilities.  If neither exceeds 0.50, hold BTC.  If "
                "one or both exceed 0.50, choose the deviation with the larger "
                "predicted probability; ties remain BTC."
            ),
            "probability_threshold": PROBABILITY_THRESHOLD,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "maximum_gross_crypto_exposure": 1.0,
            "maximum_btc_weight": 1.0,
            "maximum_alt_weight_per_asset": 0.20,
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
            "no_secondary_model_search": True,
            "fixed_probability_threshold": True,
            "no_post_result_threshold_search": True,
            "predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_selection_gates_weakened_from_v8": False,
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
        / "daily_classification_dataset.parquet"
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
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "preregistered_72h_btc_deviation_classification_dataset",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source_root": str(source_root),
        "dataset_rows": int(len(dataset)),
        "date_range": {
            "start": dataset[
                "timestamp_utc"
            ].min().isoformat(),
            "end": dataset[
                "timestamp_utc"
            ].max().isoformat(),
        },
        "class_balance": {
            ALT_LABEL: {
                "positive_fraction": float(
                    dataset[ALT_LABEL].mean()
                ),
                "positive_count": int(
                    dataset[ALT_LABEL].sum()
                ),
            },
            CASH_LABEL: {
                "positive_fraction": float(
                    dataset[CASH_LABEL].mean()
                ),
                "positive_count": int(
                    dataset[CASH_LABEL].sum()
                ),
            },
        },
        "outputs": {
            "daily_classification_dataset": str(
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
            "daily_classification_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
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
            "Fit only the preregistered purged walk-forward logistic classifiers "
            "for ALT-beats-BTC and CASH-beats-BTC.  Require every predictive "
            "quality gate to pass before any V9 portfolio simulation."
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
