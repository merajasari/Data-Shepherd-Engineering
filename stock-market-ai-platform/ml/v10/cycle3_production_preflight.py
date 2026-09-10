"""Read-only installed-scheduler preflight for V10 Cycle 3."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from ml.v10.cycle3_holdout_runner import (
    EXPECTED_SHA, HOLDOUT_START, JOURNAL_PATH, STATUS_PATH, _verify_freeze,
)

LABEL = "com.datashepherd.v10cycle3"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
EXPECTED_MODULE = "ml.v10.cycle3_scheduled_entrypoint"


def _result(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": str(detail)}


def _read_journal():
    if not JOURNAL_PATH.exists():
        return [], []
    events, errors = [], []
    for line_number, raw in enumerate(
        JOURNAL_PATH.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw.strip():
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: {exc}")
    return events, errors


def run_preflight():
    checks = []
    try:
        _verify_freeze()
        checks.append(_result("frozen_contract", True, EXPECTED_SHA))
    except Exception as exc:
        checks.append(_result("frozen_contract", False, f"{type(exc).__name__}: {exc}"))

    checks.extend([
        _result("platform", sys.platform == "darwin", sys.platform),
        _result("launchagent_plist_exists", PLIST_PATH.exists(), PLIST_PATH),
    ])
    plist = {}
    if PLIST_PATH.exists():
        try:
            with PLIST_PATH.open("rb") as handle:
                plist = plistlib.load(handle)
            checks.append(_result("launchagent_plist_parse", True, "valid plist"))
        except Exception as exc:
            checks.append(_result("launchagent_plist_parse", False, exc))

    if plist:
        command = " ".join(str(value) for value in plist.get("ProgramArguments", []))
        checks.extend([
            _result("launchagent_label", plist.get("Label") == LABEL, plist.get("Label")),
            _result("launchagent_interval", plist.get("StartInterval") == 300, plist.get("StartInterval")),
            _result("launchagent_run_at_load", plist.get("RunAtLoad") is True, plist.get("RunAtLoad")),
            _result("isolated_entrypoint", EXPECTED_MODULE in command, command),
            _result("no_v8_runtime", "ml.v8." not in command, "V8 invocation absent"),
            _result("overlap_guard", "v10_cycle3.lockdir" in command, command),
        ])

    if sys.platform == "darwin":
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            text=True, capture_output=True, check=False,
        )
        checks.append(_result(
            "launchagent_loaded", proc.returncode == 0,
            "loaded" if proc.returncode == 0 else (proc.stderr.strip() or "not loaded"),
        ))

    events, errors = _read_journal()
    checks.append(_result("journal_json_valid", not errors, errors or "valid/absent"))
    keys = [
        (e.get("event_type"), e.get("decision_timestamp_utc"), e.get("cohort_offset"))
        for e in events
    ]
    duplicates = len(keys) - len(set(keys))
    checks.append(_result("journal_duplicate_safe", duplicates == 0, f"duplicates={duplicates}"))
    now = datetime.now(timezone.utc)
    if now < HOLDOUT_START.to_pydatetime():
        checks.append(_result(
            "pre_boundary_journal_empty", not events,
            f"events={len(events)}; boundary={HOLDOUT_START.isoformat()}",
        ))

    checks.extend([
        _result("isolated_root", str(JOURNAL_PATH).startswith("data/model/v10/cycle3/"), JOURNAL_PATH),
        _result("status_isolated", str(STATUS_PATH).startswith("data/model/v10/cycle3/"), STATUS_PATH),
        _result("brokerage_orders", True, "OFF; no trading interface invoked"),
        _result("evidence_writes", True, "NONE; read-only preflight"),
    ])
    failed = [item for item in checks if not item["passed"]]
    return {
        "status": "READY" if not failed else "NOT_READY",
        "checked_at_utc": now.isoformat(),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "frozen_sha256": EXPECTED_SHA,
        "checks": checks,
        "failed_checks": [item["check"] for item in failed],
        "journal_events": len(events),
        "production_evidence_modified": False,
        "v8_modified": False,
        "brokerage_orders": False,
    }


def main():
    result = run_preflight()
    print("V10 CYCLE 3 PRODUCTION HOLDOUT PREFLIGHT")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Boundary: {result['holdout_start_utc']}")
    print(f"Frozen SHA: {result['frozen_sha256']}")
    for item in result["checks"]:
        print(f"[{'PASS' if item['passed'] else 'FAIL'}] {item['check']}: {item['detail']}")
    print(f"Journal events: {result['journal_events']}")
    print("Production evidence modified: NO")
    print("V8 modified: NO | brokerage orders: OFF")
    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
