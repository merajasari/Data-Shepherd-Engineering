"""
Silver layer writer for cleaned market data.
"""

from pathlib import Path

import pandas as pd


SILVER_PATH = Path("data/silver/stocks")


def write_silver(df: pd.DataFrame, symbol: str):
    """Write cleaned market data to the Silver layer."""

    output_path = SILVER_PATH / symbol

    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = output_path / f"{symbol}_prices.parquet"

    df.to_parquet(
        file_path,
        index=False,
    )

    print(
        f"Silver data written: {file_path}"
    )
