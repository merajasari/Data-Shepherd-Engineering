"""Parameterized one-session automation for guarded V13 quote recovery.

This is a new controller for sessions after the consumed September 8 attempt.
It never edits the historical automation directory.  The default command is
descriptive only; authorization, preflight, and collection are separate,
explicitly gated operations for one operator-bound future session.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_quote_recovery_one_shot import (
    run_quote_recovery_one_shot,
)


ROOT = Path(__file__).resolve().parents[2]
NEW_YORK = ZoneInfo("America/New_York")
OPERATOR = "Meraj Asari"
HISTORICAL_SESSION_CUTOFF = date(2026, 9, 8)
COLLECTOR_CONTRACT_SHA256 = (
    "777ead204171a56c75b003df3ac92d371a8022af4b9ad74dc63e4e90bd7cbbd0"
)
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_session_automation_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_session_automation_contract.sha256"
)
AUTOMATION_ROOT = (
    ROOT
    / "data/research/v13/fresh_regime_overlay/quote_recovery_automation"
)
INBOX_ROOT = ROOT / "data/research/v13/fresh_regime_overlay/inbox"
TERMINAL_STATUSES = {
    "COLLECTION_FAILED_NO_EVIDENCE",
    "FRESH_PAPER_DECISION_RECORDED",
    "DUPLICATE_SAFE_NOOP",
}


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    authorization: Path
    attempt: Path
    status: Path


def _require_contract() -> str:
    from ml.v13.regime_overlay_quote_recovery_one_shot import (
        _require_contract as require_collector_contract,
    )

    if require_collector_contract() != COLLECTOR_CONTRACT_SHA256:
        raise RuntimeError("V13_QUOTE_RECOVERY_COLLECTOR_CONTRACT_CHANGED")
    expected: dict[str, object] = {
        "active_paper_only_lease_required": True,
        "automatic_context_publication": False,
        "automatic_lease_renewal": False,
        "backfill": False,
        "brokerage_orders": False,
        "collection_window_eastern": "10:00_INCLUSIVE_TO_10:05_EXCLUSIVE",
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "failure_status_persisted": True,
        "live_trading_enabled": False,
        "market_session_open_operator_assertion": True,
        "maximum_attempts_per_session": 1,
        "maximum_market_data_requests": 104,
        "operator_authorization_required_before_window": True,
        "paper_trading_only": True,
        "quote_retry": "ONE_FULL_101_SYMBOL_BATCH_AFTER_5_SECONDS",
        "scheduler_installation": "SEPARATE_EXPLICIT_OPERATOR_STEP_ONLY",
        "september_8_attempt_modified": False,
        "signed_context_required": True,
        "status": (
            "PREREGISTERED_V13_PARAMETERIZED_ONE_SESSION_"
            "QUOTE_RECOVERY_AUTOMATION"
        ),
        "target_session_rule": "WEEKDAY_AFTER_2026_09_08_OPERATOR_BOUND",
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
        raise RuntimeError(
            "V13_QUOTE_RECOVERY_AUTOMATION_CONTRACT_INVALID"
        ) from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != locked or not isinstance(contract, dict):
        raise RuntimeError(
            "V13_QUOTE_RECOVERY_AUTOMATION_CONTRACT_IDENTITY_CHANGED"
        )
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_QUOTE_RECOVERY_AUTOMATION_CONTRACT_CHANGED")
    return digest


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("V13_AUTOMATION_TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _session_dates(
    target_session: str, source_session: str
) -> tuple[date, date]:
    try:
        target = date.fromisoformat(target_session)
        source = date.fromisoformat(source_session)
    except ValueError as exc:
        raise ValueError("V13_AUTOMATION_SESSION_DATE_INVALID") from exc
    if target <= HISTORICAL_SESSION_CUTOFF:
        raise ValueError("V13_AUTOMATION_HISTORICAL_SESSION_PROHIBITED")
    if target.weekday() >= 5:
        raise ValueError("V13_AUTOMATION_TARGET_WEEKDAY_REQUIRED")
    if source >= target or (target - source).days > 7:
        raise ValueError("V13_AUTOMATION_SOURCE_SESSION_INVALID")
    return target, source


def _decision_time(target: date) -> datetime:
    return datetime.combine(target, time(10, 0), NEW_YORK).astimezone(
        timezone.utc
    )


def automation_acknowledgement(target_session: str) -> str:
    return (
        "I AUTHORIZE AUTOMATIC V13 QUOTE-RECOVERY PAPER EVIDENCE FOR "
        f"{target_session} ONLY; NO LIVE BROKERAGE AUTHORITY"
    )


def session_paths(
    target_session: str, *, automation_root: Path = AUTOMATION_ROOT
) -> SessionPaths:
    target = date.fromisoformat(target_session).isoformat()
    root = automation_root.resolve()
    session_root = (root / target).resolve()
    if session_root.parent != root:
        raise RuntimeError("V13_AUTOMATION_PATH_OUTSIDE_ROOT")
    return SessionPaths(
        session_root,
        session_root / "authorization.json",
        session_root / "collection_attempt.json",
        session_root / "status.json",
    )


def _encoded(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, _encoded(payload))
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_status(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    try:
        os.write(fd, _encoded(payload))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _read_mapping(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    if re.fullmatch(r"V13_[A-Z0-9_]+(?::[A-Z0-9.\-]+)?", message):
        return message
    return f"V13_QUOTE_RECOVERY_AUTOMATION_EXCEPTION:{type(exc).__name__}"


def _active_lease(
    now: datetime,
    validator: Callable[..., Mapping[str, object]] | None,
) -> Mapping[str, object]:
    if validator is None:
        from ml.v13.regime_overlay_lease_renewal_apply import (
            validate_renewal_chain,
        )

        state = validate_renewal_chain(now_utc=now)
    else:
        state = validator(now_utc=now)
    if (
        state.get("valid") is not True
        or state.get("active") is not True
        or state.get("paper_trading_only") is not True
        or state.get("live_trading_enabled") is not False
        or state.get("brokerage_orders") is not False
        or state.get("operator") != OPERATOR
    ):
        raise RuntimeError("V13_AUTOMATION_ACTIVE_PAPER_LEASE_REQUIRED")
    lease_sha = state.get("latest_lease_sha256")
    if not isinstance(lease_sha, str) or len(lease_sha) != 64:
        raise RuntimeError("V13_AUTOMATION_EFFECTIVE_LEASE_IDENTITY_INVALID")
    return state


def _load_authorization(
    path: Path, *, target_session: str, source_session: str
) -> dict[str, object]:
    digest = _require_contract()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_INVALID") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_INVALID")
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "authorization_sha256"
    }
    observed_sha = payload.get("authorization_sha256")
    expected_sha = hashlib.sha256(_encoded(unsigned)).hexdigest()
    expected: dict[str, object] = {
        "authorization_type": "V13_QUOTE_RECOVERY_ONE_SESSION_AUTOMATION",
        "operator": OPERATOR,
        "acknowledgement": automation_acknowledgement(target_session),
        "target_session": target_session,
        "source_session": source_session,
        "market_session_open_asserted": True,
        "automation_contract_sha256": digest,
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "persisted": True,
    }
    if observed_sha != expected_sha or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_CHANGED")
    try:
        authorized_at = datetime.fromisoformat(
            str(payload["authorized_at_utc"])
        )
    except (KeyError, ValueError) as exc:
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_TIME_INVALID") from exc
    target, _ = _session_dates(target_session, source_session)
    if authorized_at.tzinfo is None or _utc(authorized_at) >= _decision_time(target):
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_AFTER_DECISION")
    return payload


def _load_context(
    *,
    inbox_root: Path,
    target_session: str,
    source_session: str,
) -> tuple[dict[str, object], dict[str, object]]:
    root = inbox_root.resolve()
    target = (root / target_session).resolve()
    if target.parent != root:
        raise RuntimeError("V13_AUTOMATION_CONTEXT_OUTSIDE_INBOX")
    try:
        ranking = json.loads(
            (target / "ranking_snapshot.json").read_text(encoding="utf-8")
        )
        control = json.loads(
            (target / "control_context.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("V13_AUTOMATION_SIGNED_CONTEXT_MISSING") from exc
    sessions = (
        control.get("source_decision_sessions")
        if isinstance(control, dict)
        else None
    )
    if (
        not isinstance(ranking, dict)
        or not isinstance(control, dict)
        or ranking.get("session_date") != target_session
        or ranking.get("source_decision_session") != source_session
        or control.get("session_date") != target_session
        or not isinstance(sessions, list)
        or len(sessions) != 2
        or sessions[-1] != source_session
    ):
        raise RuntimeError("V13_AUTOMATION_SIGNED_CONTEXT_MISMATCH")
    for key, payload in (
        ("ranking_sha256", ranking),
        ("control_context_sha256", control),
    ):
        value = payload.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise RuntimeError("V13_AUTOMATION_SIGNED_CONTEXT_MISMATCH")
    return ranking, control


def authorize_session(
    *,
    target_session: str,
    source_session: str,
    operator: str,
    acknowledgement: str,
    market_session_open: bool,
    now_utc: datetime | None = None,
    automation_root: Path = AUTOMATION_ROOT,
) -> dict[str, object]:
    digest = _require_contract()
    target, _ = _session_dates(target_session, source_session)
    now = _utc(now_utc or datetime.now(timezone.utc))
    if now >= _decision_time(target):
        raise RuntimeError(
            "V13_AUTOMATION_AUTHORIZATION_AFTER_DECISION_PROHIBITED"
        )
    if operator.strip() != OPERATOR:
        raise RuntimeError("V13_AUTOMATION_OPERATOR_IDENTITY_INVALID")
    if acknowledgement != automation_acknowledgement(target_session):
        raise RuntimeError("V13_AUTOMATION_EXACT_ACKNOWLEDGEMENT_REQUIRED")
    if market_session_open is not True:
        raise RuntimeError("V13_AUTOMATION_OPEN_SESSION_ASSERTION_REQUIRED")
    payload: dict[str, object] = {
        "authorization_type": "V13_QUOTE_RECOVERY_ONE_SESSION_AUTOMATION",
        "authorized_at_utc": now.isoformat(),
        "operator": OPERATOR,
        "acknowledgement": acknowledgement,
        "target_session": target_session,
        "source_session": source_session,
        "market_session_open_asserted": True,
        "automation_contract_sha256": digest,
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "persisted": True,
    }
    payload["authorization_sha256"] = hashlib.sha256(
        _encoded(payload)
    ).hexdigest()
    path = session_paths(
        target_session, automation_root=automation_root
    ).authorization
    if path.exists():
        existing = _read_mapping(path)
        if existing == payload:
            return {**payload, "status": "DUPLICATE_SAFE_NOOP"}
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_IMMUTABLE_CONFLICT")
    _write_exclusive(path, payload)
    return {**payload, "status": "AUTHORIZED_ONE_SESSION_AUTOMATION"}


def get_session_status(
    *,
    target_session: str,
    source_session: str,
    automation_root: Path = AUTOMATION_ROOT,
) -> dict[str, object]:
    digest = _require_contract()
    _session_dates(target_session, source_session)
    paths = session_paths(target_session, automation_root=automation_root)
    status = _read_mapping(paths.status)
    attempt = _read_mapping(paths.attempt)
    authorized = paths.authorization.exists()
    if authorized:
        _load_authorization(
            paths.authorization,
            target_session=target_session,
            source_session=source_session,
        )
    for label, record in (("ATTEMPT", attempt), ("STATUS", status)):
        if record and (
            record.get("target_session") != target_session
            or record.get("source_session") != source_session
            or record.get("automation_contract_sha256") != digest
        ):
            raise RuntimeError(f"V13_AUTOMATION_{label}_BINDING_INVALID")
    if attempt:
        if status.get("status") in TERMINAL_STATUSES:
            return status
        return {
            "status": "COLLECTION_ATTEMPTED_OUTCOME_UNRECORDED",
            "target_session": target_session,
            "source_session": source_session,
            "attempted_at_utc": attempt.get("attempted_at_utc"),
            "attempt_consumed": True,
            "retry_permitted": False,
            "backfill_permitted": False,
            "evidence_appended": False,
            "failure_reason": "TERMINAL_STATUS_MISSING",
            "market_data_requests": None,
            "contract_sha256": digest,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
    if status:
        return status
    return {
        "status": (
            "AUTHORIZED" if authorized else "NOT_AUTHORIZED"
        ),
        "target_session": target_session,
        "source_session": source_session,
        "attempt_consumed": False,
        "retry_permitted": authorized,
        "backfill_permitted": False,
        "evidence_appended": False,
        "contract_sha256": digest,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def run_preflight(
    *,
    target_session: str,
    source_session: str,
    now_utc: datetime | None = None,
    automation_root: Path = AUTOMATION_ROOT,
    inbox_root: Path = INBOX_ROOT,
    lease_validator: Callable[..., Mapping[str, object]] | None = None,
    require_api_key: bool = True,
) -> dict[str, object]:
    digest = _require_contract()
    target, _ = _session_dates(target_session, source_session)
    now = _utc(now_utc or datetime.now(timezone.utc))
    local = now.astimezone(NEW_YORK)
    if local.date() != target or local.time().replace(tzinfo=None) >= time(10, 0):
        raise RuntimeError("V13_AUTOMATION_PREFLIGHT_OUTSIDE_TARGET_WINDOW")
    paths = session_paths(target_session, automation_root=automation_root)
    authorization = _load_authorization(
        paths.authorization,
        target_session=target_session,
        source_session=source_session,
    )
    lease = _active_lease(now, lease_validator)
    ranking, control = _load_context(
        inbox_root=inbox_root,
        target_session=target_session,
        source_session=source_session,
    )
    if require_api_key and not (os.getenv("TIINGO_API_KEY") or "").strip():
        raise RuntimeError("V13_AUTOMATION_TIINGO_API_KEY_MISSING")
    result: dict[str, object] = {
        "status": "READY_FOR_AUTOMATIC_QUOTE_RECOVERY_COLLECTION",
        "checked_at_utc": now.isoformat(),
        "target_session": target_session,
        "source_session": source_session,
        "operator": authorization["operator"],
        "activation_lease_sha256": lease["latest_lease_sha256"],
        "automation_contract_sha256": digest,
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "ranking_sha256": ranking["ranking_sha256"],
        "control_context_sha256": control["control_context_sha256"],
        "market_data_requests": 0,
        "maximum_market_data_requests": 104,
        "evidence_appended": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_status(paths.status, result)
    return result


def run_collection(
    *,
    target_session: str,
    source_session: str,
    now_utc: datetime | None = None,
    automation_root: Path = AUTOMATION_ROOT,
    inbox_root: Path = INBOX_ROOT,
    lease_validator: Callable[..., Mapping[str, object]] | None = None,
    collector: Callable[..., object] = run_quote_recovery_one_shot,
    require_api_key: bool = True,
) -> dict[str, object]:
    digest = _require_contract()
    target, _ = _session_dates(target_session, source_session)
    now = _utc(now_utc or datetime.now(timezone.utc))
    local = now.astimezone(NEW_YORK)
    current = local.time().replace(tzinfo=None)
    if local.date() != target or not (
        time(10, 0) <= current < time(10, 5)
    ):
        raise RuntimeError("V13_AUTOMATION_OUTSIDE_COLLECTION_WINDOW")
    paths = session_paths(target_session, automation_root=automation_root)
    authorization = _load_authorization(
        paths.authorization,
        target_session=target_session,
        source_session=source_session,
    )
    lease = _active_lease(now, lease_validator)
    ranking, control = _load_context(
        inbox_root=inbox_root,
        target_session=target_session,
        source_session=source_session,
    )
    if require_api_key and not (os.getenv("TIINGO_API_KEY") or "").strip():
        raise RuntimeError("V13_AUTOMATION_TIINGO_API_KEY_MISSING")
    attempt = {
        "attempted_at_utc": now.isoformat(),
        "target_session": target_session,
        "source_session": source_session,
        "operator": authorization["operator"],
        "activation_lease_sha256": lease["latest_lease_sha256"],
        "automation_contract_sha256": digest,
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_exclusive(paths.attempt, attempt)
    try:
        result = collector(
            apply=True,
            now_utc=now,
            operator=str(authorization["operator"]),
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            market_session_open=bool(
                authorization["market_session_open_asserted"]
            ),
            ranking_snapshot=ranking,
            control_context=control,
        )
        result_status = getattr(result, "status", None)
        if result_status not in {
            "FRESH_PAPER_DECISION_RECORDED",
            "DUPLICATE_SAFE_NOOP",
        }:
            raise RuntimeError("V13_AUTOMATION_COLLECTOR_RESULT_INVALID")
    except Exception as exc:
        observed_requests = getattr(exc, "market_data_requests", None)
        if type(observed_requests) is not int or not (
            0 <= observed_requests <= 104
        ):
            observed_requests = None
        failure: dict[str, object] = {
            "status": "COLLECTION_FAILED_NO_EVIDENCE",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "attempted_at_utc": now.isoformat(),
            "target_session": target_session,
            "source_session": source_session,
            "collector_invoked": True,
            "attempt_consumed": True,
            "retry_permitted": False,
            "backfill_permitted": False,
            "failure_reason": _safe_failure_reason(exc),
            "market_data_requests": observed_requests,
            "request_count_status": (
                "RECORDED"
                if observed_requests is not None
                else "UNAVAILABLE_AFTER_PROVIDER_FAILURE"
            ),
            "evidence_appended": False,
            "activation_lease_sha256": lease["latest_lease_sha256"],
            "automation_contract_sha256": digest,
            "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
            "quote_recovery_policy": (
                "ONE_FULL_BATCH_RETRY_THEN_FAIL_CLOSED"
            ),
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
        _write_status(paths.status, failure)
        raise
    output: dict[str, object] = {
        "status": result_status,
        "checked_at_utc": now.isoformat(),
        "target_session": target_session,
        "source_session": source_session,
        "collector_invoked": bool(getattr(result, "collector_invoked", False)),
        "attempt_consumed": True,
        "retry_permitted": False,
        "backfill_permitted": False,
        "market_data_requests": getattr(result, "market_data_requests", None),
        "maximum_market_data_requests": 104,
        "evidence_appended": bool(getattr(result, "event_appended", False)),
        "activation_lease_sha256": getattr(
            result, "activation_lease_sha256", None
        ),
        "automation_contract_sha256": digest,
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "quote_recovery_policy": "ONE_FULL_BATCH_RETRY_THEN_FAIL_CLOSED",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_status(paths.status, output)
    return output


def describe() -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_NOT_AUTHORIZED_NOT_SCHEDULED",
        "contract_sha256": _require_contract(),
        "collector_contract_sha256": COLLECTOR_CONTRACT_SHA256,
        "maximum_attempts_per_session": 1,
        "maximum_market_data_requests": 104,
        "quote_retry": "ONE_FULL_101_SYMBOL_BATCH_AFTER_5_SECONDS",
        "backfill_permitted": False,
        "scheduler_installed": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="V13 one-session quote-recovery automation controller"
    )
    parser.add_argument(
        "--mode",
        choices=("describe", "authorize", "preflight", "collect", "status"),
        default="describe",
    )
    parser.add_argument("--target-session")
    parser.add_argument("--source-session")
    parser.add_argument("--operator", default="")
    parser.add_argument("--acknowledgement", default="")
    parser.add_argument("--market-session-open", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.mode == "describe":
        result = describe()
    else:
        if not args.target_session or not args.source_session:
            parser.error(
                "--target-session and --source-session are required for this mode"
            )
        if args.mode == "authorize":
            if not args.apply:
                parser.error("--apply is required with --mode authorize")
            result = authorize_session(
                target_session=args.target_session,
                source_session=args.source_session,
                operator=args.operator,
                acknowledgement=args.acknowledgement,
                market_session_open=args.market_session_open,
            )
        elif args.mode == "preflight":
            result = run_preflight(
                target_session=args.target_session,
                source_session=args.source_session,
            )
        elif args.mode == "collect":
            if not args.apply:
                parser.error("--apply is required with --mode collect")
            result = run_collection(
                target_session=args.target_session,
                source_session=args.source_session,
            )
        else:
            result = get_session_status(
                target_session=args.target_session,
                source_session=args.source_session,
            )
    print("V13 PARAMETERIZED QUOTE-RECOVERY SESSION AUTOMATION")
    print("=" * 80)
    for key, value in result.items():
        if key not in {"acknowledgement", "authorization_sha256"}:
            print(f"{key.replace('_', ' ').title()}: {value}")
    print("September 8 attempt modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
