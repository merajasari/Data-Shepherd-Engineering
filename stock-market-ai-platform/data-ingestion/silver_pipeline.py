"""
Reusable Bronze-to-Silver pipeline for stock market data.
"""

from pathlib import Path

import pandas as pd

from silver_transform import transform_to_silver
from silver_writer import write_silver


BRONZE_PATH = Path("data-ingestion/data/bronze/stocks")


def process_stock(stock_dir: Path) -> None:
    """Transform and write one stock's Bronze dataset."""

    symbol = stock_dir.name
    input_file = stock_dir / f"{symbol}_prices.csv"

    if not input_file.exists():
        print(f"[SKIP] {symbol}: Bronze file not found")
        return

    print(f"[START] {symbol}")

    try:
        df = pd.read_csv(input_file)

        print(f"  Bronze rows: {len(df)}")

        silver = transform_to_silver(df)

        print(f"  Silver rows: {len(silver)}")

        write_silver(silver, symbol)

        print(f"[SUCCESS] {symbol}")

    except Exception as exc:
        print(f"[ERROR] {symbol}: {exc}")


def run_pipeline() -> None:
    """Process all stock datasets in the Bronze layer."""

    if not BRONZE_PATH.exists():
        raise FileNotFoundError(
            f"Bronze path does not exist: {BRONZE_PATH}"
        )

    stock_dirs = sorted(
        path
        for path in BRONZE_PATH.iterdir()
        if path.is_dir()
    )

    if not stock_dirs:
        print("No stock datasets found.")
        return

    print(f"Found {len(stock_dirs)} stock dataset(s).")
    print()

    for stock_dir in stock_dirs:
        process_stock(stock_dir)
        print()


if __name__ == "__main__":
    run_pipeline()
