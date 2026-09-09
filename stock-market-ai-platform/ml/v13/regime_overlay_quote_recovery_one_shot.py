"""Separate guarded V13 one-shot using the preregistered quote recovery.

This collector is deliberately not imported by the historical September 8
automation or the original guarded one-shot.  The default command is inert.
An explicit invocation still requires every existing paper-only lease,
operator, acknowledgement, session, time-window, and signed-context gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
import time as clock
from typing import Callable, Mapping

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_collection_apply import commit_session_decision
from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH
from ml.v13.regime_overlay_one_shot import (
    INBOX_ROOT,
    NEW_YORK,
    OneShotResult,
    _activation,
    _load_inbox,
)
from ml.v13.regime_overlay_quote_recovery import (
    MAXIMUM_REQUESTS,
    RETRY_DELAY_SECONDS,
    _require_contract as _require_quote_recovery_contract,
    collect_signed_inputs_with_quote_recovery,
)
from ml.v13.regime_overlay_tiingo_provider import TiingoV13Client


QUOTE_RECOVERY_CONTRACT_SHA256 = (
    "72e320e88440647b604c541365aa3ff7b41de0c041a8062d2b4667b9f8c45a36"
)
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_one_shot_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_one_shot_contract.sha256"
)


def _require_contract() -> str:
    if _require_quote_recovery_contract() != QUOTE_RECOVERY_CONTRACT_SHA256:
        raise RuntimeError("V13_QUOTE_RECOVERY_PARENT_CONTRACT_CHANGED")
    expected: dict[str, object] = {
        "activation_authority": "VALID_EFFECTIVE_PAPER_ONLY_LEASE_REQUIRED",
        "backfill": False,
        "brokerage_orders": False,
        "collection_window_eastern": "10:00_INCLUSIVE_TO_10:05_EXCLUSIVE",
        "entry_quote_policy": "ONE_FIXED_DELAY_FULL_BATCH_RETRY_NO_SUBSTITUTION",
        "exact_operator_acknowledgement_required": True,
        "input_files": "V13_INBOX_ONLY",
        "legacy_one_shot_modified": False,
        "lease_timing": "SAME_LEASE_ACTIVE_AT_DECISION_AND_COLLECTION",
        "live_trading_enabled": False,
        "manual_apply_flag_required": True,
        "market_session_open_required": True,
        "maximum_market_data_requests": MAXIMUM_REQUESTS,
        "paper_trading_only": True,
        "production_event": "ONE_DUPLICATE_SAFE_SESSION_DECISION",
        "quote_recovery_contract_sha256": QUOTE_RECOVERY_CONTRACT_SHA256,
        "retry_delay_seconds": RETRY_DELAY_SECONDS,
        "scheduler_install_or_change": False,
        "second_quote_failure_action": "FAIL_CLOSED_NO_EVIDENCE",
        "september_8_attempt_modified": False,
        "status": "PREREGISTERED_V13_QUOTE_RECOVERY_GUARDED_ONE_SHOT",
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
        raise RuntimeError("V13_QUOTE_RECOVERY_ONE_SHOT_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != locked or not isinstance(contract, dict):
        raise RuntimeError("V13_QUOTE_RECOVERY_ONE_SHOT_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_QUOTE_RECOVERY_ONE_SHOT_CONTRACT_CHANGED")
    return digest


def run_quote_recovery_one_shot(
    *,
    apply: bool = False,
    now_utc: datetime | None = None,
    operator: str = "",
    acknowledgement: str = "",
    market_session_open: bool = False,
    ranking_snapshot: Mapping[str, object] | None = None,
    control_context: Mapping[str, object] | None = None,
    client_factory: Callable[[], object] = TiingoV13Client,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    activation_validator: Callable[[datetime], Mapping[str, object]] | None = None,
    sleeper: Callable[[float], None] = clock.sleep,
) -> OneShotResult:
    """Commit at most one fully validated paper decision with bounded recovery."""
    _require_contract()
    if not apply:
        return OneShotResult("IMPLEMENTED_NOT_INVOKED", False, 0, False, None, False)
    if acknowledgement != REQUIRED_ACKNOWLEDGEMENT:
        raise RuntimeError("V13_EXACT_PAPER_ONLY_ACKNOWLEDGEMENT_REQUIRED")
    if now_utc is not None and now_utc.tzinfo is None:
        raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now.astimezone(NEW_YORK)
    current = local.time().replace(tzinfo=None)
    if local.weekday() >= 5 or market_session_open is not True:
        raise RuntimeError("V13_CONFIRMED_OPEN_MARKET_SESSION_REQUIRED")
    if not (time(10, 0) <= current < time(10, 5)):
        raise RuntimeError("V13_OUTSIDE_QUOTE_RECOVERY_COLLECTION_WINDOW")
    decision = local.replace(
        hour=10, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)
    decision_state = _activation(decision, activation_validator)
    state = _activation(now, activation_validator)
    if (
        state["latest_lease_sha256"] != decision_state["latest_lease_sha256"]
        or state["operator"] != decision_state["operator"]
    ):
        raise RuntimeError("V13_SAME_LEASE_REQUIRED_AT_DECISION_AND_COLLECTION")
    if operator.strip() != state["operator"]:
        raise RuntimeError("V13_OPERATOR_MUST_MATCH_ACTIVE_LEASE")
    if not isinstance(ranking_snapshot, Mapping) or not isinstance(
        control_context, Mapping
    ):
        raise ValueError("V13_SIGNED_CONTROL_INPUTS_REQUIRED")

    client = client_factory()
    provider = collect_signed_inputs_with_quote_recovery(
        now_utc=now,
        session_date=local.date().isoformat(),
        ranking_snapshot=ranking_snapshot,
        control_context=control_context,
        client=client,
        sleeper=sleeper,
    )
    commit = commit_session_decision(
        session_date=local.date().isoformat(),
        decision_timestamp_utc=decision.isoformat(),
        ranking_snapshot=provider.bundle.ranking_snapshot,
        intraday_snapshot=provider.bundle.intraday_snapshot,
        regime_snapshot=provider.bundle.regime_snapshot,
        journal_path=journal_path,
        activation_validator=activation_validator,
    )
    return OneShotResult(
        commit.status,
        True,
        provider.request_count,
        commit.event_appended,
        commit.activation_lease_sha256,
        commit.event_appended,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guarded V13 paper collector with bounded quote recovery"
    )
    parser.add_argument("--operator", default="")
    parser.add_argument("--acknowledgement", default="")
    parser.add_argument("--ranking-snapshot")
    parser.add_argument("--control-context")
    parser.add_argument("--market-session-open", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    digest = _require_contract()
    if args.apply:
        if not args.ranking_snapshot or not args.control_context:
            parser.error(
                "--ranking-snapshot and --control-context are required with --apply"
            )
        result = run_quote_recovery_one_shot(
            apply=True,
            operator=args.operator,
            acknowledgement=args.acknowledgement,
            market_session_open=args.market_session_open,
            ranking_snapshot=_load_inbox(args.ranking_snapshot, "RANKING_SNAPSHOT"),
            control_context=_load_inbox(args.control_context, "CONTROL_CONTEXT"),
        )
    else:
        result = run_quote_recovery_one_shot()
    print("V13 GUARDED QUOTE-RECOVERY ONE-SHOT COLLECTOR")
    print("=" * 80)
    print(f"Status: {result.status}")
    print(f"Contract SHA-256: {digest}")
    print(f"Collector invoked: {'YES' if result.collector_invoked else 'NO'}")
    print(f"Market data requests: {result.market_data_requests}")
    print(f"Production evidence appended: {'YES' if result.event_appended else 'NO'}")
    print("Maximum market data requests: 104")
    print("Scheduler installed or changed: NO")
    print("September 8 attempt modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
