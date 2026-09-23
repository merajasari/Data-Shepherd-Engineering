"""Shared Crypto V6 Durable Edge Phase 4: immutable adjudication.

Reads the single preregistered Phase 3 policy result and records whether it may
advance.  This phase performs no model fitting, threshold tuning, portfolio
resimulation, future-holdout scoring, model freezing, or paper activation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v6_durable_edge"
PHASE3_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase3")
OUTPUT_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase4")
HOLDOUT = "2026-09-01T00:00:00+00:00"
GATE_PREFIX = "gate_"


def adjudicate(gates: pd.DataFrame, summary: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if len(gates) != 1:
        raise RuntimeError("V6 Phase 3 must contain exactly one preregistered policy result")
    required_gate_columns = {"passed_gate_count", "total_gate_count", "status"}
    missing = required_gate_columns - set(gates.columns)
    if missing:
        raise RuntimeError(f"Phase 3 gate results missing columns: {sorted(missing)}")
    gate_columns = sorted(
        column for column in gates.columns if column.startswith(GATE_PREFIX)
    )
    if not gate_columns:
        raise RuntimeError("Phase 3 produced no preregistered gate columns")
    row = gates.iloc[0]
    passed_count = sum(bool(row[column]) for column in gate_columns)
    if int(row["total_gate_count"]) != len(gate_columns):
        raise RuntimeError("Phase 3 total gate count does not match gate columns")
    if int(row["passed_gate_count"]) != passed_count:
        raise RuntimeError("Phase 3 passed gate count does not match gate values")

    required_summary_columns = {
        "cost_bps", "fold_count", "median_fold_net_return",
        "mean_fold_net_return", "positive_fold_fraction",
        "median_excess_vs_btc", "median_excess_vs_shared_v3",
        "positive_excess_vs_shared_v3_fraction", "worst_maximum_drawdown",
        "single_fold_profit_concentration", "mean_total_turnover",
        "mean_cash_weight",
    }
    missing = required_summary_columns - set(summary.columns)
    if missing:
        raise RuntimeError(f"Phase 3 policy summary missing columns: {sorted(missing)}")
    primary = summary[summary["cost_bps"] == 25.0]
    stress = summary[summary["cost_bps"] == 50.0]
    if len(primary) != 1 or len(stress) != 1:
        raise RuntimeError("Phase 3 primary or stress policy summary is missing")
    primary_row = primary.iloc[0]
    stress_row = stress.iloc[0]

    failed = [column for column in gate_columns if not bool(row[column])]
    qualified = passed_count == len(gate_columns)
    expected_phase3_status = (
        "QUALIFIES_FOR_HUMAN_REVIEW" if qualified else "DO_NOT_ADVANCE"
    )
    if str(row["status"]) != expected_phase3_status:
        raise RuntimeError("Phase 3 status is inconsistent with its gate values")
    disposition = gates.copy()
    disposition["failed_gates"] = ",".join(failed)
    decision = {
        "status": (
            "QUALIFIED_FOR_HUMAN_REVIEW"
            if qualified else "REJECT_CURRENT_V6_POLICY_FAMILY"
        ),
        "qualifying_candidate_count": int(qualified),
        "single_preregistered_policy": {
            "primary_cost_bps": 25.0,
            "stress_cost_bps": 50.0,
            "fold_count": int(primary_row["fold_count"]),
            "passed_gate_count": int(passed_count),
            "total_gate_count": int(len(gate_columns)),
            "median_fold_net_return": float(primary_row["median_fold_net_return"]),
            "mean_fold_net_return": float(primary_row["mean_fold_net_return"]),
            "positive_fold_fraction": float(primary_row["positive_fold_fraction"]),
            "median_excess_vs_always_btc": float(primary_row["median_excess_vs_btc"]),
            "median_excess_vs_shared_v3": float(
                primary_row["median_excess_vs_shared_v3"]
            ),
            "positive_excess_vs_shared_v3_fraction": float(
                primary_row["positive_excess_vs_shared_v3_fraction"]
            ),
            "worst_maximum_drawdown": float(primary_row["worst_maximum_drawdown"]),
            "single_fold_profit_concentration": float(
                primary_row["single_fold_profit_concentration"]
            ),
            "mean_total_turnover": float(primary_row["mean_total_turnover"]),
            "mean_cash_weight": float(primary_row["mean_cash_weight"]),
            "stress_median_fold_net_return": float(
                stress_row["median_fold_net_return"]
            ),
            "failed_gates": failed,
        },
    }
    return disposition, decision


def run(phase3_root: Path = PHASE3_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    phase3_root = Path(phase3_root)
    output_root = Path(output_root)
    manifest = json.loads(
        (phase3_root / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError("Unexpected Phase 3 research version")
    if manifest.get("future_holdout_start_utc") != HOLDOUT:
        raise RuntimeError("Unexpected Phase 3 future-holdout boundary")
    if int(manifest.get("candidate_count", 0)) != 1:
        raise RuntimeError("V6 Phase 3 did not evaluate exactly one policy")
    gates = pd.read_csv(phase3_root / "gate_results.csv")
    summary = pd.read_csv(phase3_root / "policy_summary.csv")
    disposition, decision = adjudicate(gates, summary)

    output_root.mkdir(parents=True, exist_ok=True)
    disposition.to_csv(output_root / "policy_disposition.csv", index=False)
    payload = {
        "research_version": RESEARCH_VERSION,
        "phase": 4,
        "stage": "immutable_development_adjudication",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT,
        **decision,
        "reason": (
            "The single preregistered V6 policy may advance only if every gate "
            "passes. Drawdown control and median relative outperformance are not "
            "sufficient when median absolute return, fold consistency, relative "
            "consistency, profit concentration, and stress-return gates fail."
        ),
        "outputs": {
            "policy_disposition": str(output_root / "policy_disposition.csv"),
            "adjudication": str(output_root / "adjudication.json"),
        },
        "safety": {
            "gates_changed_after_results": False,
            "threshold_search_performed": False,
            "shared_crypto_v3_modified": False,
            "rejected_v5_modified": False,
            "future_holdout_scored": False,
            "v6_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V6 as rejected development evidence. Any successor must "
            "be a separately named and preregistered hypothesis; do not tune V6 "
            "thresholds on these observed results."
        ),
    }
    (output_root / "adjudication.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase3_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
