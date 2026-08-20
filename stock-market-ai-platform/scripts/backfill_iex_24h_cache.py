#!/usr/bin/env python3
"""Backfill the persisted V5 rolling 24-hour, 5-minute IEX cache.

This utility is intentionally separate from Gunicorn. It may scan the existing
IEX stream log and, when needed, call Tiingo intraday REST in the foreground.
The dashboard itself continues to read only the tiny persisted cache.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = ROOT / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

from v5_symbols import get_v5_data_symbols  # noqa: E402

CACHE_PATH = ROOT / "data/live/iex_24h_5m_v5.json"
LATEST_QUOTES_PATH = ROOT / "data/live/latest_quotes.json"
LOG_PATHS = [ROOT / "logs/iex_stream.log", ROOT / "logs/stockiex.log"]
MAX_LOG_BYTES = 256 * 1024 * 1024
MAX_WORKERS = 4
REST_TIMEOUT_SECONDS = 8
MIN_GOOD_POINTS = 12
LIVE_RE = re.compile(r"\[LIVE\]\s+([A-Z0-9.\-]+)\s+\$?([0-9]+(?:\.[0-9]+)?)\s+(\S+)")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def cutoff_utc() -> datetime:
    return now_utc() - timedelta(hours=24)


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def normalize_rows(rows: list[dict]) -> list[dict]:
    cutoff = cutoff_utc()
    points: dict[str, float] = {}
    for row in rows or []:
        try:
            ts = pd.to_datetime(row["t"], utc=True).to_pydatetime()
            price = float(row["price"])
        except Exception:
            continue
        if ts < cutoff or price <= 0:
            continue
        bucket = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0).isoformat()
        points[bucket] = price
    return [{"t": t, "price": points[t]} for t in sorted(points)]


def load_existing_cache() -> dict[str, list[dict]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {str(s).upper(): normalize_rows(rows) for s, rows in (payload.get("series") or {}).items()}
    except Exception as exc:
        print(f"[CACHE READ WARNING] {exc}")
        return {}


def read_log_tail(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - MAX_LOG_BYTES))
            raw = fh.read()
        if size > MAX_LOG_BYTES:
            first_newline = raw.find(b"\n")
            if first_newline >= 0:
                raw = raw[first_newline + 1 :]
        return raw.decode("utf-8", errors="ignore")
    except OSError as exc:
        print(f"[LOG READ WARNING] {path}: {exc}")
        return ""


def load_log_history() -> dict[str, list[dict]]:
    cutoff = cutoff_utc()
    parsed: dict[str, list[dict]] = {}
    for path in LOG_PATHS:
        text = read_log_tail(path)
        if not text:
            continue
        print(f"Scanning {path} ...")
        for line in text.splitlines():
            match = LIVE_RE.search(line)
            if not match:
                continue
            symbol, price_text, ts_text = match.groups()
            try:
                ts = pd.to_datetime(ts_text, utc=True).to_pydatetime()
                price = float(price_text)
            except Exception:
                continue
            if ts >= cutoff and price > 0:
                parsed.setdefault(symbol, []).append({"t": ts.isoformat(), "price": price})
    return {symbol: normalize_rows(rows) for symbol, rows in parsed.items()}


def merge_series(*sources: dict[str, list[dict]]) -> dict[str, list[dict]]:
    symbols = set().union(*(source.keys() for source in sources))
    result: dict[str, list[dict]] = {}
    for symbol in symbols:
        combined: list[dict] = []
        for source in sources:
            combined.extend(source.get(symbol, []))
        rows = normalize_rows(combined)
        if rows:
            result[symbol] = rows
    return result


def fetch_symbol(symbol: str, token: str) -> tuple[str, list[dict], str | None]:
    start = cutoff_utc()
    end = now_utc()
    params = {
        "startDate": start.date().isoformat(),
        "endDate": end.date().isoformat(),
        "resampleFreq": "5min",
        "afterHours": "true",
        "forceFill": "true",
        "token": token,
    }
    urls = (
        f"https://api.tiingo.com/iex/{symbol}/prices",
        f"https://api.tiingo.com/tiingo/equity/intraday/{symbol}/prices",
    )
    errors = []
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=REST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                errors.append(f"unexpected payload from {url}")
                continue
            rows = []
            for item in payload:
                try:
                    ts = pd.to_datetime(item["date"], utc=True).to_pydatetime()
                    price = float(item.get("close"))
                except Exception:
                    continue
                if ts >= start and price > 0:
                    rows.append({"t": ts.isoformat(), "price": price})
            rows = normalize_rows(rows)
            if rows:
                return symbol, rows, None
            errors.append(f"no rows from {url}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return symbol, [], " | ".join(errors)


def latest_quotes() -> dict:
    if not LATEST_QUOTES_PATH.exists():
        return {}
    try:
        return (json.loads(LATEST_QUOTES_PATH.read_text(encoding="utf-8")).get("quotes") or {})
    except Exception:
        return {}


def append_live_marks(series: dict[str, list[dict]]) -> None:
    quotes = latest_quotes()
    now = now_utc()
    bucket = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0).isoformat()
    for symbol, quote in quotes.items():
        try:
            price = float(quote.get("reference_price"))
        except Exception:
            continue
        if price <= 0:
            continue
        rows = series.setdefault(symbol, [])
        rows.append({"t": bucket, "price": price})
        series[symbol] = normalize_rows(rows)


def main() -> int:
    symbols = get_v5_data_symbols()
    existing = load_existing_cache()
    log_history = load_log_history()
    merged = merge_series(existing, log_history)
    append_live_marks(merged)

    need_remote = [symbol for symbol in symbols if len(merged.get(symbol, [])) < MIN_GOOD_POINTS]
    print(f"Local/cache coverage: {len(symbols) - len(need_remote)}/{len(symbols)} symbols have >= {MIN_GOOD_POINTS} points")

    token = os.getenv("TIINGO_API_KEY")
    remote_success = 0
    if need_remote and token:
        print(f"Backfilling {len(need_remote)} symbols from Tiingo REST with {MAX_WORKERS} workers ...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_symbol, symbol, token): symbol for symbol in need_remote}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                symbol = futures[future]
                try:
                    _, rows, error = future.result()
                except Exception as exc:
                    rows, error = [], str(exc)
                if rows:
                    merged[symbol] = normalize_rows([*merged.get(symbol, []), *rows])
                    remote_success += 1
                    print(f"[{completed}/{len(need_remote)}] {symbol}: {len(merged[symbol])} points")
                else:
                    print(f"[{completed}/{len(need_remote)}] {symbol}: no remote rows ({error})")
    elif need_remote:
        print("TIINGO_API_KEY is not set; skipping REST backfill.")

    append_live_marks(merged)
    payload = {
        "updated_at": now_utc().isoformat(),
        "window_hours": 24,
        "interval_minutes": 5,
        "symbol_count": len(merged),
        "series": {symbol: merged.get(symbol, []) for symbol in symbols if merged.get(symbol)},
        "backfill": {
            "source": "local IEX logs + Tiingo REST fallback",
            "remote_success_count": remote_success,
            "requested_symbols": len(symbols),
        },
    }
    atomic_write_json(CACHE_PATH, payload)

    counts = {symbol: len(payload["series"].get(symbol, [])) for symbol in symbols}
    covered = [symbol for symbol, count in counts.items() if count >= 2]
    starts = [rows[0]["t"] for rows in payload["series"].values() if rows]
    ends = [rows[-1]["t"] for rows in payload["series"].values() if rows]
    print("\n===== 24H CACHE SUMMARY =====")
    print("cache:", CACHE_PATH)
    print("symbols with >=2 points:", len(covered), "/", len(symbols))
    print("earliest point:", min(starts) if starts else None)
    print("latest point:", max(ends) if ends else None)
    print("file size bytes:", CACHE_PATH.stat().st_size if CACHE_PATH.exists() else 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
