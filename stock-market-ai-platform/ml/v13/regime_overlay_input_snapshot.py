"""In-memory signed input snapshots for V13 fresh paper evidence.

All raw bars, quotes, ranks, and regime inputs are supplied by the caller.
This module performs no network I/O and writes no files.  It reuses the locked
V11 feature contract, then emits only the three canonical signed payloads
accepted by the locked V13 observation evaluator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v11.intraday_contract import derive_features, validate_completed_bars
from ml.v13.regime_overlay_contract import EXPECTED_V10_CANDIDATE, EXPECTED_V10_SHA256
from ml.v13.regime_overlay_observation import (
    COMPLETE_INPUT_STATUS,
    COMPLETE_REGIME_STATUS,
    EXPECTED_RANKING_STATUS,
    FRESH_BOUNDARY,
    signed_payload,
)


NEW_YORK = ZoneInfo("America/New_York")
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_input_snapshot_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_input_snapshot_contract.sha256")


@dataclass(frozen=True)
class SignedInputBundle:
    ranking_snapshot: Mapping[str, object]
    intraday_snapshot: Mapping[str, object]
    regime_snapshot: Mapping[str, object]
    market_data_requests: int = 0
    file_writes: int = 0
    brokerage_orders: bool = False


def _require_contract() -> str:
    expected: dict[str, object] = {
        "bar_interval_minutes": 5,
        "brokerage_orders": False,
        "completed_bars_required": 6,
        "entry_time_eastern": "10:00",
        "feature_contract": "V11_INTRADAY_PHASE2_BALANCED_MOMENTUM_CONFIRMATION_V1",
        "file_writes": False,
        "input_authority": "CALLER_SUPPLIED_RAW_MARKET_INPUTS_ONLY",
        "live_trading_enabled": False,
        "market_data_request": False,
        "paper_trading_only": True,
        "ranking_symbols_required": 100,
        "snapshot_symbols_required": 101,
        "status": "PREREGISTERED_IN_MEMORY_INPUT_SNAPSHOT_BUILDER",
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
        raise RuntimeError("V13_INPUT_SNAPSHOT_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if locked != digest or not isinstance(contract, dict):
        raise RuntimeError("V13_INPUT_SNAPSHOT_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_INPUT_SNAPSHOT_CONTRACT_CHANGED")
    return digest


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("V13_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


def _decision_time(session_date: str, timestamp_utc: str) -> datetime:
    parsed_session = date.fromisoformat(session_date)
    decision = _utc(timestamp_utc)
    local = decision.astimezone(NEW_YORK)
    if local.date() != parsed_session or local.time().replace(tzinfo=None) != time(10, 0):
        raise ValueError("V13_DECISION_MUST_BE_1000_EASTERN")
    if decision < FRESH_BOUNDARY:
        raise ValueError("V13_PRE_BOUNDARY_INPUT_PROHIBITED")
    return decision


def _symbols(ranked_symbols: Sequence[str]) -> tuple[str, ...]:
    symbols = tuple(str(symbol).upper() for symbol in ranked_symbols)
    if len(symbols) != 100 or len(set(symbols)) != 100 or "SPY" in symbols:
        raise ValueError("V13_REQUIRES_COMPLETE_100_STOCK_V10_RANKING")
    return symbols


def _number_map(
    values: Mapping[str, object], symbols: Sequence[str], error: str
) -> dict[str, float]:
    result: dict[str, float] = {}
    for symbol in symbols:
        try:
            value = float(values[symbol])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(error) from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(error)
        result[symbol] = value
    return result


def build_signed_input_bundle(
    *,
    session_date: str,
    decision_timestamp_utc: str,
    collected_at_utc: str,
    ranked_symbols: Sequence[str],
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
    previous_closes: Mapping[str, object],
    entry_prices: Mapping[str, object],
    spreads_bps: Mapping[str, object],
    v10_negative_flags: Sequence[bool],
    spy_daily_closes: Sequence[object],
) -> SignedInputBundle:
    """Validate caller inputs and construct the three signed V13 snapshots."""
    _require_contract()
    decision = _decision_time(session_date, decision_timestamp_utc)
    collected = _utc(collected_at_utc)
    if collected < decision or collected < FRESH_BOUNDARY:
        raise ValueError("V13_COLLECTION_MUST_FOLLOW_DECISION_CHECKPOINT")
    ranked = _symbols(ranked_symbols)
    universe = ranked + ("SPY",)
    if set(bars_by_symbol) != set(universe):
        raise ValueError("V13_REQUIRES_EXACT_101_SYMBOL_BAR_UNIVERSE")

    features: dict[str, dict[str, float]] = {}
    completed_bar: datetime | None = None
    for symbol in universe:
        bars = bars_by_symbol[symbol]
        validation = validate_completed_bars(
            bars,
            now_utc=decision,
            expected_symbol=symbol,
            minimum_bars=6,
            maximum_age_seconds=0,
        )
        if not validation.accepted or len(bars) != 6:
            raise ValueError("V13_COMPLETED_BAR_INPUT_REJECTED")
        derived = derive_features(bars, previous_close=float(previous_closes[symbol]))
        if derived.timestamp_utc.astimezone(NEW_YORK).date() != date.fromisoformat(session_date):
            raise ValueError("V13_INTRADAY_SESSION_MISMATCH")
        if completed_bar is None:
            completed_bar = derived.timestamp_utc
        elif derived.timestamp_utc != completed_bar:
            raise ValueError("V13_CROSS_SECTION_COMPLETED_BAR_MISMATCH")
        features[symbol] = {
            "return_15m": derived.return_15m,
            "volume_acceleration": derived.volume_acceleration,
            "realized_volatility_30m": derived.realized_volatility_30m,
        }
    if completed_bar is None:
        raise ValueError("V13_COMPLETED_BAR_INPUT_REJECTED")

    prices = _number_map(entry_prices, ranked, "V13_ENTRY_PRICE_MAP_INVALID")
    spreads: dict[str, float] = {}
    for symbol in ranked:
        try:
            value = float(spreads_bps[symbol])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("V13_SPREAD_MAP_INVALID") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError("V13_SPREAD_MAP_INVALID")
        spreads[symbol] = value
    if len(v10_negative_flags) != 2 or any(type(flag) is not bool for flag in v10_negative_flags):
        raise ValueError("V13_REQUIRES_TWO_V10_NEGATIVE_FLAGS")
    try:
        spy_closes = [float(value) for value in spy_daily_closes]
    except (TypeError, ValueError) as exc:
        raise ValueError("V13_SPY_DAILY_CLOSES_INVALID") from exc
    if len(spy_closes) != 21 or any(not math.isfinite(value) or value <= 0 for value in spy_closes):
        raise ValueError("V13_SPY_DAILY_CLOSES_INVALID")

    ranking = signed_payload(
        {
            "status": EXPECTED_RANKING_STATUS,
            "session_date": session_date,
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "symbols": list(ranked),
        },
        "ranking_sha256",
    )
    intraday = signed_payload(
        {
            "status": COMPLETE_INPUT_STATUS,
            "session_date": session_date,
            "collected_at_utc": collected.isoformat(),
            "completed_bar_utc": completed_bar.isoformat(),
            "entry_timestamp_utc": decision.isoformat(),
            "symbol_count": 101,
            "features": features,
            "entry_prices": prices,
            "spreads_bps": spreads,
        },
        "source_snapshot_sha256",
    )
    regime = signed_payload(
        {
            "status": COMPLETE_REGIME_STATUS,
            "session_date": session_date,
            "collected_at_utc": decision.isoformat(),
            "v10_negative_flags": list(v10_negative_flags),
            "spy_closes": spy_closes,
        },
        "source_regime_sha256",
    )
    return SignedInputBundle(ranking, intraday, regime)


def main() -> None:
    digest = _require_contract()
    print("V13 IN-MEMORY SIGNED INPUT SNAPSHOT BUILDER")
    print("=" * 80)
    print("Status: IMPLEMENTED_NOT_INVOKED")
    print(f"Contract SHA-256: {digest}")
    print("Caller-supplied inputs only: YES")
    print("Market data requested: NO")
    print("Files written: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
