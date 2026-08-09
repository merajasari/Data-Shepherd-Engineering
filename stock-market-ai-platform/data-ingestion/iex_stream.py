"""
Tiingo IEX real-time reference-price stream.

Subscribes to the configured stock universe and maintains
a JSON cache containing the latest live reference price.

Cache:
    data/live/latest_quotes.json
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import websocket

from symbols import get_symbols


WEBSOCKET_URL = "wss://api.tiingo.com/iex"

CACHE_PATH = Path(
    "data/live/latest_quotes.json"
)

SYMBOLS = get_symbols()

latest_quotes = {}


def utc_now():
    """Return current UTC timestamp."""
    return datetime.now(
        timezone.utc
    ).isoformat()


def build_subscription():
    """Build the Tiingo IEX subscription payload."""

    api_key = os.getenv(
        "TIINGO_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "TIINGO_API_KEY is not configured"
        )

    return {
        "eventName": "subscribe",
        "authorization": api_key,
        "eventData": {
            "thresholdLevel": 6,
            "tickers": SYMBOLS,
        },
    }


def write_cache():
    """Atomically write the latest quote cache."""

    CACHE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = CACHE_PATH.with_suffix(
        ".tmp"
    )

    payload = {
        "updated_at": utc_now(),
        "symbol_count": len(
            latest_quotes
        ),
        "configured_symbols": SYMBOLS,
        "quotes": latest_quotes,
    }

    with temp_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
            sort_keys=True,
        )

    temp_path.replace(
        CACHE_PATH
    )


def initialize_cache():
    """Create the cache before the first live tick."""

    print(
        f"Initializing live cache: "
        f"{CACHE_PATH}"
    )

    write_cache()


def on_open(ws):
    """Subscribe after connecting."""

    print(
        "Connected to Tiingo IEX WebSocket"
    )

    print(
        f"Subscribing to "
        f"{len(SYMBOLS)} symbols"
    )

    print(
        ", ".join(SYMBOLS)
    )

    ws.send(
        json.dumps(
            build_subscription()
        )
    )


def on_message(
    ws,
    message,
):
    """Process incoming Tiingo messages."""

    try:
        payload = json.loads(
            message
        )

    except json.JSONDecodeError:
        print(
            "[NON-JSON MESSAGE]",
            message,
        )
        return

    message_type = payload.get(
        "messageType"
    )

    if message_type == "H":
        print("[HEARTBEAT]")
        return

    if message_type == "I":
        print(
            "[INFO]",
            payload,
        )
        return

    if message_type == "E":
        print(
            "[TIINGO ERROR]",
            payload,
        )
        return

    if (
        message_type == "A"
        and payload.get(
            "service"
        ) == "iex"
    ):

        data = payload.get(
            "data",
            []
        )

        if len(data) < 3:
            print(
                "[INVALID LIVE MESSAGE]",
                data,
            )
            return

        timestamp = data[0]

        symbol = str(
            data[1]
        ).upper()

        reference_price = data[2]

        if symbol not in SYMBOLS:
            return

        try:
            reference_price = float(
                reference_price
            )

        except (
            TypeError,
            ValueError,
        ):
            print(
                "[INVALID PRICE]",
                symbol,
                reference_price,
            )
            return

        latest_quotes[
            symbol
        ] = {
            "symbol": symbol,
            "timestamp": timestamp,
            "reference_price":
                reference_price,
            "received_at":
                utc_now(),
        }

        write_cache()

        print(
            f"[LIVE] "
            f"{symbol:6} "
            f"${reference_price:.2f} "
            f"{timestamp}"
        )

        return

    print(
        "[MESSAGE]",
        payload,
    )


def on_error(
    ws,
    error,
):
    """Handle WebSocket errors."""

    if error:
        print(
            "[WEBSOCKET ERROR]",
            error,
        )


def on_close(
    ws,
    close_status_code,
    close_message,
):
    """Report WebSocket closure."""

    print()
    print(
        "Tiingo WebSocket closed"
    )

    print(
        "Status:",
        close_status_code,
    )

    print(
        "Message:",
        close_message,
    )


def run():
    """Start the live Tiingo stream."""

    print(
        "=" * 64
    )

    print(
        "STOCK MARKET AI PLATFORM"
    )

    print(
        "TIINGO IEX LIVE STREAM"
    )

    print(
        "=" * 64
    )

    print(
        f"Configured symbols: "
        f"{len(SYMBOLS)}"
    )

    print(
        "Feed: Tiingo IEX Reference Price"
    )

    print(
        "Threshold: 6"
    )

    print(
        f"Live cache: "
        f"{CACHE_PATH}"
    )

    print()

    initialize_cache()

    ws = websocket.WebSocketApp(
        WEBSOCKET_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    try:
        ws.run_forever(
            ping_interval=30,
            ping_timeout=10,
        )

    except KeyboardInterrupt:
        print()
        print(
            "Stopping live stream..."
        )

        ws.close()

        print(
            "Live stream stopped."
        )


if __name__ == "__main__":
    run()
