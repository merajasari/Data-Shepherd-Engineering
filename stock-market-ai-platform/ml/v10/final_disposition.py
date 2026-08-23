"""Finalize V10 development disposition without freezing or scoring holdout data."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path("data/model/v10")
PHASE4_MANIFEST = ROOT / "phase4" / "manifest.json"
PHASE4_GATES = ROOT / "phase4" / "gate_results.csv"
CYCLE2_MANIFEST = ROOT / "cycle2" / "manifest.json"
CYCLE2_GATES = ROOT / "cycle2" / "gate_results.csv"
OUTPUT_ROOT = ROOT / "disposition"
STATUS_PATH = OUTPUT_ROOT / "status.json"
EXPECTED_FAILED_GATE = "positive_regime_relative_noninferiority"


def _read_json(path):
    return json.loads(path.read_text())


def _failed_gates(path):
    import pandas as pd

    frame = pd.read_csv(path)
    if set(frame.columns) != {"gate", "passed"}:
        raise ValueError(f"Unexpected gate schema: {path}")
    passed = frame["passed"]
    if passed.dtype != bool:
        passed = passed.astype(str).str.lower().map({"true": True, "false": False})
    return frame.loc[~passed.fillna(False), "gate"].astype(str).tolist()


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    required = [
        PHASE4_MANIFEST,
        PHASE4_GATES,
        CYCLE2_MANIFEST,
        CYCLE2_GATES,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing V10 development evidence: " + ", ".join(missing))

    original = _read_json(PHASE4_MANIFEST)
    cycle2 = _read_json(CYCLE2_MANIFEST)
    original_failed = _failed_gates(PHASE4_GATES)
    cycle2_failed = _failed_gates(CYCLE2_GATES)

    checks = {
        "original_decision_do_not_freeze": original.get("decision") == "DO_NOT_FREEZE",
        "original_gates_12_of_13": (
            original.get("gates_passed") == 12 and original.get("gates_total") == 13
        ),
        "original_failed_expected_gate": original_failed == [EXPECTED_FAILED_GATE],
        "cycle2_decision_do_not_freeze": cycle2.get("decision") == "DO_NOT_FREEZE",
        "cycle2_gates_12_of_13": (
            cycle2.get("gates_passed") == 12 and cycle2.get("gates_total") == 13
        ),
        "cycle2_failed_expected_gate": cycle2_failed == [EXPECTED_FAILED_GATE],
        "original_holdout_unscored": original.get("holdout_scored") is False,
        "cycle2_holdout_unscored": cycle2.get("holdout_scored") is False,
        "original_candidate_not_frozen": original.get("candidate_frozen") is False,
        "cycle2_candidate_not_frozen": cycle2.get("candidate_frozen") is False,
        "brokerage_orders_disabled": (
            original.get("brokerage_orders") is False
            and cycle2.get("brokerage_orders") is False
        ),
        "v8_unchanged": (
            original.get("v8_modified") is False
            and cycle2.get("v8_modified") is False
        ),
        "production_unchanged": (
            original.get("production_modified") is False
            and cycle2.get("production_modified") is False
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise RuntimeError(
            "Cannot finalize V10 disposition; failed checks: " + ", ".join(failures)
        )

    payload = {
        "research_version": "stock_v10",
        "status": "REJECTED_DO_NOT_FREEZE",
        "decision": "DO_NOT_FREEZE",
        "decision_reason": (
            "Original V10 and the predeclared one-session Cycle-2 exit buffer "
            "each failed positive-regime relative noninferiority."
        ),
        "failed_gate": EXPECTED_FAILED_GATE,
        "original_gates_passed": 12,
        "original_gates_total": 13,
        "cycle2_gates_passed": 12,
        "cycle2_gates_total": 13,
        "future_holdout_start_utc": "2026-11-02T00:00:00+00:00",
        "future_holdout_status": "NOT_ACTIVATED_CANDIDATE_NOT_FROZEN",
        "dashboard_classification": "RECONSTRUCTED_DEVELOPMENT_ONLY",
        "v8_status": "SOLE_FROZEN_FORWARD_MODEL",
        "candidate_frozen": False,
        "holdout_scored": False,
        "holdout_outcomes_read": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
        "checks": checks,
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    digest_payload = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["disposition_sha256"] = hashlib.sha256(digest_payload).hexdigest()
    _atomic_write(STATUS_PATH, payload)

    print("V10 FINAL DEVELOPMENT DISPOSITION")
    print("=" * 92)
    print("Decision: REJECTED_DO_NOT_FREEZE")
    print("Original V10: 12/13 gates")
    print("Cycle 2: 12/13 gates")
    print(f"Failed gate: {EXPECTED_FAILED_GATE}")
    print("November holdout activated: NO")
    print("Dashboard classification: RECONSTRUCTED_DEVELOPMENT_ONLY")
    print("V8 status: SOLE_FROZEN_FORWARD_MODEL")
    print("Holdout outcomes read/scored: NO")
    print("V8/production modified: NO")
    print("Brokerage orders: OFF")
    print(f"Disposition SHA-256: {payload['disposition_sha256']}")


if __name__ == "__main__":
    main()
