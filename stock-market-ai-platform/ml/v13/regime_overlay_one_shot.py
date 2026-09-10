"""Explicit, lease-gated one-shot V13 fresh paper-evidence collector.

The default command is inert.  A real collection requires ``--apply``, the
exact human acknowledgement, the root operator identity, an explicit open-
session assertion, and two signed context files staged inside the V13 inbox.
No scheduler or brokerage interface is present.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_collection_apply import commit_session_decision
from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH
from ml.v13.regime_overlay_tiingo_provider import TiingoV13Client, collect_signed_inputs


ROOT = Path(__file__).resolve().parents[2]
INBOX_ROOT = ROOT / "data/research/v13/fresh_regime_overlay/inbox"
NEW_YORK = ZoneInfo("America/New_York")
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_one_shot_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_one_shot_contract.sha256")


@dataclass(frozen=True)
class OneShotResult:
    status: str
    collector_invoked: bool
    market_data_requests: int
    event_appended: bool
    activation_lease_sha256: str | None
    production_evidence_modified: bool
    scheduler_changed: bool = False
    paper_trading_only: bool = True
    live_trading_enabled: bool = False
    brokerage_orders: bool = False


def _require_contract() -> str:
    expected: dict[str, object] = {
        "activation_authority": "VALID_EFFECTIVE_PAPER_ONLY_LEASE_REQUIRED",
        "brokerage_orders": False,
        "collection_window_eastern": "10:00_INCLUSIVE_TO_10:05_EXCLUSIVE",
        "exact_operator_acknowledgement_required": True,
        "input_files": "V13_INBOX_ONLY",
        "lease_timing": "SAME_LEASE_ACTIVE_AT_DECISION_AND_COLLECTION",
        "live_trading_enabled": False,
        "manual_apply_flag_required": True,
        "market_session_open_required": True,
        "maximum_market_data_requests": 103,
        "paper_trading_only": True,
        "production_event": "ONE_DUPLICATE_SAFE_SESSION_DECISION",
        "scheduler_install_or_change": False,
        "status": "PREREGISTERED_V13_GUARDED_ONE_SHOT_COLLECTOR",
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
        raise RuntimeError("V13_ONE_SHOT_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if locked != digest or not isinstance(contract, dict):
        raise RuntimeError("V13_ONE_SHOT_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_ONE_SHOT_CONTRACT_CHANGED")
    return digest


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
    operator = state.get("operator")
    if not isinstance(lease_sha, str) or len(lease_sha) != 64 or not isinstance(operator, str):
        raise RuntimeError("V13_EFFECTIVE_LEASE_IDENTITY_INVALID")
    return state


def run_one_shot(
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
) -> OneShotResult:
    """Commit at most one fresh decision after every explicit gate passes."""
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
        raise RuntimeError("V13_OUTSIDE_ONE_SHOT_COLLECTION_WINDOW")
    decision = local.replace(hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    decision_state = _activation(decision, activation_validator)
    state = _activation(now, activation_validator)
    if (
        state["latest_lease_sha256"] != decision_state["latest_lease_sha256"]
        or state["operator"] != decision_state["operator"]
    ):
        raise RuntimeError("V13_SAME_LEASE_REQUIRED_AT_DECISION_AND_COLLECTION")
    if operator.strip() != state["operator"]:
        raise RuntimeError("V13_OPERATOR_MUST_MATCH_ACTIVE_LEASE")
    if not isinstance(ranking_snapshot, Mapping) or not isinstance(control_context, Mapping):
        raise ValueError("V13_SIGNED_CONTROL_INPUTS_REQUIRED")

    client = client_factory()
    provider = collect_signed_inputs(
        now_utc=now,
        session_date=local.date().isoformat(),
        ranking_snapshot=ranking_snapshot,
        control_context=control_context,
        client=client,
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


def _load_inbox(path_value: str, label: str) -> dict[str, object]:
    path = Path(path_value).expanduser().resolve()
    inbox = INBOX_ROOT.resolve()
    if not path.is_relative_to(inbox) or not path.is_file():
        raise RuntimeError(f"V13_{label}_MUST_BE_A_FILE_IN_V13_INBOX")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"V13_{label}_INVALID") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"V13_{label}_INVALID")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded one-shot V13 paper-evidence collector")
    parser.add_argument("--operator", default="")
    parser.add_argument("--acknowledgement", default="")
    parser.add_argument("--ranking-snapshot")
    parser.add_argument("--control-context")
    parser.add_argument("--market-session-open", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    _require_contract()
    if args.apply:
        if not args.ranking_snapshot or not args.control_context:
            parser.error("--ranking-snapshot and --control-context are required with --apply")
        result = run_one_shot(
            apply=True,
            operator=args.operator,
            acknowledgement=args.acknowledgement,
            market_session_open=args.market_session_open,
            ranking_snapshot=_load_inbox(args.ranking_snapshot, "RANKING_SNAPSHOT"),
            control_context=_load_inbox(args.control_context, "CONTROL_CONTEXT"),
        )
    else:
        result = run_one_shot()
    print("V13 GUARDED ONE-SHOT FRESH PAPER-EVIDENCE COLLECTOR")
    print("=" * 80)
    print(f"Status: {result.status}")
    print(f"Collector invoked: {'YES' if result.collector_invoked else 'NO'}")
    print(f"Market data requests: {result.market_data_requests}")
    print(f"Production evidence appended: {'YES' if result.event_appended else 'NO'}")
    print("Scheduler installed or changed: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
