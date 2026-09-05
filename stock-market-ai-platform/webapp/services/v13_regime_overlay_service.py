"""Lightweight, read-only V13 regime-overlay dashboard status."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
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
from ml.v13.regime_overlay_manual_approval import (
    APPROVAL_PATH,
    get_manual_approval_status,
)
from ml.v13.regime_overlay_activation_transition import (
    ACTIVATION_LEASE_PATH,
    plan_transition,
)
from ml.v13.regime_overlay_activation import validate_activation_lease
from ml.v13.regime_overlay_lease_renewal_apply import validate_renewal_chain
from ml.v13.regime_overlay_preflight import run_preflight
from ml.v13.regime_overlay_scheduled_entrypoint import STATUS_PATH


CACHE_TTL_SECONDS = 10.0
_CACHE: dict[str, object] = {"at": 0.0, "signature": None, "payload": None}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_INBOX_ROOT = PROJECT_ROOT / "data" / "research" / "v13" / "fresh_regime_overlay" / "inbox"


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_signed_context_metadata() -> dict[str, object]:
    """Read only signed V13 inbox metadata; never load outcomes or history."""
    try:
        targets = sorted(path for path in CONTEXT_INBOX_ROOT.iterdir() if path.is_dir())
    except OSError:
        targets = []
    if not targets:
        return {
            "status": "NOT_PUBLISHED",
            "target_session": None,
            "source_decision_session": None,
            "ranking_sha256": None,
            "control_context_sha256": None,
        }
    target = targets[-1]
    ranking = _read_json(target / "ranking_snapshot.json")
    control = _read_json(target / "control_context.json")
    source_sessions = control.get("source_decision_sessions")
    source = (
        source_sessions[-1]
        if isinstance(source_sessions, list) and source_sessions
        else ranking.get("source_decision_session")
    )
    return {
        "status": "PUBLISHED_SIGNED_V13_CONTEXT" if ranking and control else "INCOMPLETE",
        "target_session": ranking.get("session_date") or target.name,
        "source_decision_session": source,
        "ranking_sha256": ranking.get("ranking_sha256"),
        "control_context_sha256": control.get("control_context_sha256"),
    }


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
    signature = (
        _signature(STATUS_PATH),
        _signature(DEFAULT_JOURNAL_PATH),
        _signature(APPROVAL_PATH),
        _signature(ACTIVATION_LEASE_PATH),
        _signature(CONTEXT_INBOX_ROOT),
    )
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
    context = _read_signed_context_metadata()
    monitor = run_monitor()
    preflight = run_preflight()
    approval = get_manual_approval_status(preflight=preflight)
    transition = plan_transition(preflight=preflight, approval=approval)
    lease = validate_activation_lease()
    renewal_error: str | None = None
    try:
        renewal = validate_renewal_chain()
    except Exception as exc:  # the dashboard must fail closed on chain corruption
        renewal = {"valid": False, "active": False}
        renewal_error = f"V13_RENEWAL_CHAIN_INVALID:{type(exc).__name__}"
    if renewal.get("valid") is True:
        lease = {
            **lease,
            "valid": renewal.get("active") is True,
            "status": renewal.get("status"),
            "activation": (
                "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
                if renewal.get("active") is True
                else "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT"
            ),
            "operator": renewal.get("operator") or lease.get("operator"),
            "expires_at_utc": renewal.get("latest_lease_expires_at_utc") or lease.get("expires_at_utc"),
            "lease_sha256": renewal.get("latest_lease_sha256") or lease.get("lease_sha256"),
            "renewal_count": renewal.get("renewal_count", 0),
        }

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
    if renewal_error:
        failures.append(renewal_error)
    if journal_error:
        failures.append(f"JOURNAL_INVALID:{journal_error}")
    if not contract_verified:
        failures.append("CONTRACT_IDENTITY_CHANGED")
    failures = list(dict.fromkeys(str(item) for item in failures))

    payload: dict[str, object] = {
        "status": (
            "ALERT"
            if failures
            else (
                "READY_PAPER_ACTIVATED"
                if lease.get("valid") is True
                else "READY_DISABLED"
            )
        ),
        "display_status": (
            "FRESH_PAPER_EVIDENCE_ACTIVATED"
            if lease.get("valid") is True
            else "DEVELOPMENT_ONLY_ACTIVATION_DISABLED"
        ),
        "status_scope": "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "classification": "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN",
        "candidate_frozen": False,
        "candidate_id": challenger.get("candidate_id"),
        "control_id": control.get("candidate_id"),
        "contract_sha256": observed_sha,
        "contract_sha_verified": contract_verified,
        "activation": (
            lease.get("activation")
            if lease.get("valid") is True
            else evidence.get("activation_status")
        ),
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
        "manual_approval_status": (
            "VALID_FOR_ACTIVE_RENEWAL"
            if lease.get("valid") is True
            else approval.get("status")
        ),
        "manual_approval_present": (
            approval.get("manual_approval_present") is True
            or lease.get("valid") is True
        ),
        "manual_approval_valid": (
            approval.get("valid") is True
            or lease.get("valid") is True
        ),
        "activation_lease_present": ACTIVATION_LEASE_PATH.exists(),
        "activation_lease_valid": lease.get("valid") is True,
        "activation_lease_operator": lease.get("operator"),
        "activation_lease_expires_at_utc": lease.get("expires_at_utc"),
        "activation_lease_sequence": lease.get("renewal_count", 0),
        "transition_status": (
            "APPLIED_PAPER_ONLY"
            if lease.get("valid") is True
            else transition.get("status")
        ),
        "transition_eligible": transition.get("eligible") is True,
        "transition_gates_passed": transition.get("gates_passed"),
        "transition_gates_total": transition.get("gates_total"),
        "planned_activation_state": transition.get("planned_post_state"),
        "transition_application_present": True,
        "transition_applied": lease.get("valid") is True,
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
        "context_status": context["status"],
        "context_target_session": context["target_session"],
        "context_source_decision_session": context["source_decision_session"],
        "context_ranking_sha256": context["ranking_sha256"],
        "context_control_context_sha256": context["control_context_sha256"],
        "next_decision_window_utc": (
            f"{context['target_session']}T14:00:00+00:00"
            if context["target_session"]
            else None
        ),
    }
    _CACHE.update({"at": now, "signature": signature, "payload": dict(payload)})
    return payload
