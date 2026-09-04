"""Lease-gated V13 fresh paper-evidence commit layer.

The locked observation evaluator is first run against an isolated rehearsal
journal.  Only its validated event may then be converted to fresh evidence and
appended to the production journal under a valid effective paper-only lease.
This module contains no market client, scheduler, or brokerage interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    EXPECTED_COLLECTION_CONTRACT_SHA256,
    RegimeOverlayEvidenceJournal,
)
from ml.v13.regime_overlay_observation import (
    run_paired_observation,
    run_session_decision,
)


CONTRACT_PATH = Path(__file__).with_name("regime_overlay_collection_apply_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_collection_apply_contract.sha256")
EXPECTED_CONTRACT_SHA256 = EXPECTED_COLLECTION_CONTRACT_SHA256


@dataclass(frozen=True)
class CollectionCommit:
    status: str
    event_type: str
    session_date: str
    event_appended: bool
    activation_lease_sha256: str
    paper_trading_only: bool = True
    live_trading_enabled: bool = False
    brokerage_orders: bool = False


def _require_contract() -> None:
    expected: dict[str, object] = {
        "activation_authority": "VALID_EFFECTIVE_PAPER_ONLY_LEASE_REQUIRED_PER_EVENT",
        "brokerage_orders": False,
        "caller_supplied_signed_inputs_only": True,
        "decision_time_eastern": "10:00",
        "duplicate_safe": True,
        "evaluator": "REGIME_OVERLAY_OBSERVATION_LOCKED",
        "fresh_evidence_append": True,
        "holdout_outcomes_read": False,
        "live_trading_enabled": False,
        "market_data_request": False,
        "paired_observation_holding_sessions": 5,
        "paper_trading_only": True,
        "production_journal_only": True,
        "rehearsal_evaluation_before_commit": True,
        "scheduler_install_or_change": False,
        "status": "PREREGISTERED_FAIL_CLOSED_COLLECTION_COMMIT",
        "v10_control": "V10_CONTROL_5K",
        "v13_challenger": "V13_NEGATIVE_HIGH_VOL_CONFIRM_5K",
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    try:
        raw = CONTRACT_PATH.read_bytes()
        contract = json.loads(raw)
        locked = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError("V13_COLLECTION_APPLICATION_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_CONTRACT_SHA256 or locked != digest:
        raise RuntimeError("V13_COLLECTION_APPLICATION_CONTRACT_IDENTITY_CHANGED")
    if not isinstance(contract, dict) or any(contract.get(k) != v for k, v in expected.items()):
        raise RuntimeError("V13_COLLECTION_APPLICATION_CONTRACT_CHANGED")


def _fresh_event(event: Mapping[str, object], lease_sha: str) -> dict[str, object]:
    result = dict(event)
    for field in ("event_id", "previous_record_sha256", "record_sha256"):
        result.pop(field, None)
    result.update(
        {
            "rehearsal": False,
            "fresh_evidence": True,
            "activation_lease_sha256": lease_sha,
            "collection_contract_sha256": EXPECTED_CONTRACT_SHA256,
            "v13_production_evidence_modified": True,
        }
    )
    return result


def _activation(
    timestamp: datetime,
    validator: Callable[[datetime], Mapping[str, object]] | None,
) -> Mapping[str, object]:
    if validator is None:
        from ml.v13.regime_overlay_lease_renewal_apply import validate_renewal_chain

        state = validate_renewal_chain(now_utc=timestamp)
    else:
        state = validator(timestamp)
    if (
        state.get("valid") is not True
        or state.get("active") is not True
        or state.get("paper_trading_only") is not True
        or state.get("live_trading_enabled") is not False
        or state.get("brokerage_orders") is not False
    ):
        raise RuntimeError("V13_ACTIVE_PAPER_ONLY_LEASE_REQUIRED")
    lease_sha = state.get("latest_lease_sha256")
    if not isinstance(lease_sha, str) or len(lease_sha) != 64:
        raise RuntimeError("V13_EFFECTIVE_LEASE_IDENTITY_INVALID")
    return state


def commit_session_decision(
    *,
    session_date: str,
    decision_timestamp_utc: str,
    ranking_snapshot: Mapping[str, object],
    intraday_snapshot: Mapping[str, object],
    regime_snapshot: Mapping[str, object],
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    activation_validator: Callable[[datetime], Mapping[str, object]] | None = None,
) -> CollectionCommit:
    """Evaluate and append one fresh decision under an active paper lease."""
    _require_contract()
    timestamp = datetime.fromisoformat(decision_timestamp_utc.replace("Z", "+00:00"))
    state = _activation(timestamp, activation_validator)
    with TemporaryDirectory(prefix="v13_collection_decision_") as raw:
        rehearsal_path = Path(raw) / "evidence.jsonl"
        run_session_decision(
            session_date=session_date,
            decision_timestamp_utc=decision_timestamp_utc,
            ranking_snapshot=ranking_snapshot,
            intraday_snapshot=intraday_snapshot,
            regime_snapshot=regime_snapshot,
            journal_path=rehearsal_path,
            rehearsal=True,
        )
        rows = RegimeOverlayEvidenceJournal(rehearsal_path).read()
        if len(rows) != 1 or rows[0].get("event_type") != "SESSION_DECISION":
            raise RuntimeError("V13_DECISION_REHEARSAL_INVALID")
        lease_sha = str(state["latest_lease_sha256"])
        event = _fresh_event(rows[0], lease_sha)
    journal = RegimeOverlayEvidenceJournal(
        journal_path, activation_validator=activation_validator
    )
    appended = journal.append(event)
    return CollectionCommit(
        status="FRESH_PAPER_DECISION_RECORDED" if appended else "DUPLICATE_SAFE_NOOP",
        event_type="SESSION_DECISION",
        session_date=session_date,
        event_appended=appended,
        activation_lease_sha256=lease_sha,
    )


def commit_paired_observation(
    *,
    session_date: str,
    exit_session_date: str,
    exit_timestamp_utc: str,
    exit_prices: Mapping[str, float],
    exit_snapshot_sha256: str,
    completed_holding_sessions: int,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    activation_validator: Callable[[datetime], Mapping[str, object]] | None = None,
) -> CollectionCommit:
    """Evaluate and append a five-session paired outcome under a valid lease."""
    _require_contract()
    timestamp = datetime.fromisoformat(exit_timestamp_utc.replace("Z", "+00:00"))
    state = _activation(timestamp, activation_validator)
    production = RegimeOverlayEvidenceJournal(journal_path).read()
    decisions = [
        row for row in production
        if row.get("session_date") == session_date
        and row.get("event_type") == "SESSION_DECISION"
    ]
    if len(decisions) != 1:
        raise RuntimeError("V13_PAIRED_OBSERVATION_REQUIRES_ONE_FRESH_DECISION")
    with TemporaryDirectory(prefix="v13_collection_observation_") as raw:
        rehearsal_path = Path(raw) / "evidence.jsonl"
        decision = dict(decisions[0])
        for field in (
            "event_id", "previous_record_sha256", "record_sha256",
            "activation_lease_sha256", "collection_contract_sha256",
        ):
            decision.pop(field, None)
        decision.update(
            {
                "rehearsal": True,
                "fresh_evidence": False,
                "v13_production_evidence_modified": False,
            }
        )
        RegimeOverlayEvidenceJournal(rehearsal_path, rehearsal=True).append(decision)
        run_paired_observation(
            session_date=session_date,
            exit_session_date=exit_session_date,
            exit_timestamp_utc=exit_timestamp_utc,
            exit_prices=exit_prices,
            exit_snapshot_sha256=exit_snapshot_sha256,
            completed_holding_sessions=completed_holding_sessions,
            journal_path=rehearsal_path,
            rehearsal=True,
        )
        rows = RegimeOverlayEvidenceJournal(rehearsal_path).read()
        if len(rows) != 2 or rows[-1].get("event_type") != "PAIRED_SESSION_OBSERVATION":
            raise RuntimeError("V13_PAIRED_OBSERVATION_REHEARSAL_INVALID")
        lease_sha = str(state["latest_lease_sha256"])
        event = _fresh_event(rows[-1], lease_sha)
    journal = RegimeOverlayEvidenceJournal(
        journal_path, activation_validator=activation_validator
    )
    appended = journal.append(event)
    return CollectionCommit(
        status="FRESH_PAPER_OBSERVATION_RECORDED" if appended else "DUPLICATE_SAFE_NOOP",
        event_type="PAIRED_SESSION_OBSERVATION",
        session_date=session_date,
        event_appended=appended,
        activation_lease_sha256=lease_sha,
    )


def main() -> None:
    _require_contract()
    print("V13 FRESH PAPER-EVIDENCE COLLECTION COMMIT LAYER")
    print("=" * 80)
    print("Status: IMPLEMENTED_NOT_INVOKED")
    print("Caller-supplied signed inputs only: YES")
    print("Scheduler installed or changed: NO")
    print("Market data requested: NO")
    print("Production evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
