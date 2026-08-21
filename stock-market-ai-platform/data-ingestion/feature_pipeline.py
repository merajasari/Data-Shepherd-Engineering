"""Configurable Gold-to-Feature pipeline for stock market data.

Pandas remains the default production backend. Set FEATURE_BACKEND=spark to
run the isolated Spark pipeline, which writes under data/features_spark/stocks.
"""

import os
from pathlib import Path

import pandas as pd

from feature_transform import transform_to_features
from feature_writer import write_features


GOLD_PATH = Path("data/gold/stocks")
DEFAULT_FEATURE_BACKEND = "pandas"
SUPPORTED_FEATURE_BACKENDS = {"pandas", "spark"}


def get_feature_backend(value=None) -> str:
    """Resolve and validate the requested feature-processing backend."""

    raw_value = (
        os.environ.get("FEATURE_BACKEND", DEFAULT_FEATURE_BACKEND)
        if value is None
        else value
    )
    backend = str(raw_value).strip().lower()

    if backend not in SUPPORTED_FEATURE_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_FEATURE_BACKENDS))
        raise ValueError(
            f"Unsupported FEATURE_BACKEND={raw_value!r}. "
            f"Expected one of: {supported}"
        )

    return backend


def process_stock(stock_dir: Path) -> None:
    """Transform one stock's Gold dataset with the Pandas backend."""

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


def run_pandas_pipeline() -> None:
    """Process all available Gold stock datasets with Pandas."""

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


def main() -> None:
    """Route the feature pipeline to the configured backend."""

    backend = get_feature_backend()
    print(f"Feature backend: {backend}")

    if backend == "spark":
        # Import lazily so the established Pandas path does not require Java
        # merely to import or start the pipeline.
        from spark_feature_pipeline import main as run_spark_pipeline

        run_spark_pipeline()
        return

    run_pandas_pipeline()


if __name__ == "__main__":
    main()
