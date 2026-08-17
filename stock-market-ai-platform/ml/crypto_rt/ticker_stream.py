"""Read-only Coinbase real-time ticker cache for the crypto dashboard.

This stream is presentation-only. It does not feed frozen research features,
model decisions, forward journals, or brokerage logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import websocket

from ml.crypto_rt import PRODUCTS

WS_URL = "wss://advanced-trade-ws.coinbase.com"
CACHE_PATH = Path("data/live/crypto_rt/latest_tickers.json")
latest: dict[str, dict] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_cache() -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE_PATH.with_suffix(".tmp")
    payload = {
        "updated_at": utc_now(),
        "product_count": len(latest),
        "configured_products": list(PRODUCTS),
        "quotes": latest,
        "source": "Coinbase Advanced Trade public ticker WebSocket",
        "research_inputs_modified": False,
        "brokerage_orders": False,
    }
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(CACHE_PATH)


def on_open(ws):
    ws.send(json.dumps({"type": "subscribe", "product_ids": list(PRODUCTS), "channel": "ticker"}))
    ws.send(json.dumps({"type": "subscribe", "channel": "heartbeats"}))
    write_cache()
    print(f"[COINBASE TICKER] subscribed to {len(PRODUCTS)} products", flush=True)


def on_message(_ws, message):
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return
    if payload.get("channel") != "ticker":
        return
    received_at = utc_now()
    for event in payload.get("events", []):
        for ticker in event.get("tickers", []):
            product_id = str(ticker.get("product_id", "")).upper()
            if product_id not in PRODUCTS:
                continue
            try:
                price = float(ticker.get("price"))
            except (TypeError, ValueError):
                continue
            latest[product_id] = {
                "product_id": product_id,
                "price": price,
                "price_percent_chg_24_h": ticker.get("price_percent_chg_24_h"),
                "volume_24_h": ticker.get("volume_24_h"),
                "best_bid": ticker.get("best_bid"),
                "best_ask": ticker.get("best_ask"),
                "exchange_timestamp": payload.get("timestamp"),
                "received_at": received_at,
            }
    if latest:
        write_cache()


def on_error(_ws, error):
    if error:
        print(f"[COINBASE TICKER ERROR] {error}", flush=True)


def on_close(_ws, code, message):
    print(f"[COINBASE TICKER CLOSED] code={code} message={message}", flush=True)


def run() -> None:
    print("COINBASE REAL-TIME CRYPTO TICKER STREAM", flush=True)
    print("Presentation only; frozen research inputs unchanged; real orders NO", flush=True)
    ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.run_forever(ping_interval=30, ping_timeout=10)


if __name__ == "__main__":
    run()
