"""Read-only status for the future paper-shadow manual approval artifact."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from ml.trading.paper_shadow_manual_approval import APPROVAL_PATH, AUDIT_PATH, verify_approval


def get_manual_approval_status():
    default = {
        "status": "NOT_PRESENT",
        "manual_approval_required": True,
        "manual_approval_present": False,
        "activation_performed": False,
        "paper_signal_export": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }
    try:
        approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        result = verify_approval(approval, audit, now=datetime.now(timezone.utc))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return default
    safe = {**default, **result}
    safe["activation_performed"] = False
    safe["paper_signal_export"] = False
    safe["live_credentials"] = False
    safe["brokerage_orders"] = False
    return safe
