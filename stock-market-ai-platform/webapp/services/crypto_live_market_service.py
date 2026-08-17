"""Read-only access to the Coinbase real-time crypto ticker cache."""
from __future__ import annotations

import json
from pathlib import Path

CACHE_PATH = Path("data/live/crypto_rt/latest_tickers.json")


def get_all_crypto_live_tickers():
    if not CACHE_PATH.exists():
        return {"updated_at": None, "product_count": 0, "quotes": {}, "available": False}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": None, "product_count": 0, "quotes": {}, "available": False}
    quotes = payload.get("quotes", {})
    return {
        "updated_at": payload.get("updated_at"),
        "product_count": len(quotes),
        "quotes": quotes,
        "available": bool(quotes),
        "source": payload.get("source"),
        "brokerage_orders": False,
    }
