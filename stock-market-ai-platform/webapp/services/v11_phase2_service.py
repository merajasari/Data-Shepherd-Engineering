"""Lightweight read-only dashboard service for V11 Phase 2."""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_archive import (
    ARCHIVE_STATUS_PATH,
    load_archive_status,
)
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
    signature = (
        _signature(STATUS_PATH),
        _signature(DEFAULT_JOURNAL_PATH),
        _signature(ARCHIVE_STATUS_PATH),
    )
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

    archive_error = None
    try:
        archive = load_archive_status()
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        archive = None
        archive_error = str(exc)
    archived = archive is not None and archive_error is None

    decisions = [row for row in events if row.get("event_type") == "DECISION"]
    entries = [row for row in events if row.get("event_type") == "ENTRY"]
    exits = [row for row in events if row.get("event_type") == "EXIT"]
    observations = [
        row for row in events
        if row.get("event_type") == "SESSION_OBSERVATION"
    ]
    sessions = sorted({str(row.get("session_date")) for row in observations})
    latest = observations[-1] if observations else {}
    monitor = (
        {
            "status": "HEALTHY_ARCHIVED",
            "operational_status": "DISABLED_ARCHIVED",
            "failures": [],
        }
        if archived
        else run_monitor()
    )
    now = datetime.now(timezone.utc)
    state = (
        "JOURNAL_ERROR" if journal_error else
        "ARCHIVE_ERROR" if archive_error else
        "ARCHIVED_READ_ONLY" if archived else
        "WAITING_FOR_BOUNDARY" if now < BOUNDARY else
        str(operational.get("status") or "ACTIVE_WAITING_FOR_SESSION")
    )
    evidence = (
        "ARCHIVED_EVIDENCE_PRESERVED" if archived and observations else
        "ARCHIVED_NO_FRESH_EVIDENCE" if archived else
        "NO_FRESH_SESSIONS" if not observations else
        "PRELIMINARY_EVIDENCE" if len(observations) < 20 else
        "EVIDENCE_ACCUMULATING" if len(observations) < 60 else
        "CONFIRMATION_SAMPLE_MATURE"
    )
    ready = (
        observed_sha == EXPECTED_CONTRACT_SHA256
        and journal_error is None
        and archive_error is None
        and monitor["status"]
        in {"HEALTHY_PAPER_CONFIRMATION", "HEALTHY_ARCHIVED"}
    )
    display_status = (
        "ALERT" if not ready else
        "ARCHIVED_RESEARCH_REFERENCE" if archived else
        "AWAITING_FRESH_SESSION" if not observations else
        "FRESH_EVIDENCE_ACTIVE"
    )
    strategy_total = _compound(observations, "strategy_net_return")
    spy_total = _compound(observations, "spy_return")
    payload: dict[str, object] = {
        "status": (
            "READY_ARCHIVED" if ready and archived else
            "READY" if ready else "ALERT"
        ),
        "control_status": (
            "READY_ARCHIVED" if ready and archived else
            "READY" if ready else "ALERT"
        ),
        "display_status": display_status,
        "status_scope": "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "state": state,
        "evidence_status": evidence,
        "classification": (
            "ARCHIVED_RESEARCH_REFERENCE"
            if archived
            else "PREREGISTERED_FRESH_PAPER_CONFIRMATION"
        ),
        "archived": archived,
        "archived_at_utc": archive.get("archived_at_utc") if archive else None,
        "archive_contract_sha256": (
            archive.get("archive_contract_sha256") if archive else None
        ),
        "archive_manifest_sha256": (
            archive.get("archive_manifest_sha256") if archive else None
        ),
        "v13_preserved_dependency_map": (
            archive.get("v13_preserved_dependency_map", {})
            if archive else {}
        ),
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
        "scheduler_interval_seconds": 0 if archived else 300,
        "scheduler_status": (
            "DISABLED_ARCHIVED"
            if archived else monitor["operational_status"]
        ),
        "operational_status": monitor["status"],
        "operational_failures": monitor["failures"],
        "operational_checked_at_utc": operational.get("checked_at_utc"),
        "last_collection_attempt": operational.get("last_collection_attempt"),
        "collection_windows_eastern": (
            [] if archived else [
                "Decision 9:58-10:03",
                "Entry 10:03-10:08",
                "Exit 10:28-10:33",
            ]
        ),
        "catch_up_enabled": False if archived else True,
        "catch_up_policy": (
            "disabled; V11 is an archived research reference"
            if archived
            else "one same-session attempt after 10:33 Eastern"
        ),
        "maximum_collections_per_session": (
            0 if archived else MAX_COLLECTIONS_PER_SESSION
        ),
        "maximum_tiingo_requests_per_session": (
            0 if archived else MAX_REQUESTS_PER_SESSION
        ),
        "tiingo_hourly_request_limit": 500,
        "journal_error": journal_error,
        "archive_error": archive_error,
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

