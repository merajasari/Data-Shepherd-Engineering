"""Lightweight, read-only V13 regime-overlay dashboard status."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    RegimeOverlayEvidenceJournal,
    V13EvidenceJournalCorrupt,
)
from ml.v13.regime_overlay_monitor import run_monitor
from ml.v13.regime_overlay_scheduled_entrypoint import STATUS_PATH


CACHE_TTL_SECONDS = 10.0
_CACHE: dict[str, object] = {"at": 0.0, "signature": None, "payload": None}


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _read_status() -> dict[str, object]:
    if not STATUS_PATH.exists():
        return {}
    try:
        payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_v13_regime_overlay_dashboard() -> dict[str, object]:
    """Return control/evidence metadata without loading historical research data."""
    now = time.monotonic()
    signature = (_signature(STATUS_PATH), _signature(DEFAULT_JOURNAL_PATH))
    cached = _CACHE.get("payload")
    if (
        isinstance(cached, dict)
        and _CACHE.get("signature") == signature
        and now - float(_CACHE.get("at") or 0.0) < CACHE_TTL_SECONDS
    ):
        return dict(cached)

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    contract_verified = (
        observed_sha == EXPECTED_CONTRACT_SHA256 and not validate_contract(contract)
    )
    evidence = dict(contract.get("fresh_evidence") or {})
    gates = dict(contract.get("confirmation_gates") or {})
    challenger = dict(contract.get("challenger") or {})
    control = dict(contract.get("control") or {})
    operational = _read_status()
    monitor = run_monitor()

    journal_error: str | None = None
    try:
        events = RegimeOverlayEvidenceJournal(DEFAULT_JOURNAL_PATH).read()
    except V13EvidenceJournalCorrupt as exc:
        journal_error = str(exc)
        events = []

    decisions = [row for row in events if row.get("event_type") == "SESSION_DECISION"]
    observations = [
        row for row in events
        if row.get("event_type") == "PAIRED_SESSION_OBSERVATION"
    ]
    completed_sessions = len(observations)
    regime_eligible_sessions = sum(
        row.get("regime_eligible") is True for row in observations
    )
    minimum_sessions = int(evidence.get("minimum_completed_sessions") or 60)
    minimum_regime_sessions = int(
        evidence.get("minimum_regime_eligible_sessions") or 15
    )
    if journal_error:
        evidence_status = "JOURNAL_ERROR"
    elif not observations:
        evidence_status = "NO_FRESH_EVIDENCE"
    elif completed_sessions < minimum_sessions:
        evidence_status = "EVIDENCE_ACCUMULATING"
    elif regime_eligible_sessions < minimum_regime_sessions:
        evidence_status = "WAITING_FOR_REGIME_SAMPLE"
    else:
        evidence_status = "EVALUATION_SAMPLE_MATURE"

    failures = list(monitor.get("failures") or [])
    if journal_error:
        failures.append(f"JOURNAL_INVALID:{journal_error}")
    if not contract_verified:
        failures.append("CONTRACT_IDENTITY_CHANGED")
    failures = list(dict.fromkeys(str(item) for item in failures))

    payload: dict[str, object] = {
        "status": "READY_DISABLED" if not failures else "ALERT",
        "display_status": "DEVELOPMENT_ONLY_ACTIVATION_DISABLED",
        "status_scope": "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "classification": "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN",
        "candidate_frozen": False,
        "candidate_id": challenger.get("candidate_id"),
        "control_id": control.get("candidate_id"),
        "contract_sha256": observed_sha,
        "contract_sha_verified": contract_verified,
        "activation": evidence.get("activation_status"),
        "fresh_evidence_boundary_utc": evidence.get("boundary_utc"),
        "evidence_status": evidence_status,
        "decisions": len(decisions),
        "completed_sessions": completed_sessions,
        "minimum_completed_sessions": minimum_sessions,
        "regime_eligible_sessions": regime_eligible_sessions,
        "minimum_regime_eligible_sessions": minimum_regime_sessions,
        "journal_event_count": len(events),
        "journal_error": journal_error,
        "operational_status": monitor.get("status"),
        "operational_failures": failures,
        "operational_checked_at_utc": monitor.get("checked_at_utc"),
        "scheduler_status": operational.get("status", "NOT_YET_PUBLISHED"),
        "schedule_state": operational.get("schedule_state"),
        "collection_expected": operational.get("collection_expected") is True,
        "market_data_requests": int(operational.get("market_data_requests") or 0),
        "scheduler_installation_expected": False,
        "confirmation_gates": {
            "annualized_return_delta_minimum": gates.get(
                "net_annualized_return_delta_vs_control_at_least"
            ),
            "terminal_wealth_greater_than_control": gates.get(
                "terminal_wealth_greater_than_control"
            ),
            "maximum_drawdown_not_worse_than_control": gates.get(
                "maximum_drawdown_not_worse_than_control"
            ),
            "negative_high_vol_return_greater_than_control": gates.get(
                "negative_high_vol_regime_net_return_greater_than_control"
            ),
            "paired_session_win_rate_minimum": gates.get(
                "paired_session_win_rate_at_least"
            ),
            "turnover_control_multiple_maximum": gates.get(
                "turnover_not_more_than_control_multiple"
            ),
            "small_account_feasibility_pass_rate": gates.get(
                "small_account_feasibility_pass_rate"
            ),
        },
        "retrospective_classification": (
            "DEVELOPMENT_RECONSTRUCTION_ONLY_NOT_FRESH_EVIDENCE"
        ),
        "retrospective_reconstruction_read": False,
        "request_time_historical_data_load": False,
        "response_cache_ttl_seconds": CACHE_TTL_SECONDS,
        "holdout_outcomes_read": False,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    _CACHE.update({"at": now, "signature": signature, "payload": dict(payload)})
    return payload
