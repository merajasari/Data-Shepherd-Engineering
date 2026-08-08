"""
Bronze layer writer for raw market data.
"""

from pathlib import Path
import pandas as pd


BRONZE_PATH = Path("data/bronze/stocks")


def write_bronze(df: pd.DataFrame, symbol: str):

    output_path = BRONZE_PATH / symbol
    output_path.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path = output_path / f"{symbol}_prices.csv"

    df.to_csv(
        file_path,
        index=False
    )

    print(
        f"Bronze data written: {file_path}"
    )
