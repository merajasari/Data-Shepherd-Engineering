"""Rolling 24-hour intraday data for Live Stock Viewer charts.

Presentation-only. This service never writes to Gold, features, model artifacts,
or holdout evidence. It uses Tiingo intraday history plus the existing live IEX
reference-price cache.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from webapp.services.live_market_service import get_all_live_quotes

CACHE_TTL_SECONDS = 60
_top_cache = {"fetched": 0.0, "payload": None}
_symbol_cache: dict[str, dict] = {}


def _latest_local_close(symbol: str):
    path = Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")
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


def _fetch_24h(symbol: str, token: str) -> list[dict]:
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
        f"https://api.tiingo.com/tiingo/equity/intraday/{symbol}/prices",
        f"https://api.tiingo.com/iex/{symbol}/prices",
    ]
    payload = None
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            candidate = response.json()
            if isinstance(candidate, list) and candidate:
                payload = candidate
                break
        except Exception as exc:
            print(f"[24H INTRADAY ERROR] {symbol} {url}: {exc}")

    rows = []
    for item in payload or []:
        try:
            ts = pd.to_datetime(item["date"], utc=True).to_pydatetime()
            price = float(item.get("close"))
            if ts >= cutoff and price > 0:
                rows.append({"t": ts.isoformat(), "price": price})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: row["t"])
    return rows


def get_symbol_24h_intraday(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    now_mono = time.monotonic()
    cached = _symbol_cache.get(symbol)
    if cached and now_mono - cached["fetched"] < CACHE_TTL_SECONDS:
        return cached["payload"]

    token = os.getenv("TIINGO_API_KEY")
    rows = _fetch_24h(symbol, token) if token else []
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
        "live": {
            "reference_price": live_price,
            "timestamp": quote.get("timestamp"),
        },
        "source": "TIINGO_INTRADAY_5MIN_PLUS_LIVE_IEX",
    }
    _symbol_cache[symbol] = {"fetched": now_mono, "payload": payload}
    return payload


def get_today_top10_intraday(symbols: list[str]) -> dict:
    """Return a rolling 24-hour series for current Top-10 candidates."""
    now_mono = time.monotonic()
    if _top_cache["payload"] is not None and now_mono - _top_cache["fetched"] < CACHE_TTL_SECONDS:
        return _top_cache["payload"]

    live_state = get_all_live_quotes()
    quotes = live_state.get("quotes", {}) or {}
    ranked = []
    for symbol in symbols:
        prior_close = _latest_local_close(symbol)
        quote = quotes.get(symbol) or {}
        try:
            live_price = float(quote.get("reference_price"))
        except (TypeError, ValueError):
            live_price = None
        if prior_close and live_price and prior_close > 0:
            ranked.append((live_price / prior_close - 1.0, symbol, prior_close, live_price))
    ranked.sort(reverse=True)
    candidates = ranked[:10]

    token = os.getenv("TIINGO_API_KEY")
    series = {}
    if token and candidates:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_fetch_24h, symbol, token) for _, symbol, _, _ in candidates]
            for future in as_completed(futures):
                try:
                    symbol, rows = None, None
                    result = future.result()
                    # recover symbol from the submitted future by matching is awkward;
                    # use the candidate order below if this branch is ever reached.
                    rows = result
                except Exception as exc:
                    print(f"[24H INTRADAY WORKER ERROR] {exc}")

        # Re-fetch from the per-symbol cache path in a bounded 10-symbol loop so
        # symbol association remains explicit and readable.
        series = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {pool.submit(_fetch_24h, symbol, token): symbol for _, symbol, _, _ in candidates}
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    rows = future.result()
                    if rows:
                        series[symbol] = rows
                except Exception as exc:
                    print(f"[24H INTRADAY WORKER ERROR] {symbol}: {exc}")

    payload = {
        "window_hours": 24,
        "updated_at": live_state.get("updated_at"),
        "source": "TIINGO_INTRADAY_5MIN_PLUS_LIVE_IEX",
        "symbols": [symbol for _, symbol, _, _ in candidates],
        "series": series,
        "live": {
            symbol: {
                "reference_price": live_price,
                "prior_close": prior_close,
                "session_return": ret,
                "timestamp": (quotes.get(symbol) or {}).get("timestamp"),
            }
            for ret, symbol, prior_close, live_price in candidates
        },
    }
    _top_cache["fetched"] = now_mono
    _top_cache["payload"] = payload
    return payload
