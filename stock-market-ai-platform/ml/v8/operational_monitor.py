"""Operational alert monitor for the frozen V8 forward holdout.

The monitor reads operational state and may write only its own deduplication
state. It never invokes model training, mutates holdout evidence, or places
brokerage orders. New failures and recoveries are announced through macOS
Notification Center.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pandas as pd

from ml.v8.holdout_runner import (
    EXPECTED_SHA,
    HOLDOUT_START,
    JOURNAL_PATH,
    STATUS_PATH,
    _verify_freeze,
)

LABEL = "com.datashepherd.v8paper"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
MONITOR_ROOT = Path("data/model/v8/monitor")
ALERT_STATE_PATH = MONITOR_ROOT / "alert_state.json"
FIRST_EVIDENCE_DEADLINE = pd.Timestamp("2026-09-03T03:00:00Z")


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _read_json(path):
    if not path.exists():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _read_journal():
    if not JOURNAL_PATH.exists():
        return [], []
    events = []
    errors = []
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
                if not isinstance(event, dict):
                    raise ValueError("event is not a JSON object")
                events.append(event)
            except Exception as exc:
                errors.append(f"line {line_number}: {type(exc).__name__}: {exc}")
    return events, errors


def _event_key(event):
    return (
        event.get("event_type"),
        event.get("decision_timestamp_utc"),
        event.get("cohort_offset"),
    )


def _launchagent_loaded():
    if sys.platform != "darwin":
        return False, f"unsupported platform: {sys.platform}"
    target = f"gui/{os.getuid()}/{LABEL}"
    proc = subprocess.run(
        ["launchctl", "print", target],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0, proc.stderr.strip() or "loaded"


def _plist_safe():
    if not PLIST_PATH.exists():
        return False, f"missing {PLIST_PATH}"
    try:
        with PLIST_PATH.open("rb") as handle:
            plist = plistlib.load(handle)
    except Exception as exc:
        return False, f"invalid plist: {type(exc).__name__}: {exc}"
    command = " ".join(str(value) for value in plist.get("ProgramArguments", []))
    checks = [
        plist.get("Label") == LABEL,
        plist.get("StartInterval") == 300,
        plist.get("RunAtLoad") is True,
        "ml.v8.scheduled_entrypoint" in command,
        "ml.v8.holdout_runner" not in command,
    ]
    return all(checks), command


def _notify(title, message):
    if sys.platform != "darwin":
        return False
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    proc = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def run_monitor(orchestrator_error=None, now=None):
    now = now or datetime.now(timezone.utc)
    failures = []

    if orchestrator_error:
        failures.append(f"orchestrator_failure: {orchestrator_error}")

    try:
        _verify_freeze()
    except Exception as exc:
        failures.append(f"frozen_contract: {type(exc).__name__}: {exc}")

    plist_ok, plist_detail = _plist_safe()
    if not plist_ok:
        failures.append(f"scheduler_contract: {plist_detail}")

    loaded, loaded_detail = _launchagent_loaded()
    if not loaded:
        failures.append(f"scheduler_unloaded: {loaded_detail}")

    events, journal_errors = _read_journal()
    failures.extend(f"journal_invalid: {item}" for item in journal_errors)

    keys = [_event_key(event) for event in events]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        failures.append(f"journal_duplicates: {duplicate_count}")

    if now < HOLDOUT_START.to_pydatetime() and events:
        failures.append(f"pre_boundary_evidence: {len(events)} events")

    if now >= FIRST_EVIDENCE_DEADLINE.to_pydatetime() and not events:
        failures.append(
            "first_evidence_missing: no eligible event after "
            f"{FIRST_EVIDENCE_DEADLINE.isoformat()}"
        )

    status_payload, status_error = _read_json(STATUS_PATH)
    if status_error:
        failures.append(f"status_invalid: {status_error}")
    elif isinstance(status_payload, dict):
        status_value = str(status_payload.get("status", "")).upper()
        if status_value in {"ERROR", "FAILED", "NOT_READY"}:
            failures.append(f"runner_status: {status_value}")

    signature_source = "\n".join(sorted(failures))
    signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest() if failures else None
    previous, _ = _read_json(ALERT_STATE_PATH)
    previous_signature = previous.get("active_signature") if isinstance(previous, dict) else None

    notification = "NONE"
    if signature and signature != previous_signature:
        message = failures[0]
        if len(failures) > 1:
            message += f" (+{len(failures) - 1} more)"
        _notify("Data Shepherd: V8 alert", message)
        notification = "NEW_FAILURE"
    elif not signature and previous_signature:
        _notify("Data Shepherd: V8 recovered", "All monitored V8 production checks are healthy.")
        notification = "RECOVERY"

    state = {
        "checked_at_utc": now.isoformat(),
        "status": "HEALTHY" if not failures else "ALERT",
        "active_signature": signature,
        "failures": failures,
        "notification": notification,
        "frozen_sha256": EXPECTED_SHA,
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "first_evidence_deadline_utc": FIRST_EVIDENCE_DEADLINE.isoformat(),
        "journal_events": len(events),
        "production_evidence_modified": False,
        "brokerage_orders": False,
    }
    _atomic_write_json(ALERT_STATE_PATH, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--orchestrator-error", default=None)
    args = parser.parse_args(argv)
    result = run_monitor(orchestrator_error=args.orchestrator_error)

    print("V8 OPERATIONAL MONITOR")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Notification: {result['notification']}")
    print(f"Journal events: {result['journal_events']}")
    if result["failures"]:
        print("Failures:")
        for item in result["failures"]:
            print(f"  - {item}")
    else:
        print("All monitored production checks are healthy.")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    return result


if __name__ == "__main__":
    outcome = main()
    raise SystemExit(0 if outcome["status"] == "HEALTHY" else 2)
