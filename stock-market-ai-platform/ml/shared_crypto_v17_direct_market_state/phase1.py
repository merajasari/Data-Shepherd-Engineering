"""Shared Crypto V17 Direct Market State Phase 1.

V17 is a separately preregistered successor to rejected V16.

V16 used a continuous HGB regressor for broad-market seven-day median path
utility and then applied the economically natural zero threshold. It failed
three of four predictive gates and strongly under-called RISK_ON.

V17 keeps the exact same point-in-time market-state information set and exact
same binary label:

    RISK_ON  = market_median_path_utility_net25_7d > 0
    RISK_OFF = otherwise

The only learning-family change is to train that state directly with a
HistGradientBoostingClassifier using fixed balanced sample weights. No
probability threshold is used later: class prediction itself is the gate.

The frozen V15 cross-sectional ranker remains the selection engine if V17
eventually passes all predictive gates. The September 1, 2026 future holdout
remains untouched.

This phase preregisters and validates the dataset/contract only. It fits no
model and runs no portfolio simulation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v17_direct_market_state"
SOURCE_VERSION = "shared_crypto_v16_risk_gated_rank"

SOURCE_PHASE1_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase1"
)
SOURCE_PHASE3_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase3"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v17_direct_market_state/phase1"
)

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

MARKET_TARGET = "market_median_path_utility_net25_7d"
MARKET_LABEL = "market_risk_on_7d"

PRIMARY_MODEL = "hist_gradient_boosting_classifier"
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0
RANDOM_STATE = 1729
CLASS_WEIGHT_METHOD = "balanced_sample_weight"

PURGE_DAYS = 7
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 8

EXPECTED_PREDICTIVE_GATES = {
    "median_fold_balanced_accuracy_gt": 0.55,
    "median_fold_macro_f1_gt": 0.55,
    "median_fold_mcc_gt": 0.0,
    "median_fold_minimum_class_recall_gt": 0.50,
    "all_gates_required_before_portfolio_simulation": True,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def _validate_v16_contract(contract: dict) -> list[str]:
    if contract.get("research_version") != SOURCE_VERSION:
        raise RuntimeError(
            "V17 source contract is not Shared Crypto V16 Phase 1"
        )

    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError(
            "V17 source holdout differs from preregistration"
        )

    target = contract.get("market_risk_target", {})

    if target.get("primary") != MARKET_TARGET:
        raise RuntimeError(
            "V17 requires the exact V16 market utility target"
        )

    if target.get("binary_diagnostic") != MARKET_LABEL:
        raise RuntimeError(
            "V17 requires the exact V16 binary market-state label"
        )

    if target.get("risk_on_definition") != (
        "market_median_path_utility_net25_7d > 0"
    ):
        raise RuntimeError(
            "V17 requires the exact V16 zero-defined market-state label"
        )

    features = list(
        contract["risk_feature_columns"]
    )

    if len(features) != 18:
        raise RuntimeError(
            "V17 requires the exact 18 V16 point-in-time risk features"
        )

    return features


def _validate_v16_rejection(adjudication: dict) -> None:
    if adjudication.get("research_version") != SOURCE_VERSION:
        raise RuntimeError(
            "V17 requires the V16 Phase 3 adjudication"
        )

    if adjudication.get("status") != (
        "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS"
    ):
        raise RuntimeError(
            "V17 may start only after V16 is immutably rejected"
        )

    if adjudication.get("portfolio_simulation_allowed") is not False:
        raise RuntimeError(
            "V16 portfolio simulation must remain blocked"
        )

    if int(
        adjudication.get(
            "passed_predictive_gate_count",
            -1,
        )
    ) != 1:
        raise RuntimeError(
            "Unexpected V16 passed-gate count"
        )

    if int(
        adjudication.get(
            "total_predictive_gate_count",
            -1,
        )
    ) != 4:
        raise RuntimeError(
            "Unexpected V16 total-gate count"
        )


def build_dataset(
    source: pd.DataFrame,
    source_contract: dict,
    v16_adjudication: dict,
) -> tuple[pd.DataFrame, dict]:
    features = _validate_v16_contract(
        source_contract
    )
    _validate_v16_rejection(
        v16_adjudication
    )

    frame = source.copy()

    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    frame["target_endpoint_utc_7d"] = pd.to_datetime(
        frame["target_endpoint_utc_7d"],
        utc=True,
    )

    validate_pre_holdout(
        frame,
        "V17 V16 source dataset",
    )

    required = {
        "timestamp_utc",
        "target_endpoint_utc_7d",
        "eligible_asset_count",
        MARKET_TARGET,
        MARKET_LABEL,
        *features,
    }

    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(
            "V17 source dataset missing columns: "
            f"{sorted(missing)}"
        )

    if (
        frame["target_endpoint_utc_7d"]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V17 source target path reaches the future holdout"
        )

    finite = frame[
        [
            *features,
            MARKET_TARGET,
        ]
    ].replace(
        [np.inf, -np.inf],
        np.nan,
    )

    if finite.isna().any().any():
        raise RuntimeError(
            "V17 source dataset contains non-finite inputs or target"
        )

    labels = pd.to_numeric(
        frame[MARKET_LABEL],
        errors="raise",
    ).astype(int)

    expected_labels = (
        pd.to_numeric(
            frame[MARKET_TARGET],
            errors="raise",
        )
        > 0.0
    ).astype(int)

    if not labels.equals(expected_labels):
        raise RuntimeError(
            "V17 market-state label no longer equals the frozen zero-defined target"
        )

    if set(labels.unique()) != {0, 1}:
        raise RuntimeError(
            "V17 requires both RISK_OFF and RISK_ON examples"
        )

    dataset = frame[
        [
            "timestamp_utc",
            "target_endpoint_utc_7d",
            "eligible_asset_count",
            MARKET_TARGET,
            MARKET_LABEL,
            *features,
        ]
    ].sort_values(
        "timestamp_utc"
    ).reset_index(
        drop=True
    )

    v16_policy = dict(
        source_contract[
            "frozen_policy_for_later_simulation"
        ]
    )

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": (
            "preregistered_direct_balanced_binary_market_state_dataset"
        ),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source": {
            "research_version": SOURCE_VERSION,
            "phase": 1,
            "dataset": "market_risk_dataset.parquet",
            "v16_predictions_used_as_features": False,
            "v16_portfolio_results_used_as_training_target": False,
        },
        "successor_after_rejection": {
            "rejected_parent": SOURCE_VERSION,
            "parent_disposition": (
                "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS"
            ),
            "v16_zero_threshold_changed": False,
            "v16_features_changed": False,
            "v16_regressor_retuned": False,
            "v16_portfolio_simulated": False,
        },
        "hypothesis": (
            "The V16 information set may contain market-state information that "
            "is poorly captured by a continuous regression objective. Directly "
            "optimizing the frozen binary RISK_ON/RISK_OFF state with balanced "
            "sample weighting may improve class separation without changing "
            "the economically defined zero boundary or the 18 features."
        ),
        "market_state_target": {
            "primary": MARKET_LABEL,
            "definition": (
                "1 when market_median_path_utility_net25_7d > 0, else 0"
            ),
            "continuous_reference_target": MARKET_TARGET,
            "risk_on_label": 1,
            "risk_off_label": 0,
            "decision_rule": (
                "use classifier class prediction directly; no probability threshold"
            ),
            "target_path_must_finish_before_holdout": True,
        },
        "risk_feature_columns": features,
        "market_state_model": {
            "primary": PRIMARY_MODEL,
            "learning_rate": MODEL_LEARNING_RATE,
            "max_iter": MODEL_MAX_ITER,
            "max_leaf_nodes": MODEL_MAX_LEAF_NODES,
            "max_depth": None,
            "min_samples_leaf": MODEL_MIN_SAMPLES_LEAF,
            "l2_regularization": MODEL_L2_REGULARIZATION,
            "random_state": RANDOM_STATE,
            "class_weight_method": CLASS_WEIGHT_METHOD,
            "secondary_models": [],
        },
        "walk_forward": {
            "purge_days": PURGE_DAYS,
            "minimum_train_days": MIN_TRAIN_DAYS,
            "validation_days": VALIDATION_DAYS,
            "max_folds": MAX_FOLDS,
        },
        "predictive_quality_gates": dict(
            EXPECTED_PREDICTIVE_GATES
        ),
        "frozen_policy_for_later_simulation": {
            **v16_policy,
            "risk_gate_rule": (
                "deploy frozen V15 top-3 ranker only when V17 direct classifier "
                "predicts RISK_ON class 1; otherwise hold 100% cash"
            ),
            "risk_gate_probability_threshold": None,
        },
        "selection_gates": dict(
            source_contract[
                "selection_gates"
            ]
        ),
        "research_constraints": {
            "same_18_features_as_v16": True,
            "same_zero_defined_labels_as_v16": True,
            "direct_classifier_fixed_before_fit": True,
            "balanced_sample_weight_fixed_before_fit": True,
            "no_probability_threshold": True,
            "no_probability_threshold_search": True,
            "no_feature_search": True,
            "no_secondary_model_search": True,
            "no_hyperparameter_search": True,
            "v15_ranker_is_frozen_input": True,
            "v15_ranker_refit": False,
            "predictive_gates_required_before_portfolio_simulation": True,
            "portfolio_gates_carried_forward_unchanged": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "research_iteration_disclosure": (
            "V17 is motivated by observing V16's RISK_OFF bias on the same "
            "pre-holdout development history. Direct classification and "
            "balanced sample weighting are fixed before fitting V17, but this "
            "successor still carries researcher-selection risk. A development "
            "pass would not establish future performance."
        ),
        "dataset": {
            "row_count": int(len(dataset)),
            "start_utc": (
                dataset["timestamp_utc"].min().isoformat()
            ),
            "end_utc": (
                dataset["timestamp_utc"].max().isoformat()
            ),
            "risk_on_count": int(
                dataset[MARKET_LABEL].sum()
            ),
            "risk_off_count": int(
                (
                    dataset[MARKET_LABEL] == 0
                ).sum()
            ),
            "risk_on_fraction": float(
                dataset[MARKET_LABEL].mean()
            ),
            "risk_feature_count": int(
                len(features)
            ),
        },
    }

    return dataset, contract


def run(
    source_phase1_root: Path = SOURCE_PHASE1_ROOT,
    source_phase3_root: Path = SOURCE_PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_phase1_root = Path(
        source_phase1_root
    )
    source_phase3_root = Path(
        source_phase3_root
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
        / "market_risk_dataset.parquet"
    )

    adjudication = json.loads(
        (
            source_phase3_root
            / "adjudication.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    dataset, contract = build_dataset(
        source,
        source_contract,
        adjudication,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset_path = (
        output_root
        / "market_state_dataset.parquet"
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
        "stage": (
            "preregistered_direct_balanced_binary_market_state_dataset"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "dataset": contract["dataset"],
        "risk_feature_count": int(
            len(
                contract["risk_feature_columns"]
            )
        ),
        "model": PRIMARY_MODEL,
        "class_weight_method": CLASS_WEIGHT_METHOD,
        "outputs": {
            "market_state_dataset": str(
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
            "market_state_dataset": _sha256(
                dataset_path
            ),
            "contract": _sha256(
                contract_path
            ),
        },
        "safety": {
            "shared_crypto_v16_modified": False,
            "shared_crypto_v15_modified": False,
            "v15_ranker_refit": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "probability_threshold_searched": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit only the preregistered balanced V17 HGB classifier on the "
            "frozen binary market-state labels with the same 18 features and "
            "purged walk-forward protocol. Require all four predictive gates "
            "before any portfolio simulation."
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
        "--source-phase1-root",
        type=Path,
        default=SOURCE_PHASE1_ROOT,
    )
    parser.add_argument(
        "--source-phase3-root",
        type=Path,
        default=SOURCE_PHASE3_ROOT,
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
                args.source_phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
