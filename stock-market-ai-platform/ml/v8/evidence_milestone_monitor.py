"""Read-only milestone notifications for genuine V8 forward evidence.

This companion monitor never invokes the V8 runner and never edits the production
journal or status. It writes only its own notification-deduplication state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from ml.v8.holdout_runner import HOLDOUT_START, JOURNAL_PATH

STATE_PATH = Path("data/model/v8/monitor/evidence_milestones.json")
MILESTONES = (
    ("DECISION", "First genuine V8 decision recorded"),
    ("ENTRY", "First V8 next-open entry recorded"),
    ("EXIT", "First V8 five-session cohort completed"),
)


def _read_events():
    if not JOURNAL_PATH.exists():
        return []
    events = []
    for number, raw in enumerate(JOURNAL_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError(f"journal line {number} is not an object")
        events.append(event)
    return events


def _read_state():
    if not STATE_PATH.exists():
        return {"announced": []}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"announced": []}
    except Exception:
        return {"announced": []}


def _write_state(payload):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(STATE_PATH)


def _notify(title, message):
    if sys.platform != "darwin":
        return False
    esc_title = title.replace("\\", "\\\\").replace('"', '\\"')
    esc_message = message.replace("\\", "\\\\").replace('"', '\\"')
    result = subprocess.run(
        ["osascript", "-e", f'display notification "{esc_message}" with title "{esc_title}"'],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def run(now=None):
    now = now or datetime.now(timezone.utc)
    state = _read_state()
    announced = set(state.get("announced") or [])
    events = _read_events()
    new_milestones = []

    if now < HOLDOUT_START.to_pydatetime() and events:
        raise RuntimeError("pre-boundary production evidence detected")

    for event_type, message in MILESTONES:
        if event_type in announced:
            continue
        matches = [event for event in events if event.get("event_type") == event_type]
        if not matches:
            continue
        event = matches[0]
        decision = str(event.get("decision_timestamp_utc") or "")[:10]
        suffix = f" Decision date: {decision}." if decision else ""
        _notify("Data Shepherd: V8 milestone", message + "." + suffix)
        announced.add(event_type)
        new_milestones.append(event_type)

    payload = {
        "checked_at_utc": now.isoformat(),
        "announced": sorted(announced),
        "new_milestones": new_milestones,
        "journal_events": len(events),
        "production_evidence_modified": False,
        "brokerage_orders": False,
    }
    _write_state(payload)
    return payload


def main():
    result = run()
    print("V8 FORWARD-EVIDENCE MILESTONE MONITOR")
    print("=" * 88)
    print(f"Journal events: {result['journal_events']}")
    print(f"New milestones: {', '.join(result['new_milestones']) if result['new_milestones'] else 'NONE'}")
    print(f"Announced: {', '.join(result['announced']) if result['announced'] else 'NONE'}")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
