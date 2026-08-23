"""Read-only V10 future-holdout readiness audit.

This audit never reads future-holdout outcomes, never scores post-boundary data,
never freezes a candidate, and never writes production or brokerage state. It
only validates development manifests and freeze-registration prerequisites.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ml.v10.config import FUTURE_HOLDOUT_START_UTC

EXPECTED_BOUNDARY = "2026-11-02T00:00:00+00:00"
ROOT = Path("data/model/v10")
READINESS_ROOT = ROOT / "readiness"
STATUS_PATH = READINESS_ROOT / "status.json"
FREEZE_ROOT = ROOT / "freeze"
SPEC_PATH = FREEZE_ROOT / "frozen_candidate_spec.json"
LOCK_PATH = FREEZE_ROOT / "frozen_candidate.sha256"
PHASE_MANIFESTS = {
    phase: ROOT / f"phase{phase}" / "manifest.json"
    for phase in range(1, 5)
}


def _read_json(path: Path):
    return json.loads(path.read_text())


def _atomic_write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _canonical_spec_sha(spec):
    payload = dict(spec)
    payload.pop("spec_sha256", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_freeze():
    failures = []
    details = {
        "spec_path": str(SPEC_PATH),
        "lock_path": str(LOCK_PATH),
        "registered": SPEC_PATH.exists() and LOCK_PATH.exists(),
    }
    if not details["registered"]:
        failures.append(
            "V10 candidate is not frozen: frozen specification and SHA lock are absent"
        )
        return details, failures

    try:
        spec = _read_json(SPEC_PATH)
        lock_sha = LOCK_PATH.read_text().strip().split()[0]
        calculated_sha = _canonical_spec_sha(spec)
        registered_sha = str(spec.get("spec_sha256", ""))
        details.update(
            {
                "candidate_id": spec.get("candidate_id"),
                "registered_sha256": registered_sha,
                "lock_sha256": lock_sha,
                "calculated_sha256": calculated_sha,
                "holdout_start_utc": spec.get("holdout_start_utc"),
            }
        )
        if not registered_sha or registered_sha != lock_sha or registered_sha != calculated_sha:
            failures.append("V10 frozen specification SHA verification failed")
        if spec.get("holdout_start_utc") != EXPECTED_BOUNDARY:
            failures.append("V10 frozen specification has the wrong holdout boundary")
        if spec.get("candidate_id") != "switch_on_negative_spy20":
            failures.append("V10 frozen candidate is not the registered Phase-4 primary challenger")
        contract = spec.get("execution_contract") or {}
        expected = {
            "top_n": 10,
            "weighting": "equal_weight",
            "entry": "next_session_open",
            "holding_sessions": 5,
            "cohort_offsets": [0, 1, 2, 3, 4],
            "cost_bps_per_dollar_traded": 10,
            "benchmark": "SPY",
            "brokerage_orders": False,
        }
        for key, value in expected.items():
            if contract.get(key) != value:
                failures.append(f"V10 frozen execution contract mismatch: {key}")
    except Exception as exc:
        failures.append(f"Unable to validate V10 freeze registration: {exc}")
    return details, failures


def main():
    failures = []
    warnings = []
    phase_details = {}

    boundary = FUTURE_HOLDOUT_START_UTC.isoformat()
    if boundary != EXPECTED_BOUNDARY:
        failures.append(
            f"V10 boundary mismatch: expected {EXPECTED_BOUNDARY}, found {boundary}"
        )

    manifests = {}
    for phase, path in PHASE_MANIFESTS.items():
        if not path.exists():
            failures.append(f"Missing V10 Phase-{phase} manifest: {path}")
            continue
        try:
            manifest = _read_json(path)
            manifests[phase] = manifest
            phase_details[str(phase)] = {
                "path": str(path),
                "stage": manifest.get("stage"),
                "candidate_frozen": manifest.get("candidate_frozen"),
                "holdout_scored": manifest.get("holdout_scored"),
                "brokerage_orders": manifest.get("brokerage_orders"),
            }
            if manifest.get("holdout_scored") is not False:
                failures.append(f"Phase {phase} does not explicitly keep holdout_scored false")
            if manifest.get("brokerage_orders") is not False:
                failures.append(f"Phase {phase} does not explicitly disable brokerage orders")
            if manifest.get("production_modified") is not False:
                failures.append(f"Phase {phase} does not explicitly preserve production state")
            if manifest.get("v8_modified") is not False:
                failures.append(f"Phase {phase} does not explicitly preserve frozen V8")
            manifest_boundary = manifest.get("future_holdout_start_utc")
            if manifest_boundary is not None and manifest_boundary != EXPECTED_BOUNDARY:
                failures.append(f"Phase {phase} declares the wrong V10 holdout boundary")
        except Exception as exc:
            failures.append(f"Unable to read V10 Phase-{phase} manifest: {exc}")

    phase4 = manifests.get(4) or {}
    decision = phase4.get("decision")
    gates_passed = phase4.get("gates_passed")
    gates_total = phase4.get("gates_total")
    if decision != "ADVANCE_TO_FREEZE_DESIGN":
        failures.append(
            f"Phase-4 gate has not authorized freeze design: decision={decision or 'MISSING'}"
        )
    if not isinstance(gates_total, int) or gates_total <= 0 or gates_passed != gates_total:
        failures.append(
            f"Phase-4 gates are incomplete: passed={gates_passed}, total={gates_total}"
        )

    freeze_details, freeze_failures = _validate_freeze()
    failures.extend(freeze_failures)

    if not failures:
        status = "READY_FOR_HOLDOUT_INFRASTRUCTURE"
    elif any("candidate is not frozen" in item for item in failures):
        status = "NOT_READY_CANDIDATE_NOT_FROZEN"
    else:
        status = "NOT_READY"

    payload = {
        "status": status,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": EXPECTED_BOUNDARY,
        "phase_details": phase_details,
        "phase4_decision": decision,
        "phase4_gates_passed": gates_passed,
        "phase4_gates_total": gates_total,
        "freeze": freeze_details,
        "failures": failures,
        "warnings": warnings,
        "holdout_outcomes_read": False,
        "holdout_scored": False,
        "candidate_frozen_by_this_audit": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    _atomic_write_json(STATUS_PATH, payload)

    print("V10 FUTURE-HOLDOUT READINESS AUDIT")
    print("=" * 92)
    print(f"Status: {status}")
    print(f"Boundary: {EXPECTED_BOUNDARY}")
    print(f"Phase-4 decision: {decision or 'MISSING'}")
    print(f"Phase-4 gates: {gates_passed}/{gates_total}")
    print(f"Frozen candidate registered: {freeze_details.get('registered', False)}")
    print("Holdout outcomes read: NO")
    print("Holdout scored: NO")
    print("V8/production modified: NO")
    print("Brokerage orders: OFF")
    if failures:
        print("BLOCKERS:")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(2)
    print("Status: READY")


if __name__ == "__main__":
    main()
