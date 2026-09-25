"""Shared Crypto V8 Relative Value Linear Phase 3: immutable predictive adjudication.

Reads the preregistered Phase 2 predictive gate result and records whether V8
may advance to portfolio simulation.  If any predictive gate failed, V8 is
closed as rejected predictive evidence.

This phase performs no model fitting, model-family search, threshold tuning,
portfolio simulation, future-holdout scoring, model freezing, paper activation,
or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v8_relative_value_linear"
PHASE2_ROOT = Path("data/model/shared_crypto_v8_relative_value_linear/phase2")
OUTPUT_ROOT = Path("data/model/shared_crypto_v8_relative_value_linear/phase3")
HOLDOUT = "2026-09-01T00:00:00+00:00"
EXPECTED_TARGETS = {
    "alt_excess_vs_btc_net25_72h",
    "cash_excess_vs_btc_net25_72h",
}


def adjudicate(
    gate_detail: pd.DataFrame,
    gate_result: dict,
    summary: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    if set(gate_detail["target"]) != EXPECTED_TARGETS:
        raise RuntimeError(
            "V8 Phase 2 predictive targets do not match preregistration"
        )
    if len(gate_detail) != 2:
        raise RuntimeError(
            "V8 Phase 2 must contain exactly two target gate rows"
        )

    required_gate_columns = {
        "gate_median_pearson_correlation_gt_zero",
        "gate_median_mae_improvement_vs_train_mean_gt_zero",
        "gate_median_sign_accuracy_gt_50pct",
        "passed_gate_count",
        "total_gate_count",
    }
    missing = required_gate_columns - set(gate_detail.columns)
    if missing:
        raise RuntimeError(
            f"V8 Phase 2 predictive gate detail missing columns: {sorted(missing)}"
        )

    expected_total = int(gate_detail["total_gate_count"].sum())
    observed_passed = int(gate_detail["passed_gate_count"].sum())

    if int(gate_result["total_predictive_gate_count"]) != expected_total:
        raise RuntimeError(
            "V8 total predictive gate count is inconsistent"
        )
    if int(gate_result["passed_predictive_gate_count"]) != observed_passed:
        raise RuntimeError(
            "V8 passed predictive gate count is inconsistent"
        )

    all_pass = bool(
        (
            gate_detail["passed_gate_count"]
            == gate_detail["total_gate_count"]
        ).all()
    )
    if bool(gate_result["all_predictive_gates_pass"]) != all_pass:
        raise RuntimeError(
            "V8 all_predictive_gates_pass flag is inconsistent"
        )

    expected_status = (
        "ALLOW_POLICY_SIMULATION"
        if all_pass
        else "STOP_BEFORE_PORTFOLIO_SIMULATION"
    )
    if str(gate_result["status"]) != expected_status:
        raise RuntimeError(
            "V8 Phase 2 predictive status is inconsistent"
        )

    required_summary_columns = {
        "target",
        "median_pearson_correlation",
        "median_mae_improvement_vs_train_mean",
        "median_sign_accuracy",
    }
    missing = required_summary_columns - set(summary.columns)
    if missing:
        raise RuntimeError(
            f"V8 Phase 2 metrics summary missing columns: {sorted(missing)}"
        )

    detail = gate_detail.copy()
    detail["failed_gates"] = detail.apply(
        lambda row: ",".join([
            name
            for name in (
                "gate_median_pearson_correlation_gt_zero",
                "gate_median_mae_improvement_vs_train_mean_gt_zero",
                "gate_median_sign_accuracy_gt_50pct",
            )
            if not bool(row[name])
        ]),
        axis=1,
    )

    target_results = {}
    for target in sorted(EXPECTED_TARGETS):
        match = summary[summary["target"] == target]
        if len(match) != 1:
            raise RuntimeError(
                f"Missing unique V8 summary row for {target}"
            )
        row = match.iloc[0]
        gate_row = detail[detail["target"] == target].iloc[0]
        target_results[target] = {
            "median_pearson_correlation": float(
                row["median_pearson_correlation"]
            ),
            "median_mae_improvement_vs_train_mean": float(
                row["median_mae_improvement_vs_train_mean"]
            ),
            "median_sign_accuracy": float(
                row["median_sign_accuracy"]
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

    decision = {
        "status": (
            "QUALIFIED_FOR_POLICY_SIMULATION"
            if all_pass
            else "REJECT_CURRENT_V8_PREDICTIVE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": bool(all_pass),
        "passed_predictive_gate_count": observed_passed,
        "total_predictive_gate_count": expected_total,
        "passed_target_count": int(
            (
                detail["passed_gate_count"]
                == detail["total_gate_count"]
            ).sum()
        ),
        "target_count": int(len(detail)),
        "target_results": target_results,
    }
    return detail, decision


def run(
    phase2_root: Path = PHASE2_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase2_root = Path(phase2_root)
    output_root = Path(output_root)

    manifest = json.loads(
        (phase2_root / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if manifest.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError(
            "Unexpected V8 Phase 2 research version"
        )
    if manifest.get("future_holdout_start_utc") != HOLDOUT:
        raise RuntimeError(
            "Unexpected V8 Phase 2 future-holdout boundary"
        )
    if manifest.get("primary_model") != "ridge_regression":
        raise RuntimeError(
            "Unexpected V8 Phase 2 primary model"
        )
    if int(manifest.get("secondary_model_count", -1)) != 0:
        raise RuntimeError(
            "V8 Phase 2 unexpectedly searched secondary models"
        )
    if manifest.get("safety", {}).get("portfolio_simulated") is not False:
        raise RuntimeError(
            "V8 Phase 2 must not have simulated a portfolio"
        )

    gate_detail = pd.read_csv(
        phase2_root / "predictive_gate_detail.csv"
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
        phase2_root / "metrics_summary.csv"
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
    disposition.to_csv(
        output_root / "predictive_disposition.csv",
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
            "V8 may proceed to portfolio simulation only if every preregistered "
            "predictive gate passes for both BTC-relative targets.  Both targets "
            "showed positive median correlation and median sign accuracy above "
            "50%, but both failed to improve median MAE versus the training-mean "
            "baseline.  Therefore the predictive hypothesis is rejected before "
            "any portfolio simulation."
        ),
        "outputs": {
            "predictive_disposition": str(
                output_root / "predictive_disposition.csv"
            ),
            "adjudication": str(
                output_root / "adjudication.json"
            ),
        },
        "safety": {
            "predictive_gates_changed_after_results": False,
            "threshold_search_performed": False,
            "model_family_changed_after_results": False,
            "secondary_model_fit": False,
            "portfolio_simulated": False,
            "shared_crypto_v7_modified": False,
            "shared_crypto_v6_modified": False,
            "shared_crypto_v5_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "v8_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V8 as rejected predictive evidence.  Any successor must "
            "be separately named and preregistered before model fitting.  Do "
            "not simulate the V8 portfolio, relax its predictive gates, change "
            "Ridge alpha, search model families, or score the future holdout."
        ),
    }

    (
        output_root / "adjudication.json"
    ).write_text(
        json.dumps(payload, indent=2) + "\n",
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
