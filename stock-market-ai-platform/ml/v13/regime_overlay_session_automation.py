"""Preauthorized one-session automation for V13 fresh paper evidence.

The operator authorizes one exact target session before its decision window.
The scheduled runtime may then perform a read-only preflight and invoke the
existing guarded one-shot collector once.  It cannot renew leases, publish
context, backfill missed sessions, trade live, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_one_shot import run_one_shot


ROOT = Path(__file__).resolve().parents[2]
NEW_YORK = ZoneInfo("America/New_York")
TARGET_SESSION = "2026-09-08"
SOURCE_SESSION = "2026-09-04"
AUTOMATION_ACKNOWLEDGEMENT = (
    "I AUTHORIZE AUTOMATIC V13 FRESH PAPER EVIDENCE FOR 2026-09-08 ONLY; "
    "NO LIVE BROKERAGE AUTHORITY"
)
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_session_automation_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_session_automation_contract.sha256"
)
AUTOMATION_ROOT = (
    ROOT / "data/research/v13/fresh_regime_overlay/automation" / TARGET_SESSION
)
AUTHORIZATION_PATH = AUTOMATION_ROOT / "authorization.json"
ATTEMPT_PATH = AUTOMATION_ROOT / "collection_attempt.json"
STATUS_PATH = AUTOMATION_ROOT / "status.json"
INBOX_ROOT = ROOT / "data/research/v13/fresh_regime_overlay/inbox"
TERMINAL_STATUSES = {
    "COLLECTION_FAILED_NO_EVIDENCE",
    "FRESH_PAPER_DECISION_RECORDED",
}


def _require_contract() -> str:
    expected: dict[str, object] = {
        "active_paper_only_lease_required": True,
        "automatic_context_publication": False,
        "brokerage_orders": False,
        "collection_window_eastern": "10:00_INCLUSIVE_TO_10:05_EXCLUSIVE",
        "existing_guarded_one_shot_required": True,
        "live_trading_enabled": False,
        "market_session_open_operator_assertion": True,
        "maximum_attempts_per_session": 1,
        "no_backfill": True,
        "operator_authorization_required_before_window": True,
        "paper_trading_only": True,
        "scheduler_installation": "EXPLICIT_OPERATOR_INSTALL_ONLY",
        "signed_context_required": True,
        "source_session": SOURCE_SESSION,
        "status": "PREREGISTERED_V13_ONE_SESSION_AUTOMATION",
        "target_session": TARGET_SESSION,
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
        raise RuntimeError("V13_SESSION_AUTOMATION_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != locked or not isinstance(contract, dict):
        raise RuntimeError("V13_SESSION_AUTOMATION_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_SESSION_AUTOMATION_CONTRACT_CHANGED")
    return digest


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("V13_AUTOMATION_TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _encoded(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _encoded(payload)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_status(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = _encoded(payload)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
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
    """Return a bounded V13 error code without leaking credentials or URLs."""
    message = str(exc).strip()
    if re.fullmatch(r"V13_[A-Z0-9_]+(?::[A-Z0-9.\-]+)?", message):
        return message
    return f"V13_AUTOMATION_COLLECTION_EXCEPTION:{type(exc).__name__}"


def get_session_status(
    *,
    authorization_path: Path = AUTHORIZATION_PATH,
    attempt_path: Path = ATTEMPT_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, object]:
    """Report the most advanced immutable state; an attempt outranks authorization."""
    digest = _require_contract()
    status = _read_mapping(status_path)
    attempt = _read_mapping(attempt_path)
    authorized = authorization_path.exists()
    if attempt:
        if status.get("status") in TERMINAL_STATUSES:
            return status
        return {
            "status": "COLLECTION_ATTEMPTED_OUTCOME_UNRECORDED",
            "target_session": TARGET_SESSION,
            "attempted_at_utc": attempt.get("attempted_at_utc"),
            "attempt_consumed": True,
            "retry_permitted": False,
            "backfill_permitted": False,
            "evidence_appended": False,
            "failure_reason": "TERMINAL_STATUS_MISSING_SEE_IMMUTABLE_ERROR_LOG",
            "market_data_requests": None,
            "request_count_status": "UNAVAILABLE_AFTER_UNHANDLED_PROVIDER_FAILURE",
            "contract_sha256": digest,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
    if status:
        return status
    return {
        "status": "AUTHORIZED" if authorized else "NOT_AUTHORIZED",
        "target_session": TARGET_SESSION,
        "attempt_consumed": False,
        "retry_permitted": authorized,
        "backfill_permitted": False,
        "evidence_appended": False,
        "contract_sha256": digest,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def authorize_session(
    *,
    operator: str,
    acknowledgement: str,
    now_utc: datetime | None = None,
    authorization_path: Path = AUTHORIZATION_PATH,
) -> dict[str, object]:
    """Persist one immutable pre-window authorization for the target session."""
    digest = _require_contract()
    now = _utc(now_utc or datetime.now(timezone.utc))
    deadline = datetime.fromisoformat(f"{TARGET_SESSION}T14:00:00+00:00")
    if now >= deadline:
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_AFTER_DECISION_PROHIBITED")
    identity = operator.strip()
    if identity != "Meraj Asari":
        raise RuntimeError("V13_AUTOMATION_OPERATOR_IDENTITY_INVALID")
    if acknowledgement != AUTOMATION_ACKNOWLEDGEMENT:
        raise RuntimeError("V13_AUTOMATION_EXACT_ACKNOWLEDGEMENT_REQUIRED")
    payload: dict[str, object] = {
        "authorization_type": "V13_ONE_SESSION_AUTOMATION",
        "authorized_at_utc": now.isoformat(),
        "operator": identity,
        "acknowledgement": acknowledgement,
        "target_session": TARGET_SESSION,
        "source_session": SOURCE_SESSION,
        "market_session_open_asserted": True,
        "session_automation_contract_sha256": digest,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "persisted": True,
    }
    payload["authorization_sha256"] = hashlib.sha256(_encoded(payload)).hexdigest()
    if authorization_path.exists():
        existing = json.loads(authorization_path.read_text(encoding="utf-8"))
        if existing == payload:
            return {**payload, "status": "DUPLICATE_SAFE_NOOP"}
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_IMMUTABLE_CONFLICT")
    _write_exclusive(authorization_path, payload)
    return {**payload, "status": "AUTHORIZED_ONE_SESSION_AUTOMATION"}


def _load_authorization(path: Path) -> dict[str, object]:
    digest = _require_contract()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_INVALID") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_INVALID")
    observed = payload.pop("authorization_sha256", None)
    expected_sha = hashlib.sha256(_encoded(payload)).hexdigest()
    payload["authorization_sha256"] = observed
    expected = {
        "authorization_type": "V13_ONE_SESSION_AUTOMATION",
        "operator": "Meraj Asari",
        "acknowledgement": AUTOMATION_ACKNOWLEDGEMENT,
        "target_session": TARGET_SESSION,
        "source_session": SOURCE_SESSION,
        "market_session_open_asserted": True,
        "session_automation_contract_sha256": digest,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "persisted": True,
    }
    if observed != expected_sha or any(payload.get(k) != v for k, v in expected.items()):
        raise RuntimeError("V13_AUTOMATION_AUTHORIZATION_CHANGED")
    return payload


def _load_context(inbox_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    target = (inbox_root.resolve() / TARGET_SESSION).resolve()
    if target.parent != inbox_root.resolve():
        raise RuntimeError("V13_AUTOMATION_CONTEXT_OUTSIDE_INBOX")
    try:
        ranking = json.loads((target / "ranking_snapshot.json").read_text(encoding="utf-8"))
        control = json.loads((target / "control_context.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("V13_AUTOMATION_SIGNED_CONTEXT_MISSING") from exc
    if (
        not isinstance(ranking, dict)
        or not isinstance(control, dict)
        or ranking.get("session_date") != TARGET_SESSION
        or ranking.get("source_decision_session") != SOURCE_SESSION
        or control.get("session_date") != TARGET_SESSION
    ):
        raise RuntimeError("V13_AUTOMATION_SIGNED_CONTEXT_MISMATCH")
    return ranking, control


def _active_lease(
    now: datetime,
    validator: Callable[..., Mapping[str, object]] | None,
) -> Mapping[str, object]:
    if validator is None:
        from ml.v13.regime_overlay_lease_renewal_apply import validate_renewal_chain

        state = validate_renewal_chain(now_utc=now)
    else:
        state = validator(now_utc=now)
    if (
        state.get("valid") is not True
        or state.get("active") is not True
        or state.get("paper_trading_only") is not True
        or state.get("live_trading_enabled") is not False
        or state.get("brokerage_orders") is not False
        or state.get("operator") != "Meraj Asari"
    ):
        raise RuntimeError("V13_AUTOMATION_ACTIVE_PAPER_LEASE_REQUIRED")
    return state


def run_preflight(
    *,
    now_utc: datetime | None = None,
    authorization_path: Path = AUTHORIZATION_PATH,
    inbox_root: Path = INBOX_ROOT,
    status_path: Path = STATUS_PATH,
    lease_validator: Callable[..., Mapping[str, object]] | None = None,
    require_api_key: bool = True,
) -> dict[str, object]:
    """Validate the one-session automation without requesting market data."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    local = now.astimezone(NEW_YORK)
    if local.date() != date.fromisoformat(TARGET_SESSION) or local.time().replace(tzinfo=None) >= time(10, 0):
        raise RuntimeError("V13_AUTOMATION_PREFLIGHT_OUTSIDE_TARGET_WINDOW")
    authorization = _load_authorization(authorization_path)
    lease = _active_lease(now, lease_validator)
    ranking, control = _load_context(inbox_root)
    if require_api_key and not (os.getenv("TIINGO_API_KEY") or "").strip():
        raise RuntimeError("V13_AUTOMATION_TIINGO_API_KEY_MISSING")
    result: dict[str, object] = {
        "status": "READY_FOR_AUTOMATIC_COLLECTION",
        "checked_at_utc": now.isoformat(),
        "target_session": TARGET_SESSION,
        "source_session": SOURCE_SESSION,
        "operator": authorization["operator"],
        "activation_lease_sha256": lease.get("latest_lease_sha256"),
        "ranking_sha256": ranking.get("ranking_sha256"),
        "control_context_sha256": control.get("control_context_sha256"),
        "market_data_requests": 0,
        "evidence_appended": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_status(status_path, result)
    return result


def run_collection(
    *,
    now_utc: datetime | None = None,
    authorization_path: Path = AUTHORIZATION_PATH,
    attempt_path: Path = ATTEMPT_PATH,
    inbox_root: Path = INBOX_ROOT,
    status_path: Path = STATUS_PATH,
    lease_validator: Callable[..., Mapping[str, object]] | None = None,
    collector: Callable[..., object] = run_one_shot,
    require_api_key: bool = True,
) -> dict[str, object]:
    """Invoke the guarded one-shot exactly once during the target window."""
    now = _utc(now_utc or datetime.now(timezone.utc))
    local = now.astimezone(NEW_YORK)
    current = local.time().replace(tzinfo=None)
    if local.date() != date.fromisoformat(TARGET_SESSION) or not (time(10, 0) <= current < time(10, 5)):
        raise RuntimeError("V13_AUTOMATION_OUTSIDE_COLLECTION_WINDOW")
    authorization = _load_authorization(authorization_path)
    lease = _active_lease(now, lease_validator)
    ranking, control = _load_context(inbox_root)
    if require_api_key and not (os.getenv("TIINGO_API_KEY") or "").strip():
        raise RuntimeError("V13_AUTOMATION_TIINGO_API_KEY_MISSING")
    attempt = {
        "attempted_at_utc": now.isoformat(),
        "target_session": TARGET_SESSION,
        "operator": authorization["operator"],
        "activation_lease_sha256": lease.get("latest_lease_sha256"),
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_exclusive(attempt_path, attempt)
    try:
        result = collector(
            apply=True,
            now_utc=now,
            operator=str(authorization["operator"]),
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            market_session_open=bool(authorization["market_session_open_asserted"]),
            ranking_snapshot=ranking,
            control_context=control,
        )
    except Exception as exc:
        observed_requests = getattr(exc, "market_data_requests", None)
        if type(observed_requests) is not int or observed_requests < 0:
            observed_requests = None
        failure: dict[str, object] = {
            "status": "COLLECTION_FAILED_NO_EVIDENCE",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "attempted_at_utc": now.isoformat(),
            "target_session": TARGET_SESSION,
            "source_session": SOURCE_SESSION,
            "collector_invoked": True,
            "attempt_consumed": True,
            "retry_permitted": False,
            "backfill_permitted": False,
            "failure_reason": _safe_failure_reason(exc),
            "market_data_requests": observed_requests,
            "request_count_status": (
                "RECORDED" if observed_requests is not None
                else "UNAVAILABLE_AFTER_PROVIDER_FAILURE"
            ),
            "evidence_appended": False,
            "activation_lease_sha256": lease.get("latest_lease_sha256"),
            "missing_quote_policy": "FAIL_SESSION_NO_EVIDENCE_NO_RETRY",
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
        _write_status(status_path, failure)
        raise
    output: dict[str, object] = {
        "status": getattr(result, "status"),
        "checked_at_utc": now.isoformat(),
        "target_session": TARGET_SESSION,
        "source_session": SOURCE_SESSION,
        "collector_invoked": getattr(result, "collector_invoked"),
        "attempt_consumed": True,
        "retry_permitted": False,
        "backfill_permitted": False,
        "market_data_requests": getattr(result, "market_data_requests"),
        "evidence_appended": getattr(result, "event_appended"),
        "activation_lease_sha256": getattr(result, "activation_lease_sha256"),
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }
    _write_status(status_path, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="V13 one-session automatic paper collector")
    parser.add_argument("--mode", choices=("authorize", "preflight", "collect", "status"), required=True)
    parser.add_argument("--operator", default="")
    parser.add_argument("--acknowledgement", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    digest = _require_contract()
    if args.mode == "authorize":
        if not args.apply:
            parser.error("--apply is required with --mode authorize")
        result = authorize_session(operator=args.operator, acknowledgement=args.acknowledgement)
    elif args.mode == "preflight":
        result = run_preflight()
    elif args.mode == "collect":
        result = run_collection()
    else:
        result = get_session_status()
    print("V13 ONE-SESSION AUTOMATIC PAPER-EVIDENCE CONTROL")
    print("=" * 80)
    for key, value in result.items():
        if key not in {"acknowledgement", "authorization_sha256"}:
            print(f"{key.replace('_', ' ').title()}: {value}")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
