"""Local-only bulk history payload for the Live Stock Viewer comparison chart.

No network calls, no model inference, no writes.  Reads only timestamp + close from
Gold parquet files and keeps a short in-process cache so the comparison chart can
hydrate in one request without tying up web workers with 100 Tiingo REST calls.
"""
from pathlib import Path
import time
import pandas as pd

_CACHE = {"at": 0.0, "limit": 0, "payload": {}}
_CACHE_TTL = 300.0


def get_bulk_local_history(symbols, limit=130):
    now = time.monotonic()
    limit = max(10, min(int(limit), 1300))
    if _CACHE["payload"] and _CACHE["limit"] >= limit and now - _CACHE["at"] < _CACHE_TTL:
        return {s: _CACHE["payload"].get(s, [])[-limit:] for s in symbols}

    payload = {}
    for symbol in symbols:
        path = Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")
        if not path.exists():
            payload[symbol] = []
            continue
        try:
            # Column projection is important: do not deserialize the full Gold frame.
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
