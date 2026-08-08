"""
Gold layer writer for analytics-ready market data.
"""

from pathlib import Path

import pandas as pd


GOLD_PATH = Path("data/gold/stocks")


def write_gold(df: pd.DataFrame, symbol: str) -> None:
    """Write analytics-ready market data to the Gold layer."""

    output_path = GOLD_PATH / symbol

    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = output_path / f"{symbol}_prices.parquet"

    df.to_parquet(
        file_path,
        index=False,
    )

    print(f"Gold data written: {file_path}")
