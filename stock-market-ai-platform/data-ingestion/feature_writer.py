"""
Feature layer writer for ML-ready market data.
"""

from pathlib import Path

import pandas as pd


FEATURE_PATH = Path("data/features/stocks")


def write_features(df: pd.DataFrame, symbol: str) -> None:
    """Write ML-ready features to the Feature layer."""

    output_path = FEATURE_PATH / symbol

    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = output_path / f"{symbol}_features.parquet"

    df.to_parquet(
        file_path,
        index=False,
    )

    print(f"Features written: {file_path}")
