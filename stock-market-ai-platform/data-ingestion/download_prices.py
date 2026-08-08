"""
Download historical market data.
"""

from massive_client import MassiveClient
from bronze_writer import write_bronze
from validators import validate_prices


def ingest_symbol(symbol: str, start_date: str, end_date: str):

    client = MassiveClient()

    df = client.get_daily_prices(
        symbol,
        start_date,
        end_date
    )

    print(df.head())

    validate_prices(df)

    write_bronze(df, symbol)

    return df


if __name__ == "__main__":

    ingest_symbol(
        "AAPL",
        "2021-01-01",
        "2026-01-01"
    )
