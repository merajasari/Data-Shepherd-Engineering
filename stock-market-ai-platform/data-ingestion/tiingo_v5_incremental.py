"""Quota-aware incremental Tiingo EOD updater for the frozen Stock V5 runtime.

This updater is deliberately separate from the historical V5 bootstrap loader.
It uses SPY as a one-request sentinel for the newest completed Tiingo EOD bar,
then spends the remaining hourly request budget only on symbols whose Bronze
history is behind that target timestamp. Existing rows are merged and
deduplicated by timestamp, so the updater is resume-safe across hourly runs.

No model fitting, research selection, threshold tuning, or holdout evaluation is
performed here.
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from tiingo_client import TiingoClient
from v5_symbols import V5_BENCHMARK_SYMBOL, get_v5_data_symbols


BRONZE_ROOT = Path("data/bronze/stocks")
STATE_PATH = Path("data/live/v5_eod_refresh_state.json")
DEFAULT_START_DATE = "2016-08-01"
DEFAULT_MAX_REQUESTS = 45
SENTINEL_LOOKBACK_DAYS = 10


def bronze_file(symbol):
    return BRONZE_ROOT / symbol / f"{symbol}_prices.csv"


def read_bronze(symbol):
    path = bronze_file(symbol)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def latest_timestamp_ms(symbol):
    frame = read_bronze(symbol)
    if frame.empty or "timestamp" not in frame.columns:
        return None
    values = pd.to_numeric(frame["timestamp"], errors="coerce").dropna()
    if values.empty:
        return None
    return int(values.max())


def timestamp_ms_to_date(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()


def merge_price_frames(existing, incoming):
    """Return canonical timestamp-deduplicated Bronze rows, preferring incoming."""
    if existing.empty:
        merged = incoming.copy()
    elif incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True)

    if merged.empty:
        return merged
    if "timestamp" not in merged.columns:
        raise ValueError("Bronze data must contain timestamp")

    merged["timestamp"] = pd.to_numeric(merged["timestamp"], errors="raise").astype("int64")
    merged = (
        merged.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    return merged


def write_bronze_atomic(frame, symbol):
    path = bronze_file(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".csv.tmp")
    frame.to_csv(temp, index=False)
    temp.replace(path)


def fetch_symbol(client, symbol, start_date, end_date):
    frame = client.get_daily_prices(symbol, start_date, end_date)
    if frame.empty:
        raise ValueError(f"Tiingo returned no rows for {symbol}")
    return frame


def fetch_sentinel(client, today=None):
    today = today or date.today()
    start = (today - timedelta(days=SENTINEL_LOOKBACK_DAYS)).isoformat()
    frame = fetch_symbol(
        client,
        V5_BENCHMARK_SYMBOL,
        start,
        today.isoformat(),
    )
    target = int(pd.to_numeric(frame["timestamp"], errors="raise").max())
    return frame, target


def stale_symbols(target_timestamp, symbols=None):
    symbols = symbols or get_v5_data_symbols()
    return [
        symbol
        for symbol in symbols
        if latest_timestamp_ms(symbol) is None
        or latest_timestamp_ms(symbol) < target_timestamp
    ]


def symbol_fetch_start(symbol, target_timestamp):
    current = latest_timestamp_ms(symbol)
    if current is None:
        return DEFAULT_START_DATE
    # Re-request the last known session so adjusted data can safely replace the
    # existing row while still downloading only the tiny incremental tail.
    return timestamp_ms_to_date(current).isoformat()


def write_state(payload):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp.replace(STATE_PATH)


def run_incremental_refresh(max_requests=DEFAULT_MAX_REQUESTS, today=None, client=None):
    """Advance V5 Bronze data toward the latest completed Tiingo EOD session."""
    if max_requests < 1:
        raise ValueError("max_requests must be at least 1")

    client = client or TiingoClient()
    today = today or date.today()
    symbols = get_v5_data_symbols()

    sentinel_frame, target = fetch_sentinel(client, today=today)
    requests_used = 1
    updated = []
    failed = []

    # Reuse the sentinel response rather than spending a second request on SPY.
    spy_existing = read_bronze(V5_BENCHMARK_SYMBOL)
    spy_latest = latest_timestamp_ms(V5_BENCHMARK_SYMBOL)
    if spy_latest is None or spy_latest < target:
        write_bronze_atomic(
            merge_price_frames(spy_existing, sentinel_frame),
            V5_BENCHMARK_SYMBOL,
        )
        updated.append(V5_BENCHMARK_SYMBOL)

    pending = [
        symbol
        for symbol in stale_symbols(target, symbols=symbols)
        if symbol != V5_BENCHMARK_SYMBOL
    ]

    remaining_budget = max(0, max_requests - requests_used)
    batch = pending[:remaining_budget]

    for symbol in batch:
        try:
            incoming = fetch_symbol(
                client,
                symbol,
                symbol_fetch_start(symbol, target),
                today.isoformat(),
            )
            requests_used += 1
            write_bronze_atomic(
                merge_price_frames(read_bronze(symbol), incoming),
                symbol,
            )
            updated.append(symbol)
        except Exception as exc:
            requests_used += 1
            failed.append({"symbol": symbol, "error": str(exc)})

    remaining = stale_symbols(target, symbols=symbols)
    state = {
        "stage": "v5_incremental_eod_bronze",
        "target_timestamp_ms": target,
        "target_date_utc": timestamp_ms_to_date(target).isoformat(),
        "requests_used": requests_used,
        "max_requests": max_requests,
        "updated_symbols": updated,
        "failed": failed,
        "remaining_symbols": remaining,
        "complete": not remaining,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_state(state)
    return state


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help="Total Tiingo request budget for this run, including the SPY sentinel.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    state = run_incremental_refresh(max_requests=args.max_requests)

    print("V5 INCREMENTAL EOD REFRESH")
    print(f"Target session: {state['target_date_utc']}")
    print(f"Requests used: {state['requests_used']}/{state['max_requests']}")
    print(f"Updated this run: {len(state['updated_symbols'])}")
    print(f"Failed this run: {len(state['failed'])}")
    print(f"Still stale: {len(state['remaining_symbols'])}")
    print(f"Complete: {state['complete']}")
    if state["remaining_symbols"]:
        print("Remaining: " + ", ".join(state["remaining_symbols"]))
    if state["failed"]:
        print("Failures:")
        for item in state["failed"]:
            print(f"  {item['symbol']}: {item['error']}")


if __name__ == "__main__":
    main()
