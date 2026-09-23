"""StockEagle250 Phase 4: immutable development adjudication.

Reads the preregistered Phase 3 summaries and gate results, verifies their
internal consistency, and records whether either fixed candidate may advance to
human review. It performs no model fitting, portfolio resimulation, threshold
changes, holdout scoring, model freezing, paper activation, or order placement.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from ml.stock_eagle_250 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250.phase3 import CANDIDATE_IDS


PHASE = 4
PHASE3_ROOT = Path("data/model/stock_eagle_250/phase3")
OUTPUT_ROOT = Path("data/model/stock_eagle_250/phase4")
HOLDOUT_START_UTC = "2026-09-23T00:00:00+00:00"
MAXIMUM_DEVELOPMENT_ENDPOINT_UTC = "2026-09-22T00:00:00+00:00"
GATE_PREFIX = "gate_"


def validate_phase3_manifest(manifest: dict) -> None:
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "candidate_count": 2,
        "fold_count": 14,
        "future_holdout_start_utc": HOLDOUT_START_UTC,
        "future_holdout_rows_read": 0,
        "maximum_target_endpoint_utc": MAXIMUM_DEVELOPMENT_ENDPOINT_UTC,
    }
    mismatches = {
        key: {"expected": value, "actual": manifest.get(key)}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"StockEagle250 Phase 3 manifest mismatch: {mismatches}")
    if tuple(manifest.get("candidate_ids", ())) != CANDIDATE_IDS:
        raise RuntimeError("Phase 3 candidate IDs differ from the frozen pair")

    safety = manifest.get("safety", {})
    prohibited_true = (
        "hyperparameter_search_performed",
        "future_holdout_scored",
        "candidate_frozen",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "existing_model_artifacts_modified",
        "existing_forward_journals_modified",
    )
    violations = [key for key in prohibited_true if safety.get(key) is not False]
    if violations:
        raise RuntimeError(
            "Phase 3 safety state is not admissible: " + ", ".join(violations)
        )


def adjudicate(
    model_summary: pd.DataFrame,
    gate_results: pd.DataFrame,
    qualification: dict,
) -> tuple[pd.DataFrame, dict]:
    if set(model_summary["candidate_id"]) != set(CANDIDATE_IDS):
        raise RuntimeError("Model summary does not contain the fixed candidates")
    if set(gate_results["candidate_id"]) != set(CANDIDATE_IDS):
        raise RuntimeError("Gate results do not contain the fixed candidates")
    if model_summary["candidate_id"].duplicated().any():
        raise RuntimeError("Model summary contains duplicate candidates")
    if gate_results["candidate_id"].duplicated().any():
        raise RuntimeError("Gate results contain duplicate candidates")

    gate_columns = sorted(
        column for column in gate_results.columns
        if column.startswith(GATE_PREFIX)
    )
    if not gate_columns:
        raise RuntimeError("Phase 3 produced no preregistered gates")

    rows = []
    for gate_row in gate_results.itertuples(index=False):
        candidate_id = gate_row.candidate_id
        values = {
            column: bool(getattr(gate_row, column))
            for column in gate_columns
        }
        passed = sum(values.values())
        total = len(values)
        if int(gate_row.passed_gate_count) != passed:
            raise RuntimeError(
                f"{candidate_id} passed-gate count is inconsistent"
            )
        if int(gate_row.total_gate_count) != total:
            raise RuntimeError(
                f"{candidate_id} total-gate count is inconsistent"
            )
        qualified = passed == total
        if bool(gate_row.qualified_for_human_review) != qualified:
            raise RuntimeError(
                f"{candidate_id} qualification flag is inconsistent"
            )
        failed = [column for column, value in values.items() if not value]
        rows.append({
            "candidate_id": candidate_id,
            **values,
            "passed_gate_count": int(passed),
            "total_gate_count": int(total),
            "failed_gates": ",".join(failed),
            "qualified_for_human_review": qualified,
            "disposition": (
                "QUALIFIED_FOR_HUMAN_REVIEW"
                if qualified
                else "REJECT_CURRENT_CANDIDATE"
            ),
        })

    disposition = pd.DataFrame(rows).merge(
        model_summary,
        on="candidate_id",
        validate="one_to_one",
    )
    qualified_candidates = disposition.loc[
        disposition["qualified_for_human_review"],
        "candidate_id",
    ].tolist()

    expected_status = (
        "QUALIFIES_FOR_HUMAN_REVIEW"
        if qualified_candidates
        else "NO_CANDIDATE_QUALIFIED"
    )
    if qualification.get("status") != expected_status:
        raise RuntimeError("Phase 3 qualification status is inconsistent")
    if int(qualification.get("qualified_candidate_count", -1)) != len(
        qualified_candidates
    ):
        raise RuntimeError("Phase 3 qualified-candidate count is inconsistent")
    if sorted(qualification.get("qualified_candidates", [])) != sorted(
        qualified_candidates
    ):
        raise RuntimeError("Phase 3 qualified-candidate list is inconsistent")
    if qualification.get("candidate_frozen") is not False:
        raise RuntimeError("Phase 3 improperly reports a frozen candidate")
    if qualification.get("paper_trading_enabled") is not False:
        raise RuntimeError("Phase 3 improperly enables paper trading")

    failed_by_candidate = {
        row["candidate_id"]: row["failed_gates"].split(",")
        if row["failed_gates"] else []
        for row in rows
    }
    if qualified_candidates:
        status = "QUALIFIED_FOR_HUMAN_REVIEW"
        reason = (
            "At least one fixed candidate passed every preregistered development "
            "gate. Human review is still required; this adjudication does not "
            "freeze or activate a model."
        )
    else:
        status = "REJECT_CURRENT_STOCK_EAGLE_250_V1_CANDIDATES"
        reason = (
            "Neither fixed candidate passed every preregistered development "
            "gate. The gate thresholds remain unchanged after results, so no "
            "candidate may be frozen or advanced to paper evaluation."
        )

    decision = {
        "status": status,
        "qualified_candidate_count": len(qualified_candidates),
        "qualified_candidates": qualified_candidates,
        "failed_gates_by_candidate": failed_by_candidate,
        "reason": reason,
    }
    return disposition, decision


def run(
    phase3_root: Path = PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase3_root = Path(phase3_root)
    output_root = Path(output_root)

    manifest = json.loads(
        (phase3_root / "manifest.json").read_text(encoding="utf-8")
    )
    validate_phase3_manifest(manifest)
    model_summary = pd.read_csv(phase3_root / "model_summary.csv")
    gate_results = pd.read_csv(phase3_root / "gate_results.csv")
    qualification = json.loads(
        (phase3_root / "qualification.json").read_text(encoding="utf-8")
    )

    disposition, decision = adjudicate(
        model_summary,
        gate_results,
        qualification,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    disposition.to_csv(
        output_root / "candidate_disposition.csv",
        index=False,
    )

    payload = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "immutable_development_adjudication",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT_START_UTC,
        "future_holdout_rows_read": 0,
        **decision,
        "outputs": {
            "candidate_disposition":
                str(output_root / "candidate_disposition.csv"),
            "adjudication": str(output_root / "adjudication.json"),
        },
        "safety": {
            "phase3_results_recomputed": False,
            "gate_thresholds_changed_after_results": False,
            "hyperparameter_search_performed": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "existing_model_artifacts_modified": False,
            "existing_forward_journals_modified": False,
        },
        "next_step": (
            "Preserve StockEagle250 V1 as development evidence. Because neither "
            "candidate qualified, any risk-controlled successor must be a "
            "separately named, preregistered research generation with a new "
            "untouched future boundary; do not weaken the observed V1 gates."
            if not decision["qualified_candidates"]
            else
            "Conduct human review only. Do not freeze or activate a candidate "
            "without a separately authorized forward-evaluation contract."
        ),
    }
    (output_root / "adjudication.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
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
