"""Continuously reconcile closed 15-minute Coinbase candles into the research archive.

The WebSocket collector remains the low-latency live-price layer. This service is
the authoritative closed-bar layer: after each 15-minute boundary it fetches
Coinbase Exchange REST candles, merges/deduplicates them into
``data/research/crypto_intraday/raw_15m``, and records reconciliation status.

It intentionally does NOT refit models, rewrite Phase 1 research panels, inspect
future-holdout labels, or place orders. A later frozen-inference service can read
the continuously updated authoritative archive without contaminating research.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import time

import pandas as pd
import requests

from ml.crypto_rt import BAR_SECONDS, PRODUCTS
from ml.crypto_rt.backfill_15m import (
    CHUNK_SECONDS,
    _normalize_candles,
    _persist,
    _request_candles,
)

RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
LIVE_ROOT = Path("data/live/crypto_rt")
STATUS_PATH = LIVE_ROOT / "reconcile_status.json"
LATEST_CLOSED_PATH = LIVE_ROOT / "latest_authoritative_15m.json"
LOCK_PATH = LIVE_ROOT / "reconcile_15m.lock"
DEFAULT_POLL_SECONDS = 60
DEFAULT_SETTLE_SECONDS = 45


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _iso(ts) -> str:
    return _utc(ts).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _latest_archived(product_id: str) -> pd.Timestamp | None:
    root = RAW_ROOT / product_id
    paths = sorted(root.glob("*.parquet"), reverse=True)
    for path in paths:
        try:
            df = pd.read_parquet(path, columns=["timestamp_utc"])
        except Exception:
            continue
        if len(df):
            ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dropna()
            if len(ts):
                return ts.max()
    return None


def _completed_boundary(now: pd.Timestamp, settle_seconds: int) -> pd.Timestamp:
    """Exclusive end boundary for candles considered safely closed.

    At 20:15:30 with a 45-second settle delay, 20:00 is the exclusive end and
    the 19:45 candle is the latest eligible bar. At 20:15:50, 20:15 is the
    exclusive end and the 20:00 candle is eligible.
    """
    effective = _utc(now) - pd.Timedelta(seconds=settle_seconds)
    return effective.floor("15min")


def _fetch_range(session, product_id: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int]:
    cursor = start
    requests_completed = 0
    rows_received = 0
    while cursor < end:
        chunk_end = min(cursor + pd.Timedelta(seconds=CHUNK_SECONDS), end)
        payload = _request_candles(session, product_id, cursor, chunk_end)
        frame = _normalize_candles(product_id, payload)
        if not frame.empty:
            frame = frame[(frame["timestamp_utc"] >= cursor) & (frame["timestamp_utc"] < chunk_end)].copy()
            _persist(frame)
            rows_received += len(frame)
        requests_completed += 1
        cursor = chunk_end
    return requests_completed, rows_received


def reconcile_once(settle_seconds: int = DEFAULT_SETTLE_SECONDS) -> dict:
    now = pd.Timestamp.now(tz="UTC")
    end = _completed_boundary(now, settle_seconds)
    session = requests.Session()
    session.headers.update({"User-Agent": "DataShepherdEngineering-CryptoReconcile/1.0"})

    products = {}
    latest_rows = {}
    total_requests = 0
    total_rows = 0
    errors = 0

    for product_id in PRODUCTS:
        before = _latest_archived(product_id)
        if before is None:
            products[product_id] = {"status": "no_archive", "error": "No historical archive found"}
            errors += 1
            continue
        start = before + pd.Timedelta(seconds=BAR_SECONDS)
        item = {"before_utc": _iso(before), "requested_end_exclusive_utc": _iso(end)}
        if start >= end:
            item.update({"status": "current", "requests": 0, "rows_received": 0, "after_utc": _iso(before)})
            products[product_id] = item
        else:
            try:
                reqs, rows = _fetch_range(session, product_id, start, end)
                after = _latest_archived(product_id)
                item.update({"status": "updated", "requests": reqs, "rows_received": rows, "after_utc": _iso(after) if after is not None else None})
                total_requests += reqs
                total_rows += rows
                products[product_id] = item
            except Exception as exc:
                item.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
                products[product_id] = item
                errors += 1

        # Latest authoritative candle snapshot for UI/future inference.
        latest = _latest_archived(product_id)
        if latest is not None:
            month_path = RAW_ROOT / product_id / f"{latest.strftime('%Y-%m')}.parquet"
            try:
                df = pd.read_parquet(month_path)
                df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
                row = df.loc[df["timestamp_utc"] == latest].tail(1)
                if len(row):
                    r = row.iloc[0]
                    latest_rows[product_id] = {
                        "timestamp_utc": _iso(latest),
                        "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"]),
                        "volume": float(r["volume"]),
                        "source": str(r.get("source", "coinbase_exchange_rest_candles")),
                    }
            except Exception:
                pass

    generated = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at_utc": generated,
        "completed_boundary_exclusive_utc": _iso(end),
        "latest_expected_bar_start_utc": _iso(end - pd.Timedelta(seconds=BAR_SECONDS)),
        "settle_seconds": settle_seconds,
        "product_count": len(PRODUCTS),
        "products_with_errors": errors,
        "requests_completed": total_requests,
        "rows_received": total_rows,
        "products": products,
        "policy": "Authoritative closed Coinbase REST candles only; no synthetic candles, model fitting, labels, or orders.",
    }
    _atomic_json(STATUS_PATH, payload)
    _atomic_json(LATEST_CLOSED_PATH, {
        "generated_at_utc": generated,
        "bar_minutes": BAR_SECONDS // 60,
        "product_count": len(latest_rows),
        "bars": latest_rows,
    })
    return payload


def _acquire_lock() -> None:
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        fd = LOCK_PATH.open("x")
        fd.write_text(str(__import__("os").getpid()))
        fd.close()
    except FileExistsError:
        raise SystemExit("[SKIP] crypto 15m reconciliation already running")


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Run one reconciliation cycle and exit.")
    ap.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    ap.add_argument("--settle-seconds", type=int, default=DEFAULT_SETTLE_SECONDS)
    args = ap.parse_args(argv)
    if args.poll_seconds < 15:
        raise SystemExit("poll-seconds must be at least 15")

    stop = False
    def request_stop(*_args):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    _acquire_lock()
    try:
        while True:
            result = reconcile_once(args.settle_seconds)
            print(
                f"[RECONCILE] {result['generated_at_utc']} "
                f"expected={result['latest_expected_bar_start_utc']} "
                f"rows={result['rows_received']} requests={result['requests_completed']} "
                f"errors={result['products_with_errors']}",
                flush=True,
            )
            if args.once or stop:
                break
            for _ in range(max(1, args.poll_seconds)):
                if stop:
                    break
                time.sleep(1)
            if stop:
                break
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
