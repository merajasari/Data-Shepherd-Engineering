"""Publish signed frozen-V10 context into the isolated V13 inbox.

The production adapter reuses the already-frozen Cycle 3 ranking calculation
against completed shared feature data.  It does not invoke either V10 forward
journal, read holdout outcomes, request market data, change any model, append
V13 evidence, install a scheduler, or expose brokerage authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_contract import EXPECTED_V10_CANDIDATE, EXPECTED_V10_SHA256
from ml.v13.regime_overlay_observation import EXPECTED_RANKING_STATUS, signed_payload
from ml.v13.regime_overlay_tiingo_provider import COMPLETE_CONTROL_CONTEXT


ROOT = Path(__file__).resolve().parents[2]
INBOX_ROOT = ROOT / "data/research/v13/fresh_regime_overlay/inbox"
NEW_YORK = ZoneInfo("America/New_York")
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_context_publisher_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_context_publisher_contract.sha256")


@dataclass(frozen=True)
class ContextPublication:
    status: str
    session_date: str
    source_decision_session: str
    ranking_path: str
    control_context_path: str
    published: bool
    duplicate_safe: bool
    market_data_requests: int = 0
    evidence_appended: bool = False
    brokerage_orders: bool = False


def source_availability(
    *, source_decision_session: str, completed_dates: Sequence[object]
) -> dict[str, object]:
    """Describe source-date availability without ranking, network, or writes."""
    requested = date.fromisoformat(source_decision_session)
    parsed = sorted({date.fromisoformat(str(value)[:10]) for value in completed_dates})
    eligible = [value for value in parsed if value <= requested]
    latest = eligible[-1].isoformat() if eligible else None
    return {
        "requested_source_session": requested.isoformat(),
        "latest_available_completed_session": latest,
        "available_completed_session_count": len(parsed),
        "requested_source_available": bool(eligible and eligible[-1] == requested),
        "status": "AVAILABLE" if eligible and eligible[-1] == requested else "UNAVAILABLE",
    }


def inspect_source_availability(source_decision_session: str) -> dict[str, object]:
    """Inspect the frozen source's local completed-date index without writes."""
    from ml.v10 import cycle3_accelerated_forward_runner as frozen

    frozen.verify_frozen_source()
    _, _, dates, _ = frozen._load_market()
    return source_availability(
        source_decision_session=source_decision_session,
        completed_dates=dates,
    )


