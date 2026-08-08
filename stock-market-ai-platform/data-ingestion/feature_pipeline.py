"""
Reusable Gold-to-Feature pipeline for stock market data.
"""

from pathlib import Path

import pandas as pd

from feature_transform import transform_to_features
from feature_writer import write_features


GOLD_PATH = Path("data/gold/stocks")


def process_stock(stock_dir: Path) -> None:
    """Transform one stock's Gold dataset into ML features."""

    symbol = stock_dir.name

    input_file = stock_dir / f"{symbol}_prices.parquet"

    if not input_file.exists():
        print(f"[SKIP] {symbol}: Gold file not found")
        return

    print(f"[START] {symbol}")

    try:
        df = pd.read_parquet(input_file)

        print(f"  Gold rows: {len(df)}")

        features = transform_to_features(df)

        print(f"  Feature rows: {len(features)}")

        write_features(features, symbol)

        print(f"[SUCCESS] {symbol}")

    except Exception as exc:
        print(f"[ERROR] {symbol}: {exc}")


def main() -> None:
    """Process all available Gold stock datasets."""

    if not GOLD_PATH.exists():
        print(f"Gold path does not exist: {GOLD_PATH}")
        return

    stock_dirs = sorted(
        path
        for path in GOLD_PATH.iterdir()
        if path.is_dir()
    )

    print(f"Found {len(stock_dirs)} stock dataset(s).")

    for stock_dir in stock_dirs:
        process_stock(stock_dir)


if __name__ == "__main__":
    main()
