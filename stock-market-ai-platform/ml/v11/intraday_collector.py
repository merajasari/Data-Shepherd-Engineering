"""Atomic Tiingo IEX five-minute collector for V11 research.

The collector is deliberately separate from V8/V10 data and evidence roots. It
publishes only a fully validated 100-stock-plus-SPY snapshot, has no brokerage
authority, and never logs credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from ml.v11.intraday_contract import IntradayValidation, validate_completed_bars

ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from v5_symbols import get_v5_data_symbols  # noqa: E402

load_dotenv(ROOT / ".env")

DEFAULT_OUTPUT = ROOT / "data/research/v11/intraday/latest_complete_snapshot.json"
SOURCE = "tiingo_iex_historical_5min"
COLUMNS = "open,high,low,close,volume"
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class CollectionResult:
    status: str
    published: bool
    symbol_count: int
    completed_bar_utc: str | None
    output_path: str
    reasons: tuple[str, ...]
    brokerage_orders: bool = False
    v8_modified: bool = False
    v10_modified: bool = False


class TiingoIntradayClient:
    def __init__(self, token: str | None = None, *, timeout_seconds: int = 30):
        self._token = (token or os.getenv("TIINGO_API_KEY") or "").strip()
        self.timeout_seconds = timeout_seconds
        if not self._token:
            raise ValueError("TIINGO_API_KEY is required")

    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        url = f"https://api.tiingo.com/iex/{symbol}/prices"
        params = {
            "startDate": session_date,
            "endDate": session_date,
            "resampleFreq": "5min",
            "columns": COLUMNS,
            "format": "json",
        }
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Token {self._token}"},
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(
                f"Tiingo V11 intraday request failed for {symbol}: "
                f"{type(exc).__name__}; endpoint credentials redacted"
            ) from None
        if not isinstance(payload, list):
            raise RuntimeError(f"Tiingo V11 intraday response invalid for {symbol}")
        return normalize_rows(symbol, payload)


def normalize_rows(symbol: str, payload: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        rows.append(
            {
                "symbol": symbol.upper(),
                "timestamp_utc": item.get("date"),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
            }
        )
    rows.sort(key=lambda row: str(row["timestamp_utc"]))
    return rows


def _atomic_json_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _digest(series: Mapping[str, Sequence[Mapping[str, object]]]) -> str:
    encoded = json.dumps(series, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _effective_maximum_age_seconds(
    now_utc: datetime,
    session_date: str,
    configured_seconds: int,
) -> int:
    """Allow the same session's final 15:55 bar after the regular close."""
    if now_utc.tzinfo is None:
        return configured_seconds
    try:
        requested_date = date.fromisoformat(session_date)
    except ValueError:
        return configured_seconds
    local_now = now_utc.astimezone(NEW_YORK)
    if local_now.date() != requested_date or local_now.time() < time(16, 0):
        return configured_seconds
    final_bar_end_local = datetime.combine(
        requested_date,
        time(16, 0),
        tzinfo=NEW_YORK,
    )
    seconds_since_close = max(
        0,
        int((local_now - final_bar_end_local).total_seconds()),
    )
    return max(configured_seconds, seconds_since_close + 300)


