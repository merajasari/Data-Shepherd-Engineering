"""Lock the completed V12 development decision without freezing a candidate.

This module accepts exactly one evaluation identity: the preregistered V12
small-account result that retained frozen V10.  It cannot reinterpret failed
gates, modify V12, activate fresh paper evidence, or place brokerage orders.
Any successor hypothesis requires a separately preregistered research version.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Mapping

from ml.v12.challenger_contract import contract_sha256, load_contract
from ml.v12.development_evaluator import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SPEC_SHA256,
    OUTPUT_PATH as EVALUATION_PATH,
    _canonical_sha,
)


ROOT = Path(__file__).resolve().parents[2]
DISPOSITION_ROOT = ROOT / "data/research/v12/development/disposition"
DISPOSITION_PATH = DISPOSITION_ROOT / "status.json"
DISPOSITION_LOCK_PATH = DISPOSITION_ROOT / "status.sha256"

EXPECTED_EVALUATION_SHA256 = (
    "89fa9135324a041cb105d9acf21752775e838c9f6452d5bb1a192a86d5a6d6b7"
)
EXPECTED_CANDIDATES = (
    "V10_CONTROL_5K",
    "V12_INTRADAY_CONFIRM_5K",
    "V12_VOL_CONTROL_5K",
    "V12_COMBINED_5K",
)
EXPECTED_PERIOD_COUNT = 76
EXPECTED_FOLD_COUNT = 5
EXPECTED_GATES_PER_CHALLENGER = 10


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _evaluation_body(evaluation: Mapping[str, object]) -> dict[str, object]:
    body = dict(evaluation)
    body.pop("evaluation_sha256", None)
    body.pop("generated_at_utc", None)
    return body


def validate_evaluation(
    evaluation: Mapping[str, object],
    *,
    expected_evaluation_sha256: str = EXPECTED_EVALUATION_SHA256,
) -> dict[str, list[str]]:
    failures: list[str] = []
    claimed_sha = evaluation.get("evaluation_sha256")
    recomputed_sha = _canonical_sha(_evaluation_body(evaluation))
    if not (
        claimed_sha == recomputed_sha == expected_evaluation_sha256
    ):
        failures.append("EVALUATION_SHA_MISMATCH")
    if evaluation.get("contract_sha256") != EXPECTED_CONTRACT_SHA256:
        failures.append("CONTRACT_SHA_MISMATCH")
    if evaluation.get("status") != "V12_PREREGISTERED_DEVELOPMENT_EVIDENCE":
        failures.append("EVALUATION_STATUS_CHANGED")
    if evaluation.get("v10_control_candidate") != EXPECTED_V10_CANDIDATE:
        failures.append("V10_CONTROL_IDENTITY_CHANGED")
    if evaluation.get("v10_frozen_spec_sha256") != EXPECTED_V10_SPEC_SHA256:
        failures.append("V10_FROZEN_SPEC_IDENTITY_CHANGED")
    if tuple(evaluation.get("candidate_ids", ())) != EXPECTED_CANDIDATES:
        failures.append("CANDIDATE_SET_CHANGED")
    if evaluation.get("period_count") != EXPECTED_PERIOD_COUNT:
        failures.append("EXECUTABLE_PERIOD_COUNT_CHANGED")
    folds = evaluation.get("walk_forward_folds")
    if not isinstance(folds, list) or len(folds) != EXPECTED_FOLD_COUNT:
        failures.append("WALK_FORWARD_FOLD_COUNT_CHANGED")
    if evaluation.get("decision") != "RETAIN_FROZEN_V10_CONTROL":
        failures.append("DISPOSITION_DECISION_CHANGED")
    if evaluation.get("selected_candidate") != "V10_CONTROL_5K":
        failures.append("SELECTED_CANDIDATE_CHANGED")

    summaries = evaluation.get("candidate_summaries")
    if not isinstance(summaries, list):
        failures.append("CANDIDATE_SUMMARIES_INVALID")
        summaries = []
    summary_ids = tuple(
        str(row.get("candidate_id"))
        for row in summaries
        if isinstance(row, Mapping)
    )
    if summary_ids != EXPECTED_CANDIDATES:
        failures.append("CANDIDATE_SUMMARY_SET_CHANGED")
    for row in summaries:
        if not isinstance(row, Mapping):
            failures.append("CANDIDATE_SUMMARY_INVALID")
            continue
        for field in (
            "mean_terminal_wealth",
            "mean_net_annualized_return",
            "maximum_drawdown",
        ):
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                failures.append(f"SUMMARY_{field.upper()}_INVALID")
                continue
            if not math.isfinite(value):
                failures.append(f"SUMMARY_{field.upper()}_NONFINITE")

    gate_rows = evaluation.get("gate_results")
    if not isinstance(gate_rows, list):
        failures.append("GATE_RESULTS_INVALID")
        gate_rows = []
    failed_by_candidate: dict[str, list[str]] = {
        candidate_id: [] for candidate_id in EXPECTED_CANDIDATES[1:]
    }
    counts = {candidate_id: 0 for candidate_id in EXPECTED_CANDIDATES[1:]}
    all_pass = {candidate_id: True for candidate_id in EXPECTED_CANDIDATES[1:]}
    for row in gate_rows:
        if not isinstance(row, Mapping):
            failures.append("GATE_ROW_INVALID")
            continue
        candidate_id = str(row.get("candidate_id"))
        if candidate_id not in counts:
            failures.append("GATE_ROW_CANDIDATE_INVALID")
            continue
        counts[candidate_id] += 1
        passed = row.get("passed") is True
        all_pass[candidate_id] = all_pass[candidate_id] and passed
        if not passed:
            failed_by_candidate[candidate_id].append(str(row.get("gate")))
    for candidate_id in EXPECTED_CANDIDATES[1:]:
        if counts[candidate_id] != EXPECTED_GATES_PER_CHALLENGER:
            failures.append(f"GATE_COUNT_CHANGED:{candidate_id}")
        if all_pass[candidate_id]:
            failures.append(f"UNAUTHORIZED_PASSING_CHALLENGER:{candidate_id}")
        if not failed_by_candidate[candidate_id]:
            failures.append(f"FAILED_GATES_MISSING:{candidate_id}")

    gate_details = evaluation.get("gate_details")
    if not isinstance(gate_details, Mapping):
        failures.append("GATE_DETAILS_INVALID")
    else:
        control = gate_details.get("V10_CONTROL_5K")
        if not isinstance(control, Mapping) or (
            control.get("classification") != "CONTROL_NOT_A_CHALLENGER"
        ):
            failures.append("CONTROL_CLASSIFICATION_CHANGED")
        for candidate_id in EXPECTED_CANDIDATES[1:]:
            details = gate_details.get(candidate_id)
            if not isinstance(details, Mapping):
                failures.append(f"GATE_DETAILS_MISSING:{candidate_id}")
            elif details.get("all_gates_passed") is not False:
                failures.append(f"CHALLENGER_PASS_STATE_CHANGED:{candidate_id}")

    required_false = (
        "candidate_frozen",
        "fresh_paper_confirmation_activated",
        "v10_holdout_outcomes_read",
        "v11_fresh_outcomes_read",
        "v11_production_journal_read",
        "production_data_read",
        "live_trading_enabled",
        "brokerage_orders",
        "v8_modified",
        "v10_modified",
        "v11_modified",
    )
    for field in required_false:
        if evaluation.get(field) is not False:
            failures.append(f"SAFETY_{field.upper()}_MUST_BE_FALSE")
    if evaluation.get("paper_trading_only") is not True:
        failures.append("PAPER_ONLY_BOUNDARY_MISSING")

    source = evaluation.get("source_inputs")
    if not isinstance(source, Mapping):
        failures.append("SOURCE_INPUTS_INVALID")
    else:
        if source.get("v10_candidate_id") != EXPECTED_V10_CANDIDATE:
            failures.append("SOURCE_V10_CANDIDATE_CHANGED")
        if source.get("v10_frozen_spec_sha256") != EXPECTED_V10_SPEC_SHA256:
            failures.append("SOURCE_V10_SPEC_CHANGED")
        if source.get("production_inputs_read") is not False:
            failures.append("SOURCE_PRODUCTION_INPUT_READ")
        if source.get("holdout_outcomes_read") is not False:
            failures.append("SOURCE_HOLDOUT_OUTCOME_READ")

    if failures:
        raise RuntimeError("V12_DISPOSITION_BLOCKED:" + ",".join(dict.fromkeys(failures)))
    return failed_by_candidate


def build_disposition(
    evaluation: Mapping[str, object],
    failed_by_candidate: Mapping[str, list[str]],
    *,
    evaluation_sha256: str = EXPECTED_EVALUATION_SHA256,
    recorded_at_utc: str | None = None,
) -> dict[str, object]:
    summaries = {
        str(row["candidate_id"]): {
            "mean_terminal_wealth": row["mean_terminal_wealth"],
            "mean_net_annualized_return": row["mean_net_annualized_return"],
            "maximum_drawdown": row["maximum_drawdown"],
        }
        for row in evaluation["candidate_summaries"]
    }
    core: dict[str, object] = {
        "research_version": "stock_v12",
        "status": "V12_DEVELOPMENT_CLOSED_RETAIN_V10",
        "decision": "RETAIN_FROZEN_V10_CONTROL",
        "selected_candidate": "V10_CONTROL_5K",
        "decision_reason": (
            "No preregistered V12 challenger passed every development gate. "
            "Frozen V10 remains the control and no V12 candidate is promoted."
        ),
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "evaluation_sha256": evaluation_sha256,
        "v10_candidate_id": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SPEC_SHA256,
        "period_count": EXPECTED_PERIOD_COUNT,
        "walk_forward_folds": EXPECTED_FOLD_COUNT,
        "candidate_summaries": summaries,
        "failed_gates_by_challenger": dict(failed_by_candidate),
        "successor_policy": (
            "Any successor must use a separately preregistered contract and "
            "evidence not used to tune or reinterpret V12."
        ),
        "post_result_v12_tuning_allowed": False,
        "candidate_frozen": False,
        "fresh_paper_confirmation_activated": False,
        "holdout_outcomes_read": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "production_modified": False,
    }
    disposition_sha = _canonical_sha(core)
    return {
        **core,
        "disposition_sha256": disposition_sha,
        "recorded_at_utc": recorded_at_utc
        or datetime.now(timezone.utc).isoformat(),
    }


def _validate_existing_disposition(
    payload: Mapping[str, object],
    lock_sha: str,
    *,
    expected_evaluation_sha256: str = EXPECTED_EVALUATION_SHA256,
) -> None:
    core = dict(payload)
    claimed = core.pop("disposition_sha256", None)
    core.pop("recorded_at_utc", None)
    recomputed = _canonical_sha(core)
    if not (
        isinstance(claimed, str)
        and claimed == recomputed == lock_sha
        and payload.get("evaluation_sha256") == expected_evaluation_sha256
        and payload.get("decision") == "RETAIN_FROZEN_V10_CONTROL"
        and payload.get("candidate_frozen") is False
        and payload.get("fresh_paper_confirmation_activated") is False
        and payload.get("brokerage_orders") is False
    ):
        raise RuntimeError("EXISTING_V12_DISPOSITION_INVALID")


def record_disposition(
    evaluation: Mapping[str, object],
    *,
    disposition_path: Path = DISPOSITION_PATH,
    lock_path: Path = DISPOSITION_LOCK_PATH,
    expected_evaluation_sha256: str = EXPECTED_EVALUATION_SHA256,
    recorded_at_utc: str | None = None,
) -> tuple[dict[str, object], bool]:
    failed = validate_evaluation(
        evaluation,
        expected_evaluation_sha256=expected_evaluation_sha256,
    )
    existing = disposition_path.exists()
    locked = lock_path.exists()
    if existing != locked:
        raise RuntimeError("INCOMPLETE_V12_DISPOSITION_LOCK")
    if existing:
        payload = json.loads(disposition_path.read_text(encoding="utf-8"))
        lock_sha = lock_path.read_text(encoding="utf-8").strip()
        _validate_existing_disposition(
            payload,
            lock_sha,
            expected_evaluation_sha256=expected_evaluation_sha256,
        )
        if payload.get("evaluation_sha256") != expected_evaluation_sha256:
            raise RuntimeError("EXISTING_DISPOSITION_EVALUATION_CHANGED")
        return payload, False

    payload = build_disposition(
        evaluation,
        failed,
        evaluation_sha256=expected_evaluation_sha256,
        recorded_at_utc=recorded_at_utc,
    )
    _atomic_json(disposition_path, payload)
    _atomic_text(lock_path, str(payload["disposition_sha256"]) + "\n")
    return payload, True


def run(
    *,
    evaluation_path: Path = EVALUATION_PATH,
    disposition_path: Path = DISPOSITION_PATH,
    lock_path: Path = DISPOSITION_LOCK_PATH,
) -> tuple[dict[str, object], bool]:
    contract = load_contract()
    if contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V12_CONTRACT_IDENTITY_CHANGED")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    return record_disposition(
        evaluation,
        disposition_path=disposition_path,
        lock_path=lock_path,
    )


def main() -> None:
    print("DATA SHEPHERD V12 FINAL DEVELOPMENT DISPOSITION")
    print("=" * 84)
    try:
        payload, created = run()
    except Exception as exc:
        print("Status: BLOCKED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Disposition written: NO")
        print("Candidate frozen: NO")
        print("Fresh paper confirmation: DISABLED")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {payload['status']}")
    print(f"Decision: {payload['decision']}")
    print(f"Selected candidate: {payload['selected_candidate']}")
    print(f"Evaluation SHA-256: {payload['evaluation_sha256']}")
    print(f"Disposition SHA-256: {payload['disposition_sha256']}")
    print(f"New disposition written: {'YES' if created else 'NO (IDEMPOTENT)'}")
    for candidate_id, gates in payload["failed_gates_by_challenger"].items():
        print(f"{candidate_id}: failed gates={len(gates)}")
    print("Post-result V12 tuning: PROHIBITED")
    print("Candidate frozen: NO")
    print("Fresh paper confirmation: DISABLED")
    print("V10 holdout / V11 fresh outcomes read: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production modified: NO")


if __name__ == "__main__":
    main()
