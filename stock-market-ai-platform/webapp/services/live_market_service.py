"""
Live market-data service.

Reads the lightweight Tiingo IEX quote cache and exposes
the latest live reference price for the Flask application.
"""

import json
from pathlib import Path


LIVE_CACHE_PATH = Path(
    "data/live/latest_quotes.json"
)


def load_live_cache():
    """Load the latest live quote cache."""

    if not LIVE_CACHE_PATH.exists():
        return {
            "updated_at": None,
            "symbol_count": 0,
            "configured_symbols": [],
            "quotes": {},
        }

    try:
        with LIVE_CACHE_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(
                file
            )

    except (
        json.JSONDecodeError,
        OSError,
    ):
        return {
            "updated_at": None,
            "symbol_count": 0,
            "configured_symbols": [],
            "quotes": {},
        }

    return payload


def get_live_quote(symbol):
    """Return the latest live quote for one symbol."""

    symbol = symbol.upper()

    cache = load_live_cache()

    quote = cache.get(
        "quotes",
        {}
    ).get(
        symbol
    )

    if not quote:
        return {
            "symbol": symbol,
            "available": False,
            "reference_price": None,
            "timestamp": None,
            "received_at": None,
            "cache_updated_at":
                cache.get(
                    "updated_at"
                ),
        }

    return {
        "symbol": symbol,
        "available": True,
        "reference_price":
            quote.get(
                "reference_price"
            ),
        "timestamp":
            quote.get(
                "timestamp"
            ),
        "received_at":
            quote.get(
                "received_at"
            ),
        "cache_updated_at":
            cache.get(
                "updated_at"
            ),
    }


def get_all_live_quotes():
    """Return live quote state for all cached symbols."""

    cache = load_live_cache()

    quotes = cache.get(
        "quotes",
        {}
    )

    return {
        "updated_at":
            cache.get(
                "updated_at"
            ),
        "symbol_count":
            len(quotes),
        "quotes":
            quotes,
    }
