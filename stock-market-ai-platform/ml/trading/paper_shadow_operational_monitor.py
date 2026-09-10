"""Read-only operational monitor for the isolated paper-shadow scheduler.

The monitor validates the preregistered V8 bridge, scheduler contract and
persistent paper account. It writes only its own deduplicated monitor state.
It never exports signals, reads holdout outcomes, loads credentials or calls a
brokerage interface.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.trading.journal import JournalCorrupt, OrderJournal
from ml.trading.paper_shadow_signal_bridge import CONTRACT_PATH, contract_sha256, load_contract
from ml.trading.paper_shadow_state import ShadowStateRejected, ShadowStateStore

LABEL = "com.datashepherd.papershadow"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SHADOW_ROOT = Path("data/trading/paper_shadow")
STATE_PATH = SHADOW_ROOT / "account_state.json"
JOURNAL_PATH = SHADOW_ROOT / "orders.jsonl"
MONITOR_STATUS_PATH = SHADOW_ROOT / "monitor/status.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _account_health(state_path: Path, journal_path: Path) -> tuple[str, str | None, int]:
    if not state_path.exists() and not journal_path.exists():
        return "EMPTY_READY", None, 0
    if state_path.exists() != journal_path.exists():
        return "FAIL_CLOSED", "paper-shadow account state and journal are incomplete", 0
    try:
        state = ShadowStateStore(state_path).read()
        events = OrderJournal(journal_path).read()
        if state is None:
            raise ShadowStateRejected("paper-shadow account state is absent")
        journal_filled = {
            str(event["intent_id"]) for event in events if event.get("state") == "FILLED"
        }
        account_filled = {
            str(order["intent_id"])
            for order in (state.get("orders") or {}).values()
            if order.get("status") == "FILLED"
        }
        if journal_filled != account_filled:
            return "FAIL_CLOSED", "paper-shadow journal and account disagree", len(events)
        if state.get("mode") != "PAPER_ONLY" or state.get("brokerage_orders") is not False:
            return "FAIL_CLOSED", "paper-shadow account violates paper-only authority", len(events)
        return "HEALTHY", None, len(events)
    except (ShadowStateRejected, JournalCorrupt, OSError, KeyError, ValueError) as exc:
        return "FAIL_CLOSED", f"{type(exc).__name__}: paper-shadow account requires review", 0


def _plist_safe(plist_path: Path) -> tuple[bool, str]:
    if not plist_path.exists():
        return False, f"missing {plist_path}"
    try:
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
    except Exception as exc:
        return False, f"invalid plist: {type(exc).__name__}: {exc}"
    command = " ".join(str(value) for value in plist.get("ProgramArguments", []))
    checks = (
        plist.get("Label") == LABEL,
        plist.get("StartInterval") == 300,
        plist.get("RunAtLoad") is True,
        "ml.trading.paper_shadow_scheduled_entrypoint" in command,
        "paper_shadow_signal_bridge" not in command,
        "paper_shadow_runner" not in command,
        "holdout_runner" not in command,
    )
    return all(checks), command


def _launchagent_loaded() -> tuple[bool, str]:
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


def _notify(title: str, message: str) -> bool:
    if sys.platform != "darwin":
        return False
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    proc = subprocess.run(
        ["osascript", "-e", f'display notification "{escaped_message}" with title "{escaped_title}"'],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def run_monitor(
    *,
    now: datetime | None = None,
    shadow_root: Path = SHADOW_ROOT,
    plist_path: Path = PLIST_PATH,
    status_path: Path = MONITOR_STATUS_PATH,
    check_launchagent: bool = True,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failures: list[str] = []

    try:
        contract = load_contract()
    except Exception as exc:
        contract = {}
        failures.append(f"bridge_contract: {type(exc).__name__}: {exc}")

    boundary_text = str(contract.get("activation_not_before_utc") or "2026-09-01T00:00:00+00:00")
    try:
        boundary = datetime.fromisoformat(boundary_text).astimezone(timezone.utc)
    except ValueError:
        boundary = datetime.max.replace(tzinfo=timezone.utc)
        failures.append("bridge_boundary: invalid activation timestamp")

    if contract.get("source_frozen_sha256") != "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41":
        failures.append("frozen_identity: V8 SHA mismatch")
    if contract.get("activation_mode") != "MANUAL_SEPARATE_APPROVAL":
        failures.append("activation_mode: manual separate approval is not enforced")
    if contract.get("brokerage_orders") is not False:
        failures.append("brokerage_authority: bridge grants order authority")
    if contract.get("holdout_outcomes_read") is not False:
        failures.append("holdout_boundary: outcome reads are permitted")
    if contract.get("production_holdout_journal_write") is not False:
        failures.append("holdout_boundary: production journal writes are permitted")
    if contract.get("status") not in {"PREREGISTERED_DISABLED", "ACTIVE"}:
        failures.append(f"bridge_status: unexpected {contract.get('status')}")

    plist_ok, plist_detail = _plist_safe(plist_path)
    if not plist_ok:
        failures.append(f"scheduler_contract: {plist_detail}")
    if check_launchagent:
        loaded, loaded_detail = _launchagent_loaded()
        if not loaded:
            failures.append(f"scheduler_unloaded: {loaded_detail}")

    account_status, account_alert, journal_events = _account_health(
        Path(shadow_root) / "account_state.json",
        Path(shadow_root) / "orders.jsonl",
    )
    if account_alert:
        failures.append(f"paper_account: {account_alert}")

    if now < boundary:
        execution_state = "WAITING_FOR_BOUNDARY"
    elif contract.get("status") != "ACTIVE":
        execution_state = "WAITING_FOR_MANUAL_ACTIVATION"
    else:
        execution_state = "ACTIVATED_PAPER_ONLY"

    previous = _read_json(status_path)
    previous_signature = previous.get("active_signature") if previous else None
    signature_source = "\n".join(sorted(failures))
    signature = hashlib.sha256(signature_source.encode()).hexdigest() if failures else None
    notification = "NONE"
    if signature and signature != previous_signature:
        message = failures[0] + (f" (+{len(failures)-1} more)" if len(failures) > 1 else "")
        _notify("Data Shepherd: paper-shadow alert", message)
        notification = "NEW_FAILURE"
    elif not signature and previous_signature:
        _notify("Data Shepherd: paper-shadow recovered", "All paper-shadow checks are healthy.")
        notification = "RECOVERY"

    payload = {
        "checked_at_utc": now.isoformat(),
        "status": "HEALTHY" if not failures else "ALERT",
        "execution_state": execution_state,
        "active_signature": signature,
        "failures": failures,
        "notification": notification,
        "bridge_contract_sha256": contract_sha256(),
        "bridge_status": contract.get("status"),
        "activation_not_before_utc": boundary_text,
        "manual_activation_required": True,
        "frozen_v8_sha256": contract.get("source_frozen_sha256"),
        "paper_account_status": account_status,
        "journal_events": journal_events,
        "signal_exports": 0,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }
    _atomic_write_json(status_path, payload)
    return payload


def main() -> dict[str, Any]:
    result = run_monitor()
    print("PAPER-SHADOW OPERATIONAL MONITOR")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Execution state: {result['execution_state']}")
    print(f"Paper account: {result['paper_account_status']}")
    print(f"Notification: {result['notification']}")
    print(f"Journal events: {result['journal_events']}")
    if result["failures"]:
        print("Failures:")
        for item in result["failures"]:
            print(f"  - {item}")
    else:
        print("All monitored paper-shadow checks are healthy.")
    print("Signal exports: 0")
    print("Holdout outcomes read: NO")
    print("Production holdout evidence modified: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    return result


if __name__ == "__main__":
    outcome = main()
    raise SystemExit(0 if outcome["status"] == "HEALTHY" else 2)
