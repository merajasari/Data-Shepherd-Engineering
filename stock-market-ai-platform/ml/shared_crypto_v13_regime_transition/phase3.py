"""Shared Crypto V13 Regime Transition Phase 3.

Immutable predictive adjudication for V13.

Reads only Phase 2 predictive evidence and records whether the preregistered
regime-transition hierarchy qualified for portfolio simulation. If any of the
nine predictive gates failed, V13 is closed as rejected predictive evidence.

This phase performs no model fitting, feature changes, class-weight changes,
hyperparameter changes, threshold tuning, probability calibration, portfolio
simulation, future-holdout scoring, model freezing, paper activation, or
brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v13_regime_transition"
PHASE2_ROOT = Path(
    "data/model/shared_crypto_v13_regime_transition/phase2"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v13_regime_transition/phase3"
)
HOLDOUT = "2026-09-01T00:00:00+00:00"

EXPECTED_GATE_COLUMNS = (
    "gate_stage1_median_balanced_accuracy_gt_52pct",
    "gate_stage1_median_mcc_gt_zero",
    "gate_stage2_median_balanced_accuracy_gt_52pct",
    "gate_stage2_median_mcc_gt_zero",
    "gate_combined_median_balanced_accuracy_gt_36pct",
    "gate_combined_median_macro_f1_gt_36pct",
    "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero",
    "gate_combined_median_multiclass_mcc_gt_zero",
    "gate_combined_median_minimum_class_recall_gt_20pct",
)


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
    predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if len(gate_detail) != 1:
        raise RuntimeError(
            "V13 Phase 2 must contain exactly one predictive gate row"
        )

    row = gate_detail.iloc[0]
    required = {
        *EXPECTED_GATE_COLUMNS,
        "passed_gate_count",
        "total_gate_count",
    }
    missing = required - set(gate_detail.columns)
    if missing:
        raise RuntimeError(
            f"V13 Phase 2 gate detail missing columns: {sorted(missing)}"
        )

    total = int(row["total_gate_count"])
    passed = int(row["passed_gate_count"])

    if total != 9:
        raise RuntimeError(
            "V13 expected exactly nine predictive gates"
        )
    if int(
        gate_result["total_predictive_gate_count"]
    ) != total:
        raise RuntimeError(
            "V13 total predictive gate count is inconsistent"
        )
    if int(
        gate_result["passed_predictive_gate_count"]
    ) != passed:
        raise RuntimeError(
            "V13 passed predictive gate count is inconsistent"
        )

    all_pass = bool(
        passed == total
    )

    if bool(
        gate_result["all_predictive_gates_pass"]
    ) != all_pass:
        raise RuntimeError(
            "V13 all_predictive_gates_pass flag is inconsistent"
        )

    expected_status = (
        "ALLOW_POLICY_SIMULATION"
        if all_pass
        else "STOP_BEFORE_PORTFOLIO_SIMULATION"
    )

    if str(
        gate_result["status"]
    ) != expected_status:
        raise RuntimeError(
            "V13 Phase 2 predictive status is inconsistent"
        )

    if len(summary) != 1:
        raise RuntimeError(
            "V13 Phase 2 metrics summary must contain exactly one row"
        )

    summary_row = summary.iloc[0]
    required_summary = {
        "median_stage1_balanced_accuracy",
        "median_stage1_mcc",
        "median_stage2_balanced_accuracy",
        "median_stage2_mcc",
        "median_combined_balanced_accuracy",
        "median_combined_macro_f1",
        "median_combined_accuracy_improvement_vs_train_majority",
        "median_combined_multiclass_mcc",
        "median_combined_minimum_class_recall",
        "median_combined_btc_recall",
        "median_combined_alt_recall",
        "median_combined_cash_recall",
    }
    missing = required_summary - set(summary.columns)
    if missing:
        raise RuntimeError(
            f"V13 metrics summary missing columns: {sorted(missing)}"
        )

    if "predicted_sleeve" not in predictions.columns:
        raise RuntimeError(
            "V13 predictions are missing predicted_sleeve"
        )

    counts = {
        label: int(
            (
                predictions["predicted_sleeve"].astype(str)
                == label
            ).sum()
        )
        for label in ("BTC", "ALT", "CASH")
    }

    if sum(counts.values()) != len(predictions):
        raise RuntimeError(
            "V13 predictions contain an unexpected sleeve class"
        )

    failed_gates = [
        gate
        for gate in EXPECTED_GATE_COLUMNS
        if not bool(row[gate])
    ]

    disposition = gate_detail.copy()
    disposition["failed_gates"] = ",".join(
        failed_gates
    )

    decision = {
        "status": (
            "QUALIFIED_FOR_POLICY_SIMULATION"
            if all_pass
            else "REJECT_CURRENT_V13_PREDICTIVE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": bool(
            all_pass
        ),
        "passed_predictive_gate_count": passed,
        "total_predictive_gate_count": total,
        "failed_gates": failed_gates,
        "observed_predictive_metrics": {
            "median_stage1_balanced_accuracy": float(
                summary_row[
                    "median_stage1_balanced_accuracy"
                ]
            ),
            "median_stage1_mcc": float(
                summary_row[
                    "median_stage1_mcc"
                ]
            ),
            "median_stage2_balanced_accuracy": float(
                summary_row[
                    "median_stage2_balanced_accuracy"
                ]
            ),
            "median_stage2_mcc": float(
                summary_row[
                    "median_stage2_mcc"
                ]
            ),
            "median_combined_balanced_accuracy": float(
                summary_row[
                    "median_combined_balanced_accuracy"
                ]
            ),
            "median_combined_macro_f1": float(
                summary_row[
                    "median_combined_macro_f1"
                ]
            ),
            "median_combined_accuracy_improvement_vs_train_majority": float(
                summary_row[
                    "median_combined_accuracy_improvement_vs_train_majority"
                ]
            ),
            "median_combined_multiclass_mcc": float(
                summary_row[
                    "median_combined_multiclass_mcc"
                ]
            ),
            "median_combined_minimum_class_recall": float(
                summary_row[
                    "median_combined_minimum_class_recall"
                ]
            ),
            "median_combined_btc_recall": float(
                summary_row[
                    "median_combined_btc_recall"
                ]
            ),
            "median_combined_alt_recall": float(
                summary_row[
                    "median_combined_alt_recall"
                ]
            ),
            "median_combined_cash_recall": float(
                summary_row[
                    "median_combined_cash_recall"
                ]
            ),
        },
        "observed_prediction_counts": counts,
        "observed_prediction_rows": int(
            len(predictions)
        ),
    }

    return disposition, decision


def run(
    phase2_root: Path = PHASE2_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase2_root = Path(
        phase2_root
    )
    output_root = Path(
        output_root
    )

    manifest = json.loads(
        (
            phase2_root
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    if (
        manifest.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V13 Phase 2 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V13 Phase 2 holdout boundary"
        )

    if int(
        manifest.get(
            "model_feature_count",
            -1,
        )
    ) != 76:
        raise RuntimeError(
            "Unexpected V13 model feature count"
        )

    if int(
        manifest.get(
            "transition_feature_count",
            -1,
        )
    ) != 24:
        raise RuntimeError(
            "Unexpected V13 transition feature count"
        )

    if (
        manifest.get(
            "stage1_model"
        )
        != "hist_gradient_boosting_classifier"
    ):
        raise RuntimeError(
            "Unexpected V13 Stage 1 model"
        )

    if (
        manifest.get(
            "stage2_model"
        )
        != "linear_svc"
    ):
        raise RuntimeError(
            "Unexpected V13 Stage 2 model"
        )

    if (
        float(
            manifest.get(
                "stage2_C"
            )
        )
        != 0.25
    ):
        raise RuntimeError(
            "Unexpected V13 Stage 2 C"
        )

    if (
        int(
            manifest.get(
                "secondary_model_count",
                -1,
            )
        )
        != 0
    ):
        raise RuntimeError(
            "V13 Phase 2 unexpectedly searched secondary models"
        )

    safety = manifest.get(
        "safety",
        {},
    )

    for key in (
        "future_holdout_scored",
        "portfolio_simulated",
        "model_family_searched",
        "secondary_model_fit",
        "hyperparameters_tuned",
        "class_weight_tuned",
        "probability_calibrated",
        "confidence_threshold_tuned",
        "model_frozen",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if (
            safety.get(
                key
            )
            is not False
        ):
            raise RuntimeError(
                f"V13 Phase 2 safety invariant failed: {key}"
            )

    gate_detail = pd.read_csv(
        phase2_root
        / "predictive_gate_detail.csv"
    )
    gate_result = json.loads(
        (
            phase2_root
            / "predictive_gate_result.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    summary = pd.read_csv(
        phase2_root
        / "metrics_summary.csv"
    )
    predictions = pd.read_parquet(
        phase2_root
        / "daily_predictions.parquet"
    )

    disposition, decision = adjudicate(
        gate_detail,
        gate_result,
        summary,
        predictions,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    disposition_path = (
        output_root
        / "predictive_disposition.csv"
    )
    adjudication_path = (
        output_root
        / "adjudication.json"
    )

    disposition.to_csv(
        disposition_path,
        index=False,
    )

    payload = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "immutable_predictive_adjudication",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT,
        **decision,
        "reason": (
            "V13 required all nine unchanged predictive gates to pass before "
            "portfolio simulation. Adding exact 24-hour and 72-hour regime-"
            "transition features did not improve the BTC-versus-DEVIATE "
            "boundary: Stage 1 median balanced accuracy fell below 50% and "
            "median MCC became slightly negative. Stage 2 continued to pass "
            "both of its gates, but the combined hierarchy failed balanced "
            "accuracy, macro F1, and accuracy improvement versus the training-"
            "majority baseline. V13 is therefore rejected before portfolio "
            "simulation."
        ),
        "outputs": {
            "predictive_disposition": str(
                disposition_path
            ),
            "adjudication": str(
                adjudication_path
            ),
        },
        "safety": {
            "predictive_gates_changed_after_results": False,
            "transition_feature_family_changed_after_results": False,
            "stage1_hyperparameters_changed_after_results": False,
            "stage1_class_weight_changed_after_results": False,
            "stage2_specification_changed_after_results": False,
            "confidence_threshold_added_after_results": False,
            "threshold_search_performed": False,
            "probability_calibration_added_after_results": False,
            "model_family_changed_after_results": False,
            "secondary_model_fit": False,
            "portfolio_simulated": False,
            "shared_crypto_v12_modified": False,
            "shared_crypto_v11_modified": False,
            "shared_crypto_v10_modified": False,
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "v13_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V13 as rejected predictive evidence. Do not simulate the "
            "V13 portfolio, alter the transition features, retune either model, "
            "add thresholds, weaken gates, or score the future holdout. Before "
            "starting another successor on this same pre-holdout history, "
            "perform a research-family reset and define a genuinely new target, "
            "data source, or untouched development period."
        ),
    }

    adjudication_path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument(
        "--phase2-root",
        type=Path,
        default=PHASE2_ROOT,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )
    args = parser.parse_args(argv)

    print(json.dumps(
        run(
            args.phase2_root,
            args.output_root,
        ),
        indent=2,
    ))


if __name__ == "__main__":
    main()
