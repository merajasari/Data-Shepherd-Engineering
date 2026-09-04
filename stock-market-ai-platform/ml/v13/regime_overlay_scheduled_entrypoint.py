"""Disabled operational scheduler surface for preregistered V13.

V13 has no approved activation implementation or installed scheduler. This
entrypoint only publishes an atomic operational status and verifies that the
production evidence journal remains unchanged. It cannot request market data,
invoke the observation runner, append evidence, or place brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    DISABLED_ACTIVATION,
    RegimeOverlayEvidenceJournal,
)


ROOT = Path(__file__).resolve().parents[2]
NEW_YORK = ZoneInfo("America/New_York")
STATUS_PATH = ROOT / "data/research/v13/fresh_regime_overlay/operational_status.json"
DECISION_WINDOW_START = time(9, 58)
DECISION_WINDOW_END = time(10, 5)


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def schedule_state(now_utc: datetime) -> str:
    if now_utc.tzinfo is None:
        raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
    contract = load_contract()
    boundary = datetime.fromisoformat(
        str(contract["fresh_evidence"]["boundary_utc"])
    ).astimezone(timezone.utc)
    now = now_utc.astimezone(timezone.utc)
    if now < boundary:
        return "WAITING_FOR_BOUNDARY"
    local = now.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return "MARKET_CLOSED"
    local_time = local.time().replace(tzinfo=None)
    if local_time < DECISION_WINDOW_START:
        return "BEFORE_DECISION_CHECKPOINT"
    if DECISION_WINDOW_START <= local_time < DECISION_WINDOW_END:
        return "DECISION_CHECKPOINT"
    return "AFTER_DECISION_CHECKPOINT"


def run_scheduled(
    *,
    now_utc: datetime | None = None,
    status_path: Path = STATUS_PATH,
    production_journal_path: Path = DEFAULT_JOURNAL_PATH,
    runner: Callable[[], object] | None = None,
) -> dict[str, object]:
    """Publish disabled readiness without invoking ``runner``."""
    if status_path.resolve() == production_journal_path.resolve():
        raise ValueError("V13_STATUS_PATH_CANNOT_BE_EVIDENCE_JOURNAL")
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract = load_contract()
    failures = validate_contract(contract)
    observed_sha = contract_sha256(contract)
    if failures or observed_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V13_CONTRACT_IDENTITY_CHANGED")
    activation = str(contract["fresh_evidence"]["activation_status"])
    if activation != DISABLED_ACTIVATION:
        raise RuntimeError("V13_SEPARATE_ACTIVATION_IMPLEMENTATION_REQUIRED")

    before = _snapshot(production_journal_path)
    rows = RegimeOverlayEvidenceJournal(production_journal_path).read()
    if rows:
        raise RuntimeError("V13_PREACTIVATION_JOURNAL_NOT_EMPTY")
    window = schedule_state(now)
    local_session = now.astimezone(NEW_YORK).date().isoformat()
    payload: dict[str, object] = {
        "checked_at_utc": now.isoformat(),
        "status": "READY_DISABLED",
        "schedule_state": window,
        "session_date_eastern": local_session,
        "activation": activation,
        "contract_sha256": observed_sha,
        "runner_configured": runner is not None,
        "runner_invoked": False,
        "collection_expected": False,
        "scheduler_installation_expected": False,
        "market_data_requests": 0,
        "journal_events": len(rows),
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    after = _snapshot(production_journal_path)
    if before != after:
        raise RuntimeError("V13_DISABLED_ENTRYPOINT_MODIFIED_EVIDENCE")
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    print("V13 GUARDED SCHEDULED ENTRYPOINT")
    print("=" * 80)
    result = run_scheduled()
    print(f"Status: {result['status']}")
    print(f"Schedule state: {result['schedule_state']}")
    print(f"Activation: {result['activation']}")
    print("Collection expected: NO")
    print("Runner invoked: NO")
    print("Market data requests: 0")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
