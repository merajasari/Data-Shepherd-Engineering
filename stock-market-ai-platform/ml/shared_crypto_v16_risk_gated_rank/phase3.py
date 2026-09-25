"""Shared Crypto V16 Risk-Gated Rank Phase 3.

Immutable predictive adjudication for V16.

Reads only Phase 2 market-risk predictive evidence. If any of the four
preregistered predictive gates failed, V16 is closed before portfolio
simulation.

This phase performs no threshold changes, class rebalancing, model refitting,
hyperparameter changes, feature changes, portfolio simulation, future-holdout
scoring, model freezing, paper activation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v16_risk_gated_rank"

PHASE2_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase2"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v16_risk_gated_rank/phase3"
)

HOLDOUT = "2026-09-01T00:00:00+00:00"

EXPECTED_GATE_COLUMNS = (
    "gate_median_fold_spearman_ic_gt_010",
    "gate_median_fold_balanced_accuracy_gt_55pct",
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
            "V16 Phase 2 must contain exactly one predictive gate row"
        )

    if len(summary) != 1:
        raise RuntimeError(
            "V16 Phase 2 metrics summary must contain exactly one row"
        )

    row = gate_detail.iloc[0]
    summary_row = summary.iloc[0]

    required = {
        *EXPECTED_GATE_COLUMNS,
        "passed_gate_count",
        "total_gate_count",
    }

    missing = (
        required
        - set(
            gate_detail.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V16 Phase 2 gate detail missing columns: "
            f"{sorted(missing)}"
        )

    total = int(
        row[
            "total_gate_count"
        ]
    )

    passed = int(
        row[
            "passed_gate_count"
        ]
    )

    if total != 4:
        raise RuntimeError(
            "V16 expected exactly four predictive gates"
        )

    if int(
        gate_result[
            "total_predictive_gate_count"
        ]
    ) != total:
        raise RuntimeError(
            "V16 total predictive gate count is inconsistent"
        )

    if int(
        gate_result[
            "passed_predictive_gate_count"
        ]
    ) != passed:
        raise RuntimeError(
            "V16 passed predictive gate count is inconsistent"
        )

    all_pass = bool(
        passed
        == total
    )

    if bool(
        gate_result[
            "all_predictive_gates_pass"
        ]
    ) != all_pass:
        raise RuntimeError(
            "V16 all_predictive_gates_pass flag is inconsistent"
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
            "V16 Phase 2 predictive status is inconsistent"
        )

    required_summary = {
        "median_fold_spearman_ic",
        "median_fold_balanced_accuracy",
        "median_fold_mcc",
        "median_fold_minimum_class_recall",
        "median_fold_risk_off_recall",
        "median_fold_risk_on_recall",
        "median_fold_predicted_positive_fraction",
        "median_fold_actual_positive_fraction",
    }

    missing = (
        required_summary
        - set(
            summary.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V16 metrics summary missing columns: "
            f"{sorted(missing)}"
        )

    failed_gates = [
        gate
        for gate
        in EXPECTED_GATE_COLUMNS
        if not bool(
            row[
                gate
            ]
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
            else "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": bool(
            all_pass
        ),
        "passed_predictive_gate_count": (
            passed
        ),
        "total_predictive_gate_count": (
            total
        ),
        "failed_gates": (
            failed_gates
        ),
        "observed_predictive_metrics": {
            "median_fold_spearman_ic": float(
                summary_row[
                    "median_fold_spearman_ic"
                ]
            ),
            "median_fold_balanced_accuracy": float(
                summary_row[
                    "median_fold_balanced_accuracy"
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
            "median_fold_risk_off_recall": float(
                summary_row[
                    "median_fold_risk_off_recall"
                ]
            ),
            "median_fold_risk_on_recall": float(
                summary_row[
                    "median_fold_risk_on_recall"
                ]
            ),
            "median_fold_predicted_positive_fraction": float(
                summary_row[
                    "median_fold_predicted_positive_fraction"
                ]
            ),
            "median_fold_actual_positive_fraction": float(
                summary_row[
                    "median_fold_actual_positive_fraction"
                ]
            ),
        },
    }

    return (
        disposition,
        decision,
    )


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
            "Unexpected V16 Phase 2 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V16 Phase 2 holdout boundary"
        )

    if (
        manifest.get(
            "market_target"
        )
        != "market_median_path_utility_net25_7d"
    ):
        raise RuntimeError(
            "Unexpected V16 Phase 2 market target"
        )

    if (
        manifest.get(
            "risk_label"
        )
        != "market_risk_on_7d"
    ):
        raise RuntimeError(
            "Unexpected V16 Phase 2 risk label"
        )

    if float(
        manifest.get(
            "risk_threshold"
        )
    ) != 0.0:
        raise RuntimeError(
            "Unexpected V16 risk threshold"
        )

    if (
        manifest.get(
            "model"
        )
        != "hist_gradient_boosting_regressor"
    ):
        raise RuntimeError(
            "Unexpected V16 Phase 2 model"
        )

    if int(
        manifest.get(
            "risk_feature_count",
            -1,
        )
    ) != 18:
        raise RuntimeError(
            "Unexpected V16 risk feature count"
        )

    if int(
        manifest.get(
            "fold_count",
            -1,
        )
    ) != 8:
        raise RuntimeError(
            "Unexpected V16 fold count"
        )

    safety = manifest.get(
        "safety",
        {},
    )

    for key in (
        "shared_crypto_v15_modified",
        "v15_ranker_refit",
        "v15_portfolio_resimulated",
        "future_holdout_scored",
        "portfolio_simulated",
        "model_family_searched",
        "secondary_model_fit",
        "hyperparameters_tuned",
        "risk_threshold_changed",
        "threshold_search_performed",
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
                "V16 Phase 2 safety invariant failed: "
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

    (
        disposition,
        decision,
    ) = adjudicate(
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
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 3,
        "stage": (
            "immutable_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT
        ),
        **decision,
        "reason": (
            "V16 required all four preregistered market-risk predictive gates "
            "before combining the risk gate with the frozen V15 ranker. Only "
            "the median MCC gate passed. Spearman IC, balanced accuracy, and "
            "minimum class recall all failed. The fixed zero-threshold model "
            "strongly favored RISK_OFF and had very low RISK_ON recall, so V16 "
            "is rejected before any risk-gated portfolio simulation."
        ),
        "observed_development_conclusion": {
            "continuous_market_utility_prediction": (
                "Median fold Spearman IC was positive but materially below the "
                "frozen >0.10 requirement."
            ),
            "risk_state_discrimination": (
                "Median balanced accuracy was approximately random at 50%."
            ),
            "correlation_with_binary_state": (
                "Median MCC was slightly positive and was the only gate that "
                "passed."
            ),
            "risk_on_detection": (
                "Median RISK_ON recall was approximately 12.35%, while "
                "RISK_OFF recall was approximately 88.85%."
            ),
            "deployment_bias": (
                "The regressor predicted positive market utility much less "
                "often than the actual positive-market frequency, causing a "
                "strong RISK_OFF bias under the frozen zero threshold."
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
            "risk_predictive_gates_changed_after_results": False,
            "risk_threshold_changed_after_results": False,
            "risk_threshold_search_performed": False,
            "class_weights_added_after_results": False,
            "risk_features_changed_after_results": False,
            "risk_model_changed_after_results": False,
            "risk_model_refit": False,
            "v15_ranker_modified": False,
            "v15_ranker_refit": False,
            "portfolio_simulated": False,
            "future_holdout_scored": False,
            "v16_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V16 as rejected predictive evidence. Do not lower the "
            "risk gates, change the zero threshold, add post-result class "
            "weighting, alter the 18 risk features, retune HGB, or simulate "
            "the risk-gated V15 portfolio. Any successor must be separately "
            "named and preregistered before fitting."
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
