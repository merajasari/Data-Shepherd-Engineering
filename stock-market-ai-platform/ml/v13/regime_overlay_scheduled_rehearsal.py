"""End-to-end V13 scheduled collection rehearsal.

The caller injects both a market-session-open decision and raw input provider.
Only during the locked checkpoint does this module construct signed inputs and
run the V13 evaluator against an isolated temporary journal.  Production
evidence, activation artifacts, schedulers, and external data sources remain
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_input_snapshot import build_signed_input_bundle
from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH, RegimeOverlayEvidenceJournal
from ml.v13.regime_overlay_observation import run_session_decision


NEW_YORK = ZoneInfo("America/New_York")
WINDOW_START = time(9, 58)
WINDOW_END = time(10, 5)
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_scheduled_rehearsal_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_scheduled_rehearsal_contract.sha256")


@dataclass(frozen=True)
class ScheduledRehearsal:
    status: str
    schedule_state: str
    provider_invoked: bool
    evaluator_invoked: bool
    rehearsal_events: int
    action: str | None
    activation_lease_sha256: str | None = None
    production_evidence_modified: bool = False
    scheduler_changed: bool = False
    market_data_requests: int = 0
    brokerage_orders: bool = False


def _require_contract() -> str:
    expected: dict[str, object] = {
        "activation_authority": "VALID_EFFECTIVE_PAPER_ONLY_LEASE_REQUIRED",
        "brokerage_orders": False,
        "decision_window_eastern": "09:58_INCLUSIVE_TO_10:05_EXCLUSIVE",
        "input_provider": "CALLER_INJECTED_ONLY",
        "live_trading_enabled": False,
        "market_data_request": False,
        "market_session_open_required": True,
        "paper_trading_only": True,
        "production_evidence_append": False,
        "production_journal_mutation": False,
        "rehearsal_journal": "ISOLATED_TEMPORARY_ONLY",
        "scheduler_install_or_change": False,
        "status": "PREREGISTERED_SCHEDULED_COLLECTION_REHEARSAL",
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
        raise RuntimeError("V13_SCHEDULED_REHEARSAL_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if locked != digest or not isinstance(contract, dict):
        raise RuntimeError("V13_SCHEDULED_REHEARSAL_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_SCHEDULED_REHEARSAL_CONTRACT_CHANGED")
    return digest


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def _state(now: datetime) -> str:
    local = now.astimezone(NEW_YORK)
    current = local.time().replace(tzinfo=None)
    if local.weekday() >= 5:
        return "WEEKEND_CLOSED"
    if current < WINDOW_START:
        return "BEFORE_DECISION_CHECKPOINT"
    if current >= WINDOW_END:
        return "AFTER_DECISION_CHECKPOINT"
    return "DECISION_CHECKPOINT"


def _activation(
    timestamp: datetime,
    validator: Callable[[datetime], Mapping[str, object]] | None,
) -> str:
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
    return lease_sha


def run_scheduled_rehearsal(
    *,
    now_utc: datetime,
    market_session_open: bool,
    input_provider: Callable[[], Mapping[str, object]],
    production_journal_path: Path = DEFAULT_JOURNAL_PATH,
    activation_validator: Callable[[datetime], Mapping[str, object]] | None = None,
) -> ScheduledRehearsal:
    """Exercise one due collection cycle without production side effects."""
    _require_contract()
    if now_utc.tzinfo is None:
        raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
    now = now_utc.astimezone(timezone.utc)
    before = _snapshot(production_journal_path)
    schedule_state = _state(now)
    if schedule_state != "DECISION_CHECKPOINT":
        return ScheduledRehearsal("NOT_DUE", schedule_state, False, False, 0, None)
    if market_session_open is not True:
        return ScheduledRehearsal("MARKET_SESSION_CLOSED", "MARKET_SESSION_CLOSED", False, False, 0, None)

    lease_sha = _activation(now, activation_validator)
    raw = input_provider()
    if not isinstance(raw, Mapping):
        raise ValueError("V13_INPUT_PROVIDER_PAYLOAD_INVALID")
    bundle = build_signed_input_bundle(**raw)
    local = now.astimezone(NEW_YORK)
    decision = local.replace(hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    with TemporaryDirectory(prefix="v13_scheduled_rehearsal_") as directory:
        journal_path = Path(directory) / "evidence.jsonl"
        result = run_session_decision(
            session_date=local.date().isoformat(),
            decision_timestamp_utc=decision.isoformat(),
            ranking_snapshot=bundle.ranking_snapshot,
            intraday_snapshot=bundle.intraday_snapshot,
            regime_snapshot=bundle.regime_snapshot,
            journal_path=journal_path,
            rehearsal=True,
        )
        rows = RegimeOverlayEvidenceJournal(journal_path).read()
        if len(rows) != 1 or rows[0].get("fresh_evidence") is not False:
            raise RuntimeError("V13_SCHEDULED_REHEARSAL_JOURNAL_INVALID")
    after = _snapshot(production_journal_path)
    if before != after:
        raise RuntimeError("V13_SCHEDULED_REHEARSAL_MODIFIED_PRODUCTION_EVIDENCE")
    return ScheduledRehearsal(
        "PASSED_REHEARSAL_ONLY",
        schedule_state,
        True,
        True,
        1,
        result.action,
        lease_sha,
    )


def main() -> None:
    digest = _require_contract()
    print("V13 SCHEDULED COLLECTION — END-TO-END REHEARSAL")
    print("=" * 80)
    print("Status: IMPLEMENTED_NOT_INVOKED")
    print(f"Contract SHA-256: {digest}")
    print("Input provider invoked: NO")
    print("Scheduler installed or changed: NO")
    print("Market data requested: NO")
    print("Production evidence appended: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
