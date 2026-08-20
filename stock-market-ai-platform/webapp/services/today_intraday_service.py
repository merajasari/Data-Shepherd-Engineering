"""Rolling 24-hour intraday data for Live Stock Viewer charts.

Presentation-only. This service never writes to Gold, features, model artifacts,
or holdout evidence.

Primary 24-hour source: the existing local Tiingo IEX stream log. The live
stream already records every received reference-price observation, so this gives
us a fast, entitlement-independent local history without making the dashboard
fan out to external REST calls. Observations are resampled to 5-minute buckets.

Fallback source: Tiingo historical intraday REST, when available for the current
account. The existing live IEX reference-price cache is always used for the
latest mark.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from webapp.services.live_market_service import get_all_live_quotes

CACHE_TTL_SECONDS = 30
IEX_STREAM_LOG = Path("logs/iex_stream.log")
MAX_LOG_BYTES = 32 * 1024 * 1024
_top_cache = {"fetched": 0.0, "payload": None}
_symbol_cache: dict[str, dict] = {}
_log_cache = {"fetched": 0.0, "series": {}}

# Example emitted by data-ingestion/iex_stream.py:
# [LIVE] AAPL   $316.97 2026-08-20T13:46:43.907062240-04:00
_LIVE_RE = re.compile(
    r"\[LIVE\]\s+([A-Z0-9.\-]+)\s+\$?([0-9]+(?:\.[0-9]+)?)\s+(\S+)"
)


def _gold_path(symbol: str) -> Path:
    return Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")


def _latest_local_close(symbol: str):
    path = _gold_path(symbol)
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path, columns=["close"]).tail(1)
        if frame.empty:
            return None
        value = float(frame.iloc[-1]["close"])
        return value if value > 0 else None
    except Exception as exc:
        print(f"[24H PRIOR CLOSE ERROR] {symbol}: {exc}")
        return None


def _daily_closes(symbol: str) -> list[float]:
    path = _gold_path(symbol)
    if not path.exists():
        return []
    try:
        frame = pd.read_parquet(path, columns=["close"]).tail(220)
        values = pd.to_numeric(frame["close"], errors="coerce").dropna().astype(float).tolist()
        return [v for v in values if v > 0]
    except Exception as exc:
        print(f"[24H SMA HISTORY ERROR] {symbol}: {exc}")
        return []


def _read_log_tail(path: Path, max_bytes: int = MAX_LOG_BYTES) -> str:
    """Read only the newest section of a potentially large stream log."""
    if not path.exists():
        return ""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes), os.SEEK_SET)
            raw = fh.read()
        # If we started in the middle of a line, discard that partial first line.
        if size > max_bytes:
            newline = raw.find(b"\n")
            if newline >= 0:
                raw = raw[newline + 1 :]
        return raw.decode("utf-8", errors="ignore")
    except OSError as exc:
        print(f"[24H IEX LOG READ ERROR] {exc}")
        return ""


def _local_iex_24h_series() -> dict[str, list[dict]]:
    """Parse and 5-minute-resample the rolling 24h IEX reference-price log."""
    now_mono = time.monotonic()
    if _log_cache["series"] and now_mono - _log_cache["fetched"] < CACHE_TTL_SECONDS:
        return _log_cache["series"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    parsed: dict[str, list[tuple[datetime, float]]] = {}
    text = _read_log_tail(IEX_STREAM_LOG)
    for line in text.splitlines():
        match = _LIVE_RE.search(line)
        if not match:
            continue
        symbol, price_text, timestamp_text = match.groups()
        try:
            ts = pd.to_datetime(timestamp_text, utc=True, errors="raise").to_pydatetime()
            price = float(price_text)
        except (TypeError, ValueError, OverflowError):
            continue
        if ts < cutoff or price <= 0:
            continue
        parsed.setdefault(symbol, []).append((ts, price))

    result: dict[str, list[dict]] = {}
    for symbol, points in parsed.items():
        if not points:
            continue
        frame = pd.DataFrame(points, columns=["timestamp", "price"]).sort_values("timestamp")
        frame = frame.drop_duplicates("timestamp", keep="last").set_index("timestamp")
        # Last reference price in each 5-minute bucket; do not fabricate missing buckets.
        sampled = frame["price"].resample("5min").last().dropna()
        result[symbol] = [
            {"t": ts.isoformat(), "price": float(price)}
            for ts, price in sampled.items()
            if ts.to_pydatetime() >= cutoff
        ]

    _log_cache["fetched"] = now_mono
    _log_cache["series"] = result
    return result


def _fetch_24h_rest(symbol: str, token: str) -> list[dict]:
    """Fallback to Tiingo historical intraday REST if local stream history is absent."""
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=24)
    params = {
        "startDate": cutoff.date().isoformat(),
        "endDate": now_utc.date().isoformat(),
        "resampleFreq": "5min",
        "afterHours": "true",
        "forceFill": "true",
        "token": token,
    }
    urls = [
        f"https://api.tiingo.com/iex/{symbol}/prices",
        f"https://api.tiingo.com/tiingo/equity/intraday/{symbol}/prices",
    ]
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            candidate = response.json()
            if not isinstance(candidate, list) or not candidate:
                continue
            rows = []
            for item in candidate:
                try:
                    ts = pd.to_datetime(item["date"], utc=True).to_pydatetime()
                    price = float(item.get("close"))
                    if ts >= cutoff and price > 0:
                        rows.append({"t": ts.isoformat(), "price": price})
                except (KeyError, TypeError, ValueError):
                    continue
            if rows:
                rows.sort(key=lambda row: row["t"])
                return rows
        except Exception as exc:
            print(f"[24H INTRADAY REST ERROR] {symbol} {url}: {exc}")
    return []


def _get_24h_rows(symbol: str, token: str | None = None) -> tuple[list[dict], str]:
    local = _local_iex_24h_series().get(symbol, [])
    if len(local) >= 2:
        return local, "LOCAL_IEX_STREAM_LOG_5MIN"
    if token:
        remote = _fetch_24h_rest(symbol, token)
        if len(remote) >= 2:
            return remote, "TIINGO_INTRADAY_REST_5MIN"
    return local, "LOCAL_IEX_STREAM_LOG_5MIN" if local else "UNAVAILABLE"


def _with_provisional_daily_smas(symbol: str, rows: list[dict]) -> list[dict]:
    completed = _daily_closes(symbol)
    if not completed:
        return [{**row, "sma_20": None, "sma_50": None, "sma_200": None} for row in rows]
    result = []
    for row in rows:
        price = float(row["price"])
        enriched = dict(row)
        for n, key in ((20, "sma_20"), (50, "sma_50"), (200, "sma_200")):
            prior = completed[-(n - 1):] if n > 1 else []
            values = prior + [price]
            enriched[key] = sum(values) / len(values) if values else None
        result.append(enriched)
    return result


def get_symbol_24h_intraday(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    now_mono = time.monotonic()
    cached = _symbol_cache.get(symbol)
    if cached and now_mono - cached["fetched"] < CACHE_TTL_SECONDS:
        return cached["payload"]

    token = os.getenv("TIINGO_API_KEY")
    rows, source = _get_24h_rows(symbol, token)
    rows = _with_provisional_daily_smas(symbol, rows)
    live_state = get_all_live_quotes()
    quote = (live_state.get("quotes", {}) or {}).get(symbol) or {}
    try:
        live_price = float(quote.get("reference_price"))
    except (TypeError, ValueError):
        live_price = None
    payload = {
        "window_hours": 24,
        "symbol": symbol,
        "series": rows,
        "updated_at": live_state.get("updated_at"),
        "live": {"reference_price": live_price, "timestamp": quote.get("timestamp")},
        "source": source,
        "point_count": len(rows),
    }
    _symbol_cache[symbol] = {"fetched": now_mono, "payload": payload}
    return payload


def get_today_top10_intraday(symbols: list[str]) -> dict:
    """Return rolling 24-hour series for current Top-10 candidates."""
    now_mono = time.monotonic()
    if _top_cache["payload"] is not None and now_mono - _top_cache["fetched"] < CACHE_TTL_SECONDS:
        return _top_cache["payload"]

    live_state = get_all_live_quotes()
    quotes = live_state.get("quotes", {}) or {}
    local_intraday = _local_iex_24h_series()

    # Rank by actual 24h series return where possible. Fall back to latest local
    # completed close vs live mark only when a symbol lacks enough intraday points.
    ranked = []
    for symbol in symbols:
        rows = local_intraday.get(symbol, [])
        quote = quotes.get(symbol) or {}
        try:
            live_price = float(quote.get("reference_price"))
        except (TypeError, ValueError):
            live_price = None

        if len(rows) >= 2:
            start_price = float(rows[0]["price"])
            end_price = live_price if live_price and live_price > 0 else float(rows[-1]["price"])
            ret = end_price / start_price - 1.0 if start_price > 0 else float("-inf")
            ranked.append((ret, symbol, start_price, end_price))
            continue

        prior_close = _latest_local_close(symbol)
        if prior_close and live_price and prior_close > 0:
            ranked.append((live_price / prior_close - 1.0, symbol, prior_close, live_price))

    ranked.sort(reverse=True)
    candidates = ranked[:10]
    token = os.getenv("TIINGO_API_KEY")
    series: dict[str, list[dict]] = {}
    sources: dict[str, str] = {}

    # Most candidates should already be available from the local IEX stream log.
    missing = []
    for _, symbol, _, _ in candidates:
        rows = local_intraday.get(symbol, [])
        if len(rows) >= 2:
            series[symbol] = rows
            sources[symbol] = "LOCAL_IEX_STREAM_LOG_5MIN"
        elif token:
            missing.append(symbol)

    # Only REST-hydrate missing candidates, avoiding unnecessary external fan-out.
    if missing:
        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
            future_map = {pool.submit(_fetch_24h_rest, symbol, token): symbol for symbol in missing}
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    rows = future.result()
                    if len(rows) >= 2:
                        series[symbol] = rows
                        sources[symbol] = "TIINGO_INTRADAY_REST_5MIN"
                except Exception as exc:
                    print(f"[24H INTRADAY WORKER ERROR] {symbol}: {exc}")

    payload = {
        "window_hours": 24,
        "updated_at": live_state.get("updated_at"),
        "source": "LOCAL_IEX_STREAM_LOG_WITH_TIINGO_REST_FALLBACK",
        "sources": sources,
        "symbols": [symbol for _, symbol, _, _ in candidates],
        "series": series,
        "point_counts": {symbol: len(rows) for symbol, rows in series.items()},
        "live": {
            symbol: {
                "reference_price": live_price,
                "baseline_price": baseline_price,
                "window_return": ret,
                "timestamp": (quotes.get(symbol) or {}).get("timestamp"),
            }
            for ret, symbol, baseline_price, live_price in candidates
        },
    }
    _top_cache["fetched"] = now_mono
    _top_cache["payload"] = payload
    return payload
