"""Generate an atomic paper-execution engineering checkpoint.

This command exercises only deterministic temporary paper infrastructure. It never
loads credentials, connects to a broker, submits a live order, or touches V8/V10
production evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/trading/readiness/paper_engineering_status.json"
MODULES = (
    ("core_lifecycle", "ml.trading.paper_execution_regression"),
    ("failure_injection", "ml.trading.failure_injection_regression"),
    ("provenance_orchestration", "ml.trading.sandbox_orchestrator_regression"),
    ("persistent_paper_shadow", "ml.trading.paper_shadow_regression"),
    ("controlled_signal_bridge", "ml.trading.paper_shadow_bridge_regression"),
    ("paper_shadow_scheduler", "ml.trading.paper_shadow_scheduler_regression"),
    ("operational_change_control", "ml.trading.paper_shadow_operational_change_control"),
    ("day_zero_activation_audit", "ml.trading.paper_shadow_activation_audit_regression"),
    ("manual_approval_ceremony", "ml.trading.paper_shadow_manual_approval_regression"),
)


def run_module(name: str, module: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return {
        "name": name,
        "module": module,
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    print("DATA SHEPHERD PAPER-EXECUTION ENGINEERING CHECKPOINT")
    print("=" * 80)
    results = [run_module(name, module) for name, module in MODULES]
    passed = all(item["passed"] for item in results)
    payload = {
        "schema_version": 8,
        "status": "PASSED" if passed else "FAILED",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "modules": results,
        "lifecycle": [
            "PROPOSED", "RISK_APPROVED", "SUBMITTED", "ACKNOWLEDGED",
            "PARTIALLY_FILLED", "FILLED",
        ],
        "restart_recovery": passed,
        "idempotency": passed,
        "concurrency_safety": passed,
        "reconciliation": passed,
        "failure_injection": results[1]["passed"],
        "signal_provenance": results[2]["passed"],
        "sandbox_orchestration": results[2]["passed"],
        "persistent_paper_shadow": results[3]["passed"],
        "atomic_shadow_state": results[3]["passed"],
        "controlled_signal_bridge": results[4]["passed"],
        "bridge_activation_disabled": results[4]["passed"],
        "paper_shadow_scheduler": results[5]["passed"],
        "scheduler_monitor_only": results[5]["passed"],
        "operational_change_control": results[6]["passed"],
        "protected_runtime_locked": results[6]["passed"],
        "day_zero_activation_audit": results[7]["passed"],
        "activation_requires_manual_approval": results[7]["passed"],
        "activation_self_authority": False,
        "manual_approval_ceremony": results[8]["passed"],
        "manual_approval_validator_read_only": results[8]["passed"],
        "live_credentials": False,
        "brokerage_orders": False,
        "production_evidence_modified": False,
    }
    atomic_write(OUTPUT, payload)
    print("\n" + "=" * 80)
    print(f"Status: {payload['status']}")
    print(f"Checkpoint: {OUTPUT.relative_to(ROOT)}")
    print(f"Validation modules: {sum(item['passed'] for item in results)}/{len(results)} passed")
    print("Signal provenance: VERIFIED" if payload["signal_provenance"] else "Signal provenance: FAILED")
    print("Sandbox orchestration: VERIFIED" if payload["sandbox_orchestration"] else "Sandbox orchestration: FAILED")
    print("Persistent paper shadow: VERIFIED" if payload["persistent_paper_shadow"] else "Persistent paper shadow: FAILED")
    print("Controlled signal bridge: VERIFIED DISABLED" if payload["controlled_signal_bridge"] else "Controlled signal bridge: FAILED")
    print("Paper-shadow scheduler: VERIFIED MONITOR-ONLY" if payload["paper_shadow_scheduler"] else "Paper-shadow scheduler: FAILED")
    print("Operational change control: LOCKED_AND_VERIFIED" if payload["operational_change_control"] else "Operational change control: FAILED")
    print("Day-zero activation audit: PREREGISTERED MANUAL-APPROVAL ONLY" if payload["day_zero_activation_audit"] else "Day-zero activation audit: FAILED")
    print("Manual approval ceremony: VERIFIED READ-ONLY" if payload["manual_approval_ceremony"] else "Manual approval ceremony: FAILED")
    print("Mode: PAPER ONLY")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
