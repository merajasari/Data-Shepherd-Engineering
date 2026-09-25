"""Shared Crypto V18 Ranker Meta-Gate Phase 3.

Immutable predictive adjudication for V18.

Reads only Phase 2 meta-gate predictive evidence. If any of the four
preregistered predictive gates failed, V18 is closed before portfolio
simulation.

This phase performs no feature changes, class-weight changes, probability
thresholding, model refitting, hyperparameter changes, portfolio simulation,
future-holdout scoring, model freezing, paper activation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v18_ranker_meta_gate"

PHASE2_ROOT = Path(
    "data/model/shared_crypto_v18_ranker_meta_gate/phase2"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v18_ranker_meta_gate/phase3"
)

HOLDOUT = "2026-09-01T00:00:00+00:00"

EXPECTED_GATE_COLUMNS = (
    "gate_median_fold_balanced_accuracy_gt_55pct",
    "gate_median_fold_macro_f1_gt_55pct",
    "gate_median_fold_mcc_gt_zero",
    "gate_median_fold_minimum_class_recall_gt_50pct",
)


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if len(gate_detail) != 1:
        raise RuntimeError(
            "V18 Phase 2 must contain exactly one predictive gate row"
        )

    if len(summary) != 1:
        raise RuntimeError(
            "V18 Phase 2 metrics summary must contain exactly one row"
        )

    row = gate_detail.iloc[0]
    summary_row = summary.iloc[0]

    required = {
        *EXPECTED_GATE_COLUMNS,
        "passed_gate_count",
        "total_gate_count",
    }

    missing = required - set(
        gate_detail.columns
    )

    if missing:
        raise RuntimeError(
            "V18 Phase 2 gate detail missing columns: "
            f"{sorted(missing)}"
        )

    total = int(
        row["total_gate_count"]
    )
    passed = int(
        row["passed_gate_count"]
    )

    if total != 4:
        raise RuntimeError(
            "V18 expected exactly four predictive gates"
        )

    if int(
        gate_result[
            "total_predictive_gate_count"
        ]
    ) != total:
        raise RuntimeError(
            "V18 total predictive gate count is inconsistent"
        )

    if int(
        gate_result[
            "passed_predictive_gate_count"
        ]
    ) != passed:
        raise RuntimeError(
            "V18 passed predictive gate count is inconsistent"
        )

    all_pass = bool(
        passed == total
    )

    if bool(
        gate_result[
            "all_predictive_gates_pass"
        ]
    ) != all_pass:
        raise RuntimeError(
            "V18 all_predictive_gates_pass flag is inconsistent"
        )

    expected_status = (
        "ALLOW_POLICY_SIMULATION"
        if all_pass
        else "STOP_BEFORE_PORTFOLIO_SIMULATION"
    )

    if str(
        gate_result[
            "status"
        ]
    ) != expected_status:
        raise RuntimeError(
            "V18 Phase 2 predictive status is inconsistent"
        )

    required_summary = {
        "median_fold_balanced_accuracy",
        "median_fold_macro_f1",
        "median_fold_mcc",
        "median_fold_minimum_class_recall",
        "median_fold_cash_recall",
        "median_fold_deploy_recall",
        "median_fold_predicted_deploy_fraction",
        "median_fold_actual_deploy_fraction",
    }

    missing = required_summary - set(
        summary.columns
    )

    if missing:
        raise RuntimeError(
            "V18 metrics summary missing columns: "
            f"{sorted(missing)}"
        )

    failed_gates = [
        gate
        for gate in EXPECTED_GATE_COLUMNS
        if not bool(
            row[gate]
        )
    ]

    disposition = gate_detail.copy()
    disposition[
        "failed_gates"
    ] = ",".join(
        failed_gates
    )

    decision = {
        "status": (
            "QUALIFIED_FOR_POLICY_SIMULATION"
            if all_pass
            else "REJECT_CURRENT_V18_RANKER_META_GATE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": bool(
            all_pass
        ),
        "passed_predictive_gate_count": passed,
        "total_predictive_gate_count": total,
        "failed_gates": failed_gates,
        "observed_predictive_metrics": {
            "median_fold_balanced_accuracy": float(
                summary_row[
                    "median_fold_balanced_accuracy"
                ]
            ),
            "median_fold_macro_f1": float(
                summary_row[
                    "median_fold_macro_f1"
                ]
            ),
            "median_fold_mcc": float(
                summary_row[
                    "median_fold_mcc"
                ]
            ),
            "median_fold_minimum_class_recall": float(
                summary_row[
                    "median_fold_minimum_class_recall"
                ]
            ),
            "median_fold_cash_recall": float(
                summary_row[
                    "median_fold_cash_recall"
                ]
            ),
            "median_fold_deploy_recall": float(
                summary_row[
                    "median_fold_deploy_recall"
                ]
            ),
            "median_fold_predicted_deploy_fraction": float(
                summary_row[
                    "median_fold_predicted_deploy_fraction"
                ]
            ),
            "median_fold_actual_deploy_fraction": float(
                summary_row[
                    "median_fold_actual_deploy_fraction"
                ]
            ),
        },
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
            "Unexpected V18 Phase 2 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V18 Phase 2 holdout boundary"
        )

    if (
        manifest.get(
            "binary_target"
        )
        != "selected_top3_profitable_7d"
    ):
        raise RuntimeError(
            "Unexpected V18 binary target"
        )

    if (
        manifest.get(
            "continuous_reference_target"
        )
        != "selected_top3_mean_net_terminal_return_7d_25bps"
    ):
        raise RuntimeError(
            "Unexpected V18 continuous target"
        )

    if (
        manifest.get(
            "decision_rule"
        )
        != "direct_classifier_class_prediction"
    ):
        raise RuntimeError(
            "Unexpected V18 decision rule"
        )

    if (
        manifest.get(
            "probability_threshold"
        )
        is not None
    ):
        raise RuntimeError(
            "V18 must not use a probability threshold"
        )

    if (
        manifest.get(
            "model"
        )
        != "hist_gradient_boosting_classifier"
    ):
        raise RuntimeError(
            "Unexpected V18 model"
        )

    if (
        manifest.get(
            "class_weight_method"
        )
        != "balanced_sample_weight"
    ):
        raise RuntimeError(
            "Unexpected V18 class-weight method"
        )

    if int(
        manifest.get(
            "model_feature_count",
            -1,
        )
    ) != 29:
        raise RuntimeError(
            "Unexpected V18 model feature count"
        )

    if int(
        manifest.get(
            "fold_count",
            -1,
        )
    ) != 6:
        raise RuntimeError(
            "Unexpected V18 fold count"
        )

    safety = manifest.get(
        "safety",
        {},
    )

    for key in (
        "shared_crypto_v15_modified",
        "shared_crypto_v16_modified",
        "shared_crypto_v17_modified",
        "v15_ranker_refit",
        "future_holdout_scored",
        "portfolio_simulated",
        "feature_search_performed",
        "model_family_searched",
        "secondary_model_fit",
        "hyperparameters_tuned",
        "probability_threshold_used",
        "probability_threshold_searched",
        "predictive_gate_lowered",
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
                "V18 Phase 2 safety invariant failed: "
                f"{key}"
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

    disposition, decision = adjudicate(
        gate_detail,
        gate_result,
        summary,
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
        "stage": (
            "immutable_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT,
        **decision,
        "reason": (
            "V18 required all four preregistered selected-basket deployment "
            "predictive gates before combining its meta-gate with the frozen "
            "V15 ranker. Only median MCC passed. Balanced accuracy and macro "
            "F1 remained below the frozen >55% requirements, and minimum class "
            "recall remained below the frozen >50% requirement. The meta-gate "
            "therefore does not provide sufficiently reliable CASH/DEPLOY "
            "separation and is rejected before portfolio simulation."
        ),
        "observed_development_conclusion": {
            "balanced_accuracy": (
                "Median balanced accuracy was approximately 54.48%, below "
                "the frozen >55% requirement."
            ),
            "macro_f1": (
                "Median macro F1 was approximately 52.94%, below the frozen "
                ">55% requirement."
            ),
            "mcc": (
                "Median MCC was positive at approximately 0.0958 and was the "
                "only predictive gate that passed."
            ),
            "minimum_class_recall": (
                "Median minimum-class recall was approximately 40.58%, below "
                "the frozen >50% requirement."
            ),
            "cash_vs_deploy_balance": (
                "Median DEPLOY recall was materially stronger than CASH recall, "
                "and predicted deployment frequency exceeded actual deployment "
                "frequency, indicating a mild over-deployment bias."
            ),
            "fold_instability": (
                "Only fold 3 cleared all four classifier quality thresholds "
                "simultaneously; the remaining folds showed inconsistent "
                "CASH/DEPLOY separation across regimes."
            ),
        },
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
            "probability_threshold_added_after_results": False,
            "probability_threshold_search_performed": False,
            "class_weights_changed_after_results": False,
            "features_changed_after_results": False,
            "model_changed_after_results": False,
            "model_refit": False,
            "v15_ranker_modified": False,
            "v15_ranker_refit": False,
            "portfolio_simulated": False,
            "future_holdout_scored": False,
            "v18_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V18 as rejected predictive evidence. Do not add or tune "
            "a probability threshold, alter class weights, change the 29 "
            "features, retune HGB, lower gates, or simulate the meta-gated V15 "
            "portfolio. Any successor should materially change the research "
            "question rather than continue iterating on the same binary gate."
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


def main(
    argv=None,
) -> None:
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

    args = parser.parse_args(
        argv
    )

    print(
        json.dumps(
            run(
                args.phase2_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
