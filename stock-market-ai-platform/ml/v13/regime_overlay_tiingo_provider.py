"""Fail-closed Tiingo input provider for V13 fresh paper evidence.

The provider accepts signed V10 ranking/regime context from its caller and
collects only the raw market inputs required by the locked V13 evaluator.  It
writes no files and has no brokerage interface.  Network activity occurs only
when ``collect_signed_inputs`` is explicitly called with a client.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_contract import EXPECTED_V10_CANDIDATE, EXPECTED_V10_SHA256
from ml.v13.regime_overlay_input_snapshot import SignedInputBundle, build_signed_input_bundle
from ml.v13.regime_overlay_observation import EXPECTED_RANKING_STATUS, canonical_sha256


NEW_YORK = ZoneInfo("America/New_York")
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_tiingo_provider_contract.json")
LOCK_PATH = Path(__file__).with_name("regime_overlay_tiingo_provider_contract.sha256")
COMPLETE_CONTROL_CONTEXT = "COMPLETE_V13_SIGNED_V10_REGIME_CONTEXT"
MAXIMUM_REQUESTS = 103
IEX_COLUMNS = "open,high,low,close,volume"


@dataclass(frozen=True)
class ProviderResult:
    status: str
    bundle: SignedInputBundle
    request_count: int
    symbol_count: int = 101
    paper_trading_only: bool = True
    live_trading_enabled: bool = False
    brokerage_orders: bool = False


def _require_contract() -> str:
    expected: dict[str, object] = {
        "bar_requests": 101,
        "brokerage_orders": False,
        "control_context": "CALLER_SUPPLIED_CANONICALLY_SIGNED_ONLY",
        "daily_requests": 1,
        "entry_quote_policy": "VALID_POSITIVE_BID_AND_ASK_REQUIRED",
        "file_writes": False,
        "intraday_bars": "OPENING_SIX_COMPLETED_FIVE_MINUTE_BARS",
        "live_trading_enabled": False,
        "maximum_requests_per_collection": 103,
        "missing_data_action": "FAIL_CLOSED_NO_SNAPSHOT",
        "paper_trading_only": True,
        "quote_batch_requests": 1,
        "ranking_symbols": 100,
        "source": "TIINGO_IEX_AND_DAILY",
        "status": "PREREGISTERED_V13_TIINGO_INPUT_PROVIDER",
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
        raise RuntimeError("V13_TIINGO_PROVIDER_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if locked != digest or not isinstance(contract, dict):
        raise RuntimeError("V13_TIINGO_PROVIDER_CONTRACT_IDENTITY_CHANGED")
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V13_TIINGO_PROVIDER_CONTRACT_CHANGED")
    return digest


def _utc(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("V13_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError("V13_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


def _validate_signed(payload: Mapping[str, object], field: str, error: str) -> None:
    body = dict(payload)
    observed = body.pop(field, None)
    if observed != canonical_sha256(body):
        raise ValueError(error)


def _control_inputs(
    ranking_snapshot: Mapping[str, object],
    control_context: Mapping[str, object],
    session_date: str,
) -> tuple[tuple[str, ...], tuple[bool, bool]]:
    _validate_signed(ranking_snapshot, "ranking_sha256", "V13_V10_RANKING_SNAPSHOT_SHA_MISMATCH")
    if (
        ranking_snapshot.get("status") != EXPECTED_RANKING_STATUS
        or ranking_snapshot.get("session_date") != session_date
        or ranking_snapshot.get("candidate_id") != EXPECTED_V10_CANDIDATE
        or ranking_snapshot.get("frozen_spec_sha256") != EXPECTED_V10_SHA256
    ):
        raise ValueError("V13_V10_RANKING_CONTEXT_INVALID")
    symbols = tuple(str(value).upper() for value in ranking_snapshot.get("symbols", ()))
    if len(symbols) != 100 or len(set(symbols)) != 100 or "SPY" in symbols:
        raise ValueError("V13_REQUIRES_COMPLETE_100_STOCK_V10_RANKING")

    _validate_signed(control_context, "control_context_sha256", "V13_CONTROL_CONTEXT_SHA_MISMATCH")
    if (
        control_context.get("status") != COMPLETE_CONTROL_CONTEXT
        or control_context.get("session_date") != session_date
        or control_context.get("candidate_id") != EXPECTED_V10_CANDIDATE
        or control_context.get("frozen_spec_sha256") != EXPECTED_V10_SHA256
        or control_context.get("holdout_outcomes_read") is not False
    ):
        raise ValueError("V13_CONTROL_CONTEXT_INVALID")
    flags = control_context.get("v10_negative_flags")
    if (
        not isinstance(flags, Sequence)
        or isinstance(flags, (str, bytes))
        or len(flags) != 2
        or any(type(flag) is not bool for flag in flags)
    ):
        raise ValueError("V13_REQUIRES_TWO_V10_NEGATIVE_FLAGS")
    return symbols, (flags[0], flags[1])


def _positive(value: object, error: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(error)
    return number


def _opening_bars(
    symbol: str,
    rows: Sequence[Mapping[str, object]],
    session_date: str,
) -> list[dict[str, object]]:
    expected = tuple(time(9, 30 + 5 * index) for index in range(6))
    selected: list[dict[str, object]] = []
    for row in rows:
        stamp = _utc(row.get("timestamp_utc"))
        local = stamp.astimezone(NEW_YORK)
        if local.date().isoformat() != session_date:
            continue
        if local.time().replace(tzinfo=None) not in expected:
            continue
        selected.append(
            {
                "symbol": symbol,
                "timestamp_utc": stamp.isoformat(),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            }
        )
    selected.sort(key=lambda row: str(row["timestamp_utc"]))
    observed = tuple(
        _utc(row["timestamp_utc"]).astimezone(NEW_YORK).time().replace(tzinfo=None)
        for row in selected
    )
    if observed != expected:
        raise ValueError(f"V13_OPENING_BARS_INCOMPLETE:{symbol}")
    return selected


class TiingoV13Client:
    """Credential-redacting Tiingo REST client with an auditable request count."""

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout_seconds: int = 30,
        transport: object | None = None,
    ):
        self._token = (token or os.getenv("TIINGO_API_KEY") or "").strip()
        if not self._token:
            raise ValueError("TIINGO_API_KEY is required")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.request_count = 0

    def _get(self, url: str, params: Mapping[str, object]) -> object:
        if self.request_count >= MAXIMUM_REQUESTS:
            raise RuntimeError("V13_TIINGO_REQUEST_BUDGET_EXHAUSTED")
        self.request_count += 1
        try:
            target = f"{url}?{urlencode(dict(params))}"
            request = Request(target, headers={"Authorization": f"Token {self._token}"})
            if self.transport is None:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
            else:
                raw = self.transport(request, self.timeout_seconds)
            return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            raise RuntimeError("V13_TIINGO_REQUEST_FAILED; endpoint credentials redacted") from None

    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        payload = self._get(
            f"https://api.tiingo.com/iex/{symbol}/prices",
            {
                "startDate": session_date,
                "endDate": session_date,
                "resampleFreq": "5min",
                "columns": IEX_COLUMNS,
                "format": "json",
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError("V13_TIINGO_INTRADAY_RESPONSE_INVALID")
        return [
            {
                "symbol": symbol.upper(),
                "timestamp_utc": item.get("date"),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
            }
            for item in payload
            if isinstance(item, Mapping)
        ]

    def get_quotes(self, symbols: Sequence[str]) -> list[Mapping[str, object]]:
        payload = self._get(
            "https://api.tiingo.com/iex/",
            {"tickers": ",".join(symbols)},
        )
        if not isinstance(payload, list) or any(not isinstance(item, Mapping) for item in payload):
            raise RuntimeError("V13_TIINGO_QUOTE_RESPONSE_INVALID")
        return payload

    def get_spy_daily_closes(self, *, start_date: str, end_date: str) -> list[float]:
        payload = self._get(
            "https://api.tiingo.com/tiingo/daily/SPY/prices",
            {"startDate": start_date, "endDate": end_date, "format": "json"},
        )
        if not isinstance(payload, list):
            raise RuntimeError("V13_TIINGO_DAILY_RESPONSE_INVALID")
        values = []
        ordered = sorted(
            (item for item in payload if isinstance(item, Mapping)),
            key=lambda item: str(item.get("date", "")),
        )
        for item in ordered:
            if isinstance(item, Mapping):
                values.append(_positive(item.get("adjClose", item.get("close")), "V13_SPY_DAILY_CLOSE_INVALID"))
        return values


def collect_signed_inputs(
    *,
    now_utc: datetime,
    session_date: str,
    ranking_snapshot: Mapping[str, object],
    control_context: Mapping[str, object],
    client: object,
) -> ProviderResult:
    """Collect one complete 10:00 Eastern input bundle or fail without output."""
    _require_contract()
    if now_utc.tzinfo is None:
        raise ValueError("V13_NOW_MUST_BE_TIMEZONE_AWARE")
    now = now_utc.astimezone(timezone.utc)
    local = now.astimezone(NEW_YORK)
    parsed_session = date.fromisoformat(session_date)
    if local.date() != parsed_session or not (time(10, 0) <= local.time().replace(tzinfo=None) < time(10, 5)):
        raise ValueError("V13_PROVIDER_OUTSIDE_COLLECTION_WINDOW")
    symbols, flags = _control_inputs(ranking_snapshot, control_context, session_date)
    universe = symbols + ("SPY",)
    bars: dict[str, list[dict[str, object]]] = {}
    for symbol in universe:
        raw_rows = client.get_five_minute_bars(symbol, session_date)
        bars[symbol] = _opening_bars(symbol, raw_rows, session_date)

    raw_quotes = client.get_quotes(universe)
    quotes = {str(item.get("ticker", "")).upper(): item for item in raw_quotes}
    if set(quotes) != set(universe):
        raise ValueError("V13_COMPLETE_101_SYMBOL_QUOTES_REQUIRED")
    previous: dict[str, float] = {}
    entry_prices: dict[str, float] = {}
    spreads: dict[str, float] = {}
    for symbol in universe:
        quote = quotes[symbol]
        previous[symbol] = _positive(quote.get("prevClose"), f"V13_PREVIOUS_CLOSE_INVALID:{symbol}")
        bid = _positive(quote.get("bidPrice"), f"V13_BID_INVALID:{symbol}")
        ask = _positive(quote.get("askPrice"), f"V13_ASK_INVALID:{symbol}")
        if ask < bid:
            raise ValueError(f"V13_CROSSED_QUOTE_INVALID:{symbol}")
        midpoint = (bid + ask) / 2.0
        if symbol != "SPY":
            entry_prices[symbol] = midpoint
            spreads[symbol] = (ask - bid) / midpoint * 10000.0

    start_date = (parsed_session - timedelta(days=45)).isoformat()
    last_completed_daily_date = (parsed_session - timedelta(days=1)).isoformat()
    daily = list(
        client.get_spy_daily_closes(
            start_date=start_date,
            end_date=last_completed_daily_date,
        )
    )
    if len(daily) < 21:
        raise ValueError("V13_REQUIRES_21_SPY_DAILY_CLOSES")
    spy_closes = [_positive(value, "V13_SPY_DAILY_CLOSE_INVALID") for value in daily[-21:]]
    raw_request_count = getattr(client, "request_count", None)
    if type(raw_request_count) is not int or raw_request_count != MAXIMUM_REQUESTS:
        raise RuntimeError("V13_TIINGO_REQUEST_COUNT_CHANGED")
    observed_requests = raw_request_count

    decision = local.replace(hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
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
    return ProviderResult("COMPLETE_SIGNED_INPUT_BUNDLE", bundle, observed_requests)


def main() -> None:
    digest = _require_contract()
    print("V13 TIINGO SIGNED-INPUT PROVIDER")
    print("=" * 80)
    print("Status: IMPLEMENTED_NOT_INVOKED")
    print(f"Contract SHA-256: {digest}")
    print("Maximum requests per explicit collection: 103")
    print("Market data requested: NO")
    print("Files written: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
