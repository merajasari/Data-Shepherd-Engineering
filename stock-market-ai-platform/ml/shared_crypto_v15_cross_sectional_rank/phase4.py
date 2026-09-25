"""Shared Crypto V15 Cross-Sectional Rank Phase 4.

Immutable development adjudication.

Reads the single preregistered V15 Phase 3 portfolio result and records whether
V15 may advance. This phase performs no model fitting, target changes,
hyperparameter tuning, gate changes, threshold search, portfolio resimulation,
future-holdout scoring, model freezing, paper activation, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v15_cross_sectional_rank"
PHASE3_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase3"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase4"
)
HOLDOUT = "2026-09-01T00:00:00+00:00"
GATE_PREFIX = "gate_"


def adjudicate(
    gates: dict,
    summary: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    required_gate_keys = {
        "passed_gate_count",
        "total_gate_count",
        "status",
    }
    missing = (
        required_gate_keys
        - set(
            gates
        )
    )
    if missing:
        raise RuntimeError(
            "V15 Phase 3 gate results missing keys: "
            f"{sorted(missing)}"
        )

    gate_keys = sorted(
        key
        for key
        in gates
        if key.startswith(
            GATE_PREFIX
        )
    )

    if not gate_keys:
        raise RuntimeError(
            "V15 Phase 3 produced no preregistered portfolio gates"
        )

    passed_count = int(
        sum(
            bool(
                gates[
                    key
                ]
            )
            for key
            in gate_keys
        )
    )

    total_count = int(
        gates[
            "total_gate_count"
        ]
    )

    if total_count != len(
        gate_keys
    ):
        raise RuntimeError(
            "V15 Phase 3 total gate count does not match gate keys"
        )

    if int(
        gates[
            "passed_gate_count"
        ]
    ) != passed_count:
        raise RuntimeError(
            "V15 Phase 3 passed gate count does not match gate values"
        )

    required_summary_columns = {
        "cost_bps",
        "fold_count",
        "median_fold_net_return",
        "mean_fold_net_return",
        "positive_fold_fraction",
        "median_excess_vs_btc",
        "median_excess_vs_shared_v3",
        "positive_excess_vs_shared_v3_fraction",
        "worst_maximum_drawdown",
        "single_fold_profit_concentration",
        "mean_total_turnover",
        "mean_cash_weight",
        "mean_crypto_weight",
    }

    missing = (
        required_summary_columns
        - set(
            summary.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V15 Phase 3 policy summary missing columns: "
            f"{sorted(missing)}"
        )

    primary = summary[
        summary[
            "cost_bps"
        ]
        == 25.0
    ]

    stress = summary[
        summary[
            "cost_bps"
        ]
        == 50.0
    ]

    if (
        len(
            primary
        )
        != 1
        or len(
            stress
        )
        != 1
    ):
        raise RuntimeError(
            "V15 Phase 3 primary or stress policy summary is missing"
        )

    primary_row = primary.iloc[
        0
    ]
    stress_row = stress.iloc[
        0
    ]

    failed = [
        key
        for key
        in gate_keys
        if not bool(
            gates[
                key
            ]
        )
    ]

    qualified = bool(
        passed_count
        == len(
            gate_keys
        )
    )

    expected_phase3_status = (
        "QUALIFIES_FOR_HUMAN_REVIEW"
        if qualified
        else "DO_NOT_ADVANCE"
    )

    if str(
        gates[
            "status"
        ]
    ) != expected_phase3_status:
        raise RuntimeError(
            "V15 Phase 3 status is inconsistent with its gate values"
        )

    disposition = pd.DataFrame([
        {
            **gates,
            "failed_gates": (
                ",".join(
                    failed
                )
            ),
        }
    ])

    decision = {
        "status": (
            "QUALIFIED_FOR_HUMAN_REVIEW"
            if qualified
            else "REJECT_CURRENT_V15_POLICY_FAMILY"
        ),
        "qualifying_candidate_count": int(
            qualified
        ),
        "single_preregistered_policy": {
            "primary_cost_bps": 25.0,
            "stress_cost_bps": 50.0,
            "fold_count": int(
                primary_row[
                    "fold_count"
                ]
            ),
            "passed_gate_count": int(
                passed_count
            ),
            "total_gate_count": int(
                len(
                    gate_keys
                )
            ),
            "median_fold_net_return": float(
                primary_row[
                    "median_fold_net_return"
                ]
            ),
            "mean_fold_net_return": float(
                primary_row[
                    "mean_fold_net_return"
                ]
            ),
            "positive_fold_fraction": float(
                primary_row[
                    "positive_fold_fraction"
                ]
            ),
            "median_excess_vs_always_btc": float(
                primary_row[
                    "median_excess_vs_btc"
                ]
            ),
            "median_excess_vs_shared_v3": float(
                primary_row[
                    "median_excess_vs_shared_v3"
                ]
            ),
            "positive_excess_vs_shared_v3_fraction": float(
                primary_row[
                    "positive_excess_vs_shared_v3_fraction"
                ]
            ),
            "worst_maximum_drawdown": float(
                primary_row[
                    "worst_maximum_drawdown"
                ]
            ),
            "single_fold_profit_concentration": float(
                primary_row[
                    "single_fold_profit_concentration"
                ]
            ),
            "mean_total_turnover": float(
                primary_row[
                    "mean_total_turnover"
                ]
            ),
            "mean_cash_weight": float(
                primary_row[
                    "mean_cash_weight"
                ]
            ),
            "mean_crypto_weight": float(
                primary_row[
                    "mean_crypto_weight"
                ]
            ),
            "stress_median_fold_net_return": float(
                stress_row[
                    "median_fold_net_return"
                ]
            ),
            "stress_mean_fold_net_return": float(
                stress_row[
                    "mean_fold_net_return"
                ]
            ),
            "stress_worst_maximum_drawdown": float(
                stress_row[
                    "worst_maximum_drawdown"
                ]
            ),
            "stress_single_fold_profit_concentration": float(
                stress_row[
                    "single_fold_profit_concentration"
                ]
            ),
            "failed_gates": (
                failed
            ),
        },
    }

    return (
        disposition,
        decision,
    )


def run(
    phase3_root: Path = PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase3_root = Path(
        phase3_root
    )
    output_root = Path(
        output_root
    )

    manifest = json.loads(
        (
            phase3_root
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
            "Unexpected V15 Phase 3 research version"
        )

    if (
        manifest.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT
    ):
        raise RuntimeError(
            "Unexpected V15 Phase 3 holdout boundary"
        )

    if (
        manifest.get(
            "predictive_permission"
        )
        != "ALLOW_POLICY_SIMULATION"
    ):
        raise RuntimeError(
            "V15 Phase 3 lacks predictive permission"
        )

    if int(
        manifest.get(
            "candidate_count",
            0,
        )
    ) != 1:
        raise RuntimeError(
            "V15 Phase 3 did not evaluate exactly one preregistered policy"
        )

    if (
        manifest.get(
            "gate_status"
        )
        != "DO_NOT_ADVANCE"
    ):
        raise RuntimeError(
            "V15 Phase 4 expected the observed DO_NOT_ADVANCE policy result"
        )

    if int(
        manifest.get(
            "passed_gate_count",
            -1,
        )
    ) != 3:
        raise RuntimeError(
            "V15 Phase 4 expected exactly three passed portfolio gates"
        )

    if int(
        manifest.get(
            "total_gate_count",
            -1,
        )
    ) != 8:
        raise RuntimeError(
            "V15 Phase 4 expected exactly eight portfolio gates"
        )

    if int(
        manifest.get(
            "fold_count",
            -1,
        )
    ) != 7:
        raise RuntimeError(
            "V15 Phase 4 expected seven matched benchmark folds"
        )

    safety = manifest.get(
        "safety",
        {},
    )

    for key in (
        "policy_changed_after_predictive_results",
        "portfolio_gate_changed_after_results",
        "threshold_search_performed",
        "candidate_search_performed",
        "future_holdout_scored",
        "model_refit",
        "model_frozen_automatically",
        "shared_crypto_v3_modified",
        "shared_crypto_v14_modified",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if safety.get(
            key
        ) is not False:
            raise RuntimeError(
                "V15 Phase 3 safety invariant failed: "
                f"{key}"
            )

    gates = json.loads(
        (
            phase3_root
            / "gate_results.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    summary = pd.read_csv(
        phase3_root
        / "policy_summary.csv"
    )

    (
        disposition,
        decision,
    ) = adjudicate(
        gates,
        summary,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    disposition_path = (
        output_root
        / "policy_disposition.csv"
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
        "phase": 4,
        "stage": (
            "immutable_development_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT
        ),
        **decision,
        "reason": (
            "V15 cleared all four predictive ranking gates, but the single "
            "preregistered portfolio policy may advance only if all eight "
            "portfolio gates pass. Only three passed. Median absolute fold "
            "return and 50-bps stress median return were positive, and median "
            "excess versus Shared Crypto V3 was positive. However, only four "
            "of seven matched folds were profitable, median excess versus "
            "always-BTC was negative, only five of seven folds beat Shared "
            "Crypto V3, worst drawdown breached the -20% limit, and profits "
            "were too concentrated in the strongest fold."
        ),
        "observed_development_conclusion": {
            "predictive_ranking": (
                "V15 passed all four preregistered predictive ranking gates in Phase 2."
            ),
            "absolute_return_level": (
                "The frozen V15 policy passed the median fold net-return gate."
            ),
            "absolute_return_stability": (
                "The frozen V15 policy failed the >=80% positive-fold gate at 4/7 folds."
            ),
            "relative_to_always_btc": (
                "The frozen V15 policy failed the median excess versus always-BTC gate."
            ),
            "relative_to_shared_crypto_v3": (
                "Median excess versus Shared Crypto V3 was positive, but only 5/7 matched folds beat V3, below the >=80% requirement."
            ),
            "risk_control": (
                "Worst maximum drawdown was approximately -36.19%, breaching the frozen -20% limit."
            ),
            "profit_distribution": (
                "Single-fold profit concentration was approximately 45.18%, above the frozen 40% ceiling."
            ),
            "cost_robustness": (
                "The frozen policy retained a positive median fold return under the 50-bps stress cost."
            ),
            "matched_benchmark_scope": (
                "Portfolio adjudication used seven folds because the frozen Shared Crypto V3 benchmark had matched observations on seven V15 fold clocks."
            ),
        },
        "outputs": {
            "policy_disposition": str(
                disposition_path
            ),
            "adjudication": str(
                adjudication_path
            ),
        },
        "safety": {
            "portfolio_gates_changed_after_results": False,
            "predictive_gates_changed_after_results": False,
            "policy_changed_after_results": False,
            "allocation_changed_after_results": False,
            "cash_weight_changed_after_results": False,
            "turnover_limit_changed_after_results": False,
            "model_changed_after_results": False,
            "model_refit": False,
            "threshold_search_performed": False,
            "portfolio_resimulated_with_alternate_policy": False,
            "future_holdout_scored": False,
            "v15_model_frozen": False,
            "shared_crypto_v14_modified": False,
            "shared_crypto_v3_modified": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V15 as rejected portfolio evidence. Do not change the "
            "V15 top-3 allocation, cash weight, turnover cap, transaction-cost "
            "assumption, portfolio gates, or model using these observed "
            "portfolio results. Any successor must be separately named and "
            "preregistered before simulation. The useful retained evidence is "
            "that rank-target learning materially improved prediction, while "
            "the fixed 60%-crypto top-3 portfolio was not sufficiently stable."
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
        "--phase3-root",
        type=Path,
        default=PHASE3_ROOT,
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
                args.phase3_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
