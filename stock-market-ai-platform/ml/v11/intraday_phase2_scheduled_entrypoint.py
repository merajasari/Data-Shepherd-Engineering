"""Guarded five-minute scheduler entrypoint for V11 Phase 2.

While the preregistered contract is disabled this entrypoint performs no market
requests and writes no evidence. A future separately reviewed activation may
permit paper-only collection during the narrow 10:00-10:40 Eastern window.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import DEFAULT_JOURNAL_PATH
from ml.v11.intraday_phase2_preflight import EXPECTED_CONTRACT_SHA256

ROOT = Path(__file__).resolve().parents[2]
NEW_YORK = ZoneInfo("America/New_York")
STATUS_PATH = (
    ROOT / "data/research/v11/intraday/phase2/operational_status.json"
)
WINDOW_START = time(9, 58)
WINDOW_END = time(10, 40)


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def schedule_state(now_utc: datetime) -> str:
    if now_utc.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    contract = load_contract()
    boundary = datetime.fromisoformat(
        str(contract["fresh_confirmation_start_utc"])
    ).astimezone(timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    if now_utc < boundary:
        return "WAITING_FOR_BOUNDARY"
    local = now_utc.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return "MARKET_CLOSED"
    if WINDOW_START <= local.time().replace(tzinfo=None) <= WINDOW_END:
        return "OBSERVATION_WINDOW"
    return "OUTSIDE_OBSERVATION_WINDOW"


def run_scheduled(
    *,
    now_utc: datetime | None = None,
    status_path: Path = STATUS_PATH,
    production_journal_path: Path = DEFAULT_JOURNAL_PATH,
    active_runner: Callable[[], object] | None = None,
) -> dict[str, object]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract = load_contract()
    observed_sha = contract_sha256(contract)
    if observed_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("PHASE2_CONTRACT_SHA_MISMATCH")

    before = (
        production_journal_path.read_bytes()
        if production_journal_path.exists()
        else None
    )
    window = schedule_state(now)
    activation = str(contract["activation_status"])
    runner_invoked = False
    runner_status = None

    if activation == "DISABLED_PENDING_OPERATIONAL_PREFLIGHT":
        status = "READY_DISABLED"
    elif activation == "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY":
        if window == "OBSERVATION_WINDOW":
            if active_runner is None:
                from ml.v11.intraday_collector import (
                    TiingoIntradayClient,
                    collect_complete_snapshot,
                )
                from ml.v11.intraday_phase2_observation import run_from_files

                local_date = now.astimezone(NEW_YORK).date().isoformat()
                collection = collect_complete_snapshot(
                    now_utc=now,
                    session_date=local_date,
                    client=TiingoIntradayClient(),
                )
                runner_invoked = True
                if collection.published:
                    observation = run_from_files()
                    runner_status = observation.status
                else:
                    runner_status = collection.status
            else:
                runner_invoked = True
                outcome = active_runner()
                runner_status = str(
                    getattr(outcome, "status", outcome)
                )
            status = runner_status or "RUNNER_COMPLETED"
        else:
            status = window
    else:
        raise RuntimeError("PHASE2_ACTIVATION_STATE_INVALID")

    after = (
        production_journal_path.read_bytes()
        if production_journal_path.exists()
        else None
    )
    evidence_modified = before != after
    if activation == "DISABLED_PENDING_OPERATIONAL_PREFLIGHT" and evidence_modified:
        raise RuntimeError("DISABLED_ENTRYPOINT_MODIFIED_EVIDENCE")

    payload: dict[str, object] = {
        "checked_at_utc": now.isoformat(),
        "status": status,
        "schedule_state": window,
        "activation": activation,
        "contract_sha256": observed_sha,
        "runner_invoked": runner_invoked,
        "runner_status": runner_status,
        "production_evidence_modified": evidence_modified,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    print("V11 PHASE 2 GUARDED SCHEDULED ENTRYPOINT")
    print("=" * 80)
    result = run_scheduled()
    print(f"Status: {result['status']}")
    print(f"Schedule state: {result['schedule_state']}")
    print(f"Activation: {result['activation']}")
    print(f"Runner invoked: {result['runner_invoked']}")
    print(
        "Production evidence modified: "
        f"{'YES' if result['production_evidence_modified'] else 'NO'}"
    )
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
