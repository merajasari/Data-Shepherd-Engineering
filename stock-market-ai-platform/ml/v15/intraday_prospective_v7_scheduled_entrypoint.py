"""Guarded five-minute scheduler for V15 V7 prospective paper shadow."""
from __future__ import annotations

import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ml.v15.intraday_prospective_v7_contract import (
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)
from ml.v15.intraday_prospective_v7_journal import (
    DEFAULT_JOURNAL_PATH,
    V7EvidenceJournal,
)
from ml.v15.intraday_prospective_v7_runner import (
    MODEL_PATH,
    SNAPSHOT_PATH,
    load_prepared_model,
    run_from_files,
)


ROOT = Path(__file__).resolve().parents[2]
NEW_YORK = ZoneInfo("America/New_York")
STATUS_PATH = ROOT / "data/research/v15/prospective_v7/operational_status.json"
MAX_REQUESTS_PER_COLLECTION = 101
MAX_COLLECTIONS_PER_SESSION = 3
MAX_REQUESTS_PER_SESSION = MAX_REQUESTS_PER_COLLECTION * MAX_COLLECTIONS_PER_SESSION


def _clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _previous_status(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def schedule_state(now_utc: datetime) -> str:
    if now_utc.tzinfo is None:
        raise ValueError("V15_V7_NOW_MUST_BE_TIMEZONE_AWARE")
    contract = load_contract()
    local = now_utc.astimezone(NEW_YORK)
    boundary = datetime.fromisoformat(
        str(contract["evidence_boundary"]["first_eligible_session"])
    ).date()
    if local.date() < boundary:
        return "WAITING_FOR_PROSPECTIVE_BOUNDARY"
    if (
        local.weekday() >= 5
        or local.date().isoformat() in contract["lifecycle"]["market_closures"]
    ):
        return "MARKET_CLOSED"
    lifecycle = contract["lifecycle"]
    current = local.time().replace(tzinfo=None)
    decision_start, decision_end = map(_clock, lifecycle["decision_checkpoint"])
    entry_start, entry_end = map(_clock, lifecycle["entry_checkpoint"])
    exit_start, exit_end = map(_clock, lifecycle["exit_checkpoint"])
    if decision_start <= current < decision_end:
        return "DECISION_CHECKPOINT"
    if entry_start <= current < entry_end:
        return "ENTRY_CHECKPOINT"
    if exit_start <= current < exit_end:
        return "EXIT_CHECKPOINT"
    if current >= exit_end:
        return "AFTER_EXIT_CHECKPOINT"
    return "BETWEEN_CHECKPOINTS"


def _session_lifecycle(
    rows: list[dict[str, object]],
    session: str,
) -> dict[str, dict[str, object]]:
    return {
        str(row["event_type"]): row
        for row in rows
        if row["session_date"] == session
    }


def _decision_trades(event: Mapping[str, object]) -> bool:
    payload = event.get("payload")
    return isinstance(payload, Mapping) and bool(payload.get("trade"))


def _stage(
    now_utc: datetime,
    lifecycle: Mapping[str, Mapping[str, object]],
) -> tuple[str, int | None]:
    local_time = now_utc.astimezone(NEW_YORK).time().replace(tzinfo=None)
    contract = load_contract()
    windows = contract["lifecycle"]
    decision_start, decision_end = map(_clock, windows["decision_checkpoint"])
    entry_start, entry_end = map(_clock, windows["entry_checkpoint"])
    exit_start, exit_end = map(_clock, windows["exit_checkpoint"])

    decision = lifecycle.get("DECISION")
    entry = lifecycle.get("ENTRY")
    exit_event = lifecycle.get("EXIT")
    if exit_event is not None:
        return "SESSION_ALREADY_COMPLETE", None
    if decision is not None and not _decision_trades(decision):
        return "CASH_SESSION_ALREADY_COMPLETE", None
    if decision is None:
        if decision_start <= local_time < decision_end:
            minimum = 7 if local_time >= entry_start else 6
            return "DECISION_ENTRY_CHECKPOINT", minimum
        if local_time >= decision_end:
            return "MISSED_DECISION_NO_BACKFILL", None
        return "WAITING_FOR_DECISION_CHECKPOINT", None
    if entry is None:
        if entry_start <= local_time < entry_end:
            return "ENTRY_CHECKPOINT", 7
        if local_time >= entry_end:
            return "MISSED_ENTRY_NO_BACKFILL", None
        return "WAITING_FOR_ENTRY_CHECKPOINT", None
    if exit_start <= local_time < exit_end:
        return "EXIT_CHECKPOINT", 30
    if local_time >= exit_end:
        return "MISSED_EXIT_NO_BACKFILL", None
    return "WAITING_FOR_EXIT_CHECKPOINT", None


def _attempt_payload(
    outcome: object,
    *,
    now: datetime,
    session: str,
    stage: str,
    minimum_bars: int,
) -> dict[str, object]:
    reasons = getattr(outcome, "reasons", ())
    return {
        "attempted_at_utc": now.isoformat(),
        "session_date": session,
        "stage": stage,
        "minimum_completed_bars": minimum_bars,
        "status": str(getattr(outcome, "status", outcome)),
        "published": getattr(outcome, "published", None),
        "symbol_count": getattr(outcome, "symbol_count", None),
        "completed_bar_utc": getattr(outcome, "completed_bar_utc", None),
        "trimmed_incomplete_bars": getattr(
            outcome, "trimmed_incomplete_bars", None
        ),
        "reasons": (
            [str(value) for value in reasons]
            if isinstance(reasons, (list, tuple))
            else []
        ),
    }


def run_scheduled(
    *,
    now_utc: datetime | None = None,
    status_path: Path = STATUS_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    snapshot_path: Path = SNAPSHOT_PATH,
    model_path: Path = MODEL_PATH,
    model_ready_fn: Callable[[Path], object] | None = None,
    collector_fn: Callable[[datetime, str, int, Path], object] | None = None,
    runner_fn: Callable[[Path, Path], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("V15_V7_NOW_MUST_BE_TIMEZONE_AWARE")
    now = now.astimezone(timezone.utc)
    contract = load_contract()

    local_session = now.astimezone(NEW_YORK).date().isoformat()
    journal = V7EvidenceJournal(journal_path)
    rows = journal.read()
    lifecycle = _session_lifecycle(rows, local_session)
    stage, minimum_bars = _stage(now, lifecycle)
    runner_invoked = False
    collector_invoked = False
    runner_status: str | None = None
    attempt: dict[str, object] | None = None
    previous = _previous_status(status_path)
    missed = {
        "decision": list(previous.get("missed_decision_sessions") or []),
        "entry": list(previous.get("missed_entry_sessions") or []),
        "exit": list(previous.get("missed_exit_sessions") or []),
    }

    model_ready = False
    try:
        (model_ready_fn or load_prepared_model)(model_path)
        model_ready = True
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError):
        model_ready = False

    broad_state = schedule_state(now)
    if broad_state in {"WAITING_FOR_PROSPECTIVE_BOUNDARY", "MARKET_CLOSED"}:
        status = broad_state
    elif not model_ready:
        status = "WAITING_FOR_VERIFIED_MODEL_PREPARATION"
    elif stage.startswith("MISSED_"):
        status = stage
        key = (
            "decision"
            if "DECISION" in stage
            else "entry"
            if "ENTRY" in stage
            else "exit"
        )
        if local_session not in missed[key]:
            missed[key].append(local_session)
    elif minimum_bars is None:
        status = stage
    else:
        if collector_fn is None:
            from ml.v11.intraday_collector import (
                TiingoIntradayClient,
                collect_complete_snapshot,
            )

            outcome = collect_complete_snapshot(
                now_utc=now,
                session_date=local_session,
                client=TiingoIntradayClient(),
                output_path=snapshot_path,
                minimum_bars=minimum_bars,
            )
        else:
            outcome = collector_fn(
                now, local_session, minimum_bars, snapshot_path
            )
        collector_invoked = True
        attempt = _attempt_payload(
            outcome,
            now=now,
            session=local_session,
            stage=stage,
            minimum_bars=minimum_bars,
        )
        if bool(getattr(outcome, "published", False)):
            if runner_fn is None:
                result = run_from_files(
                    snapshot_path=snapshot_path,
                    journal_path=journal_path,
                )
            else:
                result = runner_fn(snapshot_path, journal_path)
            runner_invoked = True
            runner_status = str(result["status"])
            status = runner_status
        else:
            status = str(getattr(outcome, "status", "WAITING_FOR_COMPLETE_SNAPSHOT"))

    rows_after = journal.read()
    summary = {
        "decisions": sum(row["event_type"] == "DECISION" for row in rows_after),
        "entries": sum(row["event_type"] == "ENTRY" for row in rows_after),
        "completed_exits": sum(row["event_type"] == "EXIT" for row in rows_after),
        "journal_events": len(rows_after),
    }
    operational_failures = [
        f"missed_{name}_sessions:{','.join(values)}"
        for name, values in missed.items()
        if values
    ]
    payload: dict[str, object] = {
        "checked_at_utc": now.isoformat(),
        "status": status,
        "schedule_state": broad_state,
        "lifecycle_stage": stage,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "model_prepared_and_verified": model_ready,
        "collector_invoked": collector_invoked,
        "runner_invoked": runner_invoked,
        "runner_status": runner_status,
        "last_collection_attempt": attempt or previous.get("last_collection_attempt"),
        "maximum_collections_per_session": MAX_COLLECTIONS_PER_SESSION,
        "maximum_tiingo_requests_per_session": MAX_REQUESTS_PER_SESSION,
        "missed_decision_sessions": missed["decision"],
        "missed_entry_sessions": missed["entry"],
        "missed_exit_sessions": missed["exit"],
        "current_run_health": not operational_failures,
        "operational_failures": operational_failures,
        **summary,
        "paper_shadow_only": True,
        "automatic_promotion": False,
        "human_review_required": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v13_modified": False,
        "v14_modified": False,
    }
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    print("V15 V7 GUARDED PROSPECTIVE PAPER-SHADOW SCHEDULER")
    print("=" * 80)
    result = run_scheduled()
    print(f"Status: {result['status']}")
    print(f"Schedule state: {result['schedule_state']}")
    print(f"Lifecycle stage: {result['lifecycle_stage']}")
    print(f"Model prepared: {'YES' if result['model_prepared_and_verified'] else 'NO'}")
    print(f"Collector invoked: {'YES' if result['collector_invoked'] else 'NO'}")
    print(f"Runner invoked: {'YES' if result['runner_invoked'] else 'NO'}")
    print(
        "Decisions / entries / exits: "
        f"{result['decisions']} / {result['entries']} / "
        f"{result['completed_exits']}"
    )
    if result["operational_failures"]:
        print("Operational failures:")
        for failure in result["operational_failures"]:
            print(f" - {failure}")
    print("Paper shadow only: YES")
    print("Automatic promotion: NO")
    print("Brokerage orders: OFF")
    print("Existing models modified: NO")


if __name__ == "__main__":
    main()
