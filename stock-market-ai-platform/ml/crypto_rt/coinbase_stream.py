"""Continuously ingest Coinbase Exchange ticker data and build 15-minute OHLCV bars.

This is a market-data service only. It does not make portfolio decisions or place
orders. Closed 15-minute bars are persisted beneath data/live/crypto_rt/bars_15m
and latest quotes/status are written beneath data/live/crypto_rt.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import signal
import time
from typing import Dict

import pandas as pd

from ml.crypto_rt import BAR_SECONDS, PRODUCTS

try:
    import websockets
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: pip install websockets") from exc

WS_URL = "wss://ws-feed.exchange.coinbase.com"
ROOT = Path("data/live/crypto_rt")
BAR_ROOT = ROOT / "bars_15m"
LATEST_QUOTES_PATH = ROOT / "latest_quotes.json"
STATUS_PATH = ROOT / "status.json"
FLUSH_SECONDS = 5.0


@dataclass
class Bar:
    product_id: str
    bucket_start_utc: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trade_updates: int = 0

    def update(self, price: float, size: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        if math.isfinite(size) and size >= 0:
            self.volume += size
        self.trade_updates += 1

    def row(self) -> dict:
        return {
            "timestamp_utc": pd.Timestamp(self.bucket_start_utc, unit="s", tz="UTC"),
            "product_id": self.product_id,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume_from_ticker_updates": self.volume,
            "trade_updates": self.trade_updates,
            "bar_seconds": BAR_SECONDS,
            "source": "coinbase_exchange_websocket_ticker",
        }


def _bucket(epoch_seconds: float) -> int:
    return int(epoch_seconds // BAR_SECONDS) * BAR_SECONDS


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _bar_path(product_id: str, bucket_start: int) -> Path:
    day = pd.Timestamp(bucket_start, unit="s", tz="UTC").strftime("%Y-%m-%d")
    return BAR_ROOT / product_id / f"{day}.parquet"


def _persist_bar(bar: Bar) -> None:
    path = _bar_path(bar.product_id, bar.bucket_start_utc)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([bar.row()])
    if path.exists():
        existing = pd.read_parquet(path)
        existing["timestamp_utc"] = pd.to_datetime(existing["timestamp_utc"], utc=True)
        row["timestamp_utc"] = pd.to_datetime(row["timestamp_utc"], utc=True)
        out = pd.concat([existing, row], ignore_index=True)
        out = out.sort_values("timestamp_utc").drop_duplicates(
            ["timestamp_utc", "product_id"], keep="last"
        )
    else:
        out = row
    tmp = path.with_suffix(".parquet.tmp")
    out.to_parquet(tmp, index=False)
    tmp.replace(path)


class Collector:
    def __init__(self) -> None:
        self.bars: Dict[str, Bar] = {}
        self.latest: Dict[str, dict] = {}
        self.stop = asyncio.Event()
        self.started = datetime.now(timezone.utc)
        self.message_count = 0
        self.last_message_utc: str | None = None
        self.last_flush = 0.0

    async def handle_ticker(self, msg: dict) -> None:
        product = msg.get("product_id")
        if product not in PRODUCTS:
            return
        try:
            price = float(msg["price"])
            size = float(msg.get("last_size") or 0.0)
            ts = pd.to_datetime(msg.get("time"), utc=True) if msg.get("time") else pd.Timestamp.now(tz="UTC")
        except (KeyError, TypeError, ValueError):
            return
        epoch = ts.timestamp()
        bucket = _bucket(epoch)
        current = self.bars.get(product)
        if current is None:
            current = Bar(product, bucket, price, price, price, price)
            self.bars[product] = current
        elif bucket > current.bucket_start_utc:
            _persist_bar(current)
            current = Bar(product, bucket, price, price, price, price)
            self.bars[product] = current
        elif bucket < current.bucket_start_utc:
            return
        current.update(price, size)
        self.latest[product] = {
            "product_id": product,
            "price": price,
            "last_size": size,
            "time_utc": ts.isoformat(),
            "bucket_start_utc": pd.Timestamp(bucket, unit="s", tz="UTC").isoformat(),
            "best_bid": msg.get("best_bid"),
            "best_ask": msg.get("best_ask"),
            "sequence": msg.get("sequence"),
        }
        self.message_count += 1
        self.last_message_utc = ts.isoformat()

    def flush_state(self, connected: bool = True, error: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        _atomic_json(LATEST_QUOTES_PATH, {
            "generated_at_utc": now.isoformat(),
            "source": "coinbase_exchange_websocket_ticker",
            "product_count": len(self.latest),
            "quotes": self.latest,
        })
        _atomic_json(STATUS_PATH, {
            "generated_at_utc": now.isoformat(),
            "started_at_utc": self.started.isoformat(),
            "connected": connected,
            "products_requested": len(PRODUCTS),
            "products_seen": len(self.latest),
            "message_count": self.message_count,
            "last_message_utc": self.last_message_utc,
            "active_bar_count": len(self.bars),
            "bar_seconds": BAR_SECONDS,
            "error": error,
        })

    async def run_connection(self) -> None:
        subscribe = {
            "type": "subscribe",
            "product_ids": list(PRODUCTS),
            "channels": ["ticker", "heartbeat"],
        }
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_queue=10000,
        ) as ws:
            await ws.send(json.dumps(subscribe))
            self.flush_state(connected=True)
            async for raw in ws:
                if self.stop.is_set():
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                typ = msg.get("type")
                if typ == "ticker":
                    await self.handle_ticker(msg)
                elif typ == "error":
                    raise RuntimeError(msg.get("message") or repr(msg))
                now = time.monotonic()
                if now - self.last_flush >= FLUSH_SECONDS:
                    self.flush_state(connected=True)
                    self.last_flush = now

    async def run(self) -> None:
        ROOT.mkdir(parents=True, exist_ok=True)
        delay = 1.0
        while not self.stop.is_set():
            try:
                await self.run_connection()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.flush_state(connected=False, error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 60.0)
        for bar in self.bars.values():
            _persist_bar(bar)
        self.flush_state(connected=False)


def main() -> None:
    collector = Collector()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def request_stop(*_args):
        loop.call_soon_threadsafe(collector.stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)
    try:
        loop.run_until_complete(collector.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
