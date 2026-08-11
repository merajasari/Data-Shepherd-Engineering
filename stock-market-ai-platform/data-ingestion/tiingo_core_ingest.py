"""
Refresh the passive portfolio core holding.

SPY is intentionally kept outside the V4 ML universe.
"""

from datetime import date

from bronze_writer import write_bronze
from symbols import get_core_symbol
from tiingo_client import TiingoClient


START_DATE = "2016-08-01"


def main():

    symbol = get_core_symbol()

    end_date = date.today().isoformat()

    print(
        f"Refreshing core symbol "
        f"{symbol}: "
        f"{START_DATE} -> {end_date}"
    )

    client = TiingoClient()

    df = client.get_daily_prices(
        symbol,
        START_DATE,
        end_date,
    )

    if df.empty:
        raise RuntimeError(
            f"Tiingo returned no rows for {symbol}"
        )

    write_bronze(
        df,
        symbol,
    )

    print(
        f"[SUCCESS] {symbol}: "
        f"{len(df):,} rows"
    )


if __name__ == "__main__":
    main()
