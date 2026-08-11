"""
Multi-symbol Tiingo market-data ingestion.

Downloads daily historical data for all configured symbols
and writes each dataset to the Bronze layer.

The end date is calculated dynamically so the pipeline always
requests data through the current date.
"""

from datetime import date

from bronze_writer import write_bronze
from symbols import get_symbols
from tiingo_client import TiingoClient


START_DATE = "2016-08-01"

# Always request through today's date.
END_DATE = date.today().isoformat()


def main():

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
                    "Tiingo returned no rows"
                )

            write_bronze(
                df,
                symbol,
            )

            successful.append(
                (
                    symbol,
                    len(df),
                )
            )

            print(
                f"[SUCCESS] "
                f"{symbol}: "
                f"{len(df)} rows"
            )

        except Exception as exc:

            failed.append(
                (
                    symbol,
                    str(exc),
                )
            )

            print(
                f"[ERROR] "
                f"{symbol}: "
                f"{exc}"
            )

        print()

    print(
        "=" * 60
    )

    print(
        "TIINGO INGESTION SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"Successful: "
        f"{len(successful)}"
    )

    print(
        f"Failed:     "
        f"{len(failed)}"
    )

    print()

    for symbol, rows in successful:

        print(
            f"{symbol:6} "
            f"{rows:,} rows"
        )

    if failed:

        print()
        print(
            "FAILED SYMBOLS"
        )

        for symbol, error in failed:

            print(
                f"{symbol}: "
                f"{error}"
            )


if __name__ == "__main__":
    main()
