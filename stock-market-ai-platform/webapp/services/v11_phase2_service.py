"""Lightweight read-only dashboard service for V11 Phase 2."""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    EvidenceJournalCorrupt,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_phase2_monitor import run_monitor
from ml.v11.intraday_phase2_preflight import EXPECTED_CONTRACT_SHA256
from ml.v11.intraday_phase2_scheduled_entrypoint import (
    MAX_COLLECTIONS_PER_SESSION,
    MAX_REQUESTS_PER_SESSION,
    STATUS_PATH,
)

BOUNDARY = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
_CACHE_TTL_SECONDS = 10.0
_cache: dict[str, object] = {
    "signature": None,
    "expires_at": 0.0,
    "payload": None,
}


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _compound(rows: list[dict[str, object]], field: str) -> float | None:
    values = [row.get(field) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return math.prod(1.0 + float(value) for value in values) - 1.0


def get_v11_phase2_dashboard() -> dict[str, object]:
    signature = (_signature(STATUS_PATH), _signature(DEFAULT_JOURNAL_PATH))
    now_mono = time.monotonic()
    if (
        _cache["payload"] is not None
        and _cache["signature"] == signature
        and now_mono < float(_cache["expires_at"])
    ):
        return dict(_cache["payload"])

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    operational = _read_json(STATUS_PATH)
    journal_error = None
    try:
        events = Phase2EvidenceJournal(DEFAULT_JOURNAL_PATH).read()
    except EvidenceJournalCorrupt as exc:
        events = []
        journal_error = str(exc)

    decisions = [row for row in events if row.get("event_type") == "DECISION"]
    entries = [row for row in events if row.get("event_type") == "ENTRY"]
    exits = [row for row in events if row.get("event_type") == "EXIT"]
    observations = [
        row for row in events
        if row.get("event_type") == "SESSION_OBSERVATION"
    ]
    sessions = sorted({str(row.get("session_date")) for row in observations})
    latest = observations[-1] if observations else {}
    monitor = run_monitor()
    now = datetime.now(timezone.utc)
    state = (
        "JOURNAL_ERROR" if journal_error else
        "WAITING_FOR_BOUNDARY" if now < BOUNDARY else
        str(operational.get("status") or "ACTIVE_WAITING_FOR_SESSION")
    )
    evidence = (
        "NO_FRESH_SESSIONS" if not observations else
        "PRELIMINARY_EVIDENCE" if len(observations) < 20 else
        "EVIDENCE_ACCUMULATING" if len(observations) < 60 else
        "CONFIRMATION_SAMPLE_MATURE"
    )
    ready = (
        observed_sha == EXPECTED_CONTRACT_SHA256
        and journal_error is None
        and monitor["status"] == "HEALTHY_PAPER_CONFIRMATION"
    )
    display_status = (
        "ALERT" if not ready else
        "AWAITING_FRESH_SESSION" if not observations else
        "FRESH_EVIDENCE_ACTIVE"
    )
    strategy_total = _compound(observations, "strategy_net_return")
    spy_total = _compound(observations, "spy_return")
    payload: dict[str, object] = {
        "status": "READY" if ready else "ALERT",
        "control_status": "READY" if ready else "ALERT",
        "display_status": display_status,
        "status_scope": "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "state": state,
        "evidence_status": evidence,
        "classification": "PREREGISTERED_FRESH_PAPER_CONFIRMATION",
        "configuration": "MOMENTUM_BALANCED_6",
        "contract_sha256": observed_sha,
        "contract_sha_verified": observed_sha == EXPECTED_CONTRACT_SHA256,
        "fresh_confirmation_start_utc": contract[
            "fresh_confirmation_start_utc"
        ],
        "days_until_confirmation": max(
            0, (BOUNDARY.date() - now.date()).days
        ),
        "journal_event_count": len(events),
        "decisions": len(decisions),
        "entries": len(entries),
        "exits": len(exits),
        "completed_sessions": len(observations),
        "session_dates": sessions,
        "latest_session_date": latest.get("session_date"),
        "latest_strategy_net_return": latest.get("strategy_net_return"),
        "latest_spy_return": latest.get("spy_return"),
        "latest_net_excess_return": latest.get("net_excess_return"),
        "cumulative_strategy_net_return": strategy_total,
        "cumulative_spy_return": spy_total,
        "cumulative_net_excess_return": (
            strategy_total - spy_total
            if strategy_total is not None and spy_total is not None
            else None
        ),
        "scheduler_interval_seconds": 300,
        "scheduler_status": monitor["operational_status"],
        "operational_status": monitor["status"],
        "operational_failures": monitor["failures"],
        "operational_checked_at_utc": operational.get("checked_at_utc"),
        "last_collection_attempt": operational.get("last_collection_attempt"),
        "collection_windows_eastern": [
            "Decision 9:58-10:03",
            "Entry 10:03-10:08",
            "Exit 10:28-10:33",
        ],
        "catch_up_enabled": True,
        "catch_up_policy": "one same-session attempt after 10:33 Eastern",
        "maximum_collections_per_session": MAX_COLLECTIONS_PER_SESSION,
        "maximum_tiingo_requests_per_session": MAX_REQUESTS_PER_SESSION,
        "tiingo_hourly_request_limit": 500,
        "journal_error": journal_error,
        "request_time_historical_data_load": False,
        "response_cache_ttl_seconds": _CACHE_TTL_SECONDS,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "holdout_outcomes_read": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    _cache.update(
        {
            "signature": signature,
            "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
            "payload": payload,
        }
    )
    return dict(payload)
