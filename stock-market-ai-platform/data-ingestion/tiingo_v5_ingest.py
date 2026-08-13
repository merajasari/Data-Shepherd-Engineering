"""Populate Bronze history for the isolated V5 research universe.

This entry point reuses the production Tiingo client and Bronze writer but
does not alter the 26-symbol V4 ingestion configuration. It is never called
by the daily V4 pipeline.

The default behavior is deliberately resume-safe for Tiingo's free-tier request
limits: symbols that already have a non-empty Bronze file are skipped, and each
run makes at most 45 new API requests. Run the same command again after the
hourly quota resets until no symbols remain. Use --force only when you
intentionally want to redownload already-populated symbols.
"""

import argparse
from datetime import date
from pathlib import Path

from bronze_writer import write_bronze
from tiingo_client import TiingoClient
from v5_symbols import get_v5_data_symbols


DEFAULT_START_DATE = "2016-08-01"
DEFAULT_MAX_REQUESTS = 45
BRONZE_ROOT = Path("data/bronze/stocks")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Optional subset for a small batch or retry (SPY is allowed).",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=(
            "Maximum new Tiingo requests in this run. Defaults to 45 to leave "
            "headroom below the free-tier 50 requests/hour limit."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload symbols even when a non-empty Bronze file already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the requested universe and resume plan without making API calls.",
    )
    return parser.parse_args()


def requested_symbols(values):
    configured = get_v5_data_symbols()
    if not values:
        return configured

    symbols = [value.upper().strip() for value in values]
    unsupported = sorted(set(symbols) - set(configured))
    if unsupported:
        raise ValueError(
            "Symbols are outside the configured V5 data universe: "
            + ", ".join(unsupported)
        )
    return list(dict.fromkeys(symbols))


def bronze_file(symbol):
    return BRONZE_ROOT / symbol / f"{symbol}_prices.csv"


def has_local_bronze(symbol):
    """Return True when a symbol already has a non-empty Bronze price file."""
    path = bronze_file(symbol)
    return path.exists() and path.is_file() and path.stat().st_size > 0


def build_resume_plan(symbols, force=False, max_requests=DEFAULT_MAX_REQUESTS):
    if max_requests < 1:
        raise ValueError("--max-requests must be at least 1")

    skipped = []
    pending = []
    for symbol in symbols:
        if not force and has_local_bronze(symbol):
            skipped.append(symbol)
        else:
            pending.append(symbol)

    batch = pending[:max_requests]
    deferred = pending[max_requests:]
    return skipped, batch, deferred


def print_plan(symbols, skipped, batch, deferred, start_date, end_date):
    print(f"V5 configured data symbols: {len(symbols)}")
    print(f"Date range: {start_date} -> {end_date}")
    print(f"Already populated / skipped: {len(skipped)}")
    print(f"API requests planned now: {len(batch)}")
    print(f"Deferred to a later run: {len(deferred)}")
    if batch:
        print("This batch: " + ", ".join(batch))
    if deferred:
        print("Deferred: " + ", ".join(deferred))


def main():
    args = parse_args()
    symbols = requested_symbols(args.symbols)
    skipped, batch, deferred = build_resume_plan(
        symbols,
        force=args.force,
        max_requests=args.max_requests,
    )

    print_plan(
        symbols,
        skipped,
        batch,
        deferred,
        args.start_date,
        args.end_date,
    )

    if args.dry_run:
        return

    if not batch:
        print("No Tiingo requests are needed for this run.")
        return

    client = TiingoClient()
    successful = []
    failed = []

    for index, symbol in enumerate(batch, start=1):
        print(f"[{index}/{len(batch)}] {symbol}")
        try:
            frame = client.get_daily_prices(
                symbol,
                args.start_date,
                args.end_date,
            )
            if frame.empty:
                raise ValueError("Tiingo returned no rows")
            write_bronze(frame, symbol)
            successful.append(symbol)
        except Exception as exc:
            failed.append((symbol, str(exc)))
            print(f"[ERROR] {symbol}: {exc}")

    print()
    print("V5 TIINGO BATCH SUMMARY")
    print(f"Successful this run: {len(successful)}")
    print(f"Failed this run:     {len(failed)}")
    print(f"Skipped existing:    {len(skipped)}")
    print(f"Still deferred:      {len(deferred)}")

    if failed:
        print("Failed symbols:")
        for symbol, error in failed:
            print(f"  {symbol}: {error}")

    remaining = [symbol for symbol, _ in failed] + deferred
    if remaining:
        print()
        print(
            "Run the same command again after the hourly Tiingo quota resets. "
            "Existing successful Bronze files will be skipped automatically."
        )
        print("Remaining symbols: " + ", ".join(remaining))

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
