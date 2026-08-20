"""Intraday chart data for the Live Stock Viewer TODAY range.

Presentation-only: never writes to Gold, features, model artifacts, or holdout
results. Candidates are ranked from current live reference prices versus the
latest completed local close; only those candidates are then hydrated from
Tiingo intraday history.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from webapp.services.live_market_service import get_all_live_quotes

EASTERN = ZoneInfo("America/New_York")
CACHE_TTL_SECONDS = 60
_cache = {"fetched": 0.0, "payload": None}


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
        print(f"[TODAY PRIOR CLOSE ERROR] {symbol}: {exc}")
        return None


def _fetch_intraday(symbol: str, session_date: str, token: str) -> tuple[str, list]:
    """Fetch regular-session 5-minute bars for one symbol."""
    urls = [
        f"https://api.tiingo.com/tiingo/equity/intraday/{symbol}/prices",
        f"https://api.tiingo.com/iex/{symbol}/prices",
    ]
    params = {
        "startDate": session_date,
        "endDate": session_date,
        "resampleFreq": "5min",
        "afterHours": "false",
        "forceFill": "true",
        "token": token,
    }
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
            print(f"[TODAY INTRADAY ERROR] {symbol} {url}: {exc}")
    rows = []
    for item in payload or []:
        try:
            ts = str(item["date"])
            price = float(item.get("close"))
            if price > 0:
                rows.append({"t": ts, "price": price})
        except (KeyError, TypeError, ValueError):
            continue
    return symbol, rows


def get_today_top10_intraday(symbols: list[str]) -> dict:
    """Return today's Top-10 intraday series plus current live marks."""
    now_mono = time.monotonic()
    if _cache["payload"] is not None and now_mono - _cache["fetched"] < CACHE_TTL_SECONDS:
        return _cache["payload"]

    session_date = datetime.now(EASTERN).date().isoformat()
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
            futures = [pool.submit(_fetch_intraday, symbol, session_date, token) for _, symbol, _, _ in candidates]
            for future in as_completed(futures):
                try:
                    symbol, rows = future.result()
                    if rows:
                        series[symbol] = rows
                except Exception as exc:
                    print(f"[TODAY INTRADAY WORKER ERROR] {exc}")

    payload = {
        "session_date": session_date,
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
    _cache["fetched"] = now_mono
    _cache["payload"] = payload
    return payload
