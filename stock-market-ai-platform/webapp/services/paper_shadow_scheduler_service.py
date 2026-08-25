"""Read-only presentation service for paper-shadow scheduler health."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATUS_PATH = Path("data/trading/paper_shadow/monitor/status.json")


def _default() -> dict[str, Any]:
    return {
        "status": "NOT_INSTALLED",
        "execution_state": "MONITOR_NOT_STARTED",
        "checked_at_utc": None,
        "bridge_status": "PREREGISTERED_DISABLED",
        "manual_activation_required": True,
        "paper_account_status": "EMPTY_READY",
        "journal_events": 0,
        "signal_exports": 0,
        "notification": "NONE",
        "failures": [],
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }


def get_paper_shadow_scheduler_status() -> dict[str, Any]:
    try:
        payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default()
    if not isinstance(payload, dict):
        return _default()
    safe = {**_default(), **payload}
    safe["manual_activation_required"] = True
    safe["signal_exports"] = int(safe.get("signal_exports") or 0)
    safe["holdout_outcomes_read"] = False
    safe["production_holdout_evidence_modified"] = False
    safe["live_credentials"] = False
    safe["brokerage_orders"] = False
    return safe
