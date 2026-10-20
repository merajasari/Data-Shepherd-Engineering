"""Quota-ready incremental Tiingo EOD updater for the 250-stock successor universe.

Contract
--------
* 250 investable candidates.
* SPY is benchmark-only.
* 251 total market-data symbols.
* Uses SPY as a one-request sentinel for the newest completed Tiingo EOD bar.
* Requests only symbols whose Bronze history is behind that target.
* Existing Bronze history is merged and deduplicated by timestamp.
* Incoming rows replace duplicate timestamps.
* Resume-safe across partial runs.
* Writes its own Stock-250 refresh state.
* Does not fit, score, freeze, paper trade, mutate V8/V10 evidence,
  or place brokerage orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from stock_universe_250 import get_stock_250_data_symbols
from tiingo_client import TiingoClient
from v5_symbols import V5_BENCHMARK_SYMBOL


BRONZE_ROOT = Path("data/bronze/stocks")
STATE_PATH = Path("data/live/stock250_eod_refresh_state.json")

DEFAULT_START_DATE = "2016-08-01"
DEFAULT_MAX_REQUESTS = 251
SENTINEL_LOOKBACK_DAYS = 10

INVESTABLE_CANDIDATE_COUNT = 250
DATA_SYMBOL_COUNT = 251


def contracted_symbols() -> list[str]:
    symbols = list(get_stock_250_data_symbols())

    if len(symbols) != DATA_SYMBOL_COUNT:
        raise ValueError(
            f"Stock-250 updater requires {DATA_SYMBOL_COUNT} data symbols; "
            f"found {len(symbols)}"
        )

    if len(set(symbols)) != DATA_SYMBOL_COUNT:
        raise ValueError(
            "Stock-250 updater data symbols must be unique"
        )

    if symbols[-1] != V5_BENCHMARK_SYMBOL:
        raise ValueError(
            "SPY must remain the final benchmark-only data symbol"
        )

    investable = [
        symbol
        for symbol in symbols
        if symbol != V5_BENCHMARK_SYMBOL
    ]

    if len(investable) != INVESTABLE_CANDIDATE_COUNT:
        raise ValueError(
            "Stock-250 updater requires exactly "
            f"{INVESTABLE_CANDIDATE_COUNT} investable candidates"
        )

    return symbols


def bronze_file(
    symbol: str,
    bronze_root: Path | None = None,
) -> Path:
    root = bronze_root or BRONZE_ROOT
    return root / symbol / f"{symbol}_prices.csv"


def read_bronze(
    symbol: str,
    bronze_root: Path | None = None,
) -> pd.DataFrame:
    path = bronze_file(symbol, bronze_root)

    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    return pd.read_csv(path)


def latest_timestamp_ms(
    symbol: str,
    bronze_root: Path | None = None,
) -> int | None:
    frame = read_bronze(symbol, bronze_root)

    if frame.empty or "timestamp" not in frame.columns:
        return None

    values = pd.to_numeric(
        frame["timestamp"],
        errors="coerce",
    ).dropna()

    if values.empty:
        return None

    return int(values.max())


def timestamp_ms_to_date(value: int) -> date:
    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc,
    ).date()


def merge_price_frames(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
) -> pd.DataFrame:
    if existing.empty:
        merged = incoming.copy()
    elif incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat(
            [existing, incoming],
            ignore_index=True,
        )

    if merged.empty:
        return merged

    if "timestamp" not in merged.columns:
        raise ValueError(
            "Bronze data must contain timestamp"
        )

    merged["timestamp"] = pd.to_numeric(
        merged["timestamp"],
        errors="raise",
    ).astype("int64")

    return (
        merged
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )


def write_bronze_atomic(
    frame: pd.DataFrame,
    symbol: str,
    bronze_root: Path | None = None,
) -> Path:
    path = bronze_file(symbol, bronze_root)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_suffix(".csv.tmp")

    frame.to_csv(
        temp,
        index=False,
    )

    temp.replace(path)

    return path


def fetch_symbol(
    client,
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    frame = client.get_daily_prices(
        symbol,
        start_date,
        end_date,
    )

    if frame.empty:
        raise ValueError(
            f"Tiingo returned no rows for {symbol}"
        )

    return frame


def fetch_sentinel(
    client,
    today: date | None = None,
):
    today = today or date.today()

    start = (
        today
        - timedelta(days=SENTINEL_LOOKBACK_DAYS)
    ).isoformat()

    frame = fetch_symbol(
        client,
        V5_BENCHMARK_SYMBOL,
        start,
        today.isoformat(),
    )

    target = int(
        pd.to_numeric(
            frame["timestamp"],
            errors="raise",
        ).max()
    )

    return frame, target


def stale_symbols(
    target_timestamp: int,
    symbols: list[str] | None = None,
    bronze_root: Path | None = None,
) -> list[str]:
    symbols = symbols or contracted_symbols()

    return [
        symbol
        for symbol in symbols
        if latest_timestamp_ms(
            symbol,
            bronze_root,
        ) is None
        or latest_timestamp_ms(
            symbol,
            bronze_root,
        ) < target_timestamp
    ]


def symbol_fetch_start(
    symbol: str,
    bronze_root: Path | None = None,
) -> str:
    current = latest_timestamp_ms(
        symbol,
        bronze_root,
    )

    if current is None:
        return DEFAULT_START_DATE

    # Re-request the last known session so adjusted data can
    # replace the existing row safely.
    return timestamp_ms_to_date(
        current
    ).isoformat()


def write_state(
    payload: dict,
    state_path: Path | None = None,
) -> Path:
    path = state_path or STATE_PATH

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    temp.replace(path)

    return path


def run_incremental_refresh(
    max_requests: int = DEFAULT_MAX_REQUESTS,
    today: date | None = None,
    client=None,
    bronze_root: Path | None = None,
    state_path: Path | None = None,
) -> dict:
    """Advance the full 251-symbol Bronze universe toward latest Tiingo EOD."""

    if max_requests < 1:
        raise ValueError(
            "max_requests must be at least 1"
        )

    symbols = contracted_symbols()

    client = client or TiingoClient()
    today = today or date.today()

    sentinel_frame, target = fetch_sentinel(
        client,
        today=today,
    )

    requests_used = 1
    updated = []
    failed = []

    spy_existing = read_bronze(
        V5_BENCHMARK_SYMBOL,
        bronze_root,
    )

    spy_latest = latest_timestamp_ms(
        V5_BENCHMARK_SYMBOL,
        bronze_root,
    )

    if spy_latest is None or spy_latest < target:
        write_bronze_atomic(
            merge_price_frames(
                spy_existing,
                sentinel_frame,
            ),
            V5_BENCHMARK_SYMBOL,
            bronze_root,
        )

        updated.append(
            V5_BENCHMARK_SYMBOL
        )

    pending = [
        symbol
        for symbol in stale_symbols(
            target,
            symbols=symbols,
            bronze_root=bronze_root,
        )
        if symbol != V5_BENCHMARK_SYMBOL
    ]

    remaining_budget = max(
        0,
        max_requests - requests_used,
    )

    batch = pending[:remaining_budget]

    for symbol in batch:
        try:
            incoming = fetch_symbol(
                client,
                symbol,
                symbol_fetch_start(
                    symbol,
                    bronze_root,
                ),
                today.isoformat(),
            )

            requests_used += 1

            write_bronze_atomic(
                merge_price_frames(
                    read_bronze(
                        symbol,
                        bronze_root,
                    ),
                    incoming,
                ),
                symbol,
                bronze_root,
            )

            updated.append(symbol)

        except Exception as exc:
            requests_used += 1

            failed.append(
                {
                    "symbol": symbol,
                    "error": str(exc),
                }
            )

    remaining = stale_symbols(
        target,
        symbols=symbols,
        bronze_root=bronze_root,
    )

    state = {
        "stage": "stock250_incremental_eod_bronze",
        "universe_contract": {
            "investable_candidate_count":
                INVESTABLE_CANDIDATE_COUNT,
            "benchmark_symbol":
                V5_BENCHMARK_SYMBOL,
            "benchmark_investable":
                False,
            "data_symbol_count":
                DATA_SYMBOL_COUNT,
        },
        "target_timestamp_ms": target,
        "target_date_utc":
            timestamp_ms_to_date(target).isoformat(),
        "requests_used": requests_used,
        "max_requests": max_requests,
        "updated_symbols": updated,
        "failed": failed,
        "remaining_symbols": remaining,
        "complete": not remaining,
        "model_fit": False,
        "model_score": False,
        "candidate_frozen": False,
        "v8_modified": False,
        "v10_modified": False,
        "holdout_evidence_modified": False,
        "brokerage_orders": False,
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
    }

    write_state(
        state,
        state_path,
    )

    return state


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=(
            "Total Tiingo request budget for this run, "
            "including the SPY sentinel."
        ),
    )

    return parser.parse_args()


def main():
    args = parse_args()

    state = run_incremental_refresh(
        max_requests=args.max_requests,
    )

    print(
        "STOCK-250 INCREMENTAL EOD REFRESH"
    )

    print(
        "Investable candidates: "
        f"{INVESTABLE_CANDIDATE_COUNT}"
    )

    print(
        "Data symbols: "
        f"{DATA_SYMBOL_COUNT}"
    )

    print(
        "Benchmark: "
        f"{V5_BENCHMARK_SYMBOL} "
        "(non-investable)"
    )

    print(
        "Target session: "
        f"{state['target_date_utc']}"
    )

    print(
        "Requests used: "
        f"{state['requests_used']}/"
        f"{state['max_requests']}"
    )

    print(
        "Updated this run: "
        f"{len(state['updated_symbols'])}"
    )

    print(
        "Failed this run: "
        f"{len(state['failed'])}"
    )

    print(
        "Still stale: "
        f"{len(state['remaining_symbols'])}"
    )

    print(
        "Complete: "
        f"{state['complete']}"
    )

    print(
        "V8 modified: False"
    )

    print(
        "V10 modified: False"
    )

    print(
        "Holdout evidence modified: False"
    )

    print(
        "Brokerage orders: OFF"
    )

    if state["remaining_symbols"]:
        print(
            "Remaining: "
            + ", ".join(
                state["remaining_symbols"]
            )
        )

    if state["failed"]:
        print("Failures:")

        for item in state["failed"]:
            print(
                f"  {item['symbol']}: "
                f"{item['error']}"
            )


if __name__ == "__main__":
    main()
