"""Resumable, listing-aware Coinbase Exchange 15-minute historical backfill.

Builds an authoritative REST-candle archive for the configured crypto universe.
The requested research horizon defaults to 10 years, but each product begins at
its earliest discoverable Coinbase candle instead of wasting thousands of calls
on pre-listing history.

Historical REST research data stays separate from forward live WebSocket data.
Missing intervals after a product's discovered first candle are recorded and are
never synthesized. Pre-listing time is metadata, not a data-quality gap.
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
GRANULARITY_SECONDS = BAR_SECONDS
MAX_CANDLES_PER_REQUEST = 300
CHUNK_CANDLES = 288
CHUNK_SECONDS = CHUNK_CANDLES * GRANULARITY_SECONDS
REQUEST_PAUSE_SECONDS = 0.15
MAX_RETRIES = 8
DEFAULT_HISTORY_YEARS = 10

# Listing discovery uses a short legal candle request every 30 days until data is
# found, then scans the preceding 30-day block in 3-day chunks. This turns years
# of empty pre-listing requests into tens of probes rather than thousands.
DISCOVERY_STRIDE_DAYS = 30
DISCOVERY_WINDOW_DAYS = 3

ROOT = Path("data/research/crypto_intraday")
RAW_ROOT = ROOT / "raw_15m"
MANIFEST_ROOT = ROOT / "manifests"
STATUS_PATH = ROOT / "backfill_status.json"
MISSING_PATH = ROOT / "missing_intervals.csv"

COLUMNS = [
    "timestamp_utc", "product_id", "open", "high", "low", "close",
    "volume", "bar_seconds", "source",
]


@dataclass
class ProductStatus:
    product_id: str
    requested_start_utc: str
    requested_end_utc: str
    cursor_utc: str
    listing_start_utc: str | None = None
    rows_written: int = 0
    requests_completed: int = 0
    discovery_requests: int = 0
    missing_bar_count: int = 0
    prelisting_intervals_skipped: int = 0
    complete: bool = False
    last_error: str | None = None


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _floor_15m(ts) -> pd.Timestamp:
    return _utc(ts).floor("15min")


def _iso(ts) -> str:
    return _utc(ts).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _normalize_candles(product_id: str, payload) -> pd.DataFrame:
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
    return (
        pd.DataFrame(rows, columns=COLUMNS)
        .sort_values("timestamp_utc")
        .drop_duplicates(["timestamp_utc", "product_id"], keep="last")
        .reset_index(drop=True)
    )


def _request_candles(session: requests.Session, product_id: str, start, end):
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
                f"Coinbase HTTP {response.status_code} for {product_id}: "
                f"{response.text[:500]}"
            )
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == MAX_RETRIES:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 60.0)
    raise RuntimeError(last_error or f"Failed Coinbase request for {product_id}")


def _existing_earliest(product_id: str) -> pd.Timestamp | None:
    product_root = RAW_ROOT / product_id
    if not product_root.exists():
        return None
    earliest = None
    for path in sorted(product_root.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc"])
        except Exception:
            continue
        if frame.empty:
            continue
        value = pd.to_datetime(frame["timestamp_utc"], utc=True).min()
        if pd.notna(value) and (earliest is None or value < earliest):
            earliest = value
    return earliest


def _probe(session, product_id, start, end) -> pd.DataFrame:
    payload = _request_candles(session, product_id, start, end)
    frame = _normalize_candles(product_id, payload)
    if not frame.empty:
        frame = frame[(frame["timestamp_utc"] >= start) & (frame["timestamp_utc"] < end)].copy()
    time.sleep(REQUEST_PAUSE_SECONDS)
    return frame


def _discover_listing_start(session, product_id, requested_start, requested_end):
    """Return earliest discoverable candle and number of discovery requests.

    A short 3-day probe is moved forward in 30-day steps. Once a non-empty probe
    is found, the preceding 30-day block is scanned in 3-day increments. Existing
    local candles provide a safe upper bound and reduce probing further.
    """
    existing = _existing_earliest(product_id)
    search_end = min(requested_end, existing) if existing is not None else requested_end
    if search_end <= requested_start:
        return (existing if existing is not None else requested_start), 0

    stride = pd.Timedelta(days=DISCOVERY_STRIDE_DAYS)
    window = pd.Timedelta(days=DISCOVERY_WINDOW_DAYS)
    probe = requested_start
    requests_used = 0
    first_nonempty = None

    while probe < search_end:
        probe_end = min(probe + window, search_end)
        frame = _probe(session, product_id, probe, probe_end)
        requests_used += 1
        if not frame.empty:
            first_nonempty = frame["timestamp_utc"].min()
            break
        probe += stride

    if first_nonempty is None:
        # We may have hopped over the exact listing period; if local data exists,
        # use it as the upper bound and refine the preceding stride block.
        if existing is None:
            return None, requests_used
        first_nonempty = existing

    refine_start = max(requested_start, first_nonempty - stride)
    cursor = refine_start
    earliest = first_nonempty
    while cursor < first_nonempty:
        chunk_end = min(cursor + window, first_nonempty + pd.Timedelta(seconds=GRANULARITY_SECONDS))
        frame = _probe(session, product_id, cursor, chunk_end)
        requests_used += 1
        if not frame.empty:
            earliest = min(earliest, frame["timestamp_utc"].min())
            break
        cursor += window

    return _floor_15m(earliest), requests_used


def _persist(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    for (product_id, month), group in frame.groupby(
        ["product_id", frame["timestamp_utc"].dt.strftime("%Y-%m")], sort=True
    ):
        path = RAW_ROOT / product_id / f"{month}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            old = pd.read_parquet(path)
            old["timestamp_utc"] = pd.to_datetime(old["timestamp_utc"], utc=True)
            combined = pd.concat([old, group[COLUMNS]], ignore_index=True)
        else:
            combined = group[COLUMNS].copy()
        combined = combined.sort_values("timestamp_utc").drop_duplicates(
            ["timestamp_utc", "product_id"], keep="last"
        )
        tmp = path.with_suffix(".parquet.tmp")
        combined.to_parquet(tmp, index=False)
        tmp.replace(path)
    return len(frame)


def _expected_grid(start, end):
    if end <= start:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(
        start=start,
        end=end - pd.Timedelta(seconds=GRANULARITY_SECONDS),
        freq="15min",
        tz="UTC",
    )


def _missing_records(product_id, start, end, frame):
    expected = _expected_grid(start, end)
    actual = pd.DatetimeIndex(
        pd.to_datetime(
            frame.get("timestamp_utc", pd.Series(dtype="datetime64[ns]")), utc=True
        ).unique()
    )
    return [
        {
            "product_id": product_id,
            "timestamp_utc": ts.isoformat(),
            "reason": "coinbase_rest_candle_missing_after_listing",
        }
        for ts in expected.difference(actual)
    ]


def _load_status() -> dict:
    if not STATUS_PATH.exists():
        return {"products": {}}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"products": {}}


def _save_status(products, start, end):
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


def _initial_product_status(product_id, start, end, previous):
    prev = previous.get("products", {}).get(product_id, {})
    same = (
        prev.get("requested_start_utc") == _iso(start)
        and prev.get("requested_end_utc") == _iso(end)
    )
    cursor = _utc(prev.get("cursor_utc")) if same and prev.get("cursor_utc") else start
    return ProductStatus(
        product_id=product_id,
        requested_start_utc=_iso(start),
        requested_end_utc=_iso(end),
        cursor_utc=_iso(max(start, cursor)),
        listing_start_utc=prev.get("listing_start_utc") if same else None,
        rows_written=int(prev.get("rows_written", 0)) if same else 0,
        requests_completed=int(prev.get("requests_completed", 0)) if same else 0,
        discovery_requests=int(prev.get("discovery_requests", 0)) if same else 0,
        missing_bar_count=int(prev.get("missing_bar_count", 0)) if same else 0,
        prelisting_intervals_skipped=int(prev.get("prelisting_intervals_skipped", 0)) if same else 0,
        complete=bool(prev.get("complete", False)) if same else False,
        last_error=None,
    )


def _append_missing(records):
    if not records:
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(records)
    old = pd.read_csv(MISSING_PATH) if MISSING_PATH.exists() else pd.DataFrame(columns=new.columns)
    out = pd.concat([old, new], ignore_index=True)
    out = out.drop_duplicates(["product_id", "timestamp_utc", "reason"]).sort_values(
        ["product_id", "timestamp_utc"]
    )
    tmp = MISSING_PATH.with_suffix(".csv.tmp")
    out.to_csv(tmp, index=False)
    tmp.replace(MISSING_PATH)


def _prune_prelisting_missing(product_id: str, listing_start: pd.Timestamp) -> None:
    if not MISSING_PATH.exists():
        return
    frame = pd.read_csv(MISSING_PATH)
    if frame.empty or "timestamp_utc" not in frame.columns:
        return
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    keep = ~((frame["product_id"] == product_id) & (timestamps < listing_start))
    frame = frame.loc[keep].copy()
    tmp = MISSING_PATH.with_suffix(".csv.tmp")
    frame.to_csv(tmp, index=False)
    tmp.replace(MISSING_PATH)


def run_backfill(start, end, products: Iterable[str]):
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
    statuses = {p: _initial_product_status(p, start, end, previous) for p in selected}
    _save_status(statuses, start, end)

    session = requests.Session()
    session.headers.update({"User-Agent": "DataShepherdEngineering-CryptoResearch/1.0"})

    for product_id in selected:
        status = statuses[product_id]
        if status.complete:
            print(f"[SKIP] {product_id} already complete")
            continue

        # Discover once per requested range. A previously interrupted pre-listing
        # scan is intentionally superseded by this listing-aware boundary.
        if not status.listing_start_utc:
            print(f"[DISCOVER] {product_id} earliest Coinbase 15m history...")
            listing_start, discovery_requests = _discover_listing_start(
                session, product_id, start, end
            )
            status.discovery_requests += discovery_requests
            if listing_start is None:
                status.complete = True
                status.cursor_utc = _iso(end)
                status.last_error = "No Coinbase candles discovered in requested range"
                _save_status(statuses, start, end)
                print(f"[NO DATA] {product_id}")
                continue
            status.listing_start_utc = _iso(listing_start)
            status.prelisting_intervals_skipped = max(
                0, int((listing_start - start).total_seconds() // GRANULARITY_SECONDS)
            )
            status.cursor_utc = _iso(max(listing_start, start))
            # Old pre-listing requests from an interrupted run must not remain
            # classified as missing market data.
            status.missing_bar_count = 0
            _prune_prelisting_missing(product_id, listing_start)
            _save_status(statuses, start, end)
            print(
                f"[LISTING] {product_id} first candle ~ {listing_start} "
                f"(discovery requests={discovery_requests}, "
                f"prelisting bars skipped={status.prelisting_intervals_skipped})"
            )

        listing_start = _utc(status.listing_start_utc)
        cursor = max(_utc(status.cursor_utc), listing_start)
        print(f"[START] {product_id} from {cursor} to {end}")

        while cursor < end:
            chunk_end = min(cursor + pd.Timedelta(seconds=CHUNK_SECONDS), end)
            try:
                frame = _normalize_candles(
                    product_id,
                    _request_candles(session, product_id, cursor, chunk_end),
                )
                if not frame.empty:
                    frame = frame[
                        (frame["timestamp_utc"] >= cursor)
                        & (frame["timestamp_utc"] < chunk_end)
                    ].copy()
                missing = _missing_records(product_id, cursor, chunk_end, frame)
                _persist(frame)
                _append_missing(missing)

                status.rows_written += len(frame)
                status.requests_completed += 1
                status.missing_bar_count += len(missing)
                status.cursor_utc = _iso(chunk_end)
                status.last_error = None
                cursor = chunk_end
                _save_status(statuses, start, end)

                if status.requests_completed % 100 == 0 or cursor >= end:
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
        "listing_discovery_stride_days": DISCOVERY_STRIDE_DAYS,
        "listing_discovery_window_days": DISCOVERY_WINDOW_DAYS,
        "requested_start_utc": _iso(start),
        "requested_end_utc": _iso(end),
        "products": list(selected),
        "storage_root": str(RAW_ROOT),
        "missing_intervals": str(MISSING_PATH),
        "status": str(STATUS_PATH),
        "policy": (
            "Requested horizon is preserved in metadata. Each product starts at "
            "its earliest discoverable Coinbase candle. Pre-listing time is not "
            "treated as missing data. Missing candles after listing are recorded "
            "and never synthesized. Historical REST data remains separate from "
            "live WebSocket approximations."
        ),
    }
    path = MANIFEST_ROOT / f"backfill_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.json"
    _atomic_json(path, manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    default_start = (
        pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=DEFAULT_HISTORY_YEARS)
    ).floor("D").isoformat()
    ap.add_argument(
        "--start", default=default_start,
        help=f"UTC start timestamp; default is {DEFAULT_HISTORY_YEARS} years ago.",
    )
    ap.add_argument(
        "--end", default=pd.Timestamp.now(tz="UTC").floor("15min").isoformat(),
        help="UTC exclusive end timestamp; default current completed 15-minute boundary.",
    )
    ap.add_argument(
        "--products", nargs="*", default=list(PRODUCTS),
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
