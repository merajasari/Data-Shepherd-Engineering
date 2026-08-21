"""Parallel Spark Gold-to-Feature pipeline for stock market data.

Outputs are isolated under data/features_spark/stocks so the production Pandas
feature files and existing model contracts remain unchanged.
"""

from pathlib import Path

from pyspark.sql import SparkSession

from spark_feature_transform import transform_to_features_spark


GOLD_PATH = Path("data/gold/stocks")
SPARK_FEATURE_PATH = Path("data/features_spark/stocks")


def process_stock(spark: SparkSession, stock_dir: Path) -> None:
    """Transform one symbol and write an isolated Spark comparison dataset."""

    symbol = stock_dir.name
    input_file = stock_dir / f"{symbol}_prices.parquet"

    if not input_file.exists():
        print(f"[SKIP] {symbol}: Gold file not found")
        return

    output_path = SPARK_FEATURE_PATH / symbol

    print(f"[START] {symbol}")

    gold = spark.read.parquet(str(input_file))
    features = transform_to_features_spark(gold)

    row_count = features.count()
    print(f"  Spark feature rows: {row_count}")

    (
        features
        .orderBy("timestamp")
        .coalesce(1)
        .write
        .mode("overwrite")
        .parquet(str(output_path))
    )

    print(f"[SUCCESS] {symbol}: {output_path}")


def main() -> None:
    """Process every available Gold stock dataset with local Spark."""

    if not GOLD_PATH.exists():
        raise FileNotFoundError(f"Gold path does not exist: {GOLD_PATH}")

    stock_dirs = sorted(path for path in GOLD_PATH.iterdir() if path.is_dir())
    if not stock_dirs:
        print("No Gold stock datasets found.")
        return

    spark = (
        SparkSession.builder
        .appName("data-shepherd-stock-features")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    try:
        print(f"Found {len(stock_dirs)} Gold stock dataset(s).")
        for stock_dir in stock_dirs:
            try:
                process_stock(spark, stock_dir)
            except Exception as exc:
                print(f"[ERROR] {stock_dir.name}: {exc}")
                raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
