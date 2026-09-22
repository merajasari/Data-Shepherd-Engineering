"""Guarded StockEagle250 refresh through the final pre-holdout session.

This one-time research workflow updates the 250 candidates plus benchmark-only
SPY through September 22, 2026. It refuses to request September 23 or any later
date, merges incremental Tiingo rows into existing Bronze histories, rebuilds
Silver/Gold/Features, and reports whether all 251 feature files reached the
fixed cutoff.

It does not fit, score, freeze, paper trade, place orders, or write any existing
model artifact or forward journal.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = PROJECT_ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from stock_universe_250 import get_stock_250_data_symbols  # noqa: E402
from tiingo_client import TiingoClient  # noqa: E402

from ml.stock_eagle_250.backfill import (  # noqa: E402
    BRONZE_ROOT,
    DEFAULT_START_DATE,
    FEATURE_ROOT,
    bronze_file,
    feature_file,
    process_symbol_layers,
    redact_error,
    write_state,
)


HOLDOUT_START_DATE = date(2026, 9, 23)
PRE_HOLDOUT_END_DATE = date(2026, 9, 22)
DEFAULT_MAX_REQUESTS = 251
STATE_PATH = Path(
    "data/model/stock_eagle_250/pre_holdout_refresh/state.json"
)
REQUIRED_BRONZE_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
)


def parse_iso_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def validate_end_date(value) -> date:
    end_date = parse_iso_date(value)
    if end_date >= HOLDOUT_START_DATE:
        raise ValueError(
            "StockEagle250 development refresh cannot request the untouched "
            f"holdout beginning {HOLDOUT_START_DATE.isoformat()}"
        )
    if end_date != PRE_HOLDOUT_END_DATE:
        raise ValueError(
            "The preregistered one-time refresh must end exactly on "
            f"{PRE_HOLDOUT_END_DATE.isoformat()}"
        )
    return end_date


def requested_symbols(values=None) -> list[str]:
    contracted = tuple(get_stock_250_data_symbols())
    if not values:
        return list(contracted)

    symbols = list(dict.fromkeys(str(value).upper().strip() for value in values))
    unsupported = sorted(set(symbols) - set(contracted))
    if unsupported:
        raise ValueError(
            "Symbols are outside the StockEagle250 data universe: "
            + ", ".join(unsupported)
        )
    return symbols


def _session_date(values) -> date | None:
    timestamps = pd.to_datetime(values, utc=True, errors="coerce")
    valid = timestamps.dropna()
    if valid.empty:
        return None
    return valid.max().date()


def latest_bronze_session(
    symbol: str,
    bronze_root: Path = BRONZE_ROOT,
) -> date | None:
    path = bronze_file(symbol, bronze_root)
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_csv(path, usecols=["timestamp"])
    timestamps = pd.to_datetime(
        pd.to_numeric(frame["timestamp"], errors="coerce"),
        unit="ms",
        utc=True,
        errors="coerce",
    )
    return _session_date(timestamps)


def latest_feature_session(
    symbol: str,
    feature_root: Path = FEATURE_ROOT,
) -> date | None:
    path = feature_file(symbol, feature_root)
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_parquet(path, columns=["timestamp_utc"])
    return _session_date(frame["timestamp_utc"])


def build_refresh_plan(
    symbols,
    end_date=PRE_HOLDOUT_END_DATE,
    max_requests=DEFAULT_MAX_REQUESTS,
    bronze_root: Path = BRONZE_ROOT,
    feature_root: Path = FEATURE_ROOT,
) -> dict:
    end_date = validate_end_date(end_date)
    if max_requests < 1:
        raise ValueError("max_requests must be at least 1")

    complete = []
    transform_ready = []
    download_needed = []
    latest = {}

    for symbol in symbols:
        bronze_latest = latest_bronze_session(symbol, bronze_root)
        feature_latest = latest_feature_session(symbol, feature_root)
        latest[symbol] = {
            "bronze": bronze_latest.isoformat() if bronze_latest else None,
            "feature": feature_latest.isoformat() if feature_latest else None,
        }
        if bronze_latest is not None and bronze_latest >= end_date:
            if feature_latest is not None and feature_latest >= end_date:
                complete.append(symbol)
            else:
                transform_ready.append(symbol)
        else:
            download_needed.append(symbol)

    return {
        "complete": complete,
        "transform_ready": transform_ready,
        "download_batch": download_needed[:max_requests],
        "deferred": download_needed[max_requests:],
        "latest_before_refresh": latest,
    }


def merge_bronze_history(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    frames = []
    if existing is not None and not existing.empty:
        frames.append(existing.copy())
    if incoming is not None and not incoming.empty:
        frames.append(incoming.copy())
    if not frames:
        raise ValueError(f"No Bronze history is available for {symbol}")

    merged = pd.concat(frames, ignore_index=True)
    missing = sorted(set(REQUIRED_BRONZE_COLUMNS) - set(merged.columns))
    if missing:
        raise ValueError(f"Bronze history for {symbol} is missing columns: {missing}")

    merged = merged.loc[:, list(REQUIRED_BRONZE_COLUMNS)].copy()
    merged["symbol"] = symbol
    merged["timestamp"] = pd.to_numeric(merged["timestamp"], errors="coerce")
    merged = merged.dropna(subset=["timestamp"])
    merged = merged.sort_values("timestamp")
    merged = merged.drop_duplicates(subset=["symbol", "timestamp"], keep="last")
    merged = merged.reset_index(drop=True)
    if merged.empty:
        raise ValueError(f"Merged Bronze history is empty for {symbol}")
    return merged


def atomic_write_bronze(
    frame: pd.DataFrame,
    symbol: str,
    bronze_root: Path = BRONZE_ROOT,
) -> Path:
    path = bronze_file(symbol, bronze_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            frame.to_csv(handle, index=False)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return path


def refresh_one_symbol(
    symbol: str,
    end_date: date,
    client,
    bronze_root: Path = BRONZE_ROOT,
) -> dict:
    path = bronze_file(symbol, bronze_root)
    existing = pd.read_csv(path) if path.exists() and path.stat().st_size else None
    latest_before = latest_bronze_session(symbol, bronze_root)
    start_date = (
        latest_before.isoformat()
        if latest_before is not None
        else DEFAULT_START_DATE
    )
    incoming = client.get_daily_prices(
        symbol,
        start_date,
        end_date.isoformat(),
    )
    if incoming.empty:
        raise ValueError(
            f"Tiingo returned no rows for {symbol} through "
            f"{end_date.isoformat()}"
        )

    merged = merge_bronze_history(existing, incoming, symbol)
    merged_latest = _session_date(
        pd.to_datetime(
            pd.to_numeric(merged["timestamp"], errors="coerce"),
            unit="ms",
            utc=True,
            errors="coerce",
        )
    )
    if merged_latest is None or merged_latest < end_date:
        raise ValueError(
            f"{symbol} Bronze history stops at {merged_latest}; "
            f"required {end_date.isoformat()}"
        )

    atomic_write_bronze(merged, symbol, bronze_root)
    layer_result = process_symbol_layers(symbol, bronze_root=bronze_root)
    return {
        **layer_result,
        "request_start_date": start_date,
        "request_end_date": end_date.isoformat(),
        "latest_bronze_session": merged_latest.isoformat(),
    }


def run_refresh(
    symbols=None,
    end_date=PRE_HOLDOUT_END_DATE,
    max_requests=DEFAULT_MAX_REQUESTS,
    dry_run=False,
    client=None,
) -> dict:
    end_date = validate_end_date(end_date)
    contracted = tuple(get_stock_250_data_symbols())
    symbols = requested_symbols(symbols)
    plan = build_refresh_plan(
        symbols,
        end_date=end_date,
        max_requests=max_requests,
    )

    state = {
        "stage": "stock_eagle_250_guarded_pre_holdout_refresh",
        "research_only": True,
        "paper_trading_enabled": False,
        "brokerage_orders": False,
        "holdout_start_date": HOLDOUT_START_DATE.isoformat(),
        "maximum_permitted_source_date": PRE_HOLDOUT_END_DATE.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "holdout_rows_requested": 0,
        "requested_symbol_count": len(symbols),
        "contracted_data_symbol_count": len(contracted),
        "max_requests": max_requests,
        "requests_used": 0,
        "already_current": plan["complete"],
        "features_rebuilt_from_current_bronze": [],
        "downloaded_and_rebuilt": [],
        "failed": [],
        "deferred": plan["deferred"],
        "dry_run": dry_run,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        state["planned_feature_rebuilds"] = plan["transform_ready"]
        state["planned_downloads"] = plan["download_batch"]
        state["complete_requested_scope"] = (
            not plan["transform_ready"]
            and not plan["download_batch"]
            and not plan["deferred"]
        )
        state["ready_for_phase2_rebuild"] = (
            tuple(symbols) == contracted
            and state["complete_requested_scope"]
        )
        return state

    for symbol in plan["transform_ready"]:
        try:
            result = process_symbol_layers(symbol)
            feature_latest = latest_feature_session(symbol)
            if feature_latest is None or feature_latest < end_date:
                raise ValueError(
                    f"{symbol} feature history stops at {feature_latest}; "
                    f"required {end_date.isoformat()}"
                )
            state["features_rebuilt_from_current_bronze"].append({
                **result,
                "latest_feature_session": feature_latest.isoformat(),
            })
        except Exception as exc:
            state["failed"].append({
                "symbol": symbol,
                "stage": "rebuild_features_from_current_bronze",
                "error": redact_error(exc),
            })

    if plan["download_batch"]:
        client = client or TiingoClient()

    for index, symbol in enumerate(plan["download_batch"], start=1):
        state["requests_used"] += 1
        print(
            f"[{index}/{len(plan['download_batch'])}] "
            f"Refreshing {symbol} through {end_date.isoformat()}"
        )
        try:
            result = refresh_one_symbol(symbol, end_date, client)
            feature_latest = latest_feature_session(symbol)
            if feature_latest is None or feature_latest < end_date:
                raise ValueError(
                    f"{symbol} feature history stops at {feature_latest}; "
                    f"required {end_date.isoformat()}"
                )
            state["downloaded_and_rebuilt"].append({
                **result,
                "latest_feature_session": feature_latest.isoformat(),
            })
        except Exception as exc:
            state["failed"].append({
                "symbol": symbol,
                "stage": "incremental_download_or_rebuild",
                "error": redact_error(exc),
            })

    stale = []
    for symbol in symbols:
        feature_latest = latest_feature_session(symbol)
        if feature_latest is None or feature_latest < end_date:
            stale.append({
                "symbol": symbol,
                "latest_feature_session":
                    feature_latest.isoformat() if feature_latest else None,
            })

    state["stale_or_missing_features"] = stale
    state["complete_requested_scope"] = (
        not state["failed"]
        and not state["deferred"]
        and not stale
    )
    state["ready_for_phase2_rebuild"] = (
        tuple(symbols) == contracted
        and state["complete_requested_scope"]
    )
    state["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_state(state, path=STATE_PATH)
    return state


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--end-date",
        default=PRE_HOLDOUT_END_DATE.isoformat(),
        help="Must remain exactly 2026-09-22.",
    )
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help="Maximum incremental Tiingo requests in this invocation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the refresh plan without requests or data writes.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    state = run_refresh(
        symbols=args.symbols,
        end_date=args.end_date,
        max_requests=args.max_requests,
        dry_run=args.dry_run,
    )

    print("STOCKEAGLE250 GUARDED PRE-HOLDOUT REFRESH")
    print(f"Requested symbols: {state['requested_symbol_count']}")
    print(f"Cutoff: {state['requested_end_date']}")
    print(f"Holdout starts: {state['holdout_start_date']}")
    print(f"Holdout rows requested: {state['holdout_rows_requested']}")
    print(f"Already current: {len(state['already_current'])}")
    if state["dry_run"]:
        print(
            "Feature rebuilds planned: "
            f"{len(state['planned_feature_rebuilds'])}"
        )
        print(f"Tiingo requests planned: {len(state['planned_downloads'])}")
    else:
        print(
            "Features rebuilt from current Bronze: "
            f"{len(state['features_rebuilt_from_current_bronze'])}"
        )
        print(
            "Downloaded and rebuilt: "
            f"{len(state['downloaded_and_rebuilt'])}"
        )
        print(f"Requests used: {state['requests_used']}/{state['max_requests']}")
        print(f"Failed: {len(state['failed'])}")
        print(
            "Stale or missing features: "
            f"{len(state['stale_or_missing_features'])}"
        )
        print(f"State: {STATE_PATH}")
    print(f"Deferred: {len(state['deferred'])}")
    print(
        "Ready for Phase 2 rebuild: "
        f"{state['ready_for_phase2_rebuild']}"
    )

    if state.get("failed"):
        print("Failures:")
        for item in state["failed"]:
            print(f"  {item['symbol']} [{item['stage']}]: {item['error']}")
    if state.get("stale_or_missing_features"):
        print("Stale or missing:")
        for item in state["stale_or_missing_features"]:
            print(
                f"  {item['symbol']}: "
                f"{item['latest_feature_session']}"
            )

    if not state["dry_run"] and not state["ready_for_phase2_rebuild"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
