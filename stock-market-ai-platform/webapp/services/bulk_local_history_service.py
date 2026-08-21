"""Local-only bulk history payload for the Live Stock Viewer comparison chart.

Positive limits read local Gold and append the newest rolling IEX cache point when
it is newer than persisted history. A negative limit is a deliberate internal
sentinel used by the TODAY chart to request the presentation-only intraday Top-10
payload through the existing authenticated bulk-history endpoint.
"""
from pathlib import Path
import time
import pandas as pd

_CACHE = {"at": 0.0, "limit": 0, "payload": {}}
_CACHE_TTL = 300.0


def _append_latest_cached_points(payload, symbols):
    try:
        from webapp.services.today_intraday_service import get_latest_cached_points
        latest = get_latest_cached_points(list(symbols))
    except Exception as exc:
        print(f"[BULK LATEST CACHE ERROR] {exc}")
        return payload

    for symbol in symbols:
        point = latest.get(symbol)
        if not point:
            continue
        rows = list(payload.get(symbol, []))
        try:
            point_ts = pd.to_datetime(point["t"], utc=True)
            point_price = float(point["price"])
        except Exception:
            continue
        if point_price <= 0:
            continue
        last_ts = None
        if rows:
            try:
                last_ts = pd.to_datetime(rows[-1]["t"], utc=True)
            except Exception:
                last_ts = None
        if last_ts is None or point_ts > last_ts:
            rows.append({"t": point_ts.isoformat(), "price": point_price, "intraday_cache": True})
        payload[symbol] = rows
    return payload


def get_bulk_local_history(symbols, limit=130):
    raw_limit = int(limit)
    if raw_limit < 0:
        from webapp.services.today_intraday_service import get_today_top10_intraday
        return get_today_top10_intraday(list(symbols)).get("series", {})

    now = time.monotonic()
    # Keep the default payload small for fast page loads, but allow the Live Stock
    # Viewer to lazy-load the full ~10-year local history when ALL is selected.
    limit = max(10, min(raw_limit, 2600))
    if _CACHE["payload"] and _CACHE["limit"] >= limit and now - _CACHE["at"] < _CACHE_TTL:
        cached = {s: list(_CACHE["payload"].get(s, [])[-limit:]) for s in symbols}
        return _append_latest_cached_points(cached, symbols)

    payload = {}
    for symbol in symbols:
        path = Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")
        if not path.exists():
            payload[symbol] = []
            continue
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc", "close"])
            frame = frame.tail(limit)
            ts = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
            close = pd.to_numeric(frame["close"], errors="coerce")
            rows = [
                {"t": t.isoformat(), "price": float(p)}
                for t, p in zip(ts, close)
                if pd.notna(t) and pd.notna(p) and float(p) > 0
            ]
            payload[symbol] = rows
        except Exception as exc:
            print(f"[BULK LOCAL HISTORY ERROR] {symbol}: {exc}")
            payload[symbol] = []

    _CACHE.update(at=now, limit=limit, payload=payload)
    return _append_latest_cached_points({s: list(payload.get(s, [])) for s in symbols}, symbols)
