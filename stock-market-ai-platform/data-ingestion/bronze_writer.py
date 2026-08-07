"""
Writes raw market data to Bronze layer.
"""

import os


def write_bronze(df, symbol):

    os.makedirs(
        "../bronze",
        exist_ok=True
    )

    path = f"../bronze/{symbol}.parquet"

    df.to_parquet(
        path,
        index=False
    )

    print(
        f"Bronze data written: {path}"
    )"""Bronze layer writer for raw market data."""

from pathlib import Path
import pandas as pd


BRONZE_PATH = Path("data/bronze/stocks")


def write_bronze(df: pd.DataFrame, symbol: str):
    """Persist raw market data as parquet."""
    output_path = BRONZE_PATH / symbol
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f"{symbol}_prices.parquet"
    df.to_parquet(file_path, index=False)

    return file_path
