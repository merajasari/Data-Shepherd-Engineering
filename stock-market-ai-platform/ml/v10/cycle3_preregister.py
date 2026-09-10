"""Lock the preregistered V10 Cycle 3 development-only research contract.

This command reads no holdout outcomes, scores no candidate, changes no V8 or
production artifact, and places no brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

SOURCE_PATH = Path(__file__).with_name("cycle3_contract.json")
OUTPUT_ROOT = Path("data/model/v10/cycle3")
LOCKED_CONTRACT_PATH = OUTPUT_ROOT / "preregistered_contract.json"
LOCK_PATH = OUTPUT_ROOT / "preregistered_contract.sha256"
EXPECTED_CONTRACT_SHA256 = "e1df9ac21457a4494f53069b4513ecd4dfe0ae52a743eabdab6a63374998f051"
EXPECTED_CANDIDATES = [
    "c3_confirm2_full_defensive",
    "c3_confirm2_blend50",
    "c3_immediate_blend25",
]
EXPECTED_GATE_COUNT = 13
PROTECTED_V10_BOUNDARY = "2026-11-02T00:00:00+00:00"
FRESH_HOLDOUT_BOUNDARY = "2027-01-04T00:00:00+00:00"

RESULT_FILENAMES = {
    "economic_period_results.csv",
    "cohort_summary.csv",
    "portfolio_summary.csv",
    "year_summary.csv",
    "regime_summary.csv",
    "daily_ic.csv",
    "gate_results.csv",
    "candidate_summary.csv",
    "evaluation_manifest.json",
}


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


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


def _validate(contract, actual_sha):
    failures = []
    if actual_sha != EXPECTED_CONTRACT_SHA256:
        failures.append(
            f"contract SHA mismatch expected={EXPECTED_CONTRACT_SHA256} actual={actual_sha}"
        )
    candidate_ids = [item.get("candidate_id") for item in contract.get("candidates", [])]
    if candidate_ids != EXPECTED_CANDIDATES:
        failures.append(f"candidate set/order changed: {candidate_ids}")
    if len(contract.get("gates", [])) != EXPECTED_GATE_COUNT:
        failures.append("the unchanged 13-gate policy is not present")
    policy = contract.get("development_data_policy", {})
    if policy.get("original_v10_protected_boundary_utc") != PROTECTED_V10_BOUNDARY:
        failures.append("original V10 protected boundary changed")
    future = contract.get("provisional_fresh_future_holdout", {})
    if future.get("boundary_utc") != FRESH_HOLDOUT_BOUNDARY:
        failures.append("fresh future holdout boundary changed")
    if future.get("currently_activated") is not False:
        failures.append("fresh future holdout must remain inactive")
    prohibited = contract.get("prohibitions", {})
    required_false = [
        "tune_after_results",
        "access_original_v10_holdout",
        "access_fresh_future_holdout",
        "modify_v8",
        "modify_production",
        "brokerage_orders",
    ]
    for key in required_false:
        if prohibited.get(key) is not False:
            failures.append(f"prohibition must remain false: {key}")
    return failures


def main():
    payload = SOURCE_PATH.read_bytes()
    actual_sha = _sha256_bytes(payload)
    contract = json.loads(payload.decode("utf-8"))
    failures = _validate(contract, actual_sha)

    existing_results = sorted(
        path.name for path in OUTPUT_ROOT.glob("*")
        if path.name in RESULT_FILENAMES
    )
    if existing_results:
        failures.append(
            "Cycle 3 evaluation outputs already exist before registration: "
            + ", ".join(existing_results)
        )

    print("V10 CYCLE 3 PREREGISTRATION")
    print("=" * 88)
    print(f"Contract SHA-256: {actual_sha}")
    print(f"Candidates: {len(contract.get('candidates', []))}")
    print(f"Gates: {len(contract.get('gates', []))}")
    print(f"Original V10 protected boundary: {PROTECTED_V10_BOUNDARY}")
    print(f"Provisional fresh holdout: {FRESH_HOLDOUT_BOUNDARY}")

    if failures:
        print("Status: BLOCKED")
        for failure in failures:
            print(f"  - {failure}")
        print("No contract lock written.")
        raise SystemExit(2)

    locked = dict(contract)
    locked["locked_at_utc"] = datetime.now(timezone.utc).isoformat()
    locked["contract_sha256"] = actual_sha
    locked["candidate_frozen"] = False
    locked["holdout_activated"] = False
    locked["holdout_outcomes_read"] = False
    locked["holdout_scored"] = False
    locked["v8_modified"] = False
    locked["production_modified"] = False
    locked["brokerage_orders"] = False

    _atomic_write(
        LOCKED_CONTRACT_PATH,
        (json.dumps(locked, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(LOCK_PATH, (actual_sha + "\n").encode("utf-8"))

    print("Status: PREREGISTERED_AND_LOCKED")
    print(f"Lock: {LOCK_PATH}")
    print("Candidate evaluated/frozen: NO")
    print("Original/fresh holdout outcomes read: NO")
    print("V8/production modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
