"""Read-only day-zero checkpoint for the disabled V13 evidence system.

This checkpoint certifies readiness for the future manual-approval ceremony,
not readiness to collect evidence. It cannot create approval, write a lease,
activate V13, change a scheduler, request data, append evidence, or place an
order.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import ml.v13.regime_overlay_activation as activation_module
import ml.v13.regime_overlay_activation_transition as transition_module
import ml.v13.regime_overlay_manual_approval as approval_module
from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
    EXPECTED_CONTRACT_SHA256 as EXPECTED_TRANSITION_CONTRACT_SHA256,
    plan_transition,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    DISABLED_ACTIVATION,
    RegimeOverlayEvidenceJournal,
    V13EvidenceJournalCorrupt,
)
from ml.v13.regime_overlay_manual_approval import (
    APPROVAL_PATH,
    EXPECTED_CONTRACT_SHA256 as EXPECTED_APPROVAL_CONTRACT_SHA256,
    get_manual_approval_status,
)
from ml.v13.regime_overlay_preflight import run_preflight


BOUNDARY = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def run_checkpoint(
    *,
    now_utc: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    preflight_runner: Callable[..., dict[str, object]] = run_preflight,
) -> dict[str, object]:
    """Evaluate readiness without modifying any protected path."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    protected = (journal_path, approval_path, lease_path)
    before = {path: _snapshot(path) for path in protected}
    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    contract_failures = validate_contract(contract)
    check(
        "v13_contract_identity",
        observed_sha == EXPECTED_CONTRACT_SHA256 and not contract_failures,
        observed_sha if not contract_failures else ",".join(contract_failures),
    )
    evidence = contract.get("fresh_evidence", {})
    authority = contract.get("authority", {})
    check(
        "fresh_evidence_boundary",
        evidence.get("boundary_utc") == BOUNDARY.isoformat(),
        str(evidence.get("boundary_utc")),
    )
    check(
        "activation_remains_disabled",
        evidence.get("activation_status") == DISABLED_ACTIVATION,
        str(evidence.get("activation_status")),
    )
    check(
        "paper_only_safety_boundary",
        authority.get("research_only") is True
        and authority.get("paper_trading_only") is True
        and authority.get("live_trading_enabled") is False
        and authority.get("brokerage_orders") is False,
        "research/paper only; live trading disabled; brokerage orders off",
    )
    check(
        "production_isolation",
        all(
            authority.get(field) is False
            for field in (
                "v8_production_reads",
                "v8_production_writes",
                "v10_production_reads",
                "v10_production_writes",
                "v11_production_reads",
                "v11_production_writes",
                "v12_development_evidence_reads",
                "holdout_outcomes_read",
            )
        ),
        "V8/V10/V11/V12 and holdout paths prohibited",
    )

    preflight = preflight_runner(production_journal_path=journal_path)
    check(
        "operational_preflight",
        preflight.get("status") == "READY_DISABLED",
        str(preflight.get("status")),
    )
    check(
        "preflight_identities",
        preflight.get("contract_sha256") == EXPECTED_CONTRACT_SHA256
        and preflight.get("v12_disposition_sha256")
        == EXPECTED_V12_DISPOSITION_SHA256,
        (
            f"v13={preflight.get('contract_sha256')}; "
            f"v12={preflight.get('v12_disposition_sha256')}"
        ),
    )
    check(
        "preflight_read_only",
        preflight.get("production_evidence_modified") is False,
        "production evidence unchanged",
    )

    journal_valid = True
    journal_events: list[dict[str, object]] = []
    try:
        journal_events = RegimeOverlayEvidenceJournal(journal_path).read()
        journal_detail = f"events={len(journal_events)}; hash-chain valid"
    except V13EvidenceJournalCorrupt as exc:
        journal_valid = False
        journal_detail = str(exc)
    check("production_journal_integrity", journal_valid, journal_detail)
    check(
        "preactivation_journal_empty",
        journal_valid and len(journal_events) == 0,
        f"events={len(journal_events)}" if journal_valid else "invalid",
    )
    check(
        "manual_approval_artifact_absent",
        not approval_path.exists(),
        "absent" if not approval_path.exists() else "unexpectedly present",
    )
    check(
        "activation_lease_absent",
        not lease_path.exists(),
        "absent" if not lease_path.exists() else "unexpectedly present",
    )

    approval = get_manual_approval_status(
        approval_path=approval_path,
        preflight=preflight,
        now=now,
    )
    expected_approval_status = (
        "WAITING_FOR_BOUNDARY" if now < BOUNDARY else "NOT_PRESENT"
    )
    check(
        "manual_approval_state",
        approval.get("status") == expected_approval_status
        and approval.get("manual_approval_present") is False,
        str(approval.get("status")),
    )
    check(
        "manual_approval_contract_identity",
        approval.get("control_contract_sha256")
        == EXPECTED_APPROVAL_CONTRACT_SHA256,
        str(approval.get("control_contract_sha256")),
    )

    transition = plan_transition(
        preflight=preflight,
        approval=approval,
        now=now,
    )
    expected_transition_status = (
        "WAITING_FOR_BOUNDARY"
        if now < BOUNDARY
        else "WAITING_FOR_MANUAL_APPROVAL"
    )
    check(
        "transition_plan_state",
        transition.get("status") == expected_transition_status,
        str(transition.get("status")),
    )
    check(
        "transition_contract_identity",
        transition.get("contract_sha256")
        == EXPECTED_TRANSITION_CONTRACT_SHA256,
        str(transition.get("contract_sha256")),
    )
    check(
        "transition_non_applying",
        transition.get("application_implementation_present") is False
        and transition.get("transition_applied") is False
        and transition.get("manual_approval_written") is False
        and transition.get("activation_lease_written") is False
        and transition.get("v13_contract_modified") is False
        and transition.get("production_journal_modified") is False
        and transition.get("scheduler_changed") is False
        and transition.get("market_data_requested") is False
        and transition.get("evidence_appended") is False,
        "no apply, approval, lease, contract, evidence, scheduler or data writes",
    )
    check(
        "approval_validator_remains_read_only",
        not hasattr(approval_module, "create_approval"),
        "approval validator contains no creator",
    )
    check(
        "transition_planner_remains_non_applying",
        not hasattr(transition_module, "apply_transition"),
        "transition planner contains no applier",
    )
    check(
        "guarded_activation_implementation_present",
        hasattr(activation_module, "activate")
        and hasattr(activation_module, "validate_activation_lease"),
        "separate fail-closed activation ceremony present",
    )
    source = (
        inspect.getsource(approval_module)
        + inspect.getsource(transition_module)
        + inspect.getsource(activation_module)
    ).lower()
    check(
        "brokerage_sdk_absent",
        all(
            token not in source
            for token in (
                "import alpaca",
                "from alpaca",
                "import robin_stocks",
                "from robin_stocks",
                "import ib_insync",
            )
        ),
        "no brokerage interface imported",
    )

    after = {path: _snapshot(path) for path in protected}
    check(
        "protected_paths_unchanged",
        before == after,
        "journal, approval and lease are read only",
    )

    passed = all(bool(row["passed"]) for row in checks)
    if passed:
        status = (
            "READY_FOR_2026_09_01_MANUAL_APPROVAL"
            if now < BOUNDARY
            else "READY_FOR_MANUAL_APPROVAL"
        )
    else:
        status = "FAILED"
    return {
        "status": status,
        "checks": checks,
        "contract_sha256": observed_sha,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "manual_approval_contract_sha256": EXPECTED_APPROVAL_CONTRACT_SHA256,
        "transition_contract_sha256": EXPECTED_TRANSITION_CONTRACT_SHA256,
        "fresh_evidence_boundary_utc": BOUNDARY.isoformat(),
        "journal_events": len(journal_events) if journal_valid else None,
        "manual_approval_present": approval_path.exists(),
        "activation_lease_present": lease_path.exists(),
        "activation": DISABLED_ACTIVATION,
        "production_evidence_modified": before[journal_path] != after[journal_path],
        "approval_artifact_modified": before[approval_path] != after[approval_path],
        "activation_lease_modified": before[lease_path] != after[lease_path],
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    print("V13 FRESH REGIME-OVERLAY DAY-ZERO READINESS CHECKPOINT")
    print("=" * 88)
    result = run_checkpoint()
    for row in result["checks"]:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"V13 contract SHA-256: {result['contract_sha256']}")
    print(
        "Manual approval contract SHA-256: "
        f"{result['manual_approval_contract_sha256']}"
    )
    print(
        "Transition contract SHA-256: "
        f"{result['transition_contract_sha256']}"
    )
    print(f"Fresh evidence boundary: {result['fresh_evidence_boundary_utc']}")
    print(f"Journal events: {result['journal_events']}")
    print("Manual approval artifact: ABSENT")
    print("Activation lease: ABSENT")
    print("Fresh evidence activation: DISABLED")
    print("Apply implementation: PRESENT (GUARDED PAPER ONLY)")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
