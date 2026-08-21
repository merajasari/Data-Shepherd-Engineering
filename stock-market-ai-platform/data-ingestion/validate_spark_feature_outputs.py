"""Validate materialized Spark stock feature datasets before downstream use.

This is a scheduler safety gate. It checks every Gold stock dataset against the
already-written Spark Parquet dataset and exits non-zero on any incomplete or
invalid output. It does not recompute features or modify data layers.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


GOLD_PATH = Path("data/gold/stocks")
SPARK_FEATURE_PATH = Path("data/features_spark/stocks")
DEFAULT_REPORT_PATH = Path("logs/spark_feature_validation/spark_feature_validation.json")
REQUIRED_FEATURE_COLUMNS = [
    "symbol",
    "timestamp",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "return_5d",
    "price_vs_sma_20",
    "rsi_14",
    "forward_return_5d",
    "target_up_5d",
    "target_trade_5d",
]
TARGET_COLUMNS = ["forward_return_5d", "target_up_5d", "target_trade_5d"]


def validate_materialized_symbol(symbol, *, gold_path=GOLD_PATH, spark_path=SPARK_FEATURE_PATH):
    """Return a deterministic validation record for one symbol."""

    gold_file = Path(gold_path) / symbol / f"{symbol}_prices.parquet"
    feature_dir = Path(spark_path) / symbol
    record = {"symbol": symbol, "status": "FAIL"}

    if not gold_file.is_file():
        record["error"] = f"Gold input not found: {gold_file}"
        return record

    part_files = sorted(feature_dir.glob("*.parquet")) if feature_dir.is_dir() else []
    if not part_files:
        record["error"] = f"Spark feature dataset not found: {feature_dir}"
        return record

    gold = pd.read_parquet(gold_file, columns=["timestamp"])
    features = pd.read_parquet(feature_dir)
    record.update(
        {
            "gold_rows": int(len(gold)),
            "feature_rows": int(len(features)),
            "part_file_count": len(part_files),
            "missing_columns": sorted(set(REQUIRED_FEATURE_COLUMNS) - set(features.columns)),
            "duplicate_timestamps": (
                int(features["timestamp"].duplicated().sum())
                if "timestamp" in features.columns
                else None
            ),
            "timestamp_mismatches": None,
            "target_tail_null_mismatches": None,
        }
    )

    if record["missing_columns"]:
        return record

    expected_timestamps = gold["timestamp"].astype(str).sort_values().reset_index(drop=True)
    actual_timestamps = features["timestamp"].astype(str).sort_values().reset_index(drop=True)
    if len(expected_timestamps) == len(actual_timestamps):
        record["timestamp_mismatches"] = int(
            (expected_timestamps.to_numpy() != actual_timestamps.to_numpy()).sum()
        )

    ordered = features.sort_values("timestamp").reset_index(drop=True)
    tail_size = min(5, len(ordered))
    expected_tail_nulls = tail_size * len(TARGET_COLUMNS)
    actual_tail_nulls = int(ordered[TARGET_COLUMNS].tail(tail_size).isna().sum().sum())
    record["target_tail_null_mismatches"] = expected_tail_nulls - actual_tail_nulls

    passed = (
        len(gold) == len(features)
        and record["duplicate_timestamps"] == 0
        and record["timestamp_mismatches"] == 0
        and record["target_tail_null_mismatches"] == 0
    )
    record["status"] = "PASS" if passed else "FAIL"
    return record


def validate_all(*, gold_path=GOLD_PATH, spark_path=SPARK_FEATURE_PATH):
    gold_path = Path(gold_path)
    if not gold_path.is_dir():
        return [{"symbol": "*", "status": "FAIL", "error": f"Gold path not found: {gold_path}"}]

    symbols = sorted(path.name for path in gold_path.iterdir() if path.is_dir())
    if not symbols:
        return [{"symbol": "*", "status": "FAIL", "error": f"No Gold symbols found: {gold_path}"}]

    records = []
    for symbol in symbols:
        try:
            record = validate_materialized_symbol(
                symbol,
                gold_path=gold_path,
                spark_path=spark_path,
            )
        except Exception as exc:
            record = {
                "symbol": symbol,
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        records.append(record)
        print(f"[{record['status']}] {symbol}", flush=True)
    return records


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-path", type=Path, default=GOLD_PATH)
    parser.add_argument("--spark-path", type=Path, default=SPARK_FEATURE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    records = validate_all(gold_path=args.gold_path, spark_path=args.spark_path)
    passed = sum(record["status"] == "PASS" for record in records)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tested_symbol_count": len(records),
        "passed_symbol_count": passed,
        "failed_symbol_count": len(records) - passed,
        "symbols": records,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Validation report: {args.report_path}")
    print(f"Materialized Spark result: {passed}/{len(records)} symbol(s) passed")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
