"""Local-only bulk history payload for the Live Stock Viewer comparison chart.

Positive limits read local Gold only. A negative limit is a deliberate internal
sentinel used by the TODAY chart to request the presentation-only intraday Top-10
payload through the existing authenticated bulk-history endpoint.
"""
from pathlib import Path
import time
import pandas as pd

_CACHE = {"at": 0.0, "limit": 0, "payload": {}}
_CACHE_TTL = 300.0


def get_bulk_local_history(symbols, limit=130):
    raw_limit = int(limit)
    if raw_limit < 0:
        from webapp.services.today_intraday_service import get_today_top10_intraday
        return get_today_top10_intraday(list(symbols)).get("series", {})

    now = time.monotonic()
    limit = max(10, min(raw_limit, 1300))
    if _CACHE["payload"] and _CACHE["limit"] >= limit and now - _CACHE["at"] < _CACHE_TTL:
        return {s: _CACHE["payload"].get(s, [])[-limit:] for s in symbols}

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
                if pd.notna(t) and pd.notna(p)
            ]
            payload[symbol] = rows
        except Exception as exc:
            print(f"[BULK LOCAL HISTORY ERROR] {symbol}: {exc}")
            payload[symbol] = []

    _CACHE.update(at=now, limit=limit, payload=payload)
    return payload
