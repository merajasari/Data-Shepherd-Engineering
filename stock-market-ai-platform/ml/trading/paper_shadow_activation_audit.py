"""Read-only, preregistered day-zero eligibility audit for the V8 paper shadow.

Passing this audit never activates the signal bridge. Activation requires a
separate human-reviewed artifact after the frozen boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "ml/trading/paper_shadow_activation_contract.json"
LOCK_PATH = ROOT / "ml/trading/paper_shadow_activation_contract.sha256"
CHECKPOINT_PATH = ROOT / "data/trading/readiness/paper_shadow_activation_audit.json"
EXPECTED_CONTRACT_SHA = "81e211909d3bb2dd6964fae959c1e81677a7861fb3402a00f813abcf16739e94"
EXPECTED_V8_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
BOUNDARY = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _service_registered(label: str) -> bool:
    if sys.platform != "darwin":
        return False
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def _atomic_write(path: Path, payload: dict) -> None:
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


def run_audit(*, now=None, v8_payload=None, paper_monitor=None,
              paper_account=None, runtime_locked=None,
              check_services=True, persist=False) -> dict:
    now = now or datetime.now(timezone.utc)
    contract_raw = CONTRACT_PATH.read_bytes()
    contract = json.loads(contract_raw)
    contract_sha = hashlib.sha256(contract_raw).hexdigest()
    locked_sha = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]

    if v8_payload is None:
        from webapp.services.v8_holdout_service import get_v8_holdout_dashboard
        v8_payload = get_v8_holdout_dashboard()
    if paper_monitor is None:
        from webapp.services.paper_shadow_scheduler_service import get_paper_shadow_scheduler_status
        paper_monitor = get_paper_shadow_scheduler_status()
    if paper_account is None:
        from webapp.services.paper_shadow_service import get_paper_shadow_status
        paper_account = get_paper_shadow_status()
    if runtime_locked is None:
        from ml.trading.paper_shadow_operational_change_control import verify
        _, _, failures = verify()
        runtime_locked = not failures

    v8_ops = v8_payload.get("launch_operations") or {}
    v8_scheduler = (
        _service_registered("com.datashepherd.v8paper")
        if check_services else bool(v8_ops.get("scheduler_healthy"))
    )
    paper_scheduler = (
        _service_registered("com.datashepherd.papershadow")
        if check_services else paper_monitor.get("status") == "HEALTHY"
    )
    top10 = v8_payload.get("latest_research_top10") or []
    universe = v8_payload.get("ranking_eligible_count")
    bridge_status = paper_monitor.get("bridge_status", "PREREGISTERED_DISABLED")

    gate_values = [
        ("boundary_reached", now >= BOUNDARY, BOUNDARY.isoformat()),
        ("frozen_v8_identity_verified",
         contract.get("source_frozen_sha256") == EXPECTED_V8_SHA
         and v8_payload.get("frozen_sha256") == EXPECTED_V8_SHA
         and contract_sha == EXPECTED_CONTRACT_SHA and locked_sha == EXPECTED_CONTRACT_SHA,
         EXPECTED_V8_SHA),
        ("v8_readiness_ready", v8_payload.get("readiness_status") == "READY",
         str(v8_payload.get("readiness_status"))),
        ("market_data_current", v8_ops.get("market_data_current") is True,
         str(v8_ops.get("market_data_current"))),
        ("v8_scheduler_healthy", v8_scheduler, "registered/healthy"),
        ("paper_scheduler_healthy", paper_scheduler, str(paper_monitor.get("status"))),
        ("paper_runtime_locked", bool(runtime_locked), "LOCKED_AND_VERIFIED"),
        ("paper_account_reconciled",
         paper_account.get("status") in {"EMPTY_READY", "HEALTHY"}
         and paper_account.get("reconciled") is True,
         str(paper_account.get("status"))),
        ("ranking_universe_100", universe == 100, str(universe)),
        ("ranking_top10_available", len(top10) == 10, str(len(top10))),
        ("journal_writable", v8_ops.get("journal_writable") is True,
         str(v8_ops.get("journal_writable"))),
        ("journal_duplicate_safe", v8_ops.get("journal_duplicate_safe") is True,
         str(v8_ops.get("journal_duplicate_safe"))),
        ("bridge_preregistered_disabled", bridge_status == "PREREGISTERED_DISABLED",
         str(bridge_status)),
        ("manual_approval_separate",
         contract.get("activation_mode") == "SEPARATE_MANUAL_APPROVAL_ONLY",
         str(contract.get("activation_mode"))),
    ]
    gates = [{"gate": name, "passed": bool(passed), "detail": detail}
             for name, passed, detail in gate_values]
    non_boundary_passed = all(g["passed"] for g in gates if g["gate"] != "boundary_reached")
    if not non_boundary_passed:
        status = "BLOCKED"
    elif now < BOUNDARY:
        status = "WAITING_FOR_BOUNDARY"
    else:
        status = "READY_FOR_MANUAL_APPROVAL"

    payload = {
        "schema_version": 1,
        "status": status,
        "audited_at_utc": now.isoformat(),
        "activation_not_before_utc": BOUNDARY.isoformat(),
        "contract_sha256": contract_sha,
        "frozen_v8_sha256": EXPECTED_V8_SHA,
        "gates": gates,
        "gates_passed": sum(g["passed"] for g in gates),
        "gates_total": len(gates),
        "manual_approval_required": True,
        "manual_approval_present": False,
        "activation_performed": False,
        "paper_signal_export": False,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }
    if persist:
        _atomic_write(CHECKPOINT_PATH, payload)
    return payload


def main() -> None:
    payload = run_audit(persist=True)
    print("DATA SHEPHERD PAPER-SHADOW DAY-ZERO ACTIVATION AUDIT")
    print("=" * 88)
    for gate in payload["gates"]:
        state = "PASS" if gate["passed"] else (
            "WAIT" if gate["gate"] == "boundary_reached"
            and payload["status"] == "WAITING_FOR_BOUNDARY" else "FAIL"
        )
        print(f"[{state}] {gate['gate']}: {gate['detail']}")
    print("\n" + "=" * 88)
    print(f"Status: {payload['status']}")
    print(f"Gates: {payload['gates_passed']}/{payload['gates_total']}")
    print("Separate manual approval required: YES")
    print("Activation performed: NO")
    print("Paper signal export: NO")
    print("Holdout outcomes read: NO")
    print("Production evidence modified: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    if payload["status"] == "BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
