"""Download historical market data using the Massive ingestion framework."""

from massive_client import MassiveClient


def ingest_symbol(symbol: str, start_date: str, end_date: str):
    client = MassiveClient()
    data = client.get_daily_prices(symbol, start_date, end_date)

    # Future steps:
    # 1. Convert response to pandas DataFrame
    # 2. Validate schema
    # 3. Write Bronze parquet files
    # 4. Trigger Silver transformations
    return data


if __name__ == "__main__":
"""
Download historical market data.
"""

from massive_client import MassiveClient
from bronze_writer import write_bronze


def ingest_symbol(symbol, start_date, end_date):

    client = MassiveClient()

    df = client.get_daily_prices(
        symbol,
        start_date,
        end_date
    )

    print(df.head())

    write_bronze(df, symbol)

    return df


if __name__ == "__main__":

    ingest_symbol(
        "AAPL",
        "2021-01-01",
        "2026-01-01"
    )    print(ingest_symbol("AAPL", "2021-01-01", "2026-01-01"))
