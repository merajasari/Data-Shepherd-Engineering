"""Populate Bronze history for the isolated V5 research universe.

This entry point reuses the production Tiingo client and Bronze writer but
does not alter the 26-symbol V4 ingestion configuration.  It is never called
by the daily V4 pipeline.
"""

import argparse
from datetime import date

from bronze_writer import write_bronze
from tiingo_client import TiingoClient
from v5_symbols import get_v5_data_symbols


DEFAULT_START_DATE = "2016-08-01"


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
        "--dry-run",
        action="store_true",
        help="Print the requested universe without making API calls.",
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


def main():
    args = parse_args()
    symbols = requested_symbols(args.symbols)

    print(f"V5 Tiingo data symbols: {len(symbols)}")
    print(f"Date range: {args.start_date} -> {args.end_date}")

    if args.dry_run:
        print(", ".join(symbols))
        return

    client = TiingoClient()
    successful = []
    failed = []

    for index, symbol in enumerate(symbols, start=1):
        print(f"[{index}/{len(symbols)}] {symbol}")
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

    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    for symbol, error in failed:
        print(f"  {symbol}: {error}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
