"""Read-only validator for a future paper-shadow manual approval artifact.

This module cannot activate the bridge, export a signal, load credentials, or
submit an order. It only validates an explicitly supplied JSON artifact.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "ml/trading/paper_shadow_manual_approval_contract.json"
LOCK_PATH = ROOT / "ml/trading/paper_shadow_manual_approval_contract.sha256"
AUDIT_PATH = ROOT / "data/trading/readiness/paper_shadow_activation_audit.json"
APPROVAL_PATH = ROOT / "data/trading/paper_shadow/activation/manual_approval.json"
EXPECTED_CONTRACT_SHA = "28d38e8c9cfa2c5170b38b15a12d2110d04634ba6d3e7852b1bf4a111e424a4e"
BOUNDARY = datetime(2026, 9, 1, tzinfo=timezone.utc)


class ApprovalRejected(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_approval(approval: dict, audit: dict, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    contract_raw = CONTRACT_PATH.read_bytes()
    contract = json.loads(contract_raw)
    contract_sha = hashlib.sha256(contract_raw).hexdigest()
    locked_sha = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    failures = []
    def gate(name, condition, detail):
        if not condition:
            failures.append(f"{name}: {detail}")

    gate("contract_identity", contract_sha == EXPECTED_CONTRACT_SHA == locked_sha, contract_sha)
    gate("boundary_reached", now >= BOUNDARY, BOUNDARY.isoformat())
    gate("audit_ready", audit.get("status") == "READY_FOR_MANUAL_APPROVAL", audit.get("status"))
    gate("audit_sha", approval.get("activation_audit_sha256") ==
         hashlib.sha256(json.dumps(audit, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
         "approval must bind exact canonical audit")
    gate("frozen_v8", approval.get("frozen_v8_sha256") ==
         contract.get("required_frozen_v8_sha256") == audit.get("frozen_v8_sha256"),
         approval.get("frozen_v8_sha256"))
    gate("bridge_contract", approval.get("bridge_contract_sha256") ==
         contract.get("required_bridge_contract_sha256"), approval.get("bridge_contract_sha256"))
    gate("acknowledgement", approval.get("acknowledgement") ==
         contract.get("required_acknowledgement"), "exact phrase required")
    gate("operator", isinstance(approval.get("operator"), str)
         and len(approval.get("operator", "").strip()) >= 3, "operator identity required")
    try:
        approved_at = datetime.fromisoformat(str(approval.get("approved_at_utc")))
        if approved_at.tzinfo is None:
            raise ValueError("timezone required")
        approved_at = approved_at.astimezone(timezone.utc)
        gate("approval_after_boundary", approved_at >= BOUNDARY, approved_at.isoformat())
        gate("approval_not_future", approved_at <= now, approved_at.isoformat())
        gate("approval_fresh", now - approved_at <= timedelta(
             hours=int(contract["approval_validity_hours"])), approved_at.isoformat())
    except (TypeError, ValueError):
        failures.append("approval_timestamp: valid timezone-aware timestamp required")

    valid = not failures
    return {
        "status": "VALID_FOR_SEPARATE_ACTIVATION_STEP" if valid else "REJECTED",
        "valid": valid,
        "failures": failures,
        "contract_sha256": contract_sha,
        "manual_approval_present": True,
        "manual_approval_required": True,
        "activation_performed": False,
        "paper_signal_export": False,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }


def main() -> None:
    if not APPROVAL_PATH.exists():
        print("DATA SHEPHERD PAPER-SHADOW MANUAL APPROVAL VALIDATOR")
        print("=" * 80)
        print("Status: NOT_PRESENT")
        print(f"Expected artifact: {APPROVAL_PATH.relative_to(ROOT)}")
        print("Activation performed: NO")
        print("Paper signal export: NO")
        print("Brokerage orders: OFF")
        return
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    result = verify_approval(approval, audit)
    print("DATA SHEPHERD PAPER-SHADOW MANUAL APPROVAL VALIDATOR")
    print("=" * 80)
    print(f"Status: {result['status']}")
    for failure in result["failures"]:
        print(f"[FAIL] {failure}")
    print("Activation performed: NO")
    print("Paper signal export: NO")
    print("Brokerage orders: OFF")
    if not result["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
