"""Parallel Spark Gold-to-Feature pipeline for stock market data.

Outputs are isolated under data/features_spark/stocks so the production Pandas
feature files and existing model contracts remain unchanged. A complete universe
is built in a staging directory and published only after every symbol succeeds.
"""

import os
from pathlib import Path
import shutil
from uuid import uuid4

from pyspark.sql import SparkSession

from spark_feature_transform import transform_to_features_spark


GOLD_PATH = Path("data/gold/stocks")
SPARK_FEATURE_PATH = Path("data/features_spark/stocks")


def process_stock(
    spark: SparkSession,
    stock_dir: Path,
    output_root: Path = SPARK_FEATURE_PATH,
) -> None:
    """Transform one symbol into a caller-selected Spark output root."""

    symbol = stock_dir.name
    input_file = stock_dir / f"{symbol}_prices.parquet"

    if not input_file.exists():
        print(f"[SKIP] {symbol}: Gold file not found")
        return

    output_path = output_root / symbol

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
        .mode("errorifexists")
        .parquet(str(output_path))
    )

    print(f"[SUCCESS] {symbol}: {output_path}")


def _restore_interrupted_publish(output_root: Path) -> bool:
    """Restore the newest backup if a prior process stopped during publication."""

    if output_root.exists():
        return False
    backups = sorted(
        output_root.parent.glob(f".{output_root.name}.backup-*"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not backups:
        return False
    os.replace(backups[0], output_root)
    print(f"[RECOVERED] Restored prior Spark feature root: {output_root}")
    return True


def _publish_staged_root(staging_root: Path, output_root: Path) -> None:
    """Publish a completed universe while preserving the prior root on failure."""

    output_root.parent.mkdir(parents=True, exist_ok=True)
    backup_root = output_root.parent / (
        f".{output_root.name}.backup-{uuid4().hex}"
    )
    had_previous = output_root.exists()

    if had_previous:
        os.replace(output_root, backup_root)

    try:
        os.replace(staging_root, output_root)
    except Exception:
        if had_previous and backup_root.exists() and not output_root.exists():
            os.replace(backup_root, output_root)
        raise
    else:
        if backup_root.exists():
            shutil.rmtree(backup_root)

    print(f"[PUBLISHED] Complete Spark feature universe: {output_root}")


def main() -> None:
    """Build every Spark feature dataset, then publish the universe together."""

    if not GOLD_PATH.exists():
        raise FileNotFoundError(f"Gold path does not exist: {GOLD_PATH}")

    stock_dirs = sorted(path for path in GOLD_PATH.iterdir() if path.is_dir())
    if not stock_dirs:
        print("No Gold stock datasets found.")
        return

    SPARK_FEATURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _restore_interrupted_publish(SPARK_FEATURE_PATH)
    staging_root = SPARK_FEATURE_PATH.parent / (
        f".{SPARK_FEATURE_PATH.name}.staging-{uuid4().hex}"
    )
    staging_root.mkdir(parents=True, exist_ok=False)

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
        print(f"Building isolated Spark staging root: {staging_root}")
        for stock_dir in stock_dirs:
            try:
                process_stock(spark, stock_dir, output_root=staging_root)
            except Exception as exc:
                print(f"[ERROR] {stock_dir.name}: {exc}")
                raise
        _publish_staged_root(staging_root, SPARK_FEATURE_PATH)
    finally:
        spark.stop()
        if staging_root.exists():
            shutil.rmtree(staging_root)


if __name__ == "__main__":
    main()
