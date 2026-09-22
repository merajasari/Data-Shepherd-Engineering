"""Shared Crypto V4 Net-Edge Phase 4: immutable development adjudication.

Reads the preregistered Phase 3 gates and records whether any candidate may
advance to human review.  This phase performs no model fitting, threshold
tuning, portfolio resimulation, future-holdout scoring, or paper activation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v4_net_edge"
PHASE3_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase3")
OUTPUT_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase4")
GATE_PREFIX = "gate_"


def adjudicate(gates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {
        "regime_model_id", "ranking_model_id", "top_n", "cost_bps",
        "passed_gate_count", "total_gate_count", "status",
        "median_fold_net_return", "positive_fold_fraction",
        "median_excess_vs_shared_v3", "mean_excess_vs_btc",
        "worst_maximum_drawdown", "single_fold_profit_concentration",
    }
    missing = required - set(gates.columns)
    if missing:
        raise RuntimeError(f"Phase 3 gate results missing columns: {sorted(missing)}")
    gate_columns = sorted(column for column in gates.columns if column.startswith(GATE_PREFIX))
    if not gate_columns:
        raise RuntimeError("Phase 3 produced no preregistered gate columns")

    result = gates.copy()
    result["failed_gates"] = result.apply(
        lambda row: ",".join(column for column in gate_columns if not bool(row[column])),
        axis=1,
    )
    result = result.sort_values(
        ["passed_gate_count", "median_excess_vs_shared_v3"],
        ascending=[False, False],
    ).reset_index(drop=True)
    best = result.iloc[0]
    qualified = result[result["passed_gate_count"] == result["total_gate_count"]]
    status = (
        "QUALIFIED_FOR_HUMAN_REVIEW"
        if not qualified.empty
        else "REJECT_CURRENT_V4_POLICY_FAMILY"
    )
    decision = {
        "status": status,
        "qualifying_candidate_count": int(len(qualified)),
        "best_observed_candidate": {
            "regime_model_id": str(best["regime_model_id"]),
            "ranking_model_id": str(best["ranking_model_id"]),
            "top_n": int(best["top_n"]),
            "cost_bps": float(best["cost_bps"]),
            "passed_gate_count": int(best["passed_gate_count"]),
            "total_gate_count": int(best["total_gate_count"]),
            "median_fold_net_return": float(best["median_fold_net_return"]),
            "positive_fold_fraction": float(best["positive_fold_fraction"]),
            "median_excess_vs_shared_v3": float(best["median_excess_vs_shared_v3"]),
            "mean_excess_vs_btc": float(best["mean_excess_vs_btc"]),
            "worst_maximum_drawdown": float(best["worst_maximum_drawdown"]),
            "single_fold_profit_concentration": float(best["single_fold_profit_concentration"]),
            "failed_gates": [name for name in gate_columns if not bool(best[name])],
        },
    }
    return result, decision


def run(phase3_root: Path = PHASE3_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    phase3_root = Path(phase3_root)
    output_root = Path(output_root)
    manifest = json.loads((phase3_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("future_holdout_start_utc") != "2026-09-01T00:00:00+00:00":
        raise RuntimeError("Unexpected Phase 3 future-holdout boundary")
    gates = pd.read_csv(phase3_root / "gate_results.csv")
    disposition, decision = adjudicate(gates)

    output_root.mkdir(parents=True, exist_ok=True)
    disposition.to_csv(output_root / "candidate_disposition.csv", index=False)
    payload = {
        "research_version": RESEARCH_VERSION,
        "phase": 4,
        "stage": "immutable_development_adjudication",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **decision,
        "reason": (
            "No candidate may be frozen or paper-activated unless every "
            "preregistered development gate passes."
        ),
        "outputs": {
            "candidate_disposition": str(output_root / "candidate_disposition.csv"),
            "adjudication": str(output_root / "adjudication.json"),
        },
        "safety": {
            "gates_changed_after_results": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "v4_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V4 as rejected development evidence and preregister a "
            "new hypothesis rather than tuning V4 on these observed results."
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
