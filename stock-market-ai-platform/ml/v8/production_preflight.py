"""Read-only production preflight for the frozen V8 forward holdout.

This command validates the installed macOS LaunchAgent and the immutable V8
contract without invoking the EOD guard or holdout runner. It never writes
journal/status evidence and never places brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from ml.v8.holdout_runner import (
    EXPECTED_SHA,
    HOLDOUT_START,
    JOURNAL_PATH,
    STATUS_PATH,
    _verify_freeze,
)

LABEL = "com.datashepherd.v8paper"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
EXPECTED_INTERVAL_SECONDS = 300
EXPECTED_MODULE = "ml.v8.scheduled_entrypoint"
FORBIDDEN_DIRECT_MODULE = "ml.v8.holdout_runner"


def _result(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": str(detail)}


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
                events.append(json.loads(text))
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: {exc}")
    return events, errors


def _event_key(event):
    return (
        event.get("event_type"),
        event.get("decision_timestamp_utc"),
        event.get("cohort_offset"),
    )


def run_preflight():
    checks = []

    try:
        _verify_freeze()
        checks.append(_result("frozen_contract", True, EXPECTED_SHA))
    except Exception as exc:
        checks.append(_result("frozen_contract", False, f"{type(exc).__name__}: {exc}"))

    checks.append(_result("platform", sys.platform == "darwin", sys.platform))
    checks.append(_result("launchagent_plist_exists", PLIST_PATH.exists(), PLIST_PATH))

    plist = {}
    if PLIST_PATH.exists():
        try:
            with PLIST_PATH.open("rb") as handle:
                plist = plistlib.load(handle)
            checks.append(_result("launchagent_plist_parse", True, "valid plist"))
        except Exception as exc:
            checks.append(_result("launchagent_plist_parse", False, f"{type(exc).__name__}: {exc}"))

    if plist:
        args = [str(value) for value in plist.get("ProgramArguments", [])]
        command = " ".join(args)
        checks.extend([
            _result("launchagent_label", plist.get("Label") == LABEL, plist.get("Label")),
            _result(
                "launchagent_interval",
                plist.get("StartInterval") == EXPECTED_INTERVAL_SECONDS,
                plist.get("StartInterval"),
            ),
            _result("launchagent_run_at_load", plist.get("RunAtLoad") is True, plist.get("RunAtLoad")),
            _result("scheduler_uses_monitored_entrypoint", EXPECTED_MODULE in command, command),
            _result(
                "scheduler_no_direct_runner",
                FORBIDDEN_DIRECT_MODULE not in command,
                "direct holdout invocation absent" if FORBIDDEN_DIRECT_MODULE not in command else command,
            ),
        ])

    if sys.platform == "darwin":
        target = f"gui/{os.getuid()}/{LABEL}"
        proc = subprocess.run(
            ["launchctl", "print", target],
            text=True,
            capture_output=True,
            check=False,
        )
        detail = "loaded" if proc.returncode == 0 else (proc.stderr.strip() or "not loaded")
        checks.append(_result("launchagent_loaded", proc.returncode == 0, detail))

    events, journal_errors = _read_journal()
    now = datetime.now(timezone.utc)
    pre_boundary = now < HOLDOUT_START.to_pydatetime()
    checks.append(_result("journal_json_valid", not journal_errors, journal_errors or "valid/absent"))

    keys = [_event_key(event) for event in events]
    duplicate_count = len(keys) - len(set(keys))
    checks.append(_result("journal_duplicate_safe", duplicate_count == 0, f"duplicates={duplicate_count}"))

    if pre_boundary:
        checks.append(_result(
            "pre_boundary_journal_empty",
            len(events) == 0,
            f"events={len(events)}; boundary={HOLDOUT_START.isoformat()}",
        ))
    else:
        checks.append(_result(
            "holdout_boundary_reached",
            True,
            f"events={len(events)}; boundary={HOLDOUT_START.isoformat()}",
        ))

    checks.append(_result(
        "status_path_not_required",
        True,
        f"{STATUS_PATH} may be absent before the first eligible production run",
    ))
    checks.append(_result("brokerage_orders", True, "OFF; preflight invokes no trading interface"))
    checks.append(_result("evidence_writes", True, "NONE; read-only preflight"))

    failed = [item for item in checks if not item["passed"]]
    return {
        "status": "READY" if not failed else "NOT_READY",
        "checked_at_utc": now.isoformat(),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "frozen_sha256": EXPECTED_SHA,
        "checks": checks,
        "failed_checks": [item["check"] for item in failed],
        "journal_events": len(events),
        "brokerage_orders": False,
        "production_evidence_modified": False,
    }


def main():
    result = run_preflight()
    print("V8 PRODUCTION HOLDOUT PREFLIGHT")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Boundary: {result['holdout_start_utc']}")
    print(f"Frozen SHA: {result['frozen_sha256']}")
    for item in result["checks"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"[{mark}] {item['check']}: {item['detail']}")
    print(f"Journal events: {result['journal_events']}")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
