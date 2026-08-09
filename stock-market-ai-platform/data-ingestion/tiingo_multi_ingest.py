"""
Fast multi-stock ingestion using Tiingo.

Downloads the configured stock universe and writes each symbol
to the canonical Bronze layer.
"""

from pathlib import Path

from bronze_writer import write_bronze
from symbols import get_symbols
from tiingo_client import TiingoClient
from validators import validate_prices


START_DATE = "2024-08-01"
END_DATE = "2026-01-01"

BRONZE_PATH = Path(
    "data/bronze/stocks"
)


def run_ingestion():
    """Download all configured symbols from Tiingo."""

    symbols = get_symbols()

    client = TiingoClient()

    successful = []
    failed = []

    print(
        f"Tiingo ingestion starting for "
        f"{len(symbols)} symbols"
    )

    print(
        f"Date range: "
        f"{START_DATE} -> {END_DATE}"
    )

    print()

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):

        print(
            f"[{index}/{len(symbols)}] "
            f"{symbol}"
        )

        try:

            df = client.get_daily_prices(
                symbol,
                START_DATE,
                END_DATE,
            )

            if df.empty:
                raise ValueError(
                    "No market data returned"
                )

            validate_prices(
                df
            )

            write_bronze(
                df,
                symbol,
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
                f"[ERROR] {symbol}: "
                f"{exc}"
            )

        print()

    print("=" * 60)
    print("TIINGO INGESTION SUMMARY")
    print("=" * 60)

    print(
        f"Successful: {len(successful)}"
    )

    print(
        f"Failed:     {len(failed)}"
    )

    print()

    for item in successful:
        print(
            f"{item['symbol']:6} "
            f"{item['rows']:4} rows"
        )

    if failed:

        print()
        print("FAILED SYMBOLS")

        for item in failed:
            print(
                f"{item['symbol']}: "
                f"{item['error']}"
            )


if __name__ == "__main__":
    run_ingestion()
