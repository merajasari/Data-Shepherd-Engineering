"""Read-only historical crypto chart data from the authoritative 15-minute archive.

The archive remains the source of truth. For browser-scale charts we reduce each
product to its last observed close per UTC day. An archive-signature cache avoids
re-reading unchanged Parquet history on every dashboard refresh while invalidating
automatically whenever the product archive changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from ml.crypto_rt import PRODUCTS

RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
_DAILY_CACHE: dict[str, tuple[tuple, pd.DataFrame]] = {}


def _product_paths(product_id: str) -> list[Path]:
    return sorted((RAW_ROOT / product_id).glob("*.parquet"))


def _archive_signature(paths: list[Path]) -> tuple:
    """Cheap invalidation signature for a product's historical archive."""
    signature = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((path.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            signature.append((path.name, None, None))
    return tuple(signature)


def _read_product_paths(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc", "close"])
        except Exception:
            continue
        if len(frame):
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "close"])

    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["timestamp_utc", "close"])
    out = out[out["close"] > 0]
    out = out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    return out


def _daily_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["date"] = out["timestamp_utc"].dt.floor("D")
    daily = out.groupby("date", as_index=False).tail(1).copy()
    daily = daily[["date", "timestamp_utc", "close"]].sort_values("date")
    first = float(daily.iloc[0]["close"])
    daily["index_100"] = daily["close"] / first * 100.0
    return daily


def _daily_product(product_id: str) -> pd.DataFrame:
    paths = _product_paths(product_id)
    signature = _archive_signature(paths)
    cached = _DAILY_CACHE.get(product_id)
    if cached is not None and cached[0] == signature:
        return cached[1]

    daily = _daily_history(_read_product_paths(paths))
    _DAILY_CACHE[product_id] = (signature, daily)
    return daily


HISTORY_RANGE_DAYS = {
    "30D": 30,
    "90D": 90,
    "1Y": 365,
    "3Y": 3 * 365,
    "5Y": 5 * 365,
    "ALL": None,
}


def _normalize_range_key(range_key: str | None) -> str:
    key = str(range_key or "1Y").upper().strip()
    return key if key in HISTORY_RANGE_DAYS else "1Y"


def _slice_daily_for_range(daily: pd.DataFrame, range_key: str) -> pd.DataFrame:
    days = HISTORY_RANGE_DAYS[range_key]
    if daily.empty or days is None:
        return daily
    end = daily["timestamp_utc"].max()
    cutoff = end - pd.Timedelta(days=days)
    return daily[daily["timestamp_utc"] >= cutoff].copy()


def get_crypto_history_payload(
    products: Iterable[str] | None = None,
    range_key: str | None = "1Y",
) -> dict:
    requested = list(products or PRODUCTS)
    requested = [p for p in requested if p in PRODUCTS]
    if not requested:
        requested = list(PRODUCTS)

    range_key = _normalize_range_key(range_key)
    series = {}
    global_start = None
    global_end = None
    archive_total_points = 0
    loaded_total_points = 0

    for product_id in requested:
        full_daily = _daily_product(product_id)
        archive_total_points += len(full_daily)
        daily = _slice_daily_for_range(full_daily, range_key)
        if daily.empty:
            series[product_id] = {
                "available": False,
                "start_utc": None,
                "end_utc": None,
                "point_count": 0,
                "points": [],
            }
            continue

        start = daily.iloc[0]["timestamp_utc"]
        end = daily.iloc[-1]["timestamp_utc"]
        global_start = start if global_start is None else min(global_start, start)
        global_end = end if global_end is None else max(global_end, end)
        points = [
            {
                "t": row.timestamp_utc.isoformat(),
                "close": float(row.close),
                "index_100": float(row.index_100),
            }
            for row in daily.itertuples(index=False)
        ]
        loaded_total_points += len(points)
        series[product_id] = {
            "available": True,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "point_count": len(points),
            "first_close": float(daily.iloc[0]["close"]),
            "last_historical_close": float(daily.iloc[-1]["close"]),
            "points": points,
        }

    return {
        "status": "ok",
        "source": str(RAW_ROOT),
        "resolution": "daily_last_authoritative_15m_close",
        "underlying_archive_resolution": "15m",
        "normalization": "Each product begins at index 100 on its own first available observation.",
        "product_count": len(requested),
        "requested_range": range_key,
        "total_chart_points": loaded_total_points,
        "loaded_chart_points": loaded_total_points,
        "archive_total_chart_points": archive_total_points,
        "global_start_utc": global_start.isoformat() if global_start is not None else None,
        "global_end_utc": global_end.isoformat() if global_end is not None else None,
        "series": series,
        "cache": {
            "strategy": "archive_signature_per_product",
            "cached_products": len(_DAILY_CACHE),
        },
        "brokerage_orders": False,
    }
