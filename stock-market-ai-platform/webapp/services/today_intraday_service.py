"""Fast rolling 24-hour data for Live Stock Viewer charts.

This module is intentionally request-safe: no background threads, no large log
scans, and no Tiingo REST calls. The IEX stream process maintains a compact
5-minute rolling JSON cache; Gunicorn only reads that small local file and keeps
it in a short-lived in-process cache.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from webapp.services.live_market_service import get_all_live_quotes

ROOT = Path(__file__).resolve().parents[2]
V5_CACHE_PATH = ROOT / "data/live/iex_24h_5m_v5.json"
LEGACY_COMPAT_PATH = ROOT / "data/live/iex_24h_5m.json"
MEMORY_TTL_SECONDS = 5

_memory_cache = {"fetched": 0.0, "series": {}, "updated_at": None, "source": None}
_daily_cache: dict[str, list[float]] = {}


def _gold_path(symbol: str) -> Path:
    return ROOT / f"data/gold/stocks/{symbol}/{symbol}_prices.parquet"


def _daily_closes(symbol: str) -> list[float]:
    if symbol in _daily_cache:
        return _daily_cache[symbol]
    values: list[float] = []
    path = _gold_path(symbol)
    try:
        if path.exists():
            frame = pd.read_parquet(path, columns=["close"]).tail(220)
            values = [
                float(v)
                for v in pd.to_numeric(frame["close"], errors="coerce").dropna().tolist()
                if float(v) > 0
            ]
    except Exception as exc:
        print(f"[24H SMA HISTORY ERROR] {symbol}: {exc}")
    _daily_cache[symbol] = values
    return values


def _read_small_cache() -> tuple[dict[str, list[dict]], str | None, str]:
    now_mono = time.monotonic()
    if _memory_cache["series"] and now_mono - _memory_cache["fetched"] < MEMORY_TTL_SECONDS:
        return _memory_cache["series"], _memory_cache["updated_at"], _memory_cache["source"]

    path = V5_CACHE_PATH if V5_CACHE_PATH.exists() else LEGACY_COMPAT_PATH
    if not path.exists():
        _memory_cache.update({"fetched": now_mono, "series": {}, "updated_at": None, "source": "CACHE_MISSING"})
        return {}, None, "CACHE_MISSING"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    clean: dict[str, list[dict]] = {}
    updated_at = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = payload.get("updated_at")
        for symbol, rows in (payload.get("series", {}) or {}).items():
            out = []
            for row in rows or []:
                try:
                    ts = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
                    price = float(row["price"])
                except Exception:
                    continue
                if ts >= cutoff and price > 0:
                    out.append({"t": ts.isoformat(), "price": price})
            out.sort(key=lambda r: r["t"])
            if out:
                clean[str(symbol).upper()] = out
        source = "ROLLING_V5_24H_CACHE" if path == V5_CACHE_PATH else "ROLLING_COMPAT_24H_CACHE"
    except Exception as exc:
        print(f"[24H CACHE READ ERROR] {path}: {exc}")
        clean, source = {}, "CACHE_READ_ERROR"

    _memory_cache.update({
        "fetched": now_mono,
        "series": clean,
        "updated_at": updated_at,
        "source": source,
    })
    return clean, updated_at, source


def _append_live(rows: list[dict], symbol: str, quotes: dict) -> list[dict]:
    out = [dict(row) for row in rows]
    quote = quotes.get(symbol) or {}
    try:
        price = float(quote.get("reference_price"))
    except (TypeError, ValueError):
        return out
    if price <= 0:
        return out
    timestamp = quote.get("timestamp") or quote.get("received_at") or datetime.now(timezone.utc).isoformat()
    try:
        ts = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        ts = datetime.now(timezone.utc)
    bucket = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0).isoformat()
    if out and out[-1].get("t") == bucket:
        out[-1] = {"t": bucket, "price": price, "live": True}
    else:
        out.append({"t": bucket, "price": price, "live": True})
    return out


def _with_provisional_daily_smas(symbol: str, rows: list[dict]) -> list[dict]:
    completed = _daily_closes(symbol)
    if not completed:
        return [{**row, "sma_20": None, "sma_50": None, "sma_200": None} for row in rows]
    result = []
    for row in rows:
        enriched = dict(row)
        price = float(row["price"])
        for n, key in ((20, "sma_20"), (50, "sma_50"), (200, "sma_200")):
            prior = completed[-(n - 1):]
            values = prior + [price]
            enriched[key] = sum(values) / len(values) if values else None
        result.append(enriched)
    return result


def get_symbol_24h_intraday(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    series, cache_updated_at, source = _read_small_cache()
    live_state = get_all_live_quotes()
    quotes = live_state.get("quotes", {}) or {}
    rows = _append_live(series.get(symbol, []), symbol, quotes)
    rows = _with_provisional_daily_smas(symbol, rows)
    quote = quotes.get(symbol) or {}
    try:
        live_price = float(quote.get("reference_price"))
    except (TypeError, ValueError):
        live_price = None
    return {
        "window_hours": 24,
        "symbol": symbol,
        "series": rows,
        "updated_at": cache_updated_at or live_state.get("updated_at"),
        "live": {"reference_price": live_price, "timestamp": quote.get("timestamp")},
        "source": source,
        "point_count": len(rows),
    }


def get_today_top10_intraday(symbols: list[str]) -> dict:
    """Return Top-10 rolling 24h series without network or log-scan latency."""
    local_series, cache_updated_at, source = _read_small_cache()
    live_state = get_all_live_quotes()
    quotes = live_state.get("quotes", {}) or {}

    ranked = []
    for symbol in symbols:
        rows = _append_live(local_series.get(symbol, []), symbol, quotes)
        if len(rows) < 2:
            continue
        try:
            start_price = float(rows[0]["price"])
            end_price = float(rows[-1]["price"])
        except (TypeError, ValueError, KeyError):
            continue
        if start_price <= 0 or end_price <= 0:
            continue
        ranked.append((end_price / start_price - 1.0, symbol, rows))

    ranked.sort(key=lambda item: item[0], reverse=True)
    top = ranked[:10]
    return {
        "window_hours": 24,
        "updated_at": cache_updated_at or live_state.get("updated_at"),
        "source": source,
        "symbols": [symbol for _, symbol, _ in top],
        "series": {symbol: rows for _, symbol, rows in top},
        "point_counts": {symbol: len(rows) for _, symbol, rows in top},
        "cache": {
            "memory_ttl_seconds": MEMORY_TTL_SECONDS,
            "file": str(V5_CACHE_PATH),
        },
        "live": {
            symbol: {
                "reference_price": (quotes.get(symbol) or {}).get("reference_price"),
                "timestamp": (quotes.get(symbol) or {}).get("timestamp"),
                "window_return": ret,
            }
            for ret, symbol, _ in top
        },
    }
