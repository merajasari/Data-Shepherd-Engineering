"""
Reusable Silver-to-Gold pipeline for stock market data.
"""

from pathlib import Path
import pandas as pd

from gold_transform import transform_to_gold


SILVER_PATH = Path("data/silver/stocks")
GOLD_PATH = Path("data/gold/stocks")


def write_gold(df: pd.DataFrame, symbol: str) -> None:
    """Write transformed market data to the Gold layer."""

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


def process_stock(stock_dir: Path) -> None:
    """Transform one stock's Silver dataset into Gold."""

    symbol = stock_dir.name
    input_file = stock_dir / f"{symbol}_prices.parquet"

    if not input_file.exists():
        print(f"[SKIP] {symbol}: Silver file not found")
        return

    print(f"[START] {symbol}")

    try:
        df = pd.read_parquet(input_file)
        print(f"  Silver rows: {len(df)}")

        gold = transform_to_gold(df)
        print(f"  Gold rows: {len(gold)}")

        write_gold(gold, symbol)

        print(f"[SUCCESS] {symbol}")

    except Exception as exc:
        print(f"[ERROR] {symbol}: {exc}")


def run_pipeline() -> None:
    """Process all available Silver stock datasets."""

    if not SILVER_PATH.exists():
        print(f"Silver path not found: {SILVER_PATH}")
        return

    stock_dirs = sorted(
        path
        for path in SILVER_PATH.iterdir()
        if path.is_dir()
    )

    print(f"Found {len(stock_dirs)} stock dataset(s).")

    for stock_dir in stock_dirs:
        process_stock(stock_dir)


if __name__ == "__main__":
    run_pipeline()
