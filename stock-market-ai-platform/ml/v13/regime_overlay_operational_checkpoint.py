"""Read-only operational checkpoint for activated V13 paper evidence.

This checkpoint is deliberately separate from the historical day-zero audit.
It validates the effective paper-only lease and reports the real activation
artifacts without writing evidence, changing a scheduler, requesting data, or
exposing brokerage authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ml.v13.regime_overlay_activation import validate_activation_lease
from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    RegimeOverlayEvidenceJournal,
    V13EvidenceJournalCorrupt,
)
from ml.v13.regime_overlay_manual_approval import APPROVAL_PATH
from ml.v13.regime_overlay_preflight import run_preflight


def _effective_lease(
    *,
    now: datetime,
    approval_path: Path,
    lease_path: Path,
    journal_path: Path,
    lease_validator: Callable[..., dict[str, object]],
    renewal_validator: Callable[..., dict[str, object]] | None,
) -> dict[str, object]:
    """Validate the root lease, then the latest immutable renewal if present."""
    root = lease_validator(
        approval_path=approval_path,
        lease_path=lease_path,
        now_utc=now,
    )
    if root.get("valid") is True:
        return root
    if renewal_validator is None:
        try:
            from ml.v13.regime_overlay_lease_renewal_apply import (
                validate_renewal_chain,
            )
            renewal_validator = validate_renewal_chain
        except ImportError:
            return root
    try:
        chain = renewal_validator(
            approval_path=approval_path,
            lease_path=lease_path,
            renewals_path=lease_path.parent / "renewals",
            journal_path=journal_path,
            now_utc=now,
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return root
    if chain.get("valid") is not True:
        return root
    return {
        **root,
        "status": "ACTIVE_PAPER_ONLY" if chain.get("active") is True else "EXPIRED_RENEWAL_READY",
        "valid": chain.get("active") is True,
        "active": chain.get("active") is True,
        "activation": "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
        if chain.get("active") is True
        else "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "operator": chain.get("operator"),
        "expires_at_utc": chain.get("latest_lease_expires_at_utc"),
        "lease_sha256": chain.get("latest_lease_sha256"),
        "paper_trading_only": chain.get("paper_trading_only") is True,
        "live_trading_enabled": chain.get("live_trading_enabled") is True,
        "brokerage_orders": chain.get("brokerage_orders") is True,
        "scheduler_installed": False,
        "market_data_requested": False,
        "evidence_appended": False,
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("V13_CHECKPOINT_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def run_checkpoint(
    *,
    now_utc: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    approval_path: Path = APPROVAL_PATH,
    lease_path: Path = ACTIVATION_LEASE_PATH,
    preflight_runner: Callable[..., dict[str, object]] = run_preflight,
    lease_validator: Callable[..., dict[str, object]] = validate_activation_lease,
    renewal_validator: Callable[..., dict[str, object]] | None = None,
) -> dict[str, object]:
    """Evaluate effective V13 status without modifying protected paths."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    protected = (journal_path, approval_path, lease_path)
    before = {path: _snapshot(path) for path in protected}
    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    failures = validate_contract(contract)
    check(
        "v13_contract_identity",
        observed_sha == EXPECTED_CONTRACT_SHA256 and not failures,
        observed_sha if not failures else ",".join(failures),
    )

    preflight = preflight_runner(production_journal_path=journal_path)
    check(
        "production_preflight_read_only",
        preflight.get("production_evidence_modified") is False,
        "production evidence unchanged",
    )
    check(
        "production_isolation",
        preflight.get("v8_modified") is False
        and preflight.get("v10_modified") is False
        and preflight.get("v11_modified") is False
        and preflight.get("v12_modified") is False,
        "V8/V10/V11/V12 unchanged",
    )

    journal_valid = True
    journal_events: list[dict[str, object]] = []
    try:
        journal_events = RegimeOverlayEvidenceJournal(journal_path).read()
        journal_detail = f"events={len(journal_events)}; hash-chain valid"
    except V13EvidenceJournalCorrupt as exc:
        journal_valid = False
        journal_detail = str(exc)
    check("journal_integrity", journal_valid, journal_detail)

    lease = _effective_lease(
        now=now,
        approval_path=approval_path,
        lease_path=lease_path,
        journal_path=journal_path,
        lease_validator=lease_validator,
        renewal_validator=renewal_validator,
    )
    active = lease.get("valid") is True and lease.get("status") == "ACTIVE_PAPER_ONLY"
    check("paper_lease_valid", active, str(lease.get("status")))
    check(
        "paper_only_authority",
        lease.get("paper_trading_only") is True
        and lease.get("live_trading_enabled") is False
        and lease.get("brokerage_orders") is False,
        "paper trading only; live trading disabled; brokerage orders off",
    )
    check(
        "lease_no_operational_side_effects",
        lease.get("scheduler_installed", False) is False
        and lease.get("market_data_requested", False) is False
        and lease.get("evidence_appended", False) is False,
        "scheduler unchanged; market data and evidence writes absent",
    )

    after = {path: _snapshot(path) for path in protected}
    unchanged = before == after
    check("protected_paths_unchanged", unchanged, "checkpoint performed no writes")

    passed = all(bool(row["passed"]) for row in checks)
    status = "ACTIVE_PAPER_ONLY" if passed and active else "EXPIRED_OR_BLOCKED"
    return {
        "status": status,
        "checks": checks,
        "checked_at_utc": now.isoformat(),
        "contract_sha256": observed_sha,
        "activation": lease.get("activation", "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT")
        if active
        else "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "approval_artifact_present": approval_path.exists(),
        "activation_lease_present": lease_path.exists(),
        "activation_lease_valid": active,
        "activation_lease_operator": lease.get("operator"),
        "activation_lease_expires_at_utc": lease.get("expires_at_utc"),
        "journal_events": len(journal_events) if journal_valid else None,
        "production_evidence_modified": False,
        "market_data_requested": False,
        "scheduler_changed": False,
        "evidence_appended": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    result = run_checkpoint()
    print("V13 ACTIVATION-AWARE OPERATIONAL CHECKPOINT")
    print("=" * 80)
    for row in result["checks"]:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Checked at: {result['checked_at_utc']}")
    print(f"Contract SHA-256: {result['contract_sha256']}")
    print(f"Activation: {result['activation']}")
    print(
        "Approval artifact: "
        + ("PRESENT" if result["approval_artifact_present"] else "ABSENT")
    )
    print(
        "Activation lease: "
        + ("PRESENT" if result["activation_lease_present"] else "ABSENT")
    )
    print(f"Lease operator: {result['activation_lease_operator'] or 'NONE'}")
    print(f"Lease expires: {result['activation_lease_expires_at_utc'] or 'NONE'}")
    print(f"Journal events: {result['journal_events']}")
    print("Market data requested: NO")
    print("Scheduler changed: NO")
    print("Evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 modified: NO")
    if result["status"] == "EXPIRED_OR_BLOCKED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
