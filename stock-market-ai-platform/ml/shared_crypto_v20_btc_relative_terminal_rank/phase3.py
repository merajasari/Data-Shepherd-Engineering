"""Shared Crypto V20 BTC-Relative Terminal Rank Phase 3.

Immutable predictive adjudication for V20.

OFFLINE RESEARCH ONLY.
No brokerage orders, no paper-state mutation, and no automatic promotion.

Reads only Phase 2 predictive evidence. V20 required all five preregistered
predictive gates before any offline portfolio simulation. If any gate failed,
V20 is closed before simulation.

This phase performs no model refit, feature change, hyperparameter change,
threshold change, top-k change, portfolio simulation, or future-holdout scoring.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v20_btc_relative_terminal_rank"

PHASE2_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase2"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase3"
)

HOLDOUT = "2026-09-01T00:00:00+00:00"

EXPECTED_GATE_COLUMNS = (
    "gate_median_fold_daily_spearman_ic_gt_005",
    "gate_median_fold_positive_ic_day_fraction_gt_52pct",
    "gate_median_fold_top3_btc_relative_terminal_excess_gt_zero",
    "gate_positive_fold_top3_btc_relative_terminal_excess_fraction_gte_75pct",
    "gate_median_fold_top3_daily_btc_win_fraction_gt_50pct",
)


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if len(gate_detail) != 1:
        raise RuntimeError(
            "V20 Phase 2 must contain exactly one predictive gate row"
        )

    if len(summary) != 1:
        raise RuntimeError(
            "V20 Phase 2 metrics summary must contain exactly one row"
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
            "V20 Phase 2 gate detail missing columns: "
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

    if total != 5:
        raise RuntimeError(
            "V20 expected exactly five predictive gates"
        )

    if int(
        gate_result[
            "total_predictive_gate_count"
        ]
    ) != total:
        raise RuntimeError(
            "V20 total predictive gate count is inconsistent"
        )

    if int(
        gate_result[
            "passed_predictive_gate_count"
        ]
    ) != passed:
        raise RuntimeError(
            "V20 passed predictive gate count is inconsistent"
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
            "V20 all_predictive_gates_pass flag is inconsistent"
        )

    expected_status = (
        "ALLOW_OFFLINE_PORTFOLIO_SIMULATION"
        if all_pass
        else "STOP_BEFORE_PORTFOLIO_SIMULATION"
    )

    if str(
        gate_result[
            "status"
        ]
    ) != expected_status:
        raise RuntimeError(
            "V20 Phase 2 predictive status is inconsistent"
        )

    required_summary = {
        "median_fold_daily_spearman_ic",
        "median_fold_positive_ic_day_fraction",
        "median_fold_top3_btc_relative_terminal_excess",
        "positive_fold_top3_btc_relative_terminal_excess_fraction",
        "median_fold_top3_daily_btc_win_fraction",
    }

    missing = required_summary - set(
        summary.columns
    )

    if missing:
        raise RuntimeError(
            "V20 metrics summary missing columns: "
            f"{sorted(missing)}"
        )

    failed_gates = [
        gate
        for gate in EXPECTED_GATE_COLUMNS
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
            "QUALIFIED_FOR_OFFLINE_PORTFOLIO_SIMULATION"
            if all_pass
            else "REJECT_CURRENT_V20_BTC_RELATIVE_TERMINAL_RANK_HYPOTHESIS"
        ),
        "offline_portfolio_simulation_allowed": bool(
            all_pass
        ),
        "passed_predictive_gate_count": passed,
        "total_predictive_gate_count": total,
        "failed_gates": failed_gates,
        "observed_predictive_metrics": {
            "median_fold_daily_spearman_ic": float(
                summary_row[
                    "median_fold_daily_spearman_ic"
                ]
            ),
            "median_fold_positive_ic_day_fraction": float(
                summary_row[
                    "median_fold_positive_ic_day_fraction"
                ]
            ),
            "median_fold_top3_btc_relative_terminal_excess": float(
                summary_row[
                    "median_fold_top3_btc_relative_terminal_excess"
                ]
            ),
            "positive_fold_top3_btc_relative_terminal_excess_fraction": float(
                summary_row[
                    "positive_fold_top3_btc_relative_terminal_excess_fraction"
                ]
            ),
            "median_fold_top3_daily_btc_win_fraction": float(
                summary_row[
                    "median_fold_top3_daily_btc_win_fraction"
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
            "Unexpected V20 Phase 2 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V20 Phase 2 holdout boundary"
        )

    if (
        manifest.get(
            "learning_target"
        )
        != "target_btc_relative_terminal_percentile_rank_7d"
    ):
        raise RuntimeError(
            "Unexpected V20 learning target"
        )

    if (
        manifest.get(
            "economic_evaluation_target"
        )
        != "btc_relative_net_terminal_return_7d_25bps"
    ):
        raise RuntimeError(
            "Unexpected V20 economic target"
        )

    if (
        manifest.get(
            "model"
        )
        != "hist_gradient_boosting_regressor"
    ):
        raise RuntimeError(
            "Unexpected V20 model"
        )

    if int(
        manifest.get(
            "model_feature_count",
            -1,
        )
    ) != 22:
        raise RuntimeError(
            "Unexpected V20 model feature count"
        )

    if int(
        manifest.get(
            "fold_count",
            -1,
        )
    ) != 8:
        raise RuntimeError(
            "Unexpected V20 fold count"
        )

    safety = manifest.get(
        "safety",
        {},
    )

    if (
        safety.get(
            "offline_research_only"
        )
        is not True
    ):
        raise RuntimeError(
            "V20 must remain offline research only"
        )

    for key in (
        "shared_crypto_v15_modified",
        "shared_crypto_v19_modified",
        "future_holdout_scored",
        "portfolio_simulated",
        "model_family_searched",
        "secondary_model_fit",
        "hyperparameters_tuned",
        "predictive_gate_lowered",
        "threshold_search_performed",
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
                "V20 Phase 2 safety invariant failed: "
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

    disposition, decision = (
        adjudicate(
            gate_detail,
            gate_result,
            summary,
        )
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
            "V20 required all five preregistered predictive gates before any "
            "offline portfolio simulation. Cross-sectional ranking quality "
            "passed both IC gates, but the predicted top-three basket failed "
            "all three BTC-relative economic gates: median fold excess was "
            "negative, only a minority of folds had positive mean excess, and "
            "the typical fold beat BTC on fewer than half of validation days. "
            "V20 is therefore rejected before portfolio simulation."
        ),
        "observed_development_conclusion": {
            "ranking_signal": (
                "Median fold daily Spearman IC was approximately 0.0841 and "
                "median positive-IC-day fraction was approximately 64.44%, "
                "confirming useful cross-sectional ordering signal."
            ),
            "median_btc_relative_excess": (
                "Median fold top-three BTC-relative terminal excess was "
                "approximately -0.2034%, below the required >0 threshold."
            ),
            "fold_consistency": (
                "Only 25% of folds had positive mean top-three BTC-relative "
                "terminal excess, below the required 75%."
            ),
            "daily_btc_win_rate": (
                "Median fold top-three daily BTC win fraction was approximately "
                "40.83%, below the required >50%."
            ),
            "interpretation": (
                "The model can rank the cross section better than random, but "
                "that ordering does not reliably concentrate enough BTC-relative "
                "return in the predicted top three."
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
            "offline_research_only": True,
            "predictive_gates_changed_after_results": False,
            "top_k_changed_after_results": False,
            "features_changed_after_results": False,
            "model_changed_after_results": False,
            "model_refit": False,
            "hyperparameters_changed_after_results": False,
            "threshold_search_performed": False,
            "portfolio_simulated": False,
            "future_holdout_scored": False,
            "v20_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V20 as rejected predictive evidence. Do not change top-k, "
            "lower BTC-relative economic gates, retune the HGB, alter the 22 "
            "features, or simulate the V20 portfolio. Any successor should "
            "materially change the research formulation rather than optimize "
            "around the observed V20 failures."
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
