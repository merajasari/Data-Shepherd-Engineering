"""Resumable historical backfill for the 150 StockEagle250 additions.

The original frozen 100-stock data remains untouched. This workflow downloads
only missing daily Bronze histories for the additional candidates and then
builds Silver, Gold, and Pandas feature artifacts one symbol at a time.

No model is fit, scored, frozen, or paper traded by this module.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = PROJECT_ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from bronze_writer import write_bronze  # noqa: E402
from feature_transform import transform_to_features  # noqa: E402
from feature_writer import write_features  # noqa: E402
from gold_transform import transform_to_gold  # noqa: E402
from gold_writer import write_gold  # noqa: E402
from silver_transform import transform_to_silver  # noqa: E402
from silver_writer import write_silver  # noqa: E402
from stock_universe_250 import STOCK_250_ADDITIONS_BY_SECTOR  # noqa: E402
from tiingo_client import TiingoClient  # noqa: E402
from v5_symbols import V5_SYMBOLS, V5_BENCHMARK_SYMBOL  # noqa: E402


DEFAULT_START_DATE = "2016-08-01"
DEFAULT_MAX_REQUESTS = 45
BRONZE_ROOT = Path("data/bronze/stocks")
FEATURE_ROOT = Path("data/features/stocks")
STATE_PATH = Path("data/model/stock_eagle_250/backfill/state.json")

ADDITION_SYMBOLS = tuple(
    symbol
    for sector_symbols in STOCK_250_ADDITIONS_BY_SECTOR.values()
    for symbol in sector_symbols
)


def validate_scope() -> None:
    if len(ADDITION_SYMBOLS) != 150:
        raise ValueError(
            f"StockEagle250 backfill requires 150 additions, found {len(ADDITION_SYMBOLS)}"
        )
    if len(set(ADDITION_SYMBOLS)) != 150:
        raise ValueError("StockEagle250 backfill additions must be unique")
    overlap = sorted(set(ADDITION_SYMBOLS) & set(V5_SYMBOLS))
    if overlap:
        raise ValueError("Backfill scope overlaps frozen V5 candidates: " + ", ".join(overlap))
    if V5_BENCHMARK_SYMBOL in ADDITION_SYMBOLS:
        raise ValueError("SPY is already populated and must not be backfilled here")


def requested_symbols(values=None) -> list[str]:
    if not values:
        return list(ADDITION_SYMBOLS)
    symbols = list(dict.fromkeys(value.upper().strip() for value in values))
    unsupported = sorted(set(symbols) - set(ADDITION_SYMBOLS))
    if unsupported:
        raise ValueError(
            "Symbols are outside the StockEagle250 addition set: "
            + ", ".join(unsupported)
        )
    return symbols


def bronze_file(symbol: str, bronze_root: Path = BRONZE_ROOT) -> Path:
    return Path(bronze_root) / symbol / f"{symbol}_prices.csv"


def feature_file(symbol: str, feature_root: Path = FEATURE_ROOT) -> Path:
    return Path(feature_root) / symbol / f"{symbol}_features.parquet"


def nonempty_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def build_resume_plan(
    symbols,
    max_requests=DEFAULT_MAX_REQUESTS,
    bronze_root: Path = BRONZE_ROOT,
    feature_root: Path = FEATURE_ROOT,
):
    if max_requests < 1:
        raise ValueError("max_requests must be at least 1")

    complete = []
    transform_ready = []
    download_needed = []
    for symbol in symbols:
        if nonempty_file(feature_file(symbol, feature_root)):
            complete.append(symbol)
        elif nonempty_file(bronze_file(symbol, bronze_root)):
            transform_ready.append(symbol)
        else:
            download_needed.append(symbol)

    download_batch = download_needed[:max_requests]
    deferred = download_needed[max_requests:]
    return {
        "complete": complete,
        "transform_ready": transform_ready,
        "download_batch": download_batch,
        "deferred": deferred,
    }


def redact_error(exc: Exception) -> str:
    message = str(exc)
    secret = os.getenv("TIINGO_API_KEY")
    if secret:
        message = message.replace(secret, "<redacted>")
    message = re.sub(
        r"(?i)(token=)[^&\s]+",
        r"\1<redacted>",
        message,
    )
    return f"{type(exc).__name__}: {message}"


def process_symbol_layers(
    symbol: str,
    bronze_root: Path = BRONZE_ROOT,
) -> dict:
    path = bronze_file(symbol, bronze_root)
    if not nonempty_file(path):
        raise FileNotFoundError(f"Bronze history is missing for {symbol}: {path}")

    bronze = pd.read_csv(path)
    silver = transform_to_silver(bronze)
    write_silver(silver, symbol)

    gold = transform_to_gold(silver)
    write_gold(gold, symbol)

    features = transform_to_features(gold)
    write_features(features, symbol)

    return {
        "symbol": symbol,
        "bronze_rows": int(len(bronze)),
        "silver_rows": int(len(silver)),
        "gold_rows": int(len(gold)),
        "feature_rows": int(len(features)),
    }


def write_state(payload: dict, path: Path = STATE_PATH) -> None:
    path = Path(path)
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
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def run_backfill(
    symbols=None,
    start_date=DEFAULT_START_DATE,
    end_date=None,
    max_requests=DEFAULT_MAX_REQUESTS,
    dry_run=False,
    client=None,
) -> dict:
    validate_scope()
    symbols = requested_symbols(symbols)
    end_date = end_date or date.today().isoformat()
    plan = build_resume_plan(symbols, max_requests=max_requests)

    state = {
        "stage": "stock_eagle_250_additions_historical_backfill",
        "research_only": True,
        "paper_trading_enabled": False,
        "brokerage_orders": False,
        "start_date": start_date,
        "end_date": end_date,
        "requested_symbol_count": len(symbols),
        "max_requests": max_requests,
        "requests_used": 0,
        "already_complete": plan["complete"],
        "bronze_reused": [],
        "downloaded": [],
        "processed": [],
        "failed": [],
        "deferred": plan["deferred"],
        "dry_run": dry_run,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        state["planned_bronze_reuse"] = plan["transform_ready"]
        state["planned_downloads"] = plan["download_batch"]
        state["remaining_symbols"] = [
            *plan["transform_ready"],
            *plan["download_batch"],
            *plan["deferred"],
        ]
        state["complete"] = not state["remaining_symbols"]
        return state

    for symbol in plan["transform_ready"]:
        try:
            result = process_symbol_layers(symbol)
            state["bronze_reused"].append(symbol)
            state["processed"].append(result)
        except Exception as exc:
            state["failed"].append({
                "symbol": symbol,
                "stage": "transform_existing_bronze",
                "error": redact_error(exc),
            })

    if plan["download_batch"]:
        client = client or TiingoClient()

    for symbol in plan["download_batch"]:
        try:
            frame = client.get_daily_prices(symbol, start_date, end_date)
            state["requests_used"] += 1
            if frame.empty:
                raise ValueError("Tiingo returned no rows")
            write_bronze(frame, symbol)
            state["downloaded"].append(symbol)
            state["processed"].append(process_symbol_layers(symbol))
        except Exception as exc:
            if state["requests_used"] < len(state["downloaded"]) + len(state["failed"]) + 1:
                state["requests_used"] += 1
            state["failed"].append({
                "symbol": symbol,
                "stage": "download_or_transform",
                "error": redact_error(exc),
            })

    state["remaining_symbols"] = [
        symbol
        for symbol in symbols
        if not nonempty_file(feature_file(symbol))
    ]
    state["complete"] = not state["remaining_symbols"]
    state["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_state(state)
    return state


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help="Maximum new Tiingo daily-history requests in this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the resume plan without making requests or writing data layers.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    state = run_backfill(
        symbols=args.symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        max_requests=args.max_requests,
        dry_run=args.dry_run,
    )

    print("STOCKEAGLE250 HISTORICAL BACKFILL")
    print(f"Requested additions: {state['requested_symbol_count']}")
    print(f"Already complete: {len(state['already_complete'])}")
    if state["dry_run"]:
        print(f"Existing Bronze to transform: {len(state['planned_bronze_reuse'])}")
        print(f"Tiingo requests planned: {len(state['planned_downloads'])}")
    else:
        print(f"Existing Bronze transformed: {len(state['bronze_reused'])}")
        print(f"Tiingo requests used: {state['requests_used']}/{state['max_requests']}")
        print(f"Downloaded: {len(state['downloaded'])}")
        print(f"Processed through Features: {len(state['processed'])}")
        print(f"Failed: {len(state['failed'])}")
    print(f"Deferred: {len(state['deferred'])}")
    print(f"Remaining without features: {len(state['remaining_symbols'])}")
    print(f"Complete: {state['complete']}")
    if state["remaining_symbols"]:
        print("Remaining: " + ", ".join(state["remaining_symbols"]))
    if state["failed"]:
        print("Failures:")
        for item in state["failed"]:
            print(f"  {item['symbol']} [{item['stage']}]: {item['error']}")
    if not state["dry_run"]:
        print(f"State: {STATE_PATH}")


if __name__ == "__main__":
    main()
