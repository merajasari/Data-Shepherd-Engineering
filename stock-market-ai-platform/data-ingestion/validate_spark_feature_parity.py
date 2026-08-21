"""Validate Spark stock features against production Pandas feature datasets.

The validator reads existing Gold and Pandas feature Parquet files, computes the
Spark version in memory, and writes reports under logs/. It never overwrites
either feature layer.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession

from spark_feature_transform import transform_to_features_spark
from symbols import SYMBOLS


GOLD_PATH = Path("data/gold/stocks")
PANDAS_FEATURE_PATH = Path("data/features/stocks")
DEFAULT_REPORT_DIR = Path("logs/spark_feature_parity")

PARITY_COLUMNS = [
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_14",
    "rsi_centered",
    "momentum_10d",
    "forward_return_5d",
    "target_up_5d",
    "target_trade_5d",
]


def _numeric(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").to_numpy(
        dtype=float,
        na_value=np.nan,
    )


def compare_feature_frames(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    rtol: float = 1e-8,
    atol: float = 1e-10,
) -> dict:
    """Return a deterministic parity summary for two feature frames."""

    summary = {
        "status": "FAIL",
        "expected_rows": int(len(expected)),
        "actual_rows": int(len(actual)),
        "timestamp_mismatches": 0,
        "missing_columns": [],
        "value_mismatches": 0,
        "null_pattern_mismatches": 0,
        "max_absolute_error": 0.0,
    }

    missing = [
        column
        for column in ["timestamp", *PARITY_COLUMNS]
        if column not in expected.columns or column not in actual.columns
    ]
    summary["missing_columns"] = missing
    if missing:
        return summary

    expected = expected.sort_values("timestamp").reset_index(drop=True)
    actual = actual.sort_values("timestamp").reset_index(drop=True)

    common_rows = min(len(expected), len(actual))
    if common_rows:
        expected_keys = expected["timestamp"].iloc[:common_rows].astype(str)
        actual_keys = actual["timestamp"].iloc[:common_rows].astype(str)
        summary["timestamp_mismatches"] = int(
            (expected_keys.to_numpy() != actual_keys.to_numpy()).sum()
        )

    for column in PARITY_COLUMNS:
        expected_values = _numeric(expected[column].iloc[:common_rows])
        actual_values = _numeric(actual[column].iloc[:common_rows])

        expected_null = np.isnan(expected_values)
        actual_null = np.isnan(actual_values)
        null_mismatches = int(np.logical_xor(expected_null, actual_null).sum())
        summary["null_pattern_mismatches"] += null_mismatches

        finite = np.isfinite(expected_values) & np.isfinite(actual_values)
        if finite.any():
            differences = np.abs(expected_values[finite] - actual_values[finite])
            summary["max_absolute_error"] = max(
                summary["max_absolute_error"],
                float(differences.max()),
            )
            close = np.isclose(
                expected_values[finite],
                actual_values[finite],
                rtol=rtol,
                atol=atol,
            )
            summary["value_mismatches"] += int((~close).sum())

    row_count_matches = len(expected) == len(actual)
    passed = (
        row_count_matches
        and summary["timestamp_mismatches"] == 0
        and not summary["missing_columns"]
        and summary["value_mismatches"] == 0
        and summary["null_pattern_mismatches"] == 0
    )
    summary["status"] = "PASS" if passed else "FAIL"
    return summary


def validate_symbol(
    spark: SparkSession,
    symbol: str,
    *,
    rtol: float,
    atol: float,
) -> dict:
    """Compute Spark features and compare them with one production dataset."""

    gold_file = GOLD_PATH / symbol / f"{symbol}_prices.parquet"
    pandas_file = (
        PANDAS_FEATURE_PATH
        / symbol
        / f"{symbol}_features.parquet"
    )

    record = {"symbol": symbol}

    missing_inputs = [
        str(path)
        for path in (gold_file, pandas_file)
        if not path.exists()
    ]
    if missing_inputs:
        record.update(
            {
                "status": "FAIL",
                "error": "Missing required input",
                "missing_inputs": missing_inputs,
            }
        )
        return record

    expected = pd.read_parquet(pandas_file)
    spark_features = transform_to_features_spark(
        spark.read.parquet(str(gold_file))
    )
    actual = spark_features.orderBy("timestamp").toPandas()

    record.update(
        compare_feature_frames(
            expected,
            actual,
            rtol=rtol,
            atol=atol,
        )
    )
    return record


def write_reports(report_dir: Path, payload: dict) -> None:
    """Write machine-readable JSON and compact per-symbol CSV reports."""

    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "spark_feature_parity.json"
    csv_path = report_dir / "spark_feature_parity.csv"

    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    fieldnames = [
        "symbol",
        "status",
        "expected_rows",
        "actual_rows",
        "timestamp_mismatches",
        "value_mismatches",
        "null_pattern_mismatches",
        "max_absolute_error",
        "error",
        "missing_inputs",
        "missing_columns",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in payload["symbols"]:
            row = {
                key: record.get(key, "")
                for key in fieldnames
            }
            for key in ("missing_inputs", "missing_columns"):
                if isinstance(row[key], list):
                    row[key] = ";".join(row[key])
            writer.writerow(row)

    print(f"JSON report: {json_path}")
    print(f"CSV report:  {csv_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate Spark features against all Pandas feature files."
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=SYMBOLS,
        help="Optional symbol subset; defaults to the configured 26-stock universe.",
    )
    parser.add_argument("--rtol", type=float, default=1e-8)
    parser.add_argument("--atol", type=float, default=1e-10)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = [symbol.upper() for symbol in args.symbols]

    unknown = sorted(set(symbols) - set(SYMBOLS))
    if unknown:
        print(f"Unknown configured symbol(s): {unknown}", file=sys.stderr)
        return 2

    spark = (
        SparkSession.builder
        .appName("data-shepherd-production-feature-parity")
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    records = []
    try:
        for symbol in symbols:
            try:
                record = validate_symbol(
                    spark,
                    symbol,
                    rtol=args.rtol,
                    atol=args.atol,
                )
            except Exception as exc:
                record = {
                    "symbol": symbol,
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            records.append(record)
            print(f"[{record['status']}] {symbol}")
    finally:
        spark.stop()

    passed = sum(record["status"] == "PASS" for record in records)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "configured_symbol_count": len(SYMBOLS),
        "tested_symbol_count": len(records),
        "passed_symbol_count": passed,
        "failed_symbol_count": len(records) - passed,
        "rtol": args.rtol,
        "atol": args.atol,
        "symbols": records,
    }
    write_reports(args.report_dir, payload)

    print(f"Parity result: {passed}/{len(records)} symbol(s) passed")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
