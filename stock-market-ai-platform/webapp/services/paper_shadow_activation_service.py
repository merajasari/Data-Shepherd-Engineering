"""Read-only presentation adapter for the paper-shadow day-zero audit."""
from __future__ import annotations
import json
from pathlib import Path

PATH = Path("data/trading/readiness/paper_shadow_activation_audit.json")


def get_paper_shadow_activation_status():
    default = {
        "status": "PREREGISTERED_WAITING_FOR_AUDIT",
        "activation_not_before_utc": "2026-09-01T00:00:00+00:00",
        "contract_sha256": "81e211909d3bb2dd6964fae959c1e81677a7861fb3402a00f813abcf16739e94",
        "frozen_v8_sha256": "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41",
        "gates": [],
        "gates_passed": 0,
        "gates_total": 14,
        "manual_approval_required": True,
        "manual_approval_present": False,
        "activation_performed": False,
        "paper_signal_export": False,
        "holdout_outcomes_read": False,
        "production_holdout_evidence_modified": False,
        "live_credentials": False,
        "brokerage_orders": False,
    }
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    if not isinstance(payload, dict):
        return default
    safe = {**default, **payload}
    for key in (
        "activation_performed", "paper_signal_export", "holdout_outcomes_read",
        "production_holdout_evidence_modified", "live_credentials", "brokerage_orders",
        "manual_approval_present",
    ):
        safe[key] = False
    safe["manual_approval_required"] = True
    return safe