def _require_contract() -> str:
    expected: dict[str, object] = {
        "brokerage_orders": False,
        "candidate_id": EXPECTED_V10_CANDIDATE,
        "duplicate_safe": True,
        "frozen_v10_sha256": EXPECTED_V10_SHA256,
        "holdout_outcomes_read": False,
        "live_trading_enabled": False,
        "market_data_request": False,
        "output_root": "V13_FRESH_REGIME_OVERLAY_INBOX_ONLY",
        "paper_trading_only": True,
        "ranking_symbols_required": 100,
        "regime_flags_required": 2,
        "source": "READ_ONLY_FROZEN_V10_CYCLE3_RANKING_LOGIC",
        "source_session": "LATEST_COMPLETED_SESSION_BEFORE_TARGET",
        "status": "PREREGISTERED_V13_SIGNED_CONTEXT_PUBLISHER",
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
        "v13_evidence_append": False,
    }
    try:
        raw = CONTRACT_PATH.read_bytes()
        contract = json.loads(raw)
        locked = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError("V13_CONTEXT_PUBLISHER_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if locked != digest or not isinstance(contract, dict):
        raise RuntimeError("V13_CONTEXT_PUBLISHER_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_CONTEXT_PUBLISHER_CONTRACT_CHANGED")
    return digest


def build_signed_context(
    *,
    session_date: str,
    source_decision_session: str,
    ranked_symbols: Sequence[str],
    v10_negative_flags: Sequence[bool],
    v10_negative_sessions: Sequence[str],
) -> tuple[dict[str, object], dict[str, object]]:
    """Build the exact signed payload pair consumed by the V13 provider."""
    target = date.fromisoformat(session_date)
    source = date.fromisoformat(source_decision_session)
    if source >= target:
        raise ValueError("V13_CONTEXT_SOURCE_MUST_PRECEDE_TARGET_SESSION")
    symbols = tuple(str(symbol).upper() for symbol in ranked_symbols)
    if len(symbols) != 100 or len(set(symbols)) != 100 or "SPY" in symbols:
        raise ValueError("V13_REQUIRES_COMPLETE_100_STOCK_V10_RANKING")
    if (
        len(v10_negative_flags) != 2
        or any(type(flag) is not bool for flag in v10_negative_flags)
    ):
        raise ValueError("V13_REQUIRES_TWO_V10_NEGATIVE_FLAGS")
    if len(v10_negative_sessions) != 2:
        raise ValueError("V13_REQUIRES_TWO_EXACT_REGIME_SESSION_DATES")
    regime_sessions = tuple(date.fromisoformat(str(value)) for value in v10_negative_sessions)
    if not regime_sessions[0] < regime_sessions[1] == source:
        raise ValueError("V13_REGIME_SESSIONS_MUST_END_AT_DECLARED_SOURCE")
    ranking = signed_payload(
        {
            "status": EXPECTED_RANKING_STATUS,
            "session_date": session_date,
            "source_decision_session": source_decision_session,
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "symbols": list(symbols),
            "holdout_outcomes_read": False,
            "v8_modified": False,
            "v10_modified": False,
        },
        "ranking_sha256",
    )
    control = signed_payload(
        {
            "status": COMPLETE_CONTROL_CONTEXT,
            "session_date": session_date,
            "source_decision_sessions": [
                value.isoformat() for value in regime_sessions
            ],
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "v10_negative_flags": list(v10_negative_flags),
            "holdout_outcomes_read": False,
            "v8_modified": False,
            "v10_modified": False,
        },
        "control_context_sha256",
    )
    return ranking, control


def _production_source(
    source_decision_session: str,
) -> tuple[Sequence[str], Sequence[bool], Sequence[str]]:
    """Derive context without reading either prospective outcome journal."""
    from ml.v10 import cycle3_accelerated_forward_runner as frozen

    frozen.verify_frozen_source()
    symbols, frames, dates, date_to_idx = frozen._load_market()
    source_date = date.fromisoformat(source_decision_session)
    availability = source_availability(
        source_decision_session=source_decision_session,
        completed_dates=dates,
    )
    eligible = [stamp for stamp in dates if stamp.date() <= source_date]
    if not eligible or eligible[-1].date() != source_date:
        raise RuntimeError(
            "V13_DECLARED_SOURCE_SESSION_NOT_AVAILABLE:"
            f"LATEST_AVAILABLE={availability['latest_available_completed_session']}"
        )
    if dates.index(eligible[-1]) < 1:
        raise RuntimeError("V13_TWO_COMPLETED_REGIME_SESSIONS_REQUIRED")
    source_stamp = eligible[-1]
    source_index = date_to_idx[source_stamp]
    previous_stamp = dates[source_index - 1]
    ranking = frozen._rank_for_date(
        source_stamp,
        symbols,
        frames,
        dates,
        date_to_idx,
    )
    if len(ranking) != 100:
        raise RuntimeError("V13_FROZEN_V10_RANKING_NOT_COMPLETE")
    ordered = ranking.sort_values(
        ["score", "symbol"], ascending=[False, True]
    )["symbol"].astype(str).str.upper().tolist()
    def negative_spy20(timestamp: object) -> bool:
        returns = frames["SPY"].loc[:timestamp, "ret1"].dropna().tail(20)
        if len(returns) < 20:
            return False
        trailing = float((1.0 + returns).prod() - 1.0)
        return math.isfinite(trailing) and trailing < 0.0

    flags = [negative_spy20(previous_stamp), negative_spy20(source_stamp)]
    regime_sessions = [
        previous_stamp.date().isoformat(),
        source_stamp.date().isoformat(),
    ]
    return ordered, flags, regime_sessions


def _encoded(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_file(path: Path, payload: Mapping[str, object]) -> None:
    data = _encoded(payload)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_signed_context(
    *,
    session_date: str,
    source_decision_session: str,
    ranking_snapshot: Mapping[str, object],
    control_context: Mapping[str, object],
    inbox_root: Path = INBOX_ROOT,
) -> ContextPublication:
    """Atomically create one immutable session inbox or no-op identically."""
    _require_contract()
    expected_ranking, expected_control = build_signed_context(
        session_date=session_date,
        source_decision_session=source_decision_session,
        ranked_symbols=ranking_snapshot.get("symbols", ()),
        v10_negative_flags=control_context.get("v10_negative_flags", ()),
        v10_negative_sessions=control_context.get("source_decision_sessions", ()),
    )
    if dict(ranking_snapshot) != expected_ranking or dict(control_context) != expected_control:
        raise ValueError("V13_CONTEXT_PUBLICATION_PAIR_INVALID")
    root = inbox_root.resolve()
    target = (root / session_date).resolve()
    if target.parent != root:
        raise RuntimeError("V13_CONTEXT_TARGET_OUTSIDE_INBOX")
    ranking_name = "ranking_snapshot.json"
    control_name = "control_context.json"
    ranking_bytes = _encoded(ranking_snapshot)
    control_bytes = _encoded(control_context)
    if target.exists():
        expected_names = {ranking_name, control_name}
        if not target.is_dir() or {item.name for item in target.iterdir()} != expected_names:
            raise RuntimeError("V13_CONTEXT_INBOX_SESSION_INCOMPLETE")
        identical = (
            (target / ranking_name).read_bytes() == ranking_bytes
            and (target / control_name).read_bytes() == control_bytes
        )
        if not identical:
            raise RuntimeError("V13_CONTEXT_INBOX_IMMUTABLE_CONFLICT")
        return ContextPublication(
            "DUPLICATE_SAFE_NOOP",
            session_date,
            source_decision_session,
            str(target / ranking_name),
            str(target / control_name),
            False,
            True,
        )

    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{session_date}.", dir=root))
    try:
        _write_file(staging / ranking_name, ranking_snapshot)
        _write_file(staging / control_name, control_context)
        os.replace(staging, target)
    except Exception:
        for child in staging.iterdir() if staging.exists() else ():
            child.unlink(missing_ok=True)
        if staging.exists():
            staging.rmdir()
        raise
    return ContextPublication(
        "PUBLISHED_SIGNED_V13_CONTEXT",
        session_date,
        source_decision_session,
        str(target / ranking_name),
        str(target / control_name),
        True,
        False,
    )


def derive_and_publish(
    *,
    session_date: str,
    source_decision_session: str,
    now_utc: datetime | None = None,
    inbox_root: Path = INBOX_ROOT,
    source_loader: Callable[
        [str], tuple[Sequence[str], Sequence[bool], Sequence[str]]
    ] = _production_source,
) -> ContextPublication:
    """Derive frozen context and publish it before the target window closes."""
    _require_contract()
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
    local = now.astimezone(NEW_YORK)
    target = date.fromisoformat(session_date)
    if local.date() > target or (
        local.date() == target and local.time().replace(tzinfo=None) >= time(10, 5)
    ):
        raise RuntimeError("V13_CONTEXT_CANNOT_BE_PUBLISHED_AFTER_COLLECTION_WINDOW")
    symbols, flags, regime_sessions = source_loader(source_decision_session)
    ranking, control = build_signed_context(
        session_date=session_date,
        source_decision_session=source_decision_session,
        ranked_symbols=symbols,
        v10_negative_flags=flags,
        v10_negative_sessions=regime_sessions,
    )
    return publish_signed_context(
        session_date=session_date,
        source_decision_session=source_decision_session,
        ranking_snapshot=ranking,
        control_context=control,
        inbox_root=inbox_root,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish signed frozen-V10 context for V13")
    parser.add_argument("--session-date")
    parser.add_argument("--source-decision-session")
    parser.add_argument("--diagnose-source", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    digest = _require_contract()
    if args.apply:
        if not args.session_date or not args.source_decision_session:
            parser.error("--session-date and --source-decision-session are required with --apply")
        result = derive_and_publish(
            session_date=args.session_date,
            source_decision_session=args.source_decision_session,
        )
        status = result.status
        ranking_path = result.ranking_path
        control_path = result.control_context_path
    elif args.diagnose_source:
        if not args.source_decision_session:
            parser.error("--source-decision-session is required with --diagnose-source")
        availability = inspect_source_availability(args.source_decision_session)
        status = f"SOURCE_{availability['status']}"
        ranking_path = str(availability["latest_available_completed_session"] or "NONE")
        control_path = "NO_WRITES"
    else:
        status = "IMPLEMENTED_NOT_INVOKED"
        ranking_path = "NONE"
        control_path = "NONE"
    print("V13 SIGNED FROZEN-V10 INBOX CONTEXT PUBLISHER")
    print("=" * 80)
    print(f"Status: {status}")
    print(f"Contract SHA-256: {digest}")
    print(f"Ranking snapshot: {ranking_path}")
    print(f"Control context: {control_path}")
    if args.diagnose_source:
        print(f"Requested source session: {args.source_decision_session}")
        print(f"Latest available completed session: {ranking_path}")
        print("Source availability diagnostic: READ ONLY")
    print("Holdout outcomes read: NO")
    print("Market data requested: NO")
    print("V13 evidence appended: NO")
    print("V8/V10/V11/V12 modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
