"""Shared Crypto V14 Path Utility Rank Phase 3.

Immutable predictive adjudication for V14.

Reads only Phase 2 predictive ranking evidence and records whether the
preregistered path-utility ranker qualified for portfolio simulation. If any
of the four predictive gates failed, V14 is closed as rejected predictive
research evidence.

This phase performs no model fitting, target changes, gate changes,
hyperparameter changes, threshold search, portfolio simulation, future-holdout
scoring, model freezing, paper activation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v14_path_utility_rank"
PHASE2_ROOT = Path(
    "data/model/shared_crypto_v14_path_utility_rank/phase2"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v14_path_utility_rank/phase3"
)
HOLDOUT = "2026-09-01T00:00:00+00:00"

EXPECTED_GATE_COLUMNS = (
    "gate_median_fold_daily_spearman_ic_gt_005",
    "gate_median_fold_positive_ic_day_fraction_gt_52pct",
    "gate_median_fold_top3_target_utility_excess_vs_universe_gt_zero",
    "gate_positive_fold_top3_target_utility_excess_fraction_gte_75pct",
)


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
    fold_metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if len(gate_detail) != 1:
        raise RuntimeError(
            "V14 Phase 2 must contain exactly one predictive gate row"
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
            f"V14 Phase 2 gate detail missing columns: {sorted(missing)}"
        )

    total = int(
        row["total_gate_count"]
    )
    passed = int(
        row["passed_gate_count"]
    )

    if total != 4:
        raise RuntimeError(
            "V14 expected exactly four predictive gates"
        )

    if int(
        gate_result[
            "total_predictive_gate_count"
        ]
    ) != total:
        raise RuntimeError(
            "V14 total predictive gate count is inconsistent"
        )

    if int(
        gate_result[
            "passed_predictive_gate_count"
        ]
    ) != passed:
        raise RuntimeError(
            "V14 passed predictive gate count is inconsistent"
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
            "V14 all_predictive_gates_pass flag is inconsistent"
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
            "V14 Phase 2 predictive status is inconsistent"
        )

    if len(summary) != 1:
        raise RuntimeError(
            "V14 Phase 2 metrics summary must contain exactly one row"
        )

    summary_row = summary.iloc[0]

    required_summary = {
        "median_fold_daily_spearman_ic",
        "mean_fold_daily_spearman_ic",
        "median_fold_positive_ic_day_fraction",
        "median_fold_top3_target_utility_excess_vs_universe",
        "mean_fold_top3_target_utility_excess_vs_universe",
        "positive_fold_top3_target_utility_excess_fraction",
    }

    missing = required_summary - set(summary.columns)
    if missing:
        raise RuntimeError(
            f"V14 metrics summary missing columns: {sorted(missing)}"
        )

    if len(fold_metrics) != 8:
        raise RuntimeError(
            "V14 Phase 2 expected exactly eight walk-forward folds"
        )

    required_fold = {
        "fold_id",
        "median_daily_spearman_ic",
        "positive_ic_day_fraction",
        "mean_top3_target_utility_excess_vs_universe",
    }
    missing = required_fold - set(fold_metrics.columns)
    if missing:
        raise RuntimeError(
            f"V14 fold metrics missing columns: {sorted(missing)}"
        )

    failed_gates = [
        gate
        for gate in EXPECTED_GATE_COLUMNS
        if not bool(
            row[gate]
        )
    ]

    positive_top3_folds = int(
        (
            pd.to_numeric(
                fold_metrics[
                    "mean_top3_target_utility_excess_vs_universe"
                ],
                errors="raise",
            )
            > 0.0
        ).sum()
    )

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
            else "REJECT_CURRENT_V14_PREDICTIVE_HYPOTHESIS"
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
            "median_fold_daily_spearman_ic": float(
                summary_row[
                    "median_fold_daily_spearman_ic"
                ]
            ),
            "mean_fold_daily_spearman_ic": float(
                summary_row[
                    "mean_fold_daily_spearman_ic"
                ]
            ),
            "median_fold_positive_ic_day_fraction": float(
                summary_row[
                    "median_fold_positive_ic_day_fraction"
                ]
            ),
            "median_fold_top3_target_utility_excess_vs_universe": float(
                summary_row[
                    "median_fold_top3_target_utility_excess_vs_universe"
                ]
            ),
            "mean_fold_top3_target_utility_excess_vs_universe": float(
                summary_row[
                    "mean_fold_top3_target_utility_excess_vs_universe"
                ]
            ),
            "positive_fold_top3_target_utility_excess_fraction": float(
                summary_row[
                    "positive_fold_top3_target_utility_excess_fraction"
                ]
            ),
        },
        "observed_fold_count": int(
            len(fold_metrics)
        ),
        "observed_positive_top3_excess_fold_count": (
            positive_top3_folds
        ),
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
            "Unexpected V14 Phase 2 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V14 Phase 2 holdout boundary"
        )

    if (
        manifest.get(
            "target"
        )
        != "path_utility_net25_7d"
    ):
        raise RuntimeError(
            "Unexpected V14 Phase 2 target"
        )

    if (
        manifest.get(
            "model"
        )
        != "hist_gradient_boosting_regressor"
    ):
        raise RuntimeError(
            "Unexpected V14 Phase 2 model"
        )

    if int(
        manifest.get(
            "model_feature_count",
            -1,
        )
    ) != 22:
        raise RuntimeError(
            "Unexpected V14 model feature count"
        )

    if int(
        manifest.get(
            "purge_days",
            -1,
        )
    ) != 7:
        raise RuntimeError(
            "Unexpected V14 purge"
        )

    if int(
        manifest.get(
            "fold_count",
            -1,
        )
    ) != 8:
        raise RuntimeError(
            "Unexpected V14 fold count"
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
        "threshold_search_performed",
        "model_frozen",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if safety.get(
            key
        ) is not False:
            raise RuntimeError(
                f"V14 Phase 2 safety invariant failed: {key}"
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

    fold_metrics = pd.read_csv(
        phase2_root
        / "fold_metrics.csv"
    )

    disposition, decision = adjudicate(
        gate_detail,
        gate_result,
        summary,
        fold_metrics,
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
            "V14 required all four preregistered predictive ranking gates to "
            "pass before portfolio simulation. Three gates passed: median "
            "positive-IC-day fraction, median predicted-top-3 target-utility "
            "excess versus the eligible universe, and the fraction of folds "
            "with positive top-3 excess. The median fold daily Spearman IC was "
            "positive but remained below the preregistered >0.05 threshold. "
            "V14 is therefore rejected before portfolio simulation."
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
            "spearman_ic_gate_lowered_after_results": False,
            "target_definition_changed_after_results": False,
            "model_hyperparameters_changed_after_results": False,
            "model_family_changed_after_results": False,
            "secondary_model_fit": False,
            "positive_utility_threshold_changed_after_results": False,
            "threshold_search_performed": False,
            "portfolio_simulated": False,
            "shared_crypto_v13_modified": False,
            "shared_crypto_v12_modified": False,
            "shared_crypto_v11_modified": False,
            "shared_crypto_v10_modified": False,
            "shared_crypto_v9_modified": False,
            "shared_crypto_v8_modified": False,
            "future_holdout_scored": False,
            "v14_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V14 as rejected predictive evidence. Do not simulate the "
            "V14 portfolio, lower the 0.05 IC gate, retune the regressor, alter "
            "the path-utility target, change the positive-utility threshold, or "
            "score the future holdout. Any successor must be separately named "
            "and preregistered before fitting."
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
