"""Preregistered, non-activated V13 quote-availability recovery candidate.

The candidate preserves the exact 101-symbol universe and every existing
price-validity gate.  When the first quote batch is incomplete only because a
symbol or a positive bid/ask is missing, it waits exactly five seconds and
requests the same full batch once more.  It never substitutes a trade, quote,
midpoint, symbol, or prior value.  A second failure produces no snapshot or
evidence and never authorizes backfill.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time as clock
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_input_snapshot import build_signed_input_bundle
from ml.v13.regime_overlay_tiingo_provider import (
    ProviderResult,
    _control_inputs,
    _opening_bars,
    _positive,
)


NEW_YORK = ZoneInfo("America/New_York")
CONTRACT_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_contract.json"
)
LOCK_PATH = Path(__file__).with_name(
    "regime_overlay_quote_recovery_contract.sha256"
)
RETRY_DELAY_SECONDS = 5
MAXIMUM_REQUESTS = 104


def _require_contract() -> str:
    expected: dict[str, object] = {
        "bar_requests": 101,
        "brokerage_orders": False,
        "entry_quote_policy": "VALID_POSITIVE_BID_AND_ASK_REQUIRED_NO_SUBSTITUTION",
        "file_writes": False,
        "first_quote_batch_requests": 1,
        "live_trading_enabled": False,
        "maximum_quote_batch_requests": 2,
        "maximum_requests_per_collection": MAXIMUM_REQUESTS,
        "missing_quote_recovery": "ONE_FIXED_DELAY_FULL_BATCH_RETRY",
        "paper_trading_only": True,
        "production_activation": False,
        "retry_delay_seconds": RETRY_DELAY_SECONDS,
        "retry_eligible_conditions": [
            "INCOMPLETE_SYMBOL_SET",
            "MISSING_OR_NONPOSITIVE_BID",
            "MISSING_OR_NONPOSITIVE_ASK",
        ],
        "retry_scope": "EXACT_101_SYMBOL_UNIVERSE",
        "second_failure_action": (
            "FAIL_CLOSED_NO_SNAPSHOT_NO_EVIDENCE_NO_BACKFILL"
        ),
        "source": "TIINGO_IEX_AND_DAILY",
        "status": "PREREGISTERED_V13_QUOTE_RECOVERY_CANDIDATE_NOT_ACTIVATED",
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
        raise RuntimeError("V13_QUOTE_RECOVERY_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != locked or not isinstance(contract, dict):
        raise RuntimeError("V13_QUOTE_RECOVERY_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_QUOTE_RECOVERY_CONTRACT_CHANGED")
    return digest


def _positive_or_false(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _quote_map(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    return {str(item.get("ticker", "")).upper(): item for item in rows}


def _retry_required(
    rows: Sequence[Mapping[str, object]],
    universe: Sequence[str],
) -> bool:
    quotes = _quote_map(rows)
    if set(quotes) != set(universe):
        return True
    return any(
        not _positive_or_false(quotes[symbol].get("bidPrice"))
        or not _positive_or_false(quotes[symbol].get("askPrice"))
        for symbol in universe
    )


def _validated_quotes(
    rows: Sequence[Mapping[str, object]],
    universe: Sequence[str],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    quotes = _quote_map(rows)
    if set(quotes) != set(universe):
        raise ValueError("V13_COMPLETE_101_SYMBOL_QUOTES_REQUIRED")
    previous: dict[str, float] = {}
    entry_prices: dict[str, float] = {}
    spreads: dict[str, float] = {}
    for symbol in universe:
        quote = quotes[symbol]
        previous[symbol] = _positive(
            quote.get("prevClose"), f"V13_PREVIOUS_CLOSE_INVALID:{symbol}"
        )
        bid = _positive(quote.get("bidPrice"), f"V13_BID_INVALID:{symbol}")
        ask = _positive(quote.get("askPrice"), f"V13_ASK_INVALID:{symbol}")
        if ask < bid:
            raise ValueError(f"V13_CROSSED_QUOTE_INVALID:{symbol}")
        midpoint = (bid + ask) / 2.0
        if symbol != "SPY":
            entry_prices[symbol] = midpoint
            spreads[symbol] = (ask - bid) / midpoint * 10000.0
    return previous, entry_prices, spreads


def _attach_request_count(exc: Exception, client: object) -> None:
    observed = getattr(client, "request_count", None)
    if type(observed) is int and observed >= 0:
        setattr(exc, "market_data_requests", observed)


def collect_signed_inputs_with_quote_recovery(
    *,
    now_utc: datetime,
    session_date: str,
    ranking_snapshot: Mapping[str, object],
    control_context: Mapping[str, object],
    client: object,
    sleeper: Callable[[float], None] = clock.sleep,
) -> ProviderResult:
    """Build one bundle using at most one fixed-delay full-batch quote retry."""
    _require_contract()
    try:
        if now_utc.tzinfo is None:
            raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
        now = now_utc.astimezone(timezone.utc)
        local = now.astimezone(NEW_YORK)
        parsed_session = date.fromisoformat(session_date)
        current = local.time().replace(tzinfo=None)
        if local.date() != parsed_session or not (time(10, 0) <= current < time(10, 5)):
            raise ValueError("V13_QUOTE_RECOVERY_OUTSIDE_COLLECTION_WINDOW")
        symbols, flags = _control_inputs(
            ranking_snapshot, control_context, session_date
        )
        universe = symbols + ("SPY",)
        bars: dict[str, list[dict[str, object]]] = {}
        for symbol in universe:
            rows = client.get_five_minute_bars(symbol, session_date)
            bars[symbol] = _opening_bars(symbol, rows, session_date)

        raw_quotes = client.get_quotes(universe)
        if _retry_required(raw_quotes, universe):
            sleeper(float(RETRY_DELAY_SECONDS))
            raw_quotes = client.get_quotes(universe)
        previous, entry_prices, spreads = _validated_quotes(raw_quotes, universe)

        start_date = (parsed_session - timedelta(days=45)).isoformat()
        last_completed = (parsed_session - timedelta(days=1)).isoformat()
        daily = list(
            client.get_spy_daily_closes(
                start_date=start_date,
                end_date=last_completed,
            )
        )
        if len(daily) < 21:
            raise ValueError("V13_REQUIRES_21_SPY_DAILY_CLOSES")
        spy_closes = [
            _positive(value, "V13_SPY_DAILY_CLOSE_INVALID")
            for value in daily[-21:]
        ]
        request_count = getattr(client, "request_count", None)
        if type(request_count) is not int or request_count not in {103, 104}:
            raise RuntimeError("V13_QUOTE_RECOVERY_REQUEST_COUNT_CHANGED")

        decision = local.replace(
            hour=10, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)
        bundle = build_signed_input_bundle(
            session_date=session_date,
            decision_timestamp_utc=decision.isoformat(),
            collected_at_utc=now.isoformat(),
            ranked_symbols=symbols,
            bars_by_symbol=bars,
            previous_closes=previous,
            entry_prices=entry_prices,
            spreads_bps=spreads,
            v10_negative_flags=flags,
            spy_daily_closes=spy_closes,
        )
        return ProviderResult(
            "COMPLETE_SIGNED_INPUT_BUNDLE_QUOTE_RECOVERY_CANDIDATE",
            bundle,
            request_count,
        )
    except (ValueError, RuntimeError) as exc:
        _attach_request_count(exc, client)
        raise


def main() -> None:
    digest = _require_contract()
    print("V13 TIINGO QUOTE-RECOVERY CANDIDATE")
    print("=" * 80)
    print("Status: PREREGISTERED_NOT_ACTIVATED")
    print(f"Contract SHA-256: {digest}")
    print("Quote retry: ONE FULL 101-SYMBOL BATCH AFTER 5 SECONDS")
    print("Maximum requests per collection: 104")
    print("Price substitution: PROHIBITED")
    print("Universe reduction: PROHIBITED")
    print("Second failure: NO SNAPSHOT, NO EVIDENCE, NO BACKFILL")
    print("Market data requested: NO")
    print("Files written: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
