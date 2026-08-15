"""Resumable Coinbase Exchange 15-minute historical candle backfill.

This module builds an authoritative REST-candle research archive for the same
25-product crypto universe used by the real-time collector. It is intentionally
separate from data/live/crypto_rt so historical research data and forward live
WebSocket data remain distinguishable.

Key properties
--------------
* Native Coinbase Exchange 15-minute candles (granularity=900).
* Requests are chunked below the 300-candle API ceiling.
* Existing rows are merged/deduplicated by (timestamp_utc, product_id).
* Missing intervals are recorded, never synthesized.
* Progress is checkpointed after every successful chunk so runs are resumable.
* 429/5xx/network failures use bounded exponential backoff.
* No model fitting, portfolio decisions, or order execution occurs here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Iterable

import pandas as pd
import requests

from ml.crypto_rt import BAR_SECONDS, PRODUCTS

API_ROOT = "https://api.exchange.coinbase.com"
GRANULARITY_SECONDS = BAR_SECONDS  # 900 = 15 minutes
MAX_CANDLES_PER_REQUEST = 300
# Use 288 bars (= 72 hours) per request, leaving margin beneath Coinbase's cap.
CHUNK_CANDLES = 288
CHUNK_SECONDS = CHUNK_CANDLES * GRANULARITY_SECONDS
REQUEST_PAUSE_SECONDS = 0.15
MAX_RETRIES = 8

ROOT = Path("data/research/crypto_intraday")
RAW_ROOT = ROOT / "raw_15m"
MANIFEST_ROOT = ROOT / "manifests"
STATUS_PATH = ROOT / "backfill_status.json"
MISSING_PATH = ROOT / "missing_intervals.csv"

COLUMNS = [
    "timestamp_utc",
    "product_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bar_seconds",
    "source",
]


@dataclass
class ProductStatus:
    product_id: str
    requested_start_utc: str
    requested_end_utc: str
    cursor_utc: str
    rows_written: int = 0
    requests_completed: int = 0
    missing_bar_count: int = 0
    complete: bool = False
    last_error: str | None = None


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _floor_15m(ts: pd.Timestamp) -> pd.Timestamp:
    return _utc(ts).floor("15min")


def _iso(ts: pd.Timestamp) -> str:
    return _utc(ts).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _month_path(product_id: str, timestamp_utc: pd.Timestamp) -> Path:
    ts = _utc(timestamp_utc)
    return RAW_ROOT / product_id / f"{ts.strftime('%Y-%m')}.parquet"


def _normalize_candles(product_id: str, payload) -> pd.DataFrame:
    """Convert Coinbase [time, low, high, open, close, volume] rows."""
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame(columns=COLUMNS)
    rows = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) < 6:
            continue
        try:
            epoch, low, high, open_, close, volume = item[:6]
            rows.append({
                "timestamp_utc": pd.Timestamp(int(epoch), unit="s", tz="UTC"),
                "product_id": product_id,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "bar_seconds": GRANULARITY_SECONDS,
                "source": "coinbase_exchange_rest_candles",
            })
        except (TypeError, ValueError, OverflowError):
            continue
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.DataFrame(rows, columns=COLUMNS)
    out = out.sort_values("timestamp_utc").drop_duplicates(
        ["timestamp_utc", "product_id"], keep="last"
    )
    return out.reset_index(drop=True)


def _request_candles(session: requests.Session, product_id: str, start: pd.Timestamp, end: pd.Timestamp):
    url = f"{API_ROOT}/products/{product_id}/candles"
    params = {
        "granularity": GRANULARITY_SECONDS,
        "start": _iso(start),
        "end": _iso(end),
    }
    delay = 1.0
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else delay
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                time.sleep(min(wait, 60.0))
                delay = min(delay * 2.0, 60.0)
                continue
            raise RuntimeError(
                f"Coinbase HTTP {response.status_code} for {product_id}: {response.text[:500]}"
            )
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == MAX_RETRIES:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 60.0)
    raise RuntimeError(last_error or f"Failed Coinbase request for {product_id}")


def _persist(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    written = 0
    for (product_id, month), group in frame.groupby(
        ["product_id", frame["timestamp_utc"].dt.strftime("%Y-%m")], sort=True
    ):
        path = RAW_ROOT / product_id / f"{month}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            existing["timestamp_utc"] = pd.to_datetime(existing["timestamp_utc"], utc=True)
            combined = pd.concat([existing, group[COLUMNS]], ignore_index=True)
        else:
            combined = group[COLUMNS].copy()
        combined = combined.sort_values("timestamp_utc").drop_duplicates(
            ["timestamp_utc", "product_id"], keep="last"
        )
        tmp = path.with_suffix(".parquet.tmp")
        combined.to_parquet(tmp, index=False)
        tmp.replace(path)
        written += len(group)
    return written


def _expected_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    # Coinbase candle timestamps are bar starts. End is treated as exclusive here.
    if end <= start:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(start=start, end=end - pd.Timedelta(seconds=GRANULARITY_SECONDS), freq="15min", tz="UTC")


def _missing_records(product_id: str, start: pd.Timestamp, end: pd.Timestamp, frame: pd.DataFrame) -> list[dict]:
    expected = _expected_grid(start, end)
    actual = pd.DatetimeIndex(pd.to_datetime(frame.get("timestamp_utc", pd.Series(dtype="datetime64[ns]")), utc=True).unique())
    missing = expected.difference(actual)
    return [
        {
            "product_id": product_id,
            "timestamp_utc": ts.isoformat(),
            "reason": "coinbase_rest_candle_missing",
        }
        for ts in missing
    ]


def _load_status() -> dict:
    if not STATUS_PATH.exists():
        return {"products": {}}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"products": {}}


def _save_status(products: dict[str, ProductStatus], start: pd.Timestamp, end: pd.Timestamp) -> None:
    _atomic_json(STATUS_PATH, {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "coinbase_exchange_rest_candles",
        "bar_seconds": GRANULARITY_SECONDS,
        "requested_start_utc": _iso(start),
        "requested_end_utc": _iso(end),
        "product_count": len(products),
        "completed_product_count": sum(1 for p in products.values() if p.complete),
        "products": {k: asdict(v) for k, v in sorted(products.items())},
    })


def _initial_product_status(product_id: str, start: pd.Timestamp, end: pd.Timestamp, previous: dict) -> ProductStatus:
    prev = previous.get("products", {}).get(product_id, {})
    prev_same_range = (
        prev.get("requested_start_utc") == _iso(start)
        and prev.get("requested_end_utc") == _iso(end)
    )
    cursor = _utc(prev.get("cursor_utc")) if prev_same_range and prev.get("cursor_utc") else start
    return ProductStatus(
        product_id=product_id,
        requested_start_utc=_iso(start),
        requested_end_utc=_iso(end),
        cursor_utc=_iso(max(start, cursor)),
        rows_written=int(prev.get("rows_written", 0)) if prev_same_range else 0,
        requests_completed=int(prev.get("requests_completed", 0)) if prev_same_range else 0,
        missing_bar_count=int(prev.get("missing_bar_count", 0)) if prev_same_range else 0,
        complete=bool(prev.get("complete", False)) if prev_same_range else False,
        last_error=None,
    )


def _append_missing(records: list[dict]) -> None:
    if not records:
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(records)
    if MISSING_PATH.exists():
        old = pd.read_csv(MISSING_PATH)
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    out = out.drop_duplicates(["product_id", "timestamp_utc", "reason"]).sort_values(
        ["product_id", "timestamp_utc"]
    )
    tmp = MISSING_PATH.with_suffix(".csv.tmp")
    out.to_csv(tmp, index=False)
    tmp.replace(MISSING_PATH)


def run_backfill(start: pd.Timestamp, end: pd.Timestamp, products: Iterable[str]) -> dict:
    start = _floor_15m(start)
    end = _floor_15m(end)
    if end <= start:
        raise ValueError("end must be after start")

    selected = tuple(dict.fromkeys(products))
    unknown = sorted(set(selected) - set(PRODUCTS))
    if unknown:
        raise ValueError("Unknown products: " + ", ".join(unknown))

    ROOT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)

    previous = _load_status()
    statuses = {
        p: _initial_product_status(p, start, end, previous)
        for p in selected
    }
    _save_status(statuses, start, end)

    session = requests.Session()
    session.headers.update({"User-Agent": "DataShepherdEngineering-CryptoResearch/1.0"})

    for product_id in selected:
        status = statuses[product_id]
        if status.complete:
            print(f"[SKIP] {product_id} already complete")
            continue
        cursor = _utc(status.cursor_utc)
        print(f"[START] {product_id} from {cursor} to {end}")
        while cursor < end:
            chunk_end = min(cursor + pd.Timedelta(seconds=CHUNK_SECONDS), end)
            try:
                payload = _request_candles(session, product_id, cursor, chunk_end)
                frame = _normalize_candles(product_id, payload)
                # Only retain bars in the requested half-open interval.
                if not frame.empty:
                    frame = frame[
                        (frame["timestamp_utc"] >= cursor)
                        & (frame["timestamp_utc"] < chunk_end)
                    ].copy()
                missing = _missing_records(product_id, cursor, chunk_end, frame)
                _persist(frame)
                _append_missing(missing)

                status.rows_written += int(len(frame))
                status.requests_completed += 1
                status.missing_bar_count += len(missing)
                status.cursor_utc = _iso(chunk_end)
                status.last_error = None
                cursor = chunk_end
                _save_status(statuses, start, end)
                if status.requests_completed % 25 == 0 or cursor >= end:
                    print(
                        f"  {product_id}: requests={status.requests_completed} "
                        f"rows={status.rows_written} missing={status.missing_bar_count} "
                        f"cursor={cursor}"
                    )
                time.sleep(REQUEST_PAUSE_SECONDS)
            except Exception as exc:
                status.last_error = f"{type(exc).__name__}: {exc}"
                _save_status(statuses, start, end)
                raise
        status.complete = True
        status.cursor_utc = _iso(end)
        _save_status(statuses, start, end)
        print(f"[SUCCESS] {product_id}")

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "coinbase_exchange_rest_candles",
        "api_root": API_ROOT,
        "granularity_seconds": GRANULARITY_SECONDS,
        "request_chunk_candles": CHUNK_CANDLES,
        "requested_start_utc": _iso(start),
        "requested_end_utc": _iso(end),
        "products": list(selected),
        "storage_root": str(RAW_ROOT),
        "missing_intervals": str(MISSING_PATH),
        "status": str(STATUS_PATH),
        "policy": "Missing candles are recorded and never synthesized. Historical REST candles remain separate from live WebSocket approximations.",
    }
    manifest_path = MANIFEST_ROOT / f"backfill_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.json"
    _atomic_json(manifest_path, manifest)
    return manifest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--start",
        default=(pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)).floor("D").isoformat(),
        help="UTC start timestamp; default is 365 days ago.",
    )
    ap.add_argument(
        "--end",
        default=pd.Timestamp.now(tz="UTC").floor("15min").isoformat(),
        help="UTC exclusive end timestamp; default is the current completed 15-minute boundary.",
    )
    ap.add_argument(
        "--products",
        nargs="*",
        default=list(PRODUCTS),
        help="Optional subset of configured product IDs.",
    )
    args = ap.parse_args(argv)

    manifest = run_backfill(_utc(args.start), _utc(args.end), args.products)
    print("CRYPTO INTRADAY 15-MINUTE BACKFILL COMPLETE")
    print("=" * 72)
    print(f"Start: {manifest['requested_start_utc']}")
    print(f"End:   {manifest['requested_end_utc']}")
    print(f"Products: {len(manifest['products'])}")
    print(f"Bars: {manifest['storage_root']}")
    print(f"Status: {manifest['status']}")
    print(f"Missing intervals: {manifest['missing_intervals']}")


if __name__ == "__main__":
    main()
