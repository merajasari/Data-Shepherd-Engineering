"""Duplicate-safe operational alerts for disabled V13 controls.

This process may write only its own alert-deduplication state. It performs no
market request, evidence append, activation, scheduler change, or brokerage
operation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping

from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH
from ml.v13.regime_overlay_monitor import run_monitor as run_health_monitor
from ml.v13.regime_overlay_scheduled_entrypoint import STATUS_PATH


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data/research/v13/fresh_regime_overlay/alerts/status.json"


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
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
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def run(
    *,
    now: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
    state_path: Path = STATE_PATH,
    notifier: Callable[[str, str], bool] = _notify,
    health_runner: Callable[..., Mapping[str, object]] = run_health_monitor,
) -> dict[str, object]:
    resolved_state = state_path.resolve()
    if resolved_state in (journal_path.resolve(), status_path.resolve()):
        raise ValueError("V13_ALERT_STATE_PATH_MUST_BE_ISOLATED")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = _read_state(state_path)
    health = dict(health_runner(journal_path=journal_path, status_path=status_path))
    failures = sorted(set(str(value) for value in health.get("failures") or []))
    signature = (
        hashlib.sha256("\n".join(failures).encode("utf-8")).hexdigest()
        if failures
        else None
    )
    previous_signature = previous.get("active_failure_signature")
    notification = "NONE"
    if signature and signature != previous_signature:
        summary = failures[0]
        if len(failures) > 1:
            summary += f" (+{len(failures) - 1} more)"
        notifier("Data Shepherd: V13 control alert", summary)
        notification = "NEW_FAILURE"
    elif not signature and previous_signature:
        notifier(
            "Data Shepherd: V13 controls recovered",
            "V13 disabled operational controls returned to a healthy state.",
        )
        notification = "RECOVERY"

    payload: dict[str, object] = {
        "checked_at_utc": now.isoformat(),
        "status": "HEALTHY_DISABLED" if not failures else "ALERT",
        "active_failure_signature": signature,
        "failures": failures,
        "operational_notification": notification,
        "journal_events": health.get("journal_events", 0),
        "activation": health.get("activation"),
        "collection_expected": health.get("collection_expected") is True,
        "scheduler_installation_expected": False,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    _atomic_write(state_path, payload)
    return payload


def main() -> None:
    print("V13 DISABLED OPERATIONAL ALERTS")
    print("=" * 80)
    result = run()
    print(f"Status: {result['status']}")
    print(f"Activation: {result['activation']}")
    print(f"Operational notification: {result['operational_notification']}")
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f" - {failure}")
    print("Scheduler installation expected: NO")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
