"""End-to-end, in-memory rehearsal of the V13 activation ceremony.

This module proves that a correctly bound human approval could satisfy the
locked transition planner. It deliberately has no file-write, scheduler,
market-data, evidence-append, activation, or brokerage surface.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
    APPROVAL_PATH,
    EXPECTED_CONTRACT_SHA256 as EXPECTED_TRANSITION_CONTRACT_SHA256,
    plan_transition,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_V13_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
)
from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH
from ml.v13.regime_overlay_manual_approval import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_APPROVAL_CONTRACT_SHA256,
    canonical_sha256,
    verify_approval,
)
from ml.v13.regime_overlay_preflight import run_preflight


REQUIRED_ACKNOWLEDGEMENT = (
    "I APPROVE V13 FRESH PAPER EVIDENCE ONLY; NO LIVE BROKERAGE AUTHORITY"
)
REHEARSAL_OPERATOR = "V13_ACTIVATION_REHEARSAL"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def build_rehearsal_approval(
    *,
    preflight: dict[str, object],
    approved_at_utc: datetime,
    operator: str = REHEARSAL_OPERATOR,
) -> dict[str, object]:
    """Construct a non-persisted approval bound to one exact preflight."""
    approved_at = _utc(approved_at_utc)
    return {
        "approval_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "approved_at_utc": approved_at.isoformat(),
        "operator": operator,
        "acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
        "preflight_sha256": canonical_sha256(preflight),
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "rehearsal": True,
        "persisted": False,
    }


def build_proposed_lease(
    *,
    approval: dict[str, object],
    issued_at_utc: datetime,
) -> dict[str, object]:
    """Describe the future lease in memory without writing or applying it."""
    issued_at = _utc(issued_at_utc)
    return {
        "lease_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "issued_at_utc": issued_at.isoformat(),
        "expires_at_utc": (issued_at + timedelta(hours=24)).isoformat(),
        "approval_sha256": canonical_sha256(approval),
        "manual_approval_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "transition_contract_sha256": EXPECTED_TRANSITION_CONTRACT_SHA256,
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "activation_state": "ENABLED_FRESH_EVIDENCE_PAPER_ONLY",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "rehearsal": True,
        "persisted": False,
    }


def run_rehearsal(
    *,
    now_utc: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    operator: str = REHEARSAL_OPERATOR,
) -> dict[str, object]:
    """Exercise approval and transition gates without changing any path."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    protected = (journal_path, approval_path, lease_path)
    before = {path: _snapshot(path) for path in protected}

    preflight = run_preflight(production_journal_path=journal_path)
    approval_payload = build_rehearsal_approval(
        preflight=preflight,
        approved_at_utc=now,
        operator=operator,
    )
    approval_result = verify_approval(
        approval_payload,
        preflight,
        now=now,
    )
    transition = plan_transition(
        preflight=preflight,
        approval=approval_result,
        now=now,
    )
    proposed_lease = build_proposed_lease(
        approval=approval_payload,
        issued_at_utc=now,
    )

    after = {path: _snapshot(path) for path in protected}
    protected_unchanged = before == after
    passed = (
        preflight.get("status") == "READY_DISABLED"
        and approval_result.get("status")
        == "VALID_FOR_SEPARATE_ACTIVATION_STEP"
        and approval_result.get("valid") is True
        and transition.get("status") == "ELIGIBLE_PLAN_ONLY"
        and transition.get("eligible") is True
        and transition.get("transition_applied") is False
        and proposed_lease.get("persisted") is False
        and protected_unchanged
    )
    return {
        "status": "PASSED_REHEARSAL_ONLY" if passed else "FAILED_REHEARSAL",
        "rehearsal": True,
        "approval_status": approval_result.get("status"),
        "approval_valid": approval_result.get("valid") is True,
        "approval_payload_sha256": canonical_sha256(approval_payload),
        "approval_artifact_written": False,
        "transition_status": transition.get("status"),
        "transition_eligible_in_rehearsal": transition.get("eligible") is True,
        "transition_gates_passed": transition.get("gates_passed"),
        "transition_gates_total": transition.get("gates_total"),
        "transition_applied": False,
        "proposed_lease": proposed_lease,
        "proposed_lease_sha256": canonical_sha256(proposed_lease),
        "activation_lease_written": False,
        "protected_paths_unchanged": protected_unchanged,
        "production_evidence_modified": False,
        "scheduler_changed": False,
        "market_data_requested": False,
        "evidence_appended": False,
        "activation_performed": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    result = run_rehearsal()
    print("V13 ACTIVATION CEREMONY — IN-MEMORY REHEARSAL")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(f"Approval validation: {result['approval_status']}")
    print(
        "Transition plan: "
        f"{result['transition_status']} "
        f"({result['transition_gates_passed']}/{result['transition_gates_total']})"
    )
    print(f"Proposed lease SHA-256: {result['proposed_lease_sha256']}")
    print("Approval artifact written: NO")
    print("Activation lease written: NO")
    print("Transition applied: NO")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Production evidence modified: NO")
    print("Fresh evidence activation performed: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] != "PASSED_REHEARSAL_ONLY":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
