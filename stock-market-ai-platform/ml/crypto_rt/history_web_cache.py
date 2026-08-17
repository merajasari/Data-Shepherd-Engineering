"""Publish compact persistent crypto-history payloads for the web dashboard.

The authoritative 15-minute Parquet archive remains the source of truth. This
module performs the expensive archive scan outside the request path and writes
small daily JSON payloads that Flask can serve directly.

The current Coinbase ticker is still appended separately by the browser, so the
historical cache only needs to rebuild once per UTC day under normal operation.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ml.crypto_rt import PRODUCTS

RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
OUTPUT_ROOT = Path("data/live/crypto_rt/history_web")
STATE_PATH = OUTPUT_ROOT / "cache_state.json"

RANGE_DAYS: dict[str, int | None] = {
    "30D": 30,
    "90D": 90,
    "1Y": 365,
    "3Y": 365 * 3,
    "5Y": 365 * 5,
    "ALL": None,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _product_paths(product_id: str) -> list[Path]:
    return sorted((RAW_ROOT / product_id).glob("*.parquet"))


def _read_daily_product(product_id: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in _product_paths(product_id):
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc", "close"])
        except Exception as exc:
            print(f"[WARN] {product_id}: cannot read {path.name}: {exc}")
            continue
        if len(frame):
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "close", "index_100"])

    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["timestamp_utc", "close"])
    out = out[out["close"] > 0]
    out = out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    out["date"] = out["timestamp_utc"].dt.floor("D")
    out = out.groupby("date", as_index=False).tail(1)
    out = out[["timestamp_utc", "close"]].sort_values("timestamp_utc").reset_index(drop=True)
    if len(out):
        first = float(out.iloc[0]["close"])
        out["index_100"] = out["close"] / first * 100.0
    else:
        out["index_100"] = pd.Series(dtype=float)
    return out


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _all_outputs_exist() -> bool:
    return all((OUTPUT_ROOT / f"{name}.json").exists() for name in RANGE_DAYS)


def _needs_rebuild(force: bool) -> bool:
    if force or not _all_outputs_exist():
        return True
    state = _load_state()
    return state.get("source_utc_date") != _utc_now().date().isoformat()


def _slice_frame(frame: pd.DataFrame, days: int | None, global_end: pd.Timestamp | None) -> pd.DataFrame:
    if frame.empty or days is None or global_end is None:
        return frame
    cutoff = global_end - pd.Timedelta(days=days)
    return frame[frame["timestamp_utc"] >= cutoff].copy()


def _payload_for_range(
    daily_by_product: dict[str, pd.DataFrame],
    range_name: str,
    days: int | None,
    archive_start: pd.Timestamp | None,
    archive_end: pd.Timestamp | None,
    archive_total_points: int,
    generated_at: datetime,
) -> dict:
    series: dict[str, dict] = {}
    loaded_start = None
    loaded_end = None
    loaded_points = 0

    for product_id in PRODUCTS:
        full = daily_by_product.get(product_id)
        if full is None:
            full = pd.DataFrame(columns=["timestamp_utc", "close", "index_100"])
        frame = _slice_frame(full, days, archive_end)
        if frame.empty:
            series[product_id] = {
                "available": False,
                "start_utc": None,
                "end_utc": None,
                "point_count": 0,
                "points": [],
            }
            continue

        start = frame.iloc[0]["timestamp_utc"]
        end = frame.iloc[-1]["timestamp_utc"]
        loaded_start = start if loaded_start is None else min(loaded_start, start)
        loaded_end = end if loaded_end is None else max(loaded_end, end)

        # Re-normalize each requested window to 100 at its own first loaded point.
        first_close = float(frame.iloc[0]["close"])
        points = [
            {
                "t": row.timestamp_utc.isoformat(),
                "close": round(float(row.close), 12),
                "index_100": round(float(row.close) / first_close * 100.0, 8),
            }
            for row in frame.itertuples(index=False)
        ]
        loaded_points += len(points)
        series[product_id] = {
            "available": True,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "point_count": len(points),
            "first_close": first_close,
            "last_historical_close": float(frame.iloc[-1]["close"]),
            "points": points,
        }

    return {
        "status": "ok",
        "source": str(RAW_ROOT),
        "delivery_source": "persistent_precomputed_web_cache",
        "generated_at_utc": generated_at.isoformat(),
        "range": range_name,
        "range_days": days,
        "resolution": "daily_last_authoritative_15m_close",
        "underlying_archive_resolution": "15m",
        "normalization": "Each product begins at index 100 on its first observation in the requested window.",
        "product_count": len(PRODUCTS),
        "total_chart_points": loaded_points,
        "global_start_utc": loaded_start.isoformat() if loaded_start is not None else None,
        "global_end_utc": loaded_end.isoformat() if loaded_end is not None else None,
        "archive_total_chart_points": archive_total_points,
        "archive_global_start_utc": archive_start.isoformat() if archive_start is not None else None,
        "archive_global_end_utc": archive_end.isoformat() if archive_end is not None else None,
        "series": series,
        "brokerage_orders": False,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    tmp.replace(path)


def publish(force: bool = False) -> bool:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not _needs_rebuild(force):
        print("CRYPTO HISTORY WEB CACHE: current UTC-day cache already exists; nothing to rebuild")
        return False

    started = _utc_now()
    print("CRYPTO HISTORY WEB CACHE")
    print("=" * 88)
    print(f"Building persistent daily history for {len(PRODUCTS)} products...")

    daily_by_product: dict[str, pd.DataFrame] = {}
    archive_start = None
    archive_end = None
    archive_total_points = 0

    for index, product_id in enumerate(PRODUCTS, start=1):
        daily = _read_daily_product(product_id)
        daily_by_product[product_id] = daily
        if len(daily):
            start = daily.iloc[0]["timestamp_utc"]
            end = daily.iloc[-1]["timestamp_utc"]
            archive_start = start if archive_start is None else min(archive_start, start)
            archive_end = end if archive_end is None else max(archive_end, end)
            archive_total_points += len(daily)
        print(f"[{index:02d}/{len(PRODUCTS):02d}] {product_id}: {len(daily):,} daily points")

    generated_at = _utc_now()
    for range_name, days in RANGE_DAYS.items():
        payload = _payload_for_range(
            daily_by_product,
            range_name,
            days,
            archive_start,
            archive_end,
            archive_total_points,
            generated_at,
        )
        path = OUTPUT_ROOT / f"{range_name}.json"
        _atomic_json(path, payload)
        print(f"[WRITE] {range_name:>3}: {payload['total_chart_points']:,} points -> {path}")

    state = {
        "status": "ok",
        "source_utc_date": generated_at.date().isoformat(),
        "generated_at_utc": generated_at.isoformat(),
        "build_seconds": round((generated_at - started).total_seconds(), 3),
        "product_count": len(PRODUCTS),
        "archive_total_chart_points": archive_total_points,
        "archive_global_start_utc": archive_start.isoformat() if archive_start is not None else None,
        "archive_global_end_utc": archive_end.isoformat() if archive_end is not None else None,
        "brokerage_orders": False,
    }
    _atomic_json(STATE_PATH, state)
    print("=" * 88)
    print(f"READY: persistent web cache built in {state['build_seconds']:.1f}s")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild even if today's persistent cache exists")
    args = parser.parse_args()
    publish(force=args.force)


if __name__ == "__main__":
    main()
