"""Create a fail-closed V8 day-zero readiness release checkpoint.

Runs the reviewed validation suite, isolated boundary regression, and operational
monitor before recording source/frozen hashes and scheduler registration. The
checkpoint is operational metadata, not holdout evidence. No brokerage interface
is imported or invoked.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ml.v8 import holdout_runner as prod
from ml.v8.operational_change_control import MANIFEST_PATH, verify
from ml.v8.production_preflight import run_preflight

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_ROOT = PROJECT_ROOT / "data/model/v8/release_checkpoints"
V10_SPEC_PATH = PROJECT_ROOT / "data/model/v10/cycle3/freeze/frozen_candidate_spec.json"
EXPECTED_V10_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
EXPECTED_V10_ID = "c3_confirm2_blend50"
REQUIRED_SERVICES = [
    "com.datashepherd.v8paper",
    "com.datashepherd.v10cycle3",
    "com.datashepherd.web",
    "com.datashepherd.cloudflared",
]
VALIDATION_MODULES = [
    ("complete_validation_suite", "ml.v8.complete_validation_suite"),
    ("boundary_transition_regression", "ml.v8.boundary_transition_regression"),
    ("operational_monitor", "ml.v8.operational_monitor"),
]


def _sha256(path):
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _git_commit():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "unable to resolve git commit")
    return result.stdout.strip()


def _service_status(label):
    if sys.platform != "darwin":
        return {"label": label, "loaded": False, "detail": f"unsupported platform: {sys.platform}"}
    target = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        ["launchctl", "print", target],
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "label": label,
        "loaded": result.returncode == 0,
        "detail": "registered" if result.returncode == 0 else (result.stderr.strip() or "not registered"),
    }


def _run_module(label, module):
    print(f"\n--- {label}: python -m {module} ---", flush=True)
    result = subprocess.run([sys.executable, "-m", module], cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        raise RuntimeError(f"{module} exited {result.returncode}")
    return {"label": label, "module": module, "status": "PASSED"}


def main():
    print("V8 DAY-ZERO READINESS RELEASE CHECKPOINT")
    print("=" * 92)
    journal_before = _sha256(PROJECT_ROOT / prod.JOURNAL_PATH)
    status_before = _sha256(PROJECT_ROOT / prod.STATUS_PATH)

    validations = [_run_module(label, module) for label, module in VALIDATION_MODULES]

    preflight = run_preflight()
    if preflight.get("status") != "READY":
        raise RuntimeError("production preflight is not READY")

    manifest, protected, change_failures = verify()
    if change_failures:
        raise RuntimeError("operational change control failed: " + "; ".join(change_failures))

    if not V10_SPEC_PATH.exists():
        raise FileNotFoundError(f"missing {V10_SPEC_PATH}")
    v10_spec = json.loads(V10_SPEC_PATH.read_text(encoding="utf-8"))
    if v10_spec.get("spec_sha256") != EXPECTED_V10_SHA:
        raise RuntimeError("V10 Cycle 3 frozen SHA mismatch")
    if v10_spec.get("candidate_id") != EXPECTED_V10_ID:
        raise RuntimeError("V10 Cycle 3 candidate mismatch")

    services = [_service_status(label) for label in REQUIRED_SERVICES]
    unavailable = [item["label"] for item in services if not item["loaded"]]
    if unavailable:
        raise RuntimeError("required LaunchAgent service(s) not registered: " + ", ".join(unavailable))

    journal_after = _sha256(PROJECT_ROOT / prod.JOURNAL_PATH)
    status_after = _sha256(PROJECT_ROOT / prod.STATUS_PATH)
    if journal_before != journal_after:
        raise RuntimeError("production holdout journal changed during day-zero validation")
    if status_before != status_after:
        raise RuntimeError("production holdout status changed during day-zero validation")

    now = datetime.now(timezone.utc)
    checkpoint = {
        "contract": "V8_FROZEN_FORWARD_HOLDOUT_DAY_ZERO_RELEASE",
        "status": "READY_FOR_2026_09_01",
        "created_at_utc": now.isoformat(),
        "git_commit": _git_commit(),
        "v8": {
            "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256": prod.EXPECTED_SHA,
            "holdout_start_utc": prod.HOLDOUT_START.isoformat(),
            "production_journal_sha256_before": journal_before,
            "production_journal_sha256_after": journal_after,
            "production_status_sha256_before": status_before,
            "production_status_sha256_after": status_after,
            "production_evidence_modified": False,
        },
        "v10_cycle3_reference": {
            "candidate_id": EXPECTED_V10_ID,
            "frozen_sha256": EXPECTED_V10_SHA,
            "holdout_start_utc": v10_spec["holdout_contract"]["fresh_holdout_start_utc"],
            "modified": False,
        },
        "operational_manifest": {
            "path": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
            "sha256": _sha256(MANIFEST_PATH),
            "contract": manifest.get("contract"),
            "protected_files": protected,
        },
        "preflight": {
            "status": preflight["status"],
            "journal_events": preflight["journal_events"],
            "failed_checks": preflight["failed_checks"],
        },
        "validations": validations,
        "services": services,
        "safety": {
            "boundary_regression_isolated": True,
            "frozen_strategy_modified": False,
            "holdout_outcomes_read_for_selection": False,
            "brokerage_orders": False,
        },
    }
    path = CHECKPOINT_ROOT / f"v8_day_zero_{now.date().isoformat()}.json"
    _atomic_write_json(path, checkpoint)

    print("\n" + "=" * 92)
    print("Status: READY_FOR_2026_09_01")
    print(f"Checkpoint: {path.relative_to(PROJECT_ROOT)}")
    print(f"Git commit: {checkpoint['git_commit']}")
    print(f"V8 frozen SHA: {prod.EXPECTED_SHA}")
    print(f"V10 Cycle 3 reference SHA: {EXPECTED_V10_SHA}")
    print(f"Operational protected files: {len(protected)}")
    print(f"Required services registered: {len(services)}/{len(REQUIRED_SERVICES)}")
    print("Production journal/status unchanged: True/True")
    print("Frozen models modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
