"""Tiingo IEX real-time reference-price stream.

Maintains the existing latest-quote cache and a compact rolling 24-hour,
5-minute cache for Live Stock Viewer charts. The rolling cache is produced by
the stream process itself so Gunicorn never needs to scan logs or call Tiingo
REST to render TODAY.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import websocket

from symbols import get_symbols

ROOT = Path(__file__).resolve().parents[1]
WEBSOCKET_URL = "wss://api.tiingo.com/iex"
CACHE_PATH = ROOT / "data/live/latest_quotes.json"
ROLLING_WRITE_SECONDS = 5


def get_stream_symbols():
    explicit = os.getenv("IEX_SYMBOLS", "").strip()
    if explicit:
        symbols = [value.strip().upper() for value in explicit.split(",") if value.strip()]
        return list(dict.fromkeys(symbols))

    symbol_set = os.getenv("IEX_SYMBOL_SET", "legacy").strip().lower()
    if symbol_set in {"legacy", "v4", "26"}:
        return get_symbols()
    if symbol_set in {"v5", "101"}:
        from v5_symbols import get_v5_data_symbols
        return get_v5_data_symbols()
    raise RuntimeError("Unsupported IEX_SYMBOL_SET. Use legacy, v5, or provide IEX_SYMBOLS.")


SYMBOLS = get_stream_symbols()
ROLLING_24H_PATH = ROOT / (
    "data/live/iex_24h_5m_v5.json" if len(SYMBOLS) >= 50 else "data/live/iex_24h_5m_legacy.json"
)
latest_quotes = {}
rolling_5m = {}
last_rolling_write = 0.0
last_disk_mtime = 0.0


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def build_subscription():
    api_key = os.getenv("TIINGO_API_KEY")
    if not api_key:
        raise RuntimeError("TIINGO_API_KEY is not configured")
    return {
        "eventName": "subscribe",
        "authorization": api_key,
        "eventData": {"thresholdLevel": 6, "tickers": SYMBOLS},
    }


def _atomic_json_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), sort_keys=True)
    temp.replace(path)


def write_cache():
    _atomic_json_write(CACHE_PATH, {
        "updated_at": utc_now(),
        "symbol_count": len(latest_quotes),
        "configured_symbols": SYMBOLS,
        "quotes": latest_quotes,
    })


def _bucket_5m(now: datetime) -> str:
    return now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0).isoformat()


def _prune_rolling(now: datetime):
    cutoff = now - timedelta(hours=24)
    for symbol in list(rolling_5m):
        rows = []
        for row in rolling_5m[symbol]:
            try:
                ts = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
            except Exception:
                continue
            if ts >= cutoff:
                rows.append(row)
        if rows:
            rolling_5m[symbol] = rows
        else:
            rolling_5m.pop(symbol, None)


def _normalize_rows(rows):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    buckets = {}
    for row in rows or []:
        try:
            ts = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts = ts.astimezone(timezone.utc)
            price = float(row["price"])
        except Exception:
            continue
        if ts < cutoff or price <= 0:
            continue
        bucket = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0).isoformat()
        buckets[bucket] = price
    return [{"t": t, "price": buckets[t]} for t in sorted(buckets)]


def _merge_series(external):
    for symbol, ext_rows in (external or {}).items():
        symbol = str(symbol).upper()
        if symbol not in SYMBOLS:
            continue
        merged = [*rolling_5m.get(symbol, []), *ext_rows]
        rows = _normalize_rows(merged)
        if rows:
            rolling_5m[symbol] = rows


def _record_rolling(symbol: str, price: float):
    now = datetime.now(timezone.utc)
    bucket = _bucket_5m(now)
    rows = rolling_5m.setdefault(symbol, [])
    if rows and rows[-1].get("t") == bucket:
        rows[-1]["price"] = price
    else:
        rows.append({"t": bucket, "price": price})
    _prune_rolling(now)


def _load_payload(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        series = payload.get("series", {}) or {}
        if isinstance(series, dict):
            return {
                str(symbol).upper(): _normalize_rows(rows)
                for symbol, rows in series.items()
                if isinstance(rows, list)
            }
    except Exception as exc:
        print("[ROLLING CACHE LOAD ERROR]", path, exc)
    return {}


def _load_rolling_cache():
    global rolling_5m, last_disk_mtime
    candidates = [ROLLING_24H_PATH]
    if len(SYMBOLS) >= 50:
        candidates.append(ROOT / "data/live/iex_24h_5m.json")
    for path in candidates:
        if not path.exists():
            continue
        series = _load_payload(path)
        if series:
            rolling_5m = series
            _prune_rolling(datetime.now(timezone.utc))
            if path == ROLLING_24H_PATH:
                try:
                    last_disk_mtime = path.stat().st_mtime
                except OSError:
                    pass
            print(f"Loaded rolling 24h cache for {len(rolling_5m)} symbols from {path}")
            return


def _merge_external_cache_if_newer():
    """Merge a foreground backfill that was written while this stream is running."""
    global last_disk_mtime
    if not ROLLING_24H_PATH.exists():
        return
    try:
        mtime = ROLLING_24H_PATH.stat().st_mtime
    except OSError:
        return
    if mtime <= last_disk_mtime + 1e-6:
        return
    external = _load_payload(ROLLING_24H_PATH)
    if external:
        before = sum(len(rows) for rows in rolling_5m.values())
        _merge_series(external)
        after = sum(len(rows) for rows in rolling_5m.values())
        print(f"Merged external rolling-cache backfill: {before} -> {after} points")
    last_disk_mtime = mtime


def _write_rolling_cache(force=False):
    global last_rolling_write, last_disk_mtime
    now_mono = time.monotonic()
    if not force and now_mono - last_rolling_write < ROLLING_WRITE_SECONDS:
        return
    _merge_external_cache_if_newer()
    _atomic_json_write(ROLLING_24H_PATH, {
        "updated_at": utc_now(),
        "window_hours": 24,
        "interval_minutes": 5,
        "symbol_count": len(rolling_5m),
        "series": rolling_5m,
    })
    try:
        last_disk_mtime = ROLLING_24H_PATH.stat().st_mtime
    except OSError:
        pass
    last_rolling_write = now_mono


def initialize_cache():
    print(f"Initializing live cache: {CACHE_PATH}")
    print(f"Rolling 24h cache: {ROLLING_24H_PATH}")
    _load_rolling_cache()
    write_cache()
    _write_rolling_cache(force=True)


def on_open(ws):
    print("Connected to Tiingo IEX WebSocket")
    print(f"Subscribing to {len(SYMBOLS)} symbols")
    print(", ".join(SYMBOLS))
    ws.send(json.dumps(build_subscription()))


def on_message(ws, message):
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        print("[NON-JSON MESSAGE]", message)
        return

    message_type = payload.get("messageType")
    if message_type == "H":
        print("[HEARTBEAT]")
        return
    if message_type == "I":
        print("[INFO]", payload)
        return
    if message_type == "E":
        print("[TIINGO ERROR]", payload)
        return

    if message_type == "A" and payload.get("service") == "iex":
        data = payload.get("data", [])
        if len(data) < 3:
            print("[INVALID LIVE MESSAGE]", data)
            return
        timestamp = data[0]
        symbol = str(data[1]).upper()
        if symbol not in SYMBOLS:
            return
        try:
            reference_price = float(data[2])
        except (TypeError, ValueError):
            print("[INVALID PRICE]", symbol, data[2])
            return

        latest_quotes[symbol] = {
            "symbol": symbol,
            "timestamp": timestamp,
            "reference_price": reference_price,
            "received_at": utc_now(),
        }
        _record_rolling(symbol, reference_price)
        write_cache()
        _write_rolling_cache()
        print(f"[LIVE] {symbol:6} ${reference_price:.2f} {timestamp}")
        return

    print("[MESSAGE]", payload)


def on_error(ws, error):
    if error:
        print("[WEBSOCKET ERROR]", error)


def on_close(ws, close_status_code, close_message):
    _write_rolling_cache(force=True)
    print("\nTiingo WebSocket closed")
    print("Status:", close_status_code)
    print("Message:", close_message)


def run():
    print("=" * 64)
    print("STOCK MARKET AI PLATFORM")
    print("TIINGO IEX LIVE STREAM")
    print("=" * 64)
    print(f"Configured symbols: {len(SYMBOLS)}")
    print("Feed: Tiingo IEX Reference Price")
    print("Threshold: 6")
    print(f"Live cache: {CACHE_PATH}")
    print(f"Rolling 24h cache: {ROLLING_24H_PATH}\n")
    initialize_cache()

    ws = websocket.WebSocketApp(
        WEBSOCKET_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    try:
        ws.run_forever(ping_interval=30, ping_timeout=10)
    except KeyboardInterrupt:
        print("\nStopping live stream...")
        ws.close()
        print("Live stream stopped.")


if __name__ == "__main__":
    run()
