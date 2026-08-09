"""
Rate-limit-aware multi-symbol market data ingestion pipeline.
"""

from pathlib import Path
import time

import requests

from download_prices import ingest_symbol
from symbols import get_symbols


START_DATE = "2021-01-01"
END_DATE = "2026-01-01"

BRONZE_PATH = Path("data/bronze/stocks")

REQUEST_DELAY_SECONDS = 15
MAX_RETRIES = 5
RETRY_WAIT_SECONDS = 60


def bronze_file(symbol: str) -> Path:
    """Return expected Bronze file path."""

    return (
        BRONZE_PATH
        / symbol
        / f"{symbol}_prices.csv"
    )


def ingest_with_retry(symbol: str):
    """Ingest one symbol with retry handling for HTTP 429."""

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            return ingest_symbol(
                symbol,
                START_DATE,
                END_DATE,
            )

        except requests.exceptions.HTTPError as exc:

            status_code = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            if (
                status_code == 429
                and attempt < MAX_RETRIES
            ):
                print(
                    f"[RATE LIMIT] {symbol}: "
                    f"waiting {RETRY_WAIT_SECONDS}s "
                    f"before retry "
                    f"{attempt + 1}/{MAX_RETRIES}"
                )

                time.sleep(
                    RETRY_WAIT_SECONDS
                )

                continue

            raise


def run_multi_ingest():
    """Ingest all configured symbols."""

    symbols = get_symbols()

    successful = []
    skipped = []
    failed = []

    print(
        f"Starting ingestion for "
        f"{len(symbols)} symbols"
    )

    print(
        f"Date range: "
        f"{START_DATE} -> {END_DATE}"
    )

    print(
        f"Delay between API requests: "
        f"{REQUEST_DELAY_SECONDS}s"
    )

    print()

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):

        print(
            f"[{index}/{len(symbols)}] "
            f"Processing {symbol}"
        )

        output_file = bronze_file(
            symbol
        )

        if output_file.exists():

            skipped.append(
                symbol
            )

            print(
                f"[SKIP] {symbol}: "
                f"Bronze dataset already exists"
            )

            print()

            continue

        try:

            df = ingest_with_retry(
                symbol
            )

            successful.append(
                {
                    "symbol": symbol,
                    "rows": len(df),
                }
            )

            print(
                f"[SUCCESS] {symbol}: "
                f"{len(df)} rows"
            )

        except Exception as exc:

            failed.append(
                {
                    "symbol": symbol,
                    "error": str(exc),
                }
            )

            print(
                f"[ERROR] {symbol}: {exc}"
            )

        print()

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print("=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)

    print(
        f"Successful: {len(successful)}"
    )

    print(
        f"Skipped:    {len(skipped)}"
    )

    print(
        f"Failed:     {len(failed)}"
    )

    if successful:
        print()
        print("Successful symbols:")

        for item in successful:
            print(
                f"  {item['symbol']}: "
                f"{item['rows']} rows"
            )

    if skipped:
        print()
        print("Skipped symbols:")

        for symbol in skipped:
            print(
                f"  {symbol}"
            )

    if failed:
        print()
        print("Failed symbols:")

        for item in failed:
            print(
                f"  {item['symbol']}: "
                f"{item['error']}"
            )


if __name__ == "__main__":
    run_multi_ingest()
