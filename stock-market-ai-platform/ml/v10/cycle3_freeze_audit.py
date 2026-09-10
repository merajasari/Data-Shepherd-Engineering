"""Independent freeze audit for the selected V10 Cycle 3 candidate.

The audit consumes only locked preregistration and development outputs. It
recomputes the registered selection rule, verifies all realized periods end
before the original protected boundary, and registers an immutable candidate
specification for the fresh 2027-01-04 holdout.

It never reads holdout outcomes, modifies V8/production, or places orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import pandas as pd

CYCLE_ROOT = Path("data/model/v10/cycle3")
SOURCE_CONTRACT = Path(__file__).with_name("cycle3_contract.json")
LOCKED_CONTRACT = CYCLE_ROOT / "preregistered_contract.json"
CONTRACT_LOCK = CYCLE_ROOT / "preregistered_contract.sha256"
EVALUATION_MANIFEST = CYCLE_ROOT / "evaluation_manifest.json"
GATE_PATH = CYCLE_ROOT / "gate_results.csv"
SUMMARY_PATH = CYCLE_ROOT / "candidate_summary.csv"
PERIOD_PATH = CYCLE_ROOT / "economic_period_results.csv"

FREEZE_ROOT = CYCLE_ROOT / "freeze"
SPEC_PATH = FREEZE_ROOT / "frozen_candidate_spec.json"
LOCK_PATH = FREEZE_ROOT / "frozen_candidate.sha256"
AUDIT_PATH = FREEZE_ROOT / "freeze_audit.json"

EXPECTED_CONTRACT_SHA256 = "e1df9ac21457a4494f53069b4513ecd4dfe0ae52a743eabdab6a63374998f051"
EXPECTED_SELECTED = "c3_confirm2_blend50"
EXPECTED_BASELINE = "v8_distance_only"
ORIGINAL_PROTECTED_BOUNDARY = pd.Timestamp("2026-11-02T00:00:00Z")
FRESH_HOLDOUT_BOUNDARY = pd.Timestamp("2027-01-04T00:00:00Z")


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _canonical_sha(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_and_validate():
    required = [
        SOURCE_CONTRACT, LOCKED_CONTRACT, CONTRACT_LOCK, EVALUATION_MANIFEST,
        GATE_PATH, SUMMARY_PATH, PERIOD_PATH,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Cycle 3 audit inputs: " + ", ".join(missing))
    if any(path.exists() for path in [SPEC_PATH, LOCK_PATH, AUDIT_PATH]):
        raise RuntimeError("Cycle 3 freeze outputs already exist; audit is single-pass")

    source_sha = hashlib.sha256(SOURCE_CONTRACT.read_bytes()).hexdigest()
    lock_sha = CONTRACT_LOCK.read_text(encoding="utf-8").strip()
    contract = json.loads(LOCKED_CONTRACT.read_text(encoding="utf-8"))
    evaluation = json.loads(EVALUATION_MANIFEST.read_text(encoding="utf-8"))
    gates = pd.read_csv(GATE_PATH)
    summary = pd.read_csv(SUMMARY_PATH)
    periods = pd.read_csv(PERIOD_PATH)

    failures = []
    if not (
        source_sha == lock_sha == contract.get("contract_sha256")
        == evaluation.get("contract_sha256") == EXPECTED_CONTRACT_SHA256
    ):
        failures.append("preregistration/evaluation contract SHA mismatch")

    expected_candidate_ids = [
        item.get("candidate_id") for item in contract.get("candidates", [])
    ]
    if sorted(gates["candidate_id"].unique().tolist()) != sorted(expected_candidate_ids):
        failures.append("gate results candidate set differs from preregistration")

    gate_counts = gates.groupby("candidate_id").size().to_dict()
    if any(gate_counts.get(candidate_id) != 13 for candidate_id in expected_candidate_ids):
        failures.append(f"every candidate must have exactly 13 gates: {gate_counts}")

    gate_pass = gates.groupby("candidate_id")["passed"].apply(
        lambda values: bool(pd.Series(values).astype(bool).all())
    )
    passers = summary[
        summary["candidate_id"].map(gate_pass).fillna(False)
    ].sort_values(
        ["mean_transition_notional", "candidate_id"],
        ascending=[True, True],
    )
    recomputed_selected = None if passers.empty else str(passers.iloc[0]["candidate_id"])

    if recomputed_selected != EXPECTED_SELECTED:
        failures.append(
            f"registered selection rule produced {recomputed_selected}, expected {EXPECTED_SELECTED}"
        )
    if evaluation.get("selected_candidate") != recomputed_selected:
        failures.append("evaluation manifest selection differs from recomputed selection")
    if evaluation.get("decision") != "ELIGIBLE_FOR_SEPARATE_FREEZE_AUDIT":
        failures.append("evaluation did not authorize a separate freeze audit")

    selected_gates = gates[gates["candidate_id"] == EXPECTED_SELECTED]
    if len(selected_gates) != 13 or not selected_gates["passed"].astype(bool).all():
        failures.append("selected candidate did not pass all 13 gates")

    decision_ts = pd.to_datetime(periods["decision_timestamp_utc"], utc=True)
    exit_ts = pd.to_datetime(periods["exit_timestamp_utc"], utc=True)
    if decision_ts.max() >= ORIGINAL_PROTECTED_BOUNDARY:
        failures.append("a development decision reaches the original protected boundary")
    if exit_ts.max() >= ORIGINAL_PROTECTED_BOUNDARY:
        failures.append("a realized development exit reaches the original protected boundary")

    safety_false = [
        "candidate_frozen", "freeze_audit_completed", "holdout_activated",
        "original_holdout_outcomes_read", "fresh_holdout_outcomes_read",
        "holdout_scored", "v8_modified", "production_modified", "brokerage_orders",
    ]
    for key in safety_false:
        if evaluation.get(key) is not False:
            failures.append(f"pre-audit evaluation safety field must be false: {key}")

    if failures:
        raise RuntimeError("; ".join(failures))
    return contract, evaluation, gates, summary, periods, recomputed_selected


def main():
    print("V10 CYCLE 3 FREEZE AUDIT")
    print("=" * 96)
    try:
        contract, evaluation, gates, summary, periods, selected = _load_and_validate()
    except Exception as exc:
        print("Status: BLOCKED")
        print(f"  - {type(exc).__name__}: {exc}")
        print("Candidate frozen: NO | fresh holdout activated: NO")
        print("Holdout outcomes read/scored: NO")
        print("V8/production modified: NO | brokerage orders: OFF")
        raise SystemExit(2)

    selected_row = summary.set_index("candidate_id").loc[selected]
    selected_gate_names = gates[
        (gates["candidate_id"] == selected) & gates["passed"].astype(bool)
    ]["gate"].tolist()

    spec_core = {
        "research_version": "stock_v10_cycle3",
        "candidate_id": selected,
        "baseline": EXPECTED_BASELINE,
        "preregistration_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "selection_rule": contract["selection_rule"],
        "development_validation": {
            "gates_passed": 13,
            "gates_total": 13,
            "passed_gate_names": selected_gate_names,
            "mean_transition_notional": float(selected_row["mean_transition_notional"]),
            "mean_cost_drag": float(selected_row["mean_cost_drag"]),
            "negative_regime_wins": int(selected_row["negative_regime_wins"]),
            "positive_regime_noninferior": int(
                selected_row["positive_regime_noninferior"]
            ),
            "latest_decision_timestamp_utc": pd.to_datetime(
                periods["decision_timestamp_utc"], utc=True
            ).max().isoformat(),
            "latest_exit_timestamp_utc": pd.to_datetime(
                periods["exit_timestamp_utc"], utc=True
            ).max().isoformat(),
        },
        "signal_contract": {
            "v8_signal": "distance_from_low_20d",
            "defensive_signal": (
                "0.5 * percentile_rank(downside_vol_ratio_20) + "
                "0.5 * percentile_rank(volume_trend_5_20)"
            ),
            "negative_entry": "two consecutive completed negative_spy20 decisions",
            "negative_score": (
                "0.5 * percentile_rank(distance_from_low_20d) + "
                "0.5 * defensive_signal"
            ),
            "positive_score": "exact V8 raw distance_from_low_20d score",
            "positive_exit": "immediate on first completed non-negative decision",
        },
        "portfolio_contract": {
            "top_n": 10,
            "weighting": "equal_weight",
            "entry": "next_session_open",
            "holding_sessions": 5,
            "cohort_offsets": [0, 1, 2, 3, 4],
        },
        "cost_contract": {
            "primary_cost_bps_per_dollar_traded": 10,
        },
        "holdout_contract": {
            "fresh_holdout_start_utc": FRESH_HOLDOUT_BOUNDARY.isoformat(),
            "original_v10_boundary_utc": ORIGINAL_PROTECTED_BOUNDARY.isoformat(),
            "append_only": True,
            "candidate_retuning_allowed": False,
            "holdout_outcomes_for_selection_allowed": False,
        },
        "authority": {
            "modify_v8": False,
            "modify_production": False,
            "brokerage_orders": False,
        },
    }
    spec_sha = _canonical_sha(spec_core)
    spec = dict(spec_core)
    spec["spec_sha256"] = spec_sha
    spec["frozen_at_utc"] = datetime.now(timezone.utc).isoformat()

    audit = {
        "status": "FROZEN_FRESH_HOLDOUT_AUTHORIZED",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_candidate": selected,
        "spec_sha256": spec_sha,
        "preregistration_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "selection_recomputed": True,
        "all_13_gates_verified": True,
        "development_periods_before_original_boundary": True,
        "fresh_holdout_start_utc": FRESH_HOLDOUT_BOUNDARY.isoformat(),
        "fresh_holdout_activated": True,
        "original_holdout_outcomes_read": False,
        "fresh_holdout_outcomes_read": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }

    _atomic_write(
        SPEC_PATH,
        (json.dumps(spec, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(LOCK_PATH, (spec_sha + "\n").encode("utf-8"))
    _atomic_write(
        AUDIT_PATH,
        (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )

    print(f"Selected candidate: {selected}")
    print("Gates verified: 13/13")
    print(f"Mean transition notional: {float(selected_row['mean_transition_notional']):.6f}")
    print(f"Mean cost drag: {float(selected_row['mean_cost_drag']):.6f}")
    print(f"Frozen candidate SHA-256: {spec_sha}")
    print(f"Fresh holdout boundary: {FRESH_HOLDOUT_BOUNDARY.isoformat()}")
    print("Status: FROZEN_FRESH_HOLDOUT_AUTHORIZED")
    print("Original/fresh holdout outcomes read/scored: NO")
    print("V8/production modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
