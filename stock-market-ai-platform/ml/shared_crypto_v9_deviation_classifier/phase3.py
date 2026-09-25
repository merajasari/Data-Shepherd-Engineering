"""Shared Crypto V9 Deviation Classifier Phase 3.

Immutable predictive adjudication for V9.

Reads only Phase 2 predictive evidence and records whether the preregistered
classifier hypothesis qualified for portfolio simulation.  If any of the eight
predictive gates failed, V9 is closed as rejected predictive evidence.

This phase performs no model fitting, threshold tuning, portfolio simulation,
future-holdout scoring, model freezing, paper activation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v9_deviation_classifier"
PHASE2_ROOT = Path(
    "data/model/shared_crypto_v9_deviation_classifier/phase2"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v9_deviation_classifier/phase3"
)
HOLDOUT = "2026-09-01T00:00:00+00:00"
EXPECTED_TARGETS = {
    "alt_beats_btc_net25_72h",
    "cash_beats_btc_net25_72h",
}
EXPECTED_GATE_COLUMNS = (
    "gate_median_roc_auc_gt_52pct",
    "gate_median_balanced_accuracy_gt_52pct",
    "gate_median_brier_improvement_gt_zero",
    "gate_median_log_loss_improvement_gt_zero",
)


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if set(gate_detail["target"]) != EXPECTED_TARGETS:
        raise RuntimeError(
            "V9 Phase 2 predictive targets do not match preregistration"
        )
    if len(gate_detail) != 2:
        raise RuntimeError(
            "V9 Phase 2 must contain exactly two target gate rows"
        )

    required = {
        *EXPECTED_GATE_COLUMNS,
        "passed_gate_count",
        "total_gate_count",
    }
    missing = required - set(gate_detail.columns)
    if missing:
        raise RuntimeError(
            f"V9 Phase 2 gate detail missing columns: {sorted(missing)}"
        )

    total = int(
        gate_detail["total_gate_count"].sum()
    )
    passed = int(
        gate_detail["passed_gate_count"].sum()
    )

    if int(
        gate_result["total_predictive_gate_count"]
    ) != total:
        raise RuntimeError(
            "V9 total predictive gate count is inconsistent"
        )
    if int(
        gate_result["passed_predictive_gate_count"]
    ) != passed:
        raise RuntimeError(
            "V9 passed predictive gate count is inconsistent"
        )

    all_pass = bool(
        (
            gate_detail["passed_gate_count"]
            == gate_detail["total_gate_count"]
        ).all()
    )

    if bool(
        gate_result["all_predictive_gates_pass"]
    ) != all_pass:
        raise RuntimeError(
            "V9 all_predictive_gates_pass flag is inconsistent"
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
            "V9 Phase 2 predictive status is inconsistent"
        )

    required_summary = {
        "target",
        "median_roc_auc",
        "median_balanced_accuracy",
        "median_brier_improvement_vs_train_prevalence",
        "median_log_loss_improvement_vs_train_prevalence",
    }
    missing = required_summary - set(summary.columns)
    if missing:
        raise RuntimeError(
            f"V9 metrics summary missing columns: {sorted(missing)}"
        )

    disposition = gate_detail.copy()
    disposition["failed_gates"] = disposition.apply(
        lambda row: ",".join(
            gate
            for gate in EXPECTED_GATE_COLUMNS
            if not bool(row[gate])
        ),
        axis=1,
    )

    target_results = {}
    for target in sorted(EXPECTED_TARGETS):
        metric_row = summary[
            summary["target"] == target
        ]
        gate_row = disposition[
            disposition["target"] == target
        ]

        if len(metric_row) != 1:
            raise RuntimeError(
                f"Missing unique V9 summary row for {target}"
            )
        if len(gate_row) != 1:
            raise RuntimeError(
                f"Missing unique V9 gate row for {target}"
            )

        metric_row = metric_row.iloc[0]
        gate_row = gate_row.iloc[0]

        target_results[target] = {
            "median_roc_auc": float(
                metric_row["median_roc_auc"]
            ),
            "median_balanced_accuracy": float(
                metric_row["median_balanced_accuracy"]
            ),
            "median_brier_improvement_vs_train_prevalence": float(
                metric_row[
                    "median_brier_improvement_vs_train_prevalence"
                ]
            ),
            "median_log_loss_improvement_vs_train_prevalence": float(
                metric_row[
                    "median_log_loss_improvement_vs_train_prevalence"
                ]
            ),
            "passed_gate_count": int(
                gate_row["passed_gate_count"]
            ),
            "total_gate_count": int(
                gate_row["total_gate_count"]
            ),
            "failed_gates": [
                value
                for value in str(
                    gate_row["failed_gates"]
                ).split(",")
                if value
            ],
        }

    return disposition, {
        "status": (
            "QUALIFIED_FOR_POLICY_SIMULATION"
            if all_pass
            else "REJECT_CURRENT_V9_PREDICTIVE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": bool(
            all_pass
        ),
        "passed_predictive_gate_count": passed,
        "total_predictive_gate_count": total,
        "passed_target_count": int(
            (
                disposition["passed_gate_count"]
                == disposition["total_gate_count"]
            ).sum()
        ),
        "target_count": int(
            len(disposition)
        ),
        "target_results": target_results,
    }


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
        manifest.get("research_version")
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V9 Phase 2 research version"
        )
    if (
        manifest.get("future_holdout_start_utc")
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V9 Phase 2 holdout boundary"
        )
    if (
        manifest.get("primary_model")
        != "logistic_regression"
    ):
        raise RuntimeError(
            "Unexpected V9 Phase 2 primary model"
        )
    if (
        float(
            manifest.get("logistic_C")
        )
        != 0.5
    ):
        raise RuntimeError(
            "Unexpected V9 Phase 2 logistic C"
        )
    if (
        float(
            manifest.get(
                "probability_threshold"
            )
        )
        != 0.5
    ):
        raise RuntimeError(
            "Unexpected V9 Phase 2 probability threshold"
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
            "V9 Phase 2 unexpectedly searched secondary models"
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
        "probability_threshold_tuned",
        "model_frozen",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if safety.get(key) is not False:
            raise RuntimeError(
                f"V9 Phase 2 safety invariant failed: {key}"
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
        "stage": "immutable_predictive_adjudication",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": HOLDOUT,
        **decision,
        "reason": (
            "V9 required all eight preregistered predictive gates to pass "
            "before portfolio simulation. ALT passed only median balanced "
            "accuracy; CASH passed only median ROC-AUC. Both targets failed "
            "the Brier-score and log-loss improvement gates versus the "
            "training-prevalence baseline. V9 is therefore rejected before "
            "portfolio simulation."
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
            "probability_threshold_changed_after_results": False,
            "threshold_search_performed": False,
            "model_family_changed_after_results": False,
            "secondary_model_fit": False,
            "portfolio_simulated": False,
            "shared_crypto_v8_modified": False,
            "shared_crypto_v7_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "v9_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V9 as rejected predictive evidence. Any successor must "
            "be separately named and preregistered before fitting. Do not "
            "simulate the V9 portfolio, change its probability threshold, "
            "retune logistic C, weaken predictive gates, search model families, "
            "or score the future holdout."
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
