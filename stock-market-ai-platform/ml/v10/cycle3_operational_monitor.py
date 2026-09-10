"""Read-only operational alert monitor for frozen V10 Cycle 3."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from ml.v10.cycle3_holdout_runner import (
    EXPECTED_SHA,
    HOLDOUT_START,
    JOURNAL_PATH,
    STATUS_PATH,
    _verify_freeze,
)

LABEL = "com.datashepherd.v10cycle3"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
MONITOR_ROOT = Path("data/model/v10/cycle3/monitor")
ALERT_STATE_PATH = MONITOR_ROOT / "alert_state.json"
FIRST_EVIDENCE_DEADLINE = datetime(2027, 1, 7, 3, 0, tzinfo=timezone.utc)


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
    events, errors = [], []
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
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
    proc = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        text=True, capture_output=True, check=False,
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
        "ml.v10.cycle3_scheduled_entrypoint" in command,
        "ml.v8." not in command,
    ]
    return all(checks), command


def _notify(title, message):
    if sys.platform != "darwin":
        return False
    title = title.replace("\\", "\\\\").replace('"', '\\"')
    message = message.replace("\\", "\\\\").replace('"', '\\"')
    proc = subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
        text=True, capture_output=True, check=False,
    )
    return proc.returncode == 0


def run_monitor(runner_error=None, now=None):
    now = now or datetime.now(timezone.utc)
    failures = []
    if runner_error:
        failures.append(f"runner_failure: {runner_error}")

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
    duplicates = len(keys) - len(set(keys))
    if duplicates:
        failures.append(f"journal_duplicates: {duplicates}")

    boundary = HOLDOUT_START.to_pydatetime()
    if now < boundary and events:
        failures.append(f"pre_boundary_evidence: {len(events)} events")
    if now >= FIRST_EVIDENCE_DEADLINE and not events:
        failures.append(
            "first_evidence_missing: no eligible event after "
            f"{FIRST_EVIDENCE_DEADLINE.isoformat()}"
        )

    status, status_error = _read_json(STATUS_PATH)
    if status_error:
        failures.append(f"status_invalid: {status_error}")
    elif isinstance(status, dict):
        value = str(status.get("status", "")).upper()
        if value in {"ERROR", "FAILED", "NOT_READY"}:
            failures.append(f"runner_status: {value}")
        if status.get("frozen_sha256") not in {None, EXPECTED_SHA}:
            failures.append("runner_status_sha_mismatch")

    signature_source = "\n".join(sorted(failures))
    signature = (
        hashlib.sha256(signature_source.encode("utf-8")).hexdigest()
        if failures else None
    )
    previous, _ = _read_json(ALERT_STATE_PATH)
    previous_signature = (
        previous.get("active_signature") if isinstance(previous, dict) else None
    )

    notification = "NONE"
    if signature and signature != previous_signature:
        message = failures[0] + (
            f" (+{len(failures) - 1} more)" if len(failures) > 1 else ""
        )
        _notify("Data Shepherd: V10 Cycle 3 alert", message)
        notification = "NEW_FAILURE"
    elif not signature and previous_signature:
        _notify(
            "Data Shepherd: V10 Cycle 3 recovered",
            "All monitored Cycle 3 holdout checks are healthy.",
        )
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
        "v8_modified": False,
        "brokerage_orders": False,
    }
    _atomic_write_json(ALERT_STATE_PATH, state)
    return state


def main():
    result = run_monitor()
    print("V10 CYCLE 3 OPERATIONAL MONITOR")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Notification: {result['notification']}")
    print(f"Journal events: {result['journal_events']}")
    if result["failures"]:
        print("Failures:")
        for item in result["failures"]:
            print(f"  - {item}")
    else:
        print("All monitored Cycle 3 holdout checks are healthy.")
    print("Production evidence modified: NO")
    print("V8 modified: NO | brokerage orders: OFF")
    return result


if __name__ == "__main__":
    outcome = main()
    raise SystemExit(0 if outcome["status"] == "HEALTHY" else 2)
