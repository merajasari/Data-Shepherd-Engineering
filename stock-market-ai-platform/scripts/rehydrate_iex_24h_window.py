#!/usr/bin/env python3
"""Force-hydrate the V5 rolling cache toward a true 24-hour window.

Unlike the original backfill utility, this script judges coverage by time span,
not merely by point count. It runs outside Gunicorn and writes the same compact
cache consumed by the dashboard.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backfill_iex_24h_cache import (
    CACHE_PATH,
    MAX_WORKERS,
    append_live_marks,
    atomic_write_json,
    fetch_symbol,
    load_existing_cache,
    load_log_history,
    merge_series,
    normalize_rows,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = ROOT / "data-ingestion"
import sys
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))
from stock_universe_250 import get_stock_250_data_symbols  # noqa: E402
from v5_symbols import get_v5_data_symbols  # noqa: E402

START_TOLERANCE_HOURS = 2.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def cutoff_utc() -> datetime:
    return now_utc() - timedelta(hours=24)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def span_hours(rows: list[dict]) -> float:
    if len(rows) < 2:
        return 0.0
    try:
        return max(0.0, (parse_ts(rows[-1]["t"]) - parse_ts(rows[0]["t"])).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def reaches_window_start(rows: list[dict]) -> bool:
    if len(rows) < 2:
        return False
    try:
        oldest = parse_ts(rows[0]["t"])
    except Exception:
        return False
    lag = (oldest - cutoff_utc()).total_seconds() / 3600.0
    return lag <= START_TOLERANCE_HOURS


def main() -> int:
    symbols = get_stock_250_data_symbols() if USE_STOCK_250 else get_v5_data_symbols()
    merged = merge_series(load_existing_cache(), load_log_history())
    append_live_marks(merged)

    need_remote = [symbol for symbol in symbols if not reaches_window_start(merged.get(symbol, []))]
    print(f"True-window local coverage: {len(symbols)-len(need_remote)}/{len(symbols)}")
    print(f"Symbols requiring 24h hydration: {len(need_remote)}")

    token = os.getenv("TIINGO_API_KEY")
    success = 0
    if need_remote and not token:
        print("TIINGO_API_KEY is not set; cannot hydrate the missing historical window.")
    elif need_remote:
        print(f"Fetching historical intraday bars with {MAX_WORKERS} workers ...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_symbol, symbol, token): symbol for symbol in need_remote}
            for i, future in enumerate(as_completed(futures), 1):
                symbol = futures[future]
                try:
                    _, rows, error = future.result()
                except Exception as exc:
                    rows, error = [], str(exc)
                if rows:
                    merged[symbol] = normalize_rows([*merged.get(symbol, []), *rows])
                    success += 1
                    print(f"[{i}/{len(need_remote)}] {symbol}: {len(merged[symbol])} points, span={span_hours(merged[symbol]):.2f}h")
                else:
                    print(f"[{i}/{len(need_remote)}] {symbol}: no historical rows ({error})")

    append_live_marks(merged)
    window_end = now_utc()
    window_start = window_end - timedelta(hours=24)
    payload = {
        "updated_at": window_end.isoformat(),
        "window_hours": 24,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "interval_minutes": 5,
        "symbol_count": len(merged),
        "series": {symbol: merged.get(symbol, []) for symbol in symbols if merged.get(symbol)},
        "backfill": {
            "source": "local IEX logs + forced historical hydration by time coverage",
            "remote_success_count": success,
            "requested_symbols": len(need_remote),
        },
    }
    atomic_write_json(CACHE_PATH, payload)

    starts = [rows[0]["t"] for rows in payload["series"].values() if rows]
    ends = [rows[-1]["t"] for rows in payload["series"].values() if rows]
    complete = [s for s in symbols if reaches_window_start(payload["series"].get(s, []))]
    spans = [span_hours(rows) for rows in payload["series"].values() if len(rows) >= 2]

    print("\n===== TRUE 24H WINDOW SUMMARY =====")
    print("cache:", CACHE_PATH)
    print("window start:", window_start.isoformat())
    print("window end:", window_end.isoformat())
    print("symbols reaching window start:", len(complete), "/", len(symbols))
    print("earliest actual point:", min(starts) if starts else None)
    print("latest actual point:", max(ends) if ends else None)
    print("max actual span hours:", round(max(spans), 2) if spans else 0)
    print("file size bytes:", CACHE_PATH.stat().st_size if CACHE_PATH.exists() else 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
