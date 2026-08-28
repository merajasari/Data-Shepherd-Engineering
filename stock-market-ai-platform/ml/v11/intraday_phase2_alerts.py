"""Read-only milestone and operational alerts for V11 Phase 2.

This monitor reads the tamper-evident Phase 2 journal and launch status. It may
write only its own notification-deduplication state. It never collects market
data, writes research evidence, accesses V8/V10 production, or places orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Mapping

from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_phase2_monitor import run_monitor as run_health_monitor

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = (
    ROOT / "data/research/v11/intraday/phase2/alerts/status.json"
)
SCHEDULER_LABEL = "com.datashepherd.v11phase2"
MILESTONES = (
    ("DECISION", "First genuine V11 Phase 2 decision recorded"),
    ("ENTRY", "First V11 Phase 2 paper entry recorded"),
    ("SESSION_OBSERVATION", "First V11 Phase 2 session completed"),
)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"announced": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"announced": []}
    return payload if isinstance(payload, dict) else {"announced": []}


def _notify(title: str, message: str) -> bool:
    if sys.platform != "darwin":
        return False
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    result = subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{escaped_message}" with title "{escaped_title}"',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _scheduler_health() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return True, "launchd check not applicable"
    target = f"gui/{os.getuid()}/{SCHEDULER_LABEL}"
    result = subprocess.run(
        ["launchctl", "print", target],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False, "LaunchAgent is not registered"
    match = re.search(r"last exit code\s*=\s*(-?\d+)", result.stdout)
    if match and int(match.group(1)) != 0:
        return False, f"LaunchAgent last exit code is {match.group(1)}"
    return True, "registered; last exit code is healthy"


def run(
    *,
    now: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    state_path: Path = STATE_PATH,
    notifier: Callable[[str, str], bool] = _notify,
    scheduler_check: Callable[[], tuple[bool, str]] = _scheduler_health,
    health_runner: Callable[..., Mapping[str, object]] = run_health_monitor,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    events = Phase2EvidenceJournal(journal_path).read()
    state = _read_state(state_path)
    announced = set(state.get("announced") or [])
    notifications: list[str] = []

    for event_type, message in MILESTONES:
        if event_type in announced:
            continue
        event = next(
            (row for row in events if row.get("event_type") == event_type),
            None,
        )
        if event is None:
            continue
        session_date = str(event.get("session_date") or "")
        suffix = f" Session: {session_date}." if session_date else ""
        notifier("Data Shepherd: V11 milestone", message + "." + suffix)
        announced.add(event_type)
        notifications.append(event_type)

    health = dict(
        health_runner(journal_path=journal_path)
    )
    failures = [str(item) for item in health.get("failures") or []]
    scheduler_ok, scheduler_detail = scheduler_check()
    if not scheduler_ok:
        failures.append(f"SCHEDULER_FAILURE:{scheduler_detail}")
    operational = str(health.get("operational_status") or "").upper()
    if any(token in operational for token in ("ERROR", "FAILED", "ALERT")):
        failures.append(f"SCHEDULED_STATUS:{operational}")

    failures = sorted(set(failures))
    signature = (
        hashlib.sha256("\n".join(failures).encode("utf-8")).hexdigest()
        if failures
        else None
    )
    previous_signature = state.get("active_failure_signature")
    operational_notification = "NONE"
    if signature and signature != previous_signature:
        summary = failures[0]
        if len(failures) > 1:
            summary += f" (+{len(failures) - 1} more)"
        notifier("Data Shepherd: V11 alert", summary)
        operational_notification = "NEW_FAILURE"
    elif not signature and previous_signature:
        notifier(
            "Data Shepherd: V11 recovered",
            "V11 Phase 2 scheduler and monitored paper-confirmation checks recovered.",
        )
        operational_notification = "RECOVERY"

    payload = {
        "checked_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": "HEALTHY" if not failures else "ALERT",
        "announced": sorted(announced),
        "new_milestones": notifications,
        "active_failure_signature": signature,
        "failures": failures,
        "operational_notification": operational_notification,
        "scheduler_detail": scheduler_detail,
        "journal_events": len(events),
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    _atomic_write_json(state_path, payload)
    return payload


def main() -> None:
    result = run()
    print("V11 PHASE 2 MILESTONE + OPERATIONAL ALERTS")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Journal events: {result['journal_events']}")
    print(
        "New milestones: "
        + (
            ", ".join(result["new_milestones"])
            if result["new_milestones"]
            else "NONE"
        )
    )
    print(f"Operational notification: {result['operational_notification']}")
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f" - {failure}")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