def collect_complete_snapshot(
    *,
    now_utc: datetime,
    session_date: str,
    client: object,
    output_path: Path = DEFAULT_OUTPUT,
    symbols: Sequence[str] | None = None,
    minimum_bars: int = 6,
    maximum_age_seconds: int = 420,
) -> CollectionResult:
    universe = tuple(symbols or get_v5_data_symbols())
    reasons: list[str] = []
    if len(universe) != 101 or len(set(universe)) != 101 or "SPY" not in universe:
        reasons.append("UNIVERSE_CONTRACT_VIOLATION")
    if now_utc.tzinfo is None:
        reasons.append("NOW_MUST_BE_TIMEZONE_AWARE")

    effective_maximum_age_seconds = _effective_maximum_age_seconds(
        now_utc,
        session_date,
        maximum_age_seconds,
    )
    staged: dict[str, list[dict[str, object]]] = {}
    fetched_latest_timestamps: set[str] = set()
    fetched_bar_counts: set[int] = set()
    for symbol in universe:
        try:
            rows = client.get_five_minute_bars(symbol, session_date)
        except Exception:
            reasons.append(f"FETCH_FAILED:{symbol}")
            continue
        if rows:
            fetched_latest_timestamps.add(str(rows[-1]["timestamp_utc"]))
            fetched_bar_counts.add(len(rows))
        validation = validate_completed_bars(
            rows,
            now_utc=now_utc,
            expected_symbol=symbol,
            minimum_bars=minimum_bars,
            maximum_age_seconds=effective_maximum_age_seconds,
        )
        if validation.accepted:
            staged[symbol] = rows
        else:
            reasons.extend(f"{reason}:{symbol}" for reason in validation.reasons)

    latest_timestamps = {
        str(rows[-1]["timestamp_utc"])
        for rows in staged.values()
        if rows
    }
    bar_counts = {len(rows) for rows in staged.values()}
    if len(staged) != 101:
        reasons.append("COMPLETE_UNIVERSE_NOT_AVAILABLE")
    if len(fetched_latest_timestamps) != 1:
        reasons.append("LATEST_BAR_NOT_ALIGNED")
    if len(fetched_bar_counts) != 1:
        reasons.append("BAR_COUNTS_NOT_ALIGNED")
    final_session_mode = effective_maximum_age_seconds > maximum_age_seconds
    if final_session_mode and len(fetched_latest_timestamps) == 1:
        try:
            final_timestamp = datetime.fromisoformat(
                next(iter(fetched_latest_timestamps)).replace("Z", "+00:00")
            ).astimezone(NEW_YORK)
            if (
                final_timestamp.date().isoformat() != session_date
                or final_timestamp.time().replace(tzinfo=None) != time(15, 55)
            ):
                reasons.append("FINAL_SESSION_BAR_MISSING")
        except ValueError:
            reasons.append("FINAL_SESSION_BAR_MISSING")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return CollectionResult(
            status="WAITING_FOR_COMPLETE_INTRADAY_SNAPSHOT",
            published=False,
            symbol_count=len(staged),
            completed_bar_utc=next(iter(latest_timestamps)) if len(latest_timestamps) == 1 else None,
            output_path=str(output_path.relative_to(ROOT) if output_path.is_relative_to(ROOT) else output_path),
            reasons=unique_reasons,
        )

    completed_bar = next(iter(latest_timestamps))
    payload: dict[str, object] = {
        "contract_id": "V11_INTRADAY_5MIN_RESEARCH_V1",
        "status": "COMPLETE_RESEARCH_SNAPSHOT",
        "source": SOURCE,
        "session_date": session_date,
        "generated_at_utc": now_utc.astimezone(timezone.utc).isoformat(),
        "completed_bar_utc": completed_bar,
        "bar_interval_minutes": 5,
        "freshness_mode": (
            "FINAL_SESSION_SNAPSHOT"
            if final_session_mode
            else "LIVE_SESSION"
        ),
        "symbol_count": len(staged),
        "symbols": list(universe),
        "series_sha256": _digest(staged),
        "series": staged,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    _atomic_json_write(output_path, payload)
    return CollectionResult(
        status="PUBLISHED_COMPLETE_RESEARCH_SNAPSHOT",
        published=True,
        symbol_count=len(staged),
        completed_bar_utc=completed_bar,
        output_path=str(output_path.relative_to(ROOT) if output_path.is_relative_to(ROOT) else output_path),
        reasons=(),
    )


def main() -> None:
    now = datetime.now(timezone.utc)
    session_date = now.astimezone(NEW_YORK).date().isoformat()
    result = collect_complete_snapshot(
        now_utc=now,
        session_date=session_date,
        client=TiingoIntradayClient(),
    )
    print("V11 FIVE-MINUTE INTRADAY COLLECTOR")
    print("=" * 80)
    print(f"Status: {result.status}")
    print(f"Published: {result.published}")
    print(f"Symbols ready: {result.symbol_count}/101")
    print(f"Completed bar: {result.completed_bar_utc or 'NONE'}")
    if result.reasons:
        print("Reasons:")
        for reason in result.reasons[:20]:
            print(f" - {reason}")
        if len(result.reasons) > 20:
            print(f" - ... {len(result.reasons) - 20} additional reasons")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
