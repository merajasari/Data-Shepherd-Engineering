import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "validate_spark_feature_outputs",
    PROJECT_ROOT / "data-ingestion/validate_spark_feature_outputs.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def feature_frame():
    rows = 8
    frame = pd.DataFrame(
        {
            "symbol": ["AAPL"] * rows,
            "timestamp": list(range(1, rows + 1)),
            "timestamp_utc": pd.date_range("2026-01-01", periods=rows, tz="UTC"),
            "open": [1.0] * rows,
            "high": [2.0] * rows,
            "low": [0.5] * rows,
            "close": [1.5] * rows,
            "volume": [100.0] * rows,
            "return_5d": [0.0] * rows,
            "price_vs_sma_20": [0.0] * rows,
            "rsi_14": [50.0] * rows,
            "forward_return_5d": [0.1, 0.1, 0.1] + [None] * 5,
            "target_up_5d": [1.0, 1.0, 1.0] + [None] * 5,
            "target_trade_5d": [1.0, 1.0, 1.0] + [None] * 5,
        }
    )
    return frame


class SparkFeatureOutputValidationTests(unittest.TestCase):
    def write_datasets(self, root):
        gold_root = root / "gold"
        spark_root = root / "spark"
        gold_dir = gold_root / "AAPL"
        feature_dir = spark_root / "AAPL"
        gold_dir.mkdir(parents=True)
        feature_dir.mkdir(parents=True)
        pd.DataFrame({"timestamp": list(range(1, 9))}).to_parquet(
            gold_dir / "AAPL_prices.parquet",
            index=False,
        )
        feature_frame().to_parquet(feature_dir / "part-00000.parquet", index=False)
        return gold_root, spark_root, feature_dir

    def test_complete_materialized_dataset_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            gold_root, spark_root, _ = self.write_datasets(Path(directory))
            record = module.validate_materialized_symbol(
                "AAPL",
                gold_path=gold_root,
                spark_path=spark_root,
            )
            self.assertEqual(record["status"], "PASS")
            self.assertEqual(record["timestamp_mismatches"], 0)

    def test_missing_target_tail_nulls_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            gold_root, spark_root, feature_dir = self.write_datasets(Path(directory))
            frame = feature_frame()
            frame.loc[7, "target_up_5d"] = 1.0
            frame.to_parquet(feature_dir / "part-00000.parquet", index=False)
            record = module.validate_materialized_symbol(
                "AAPL",
                gold_path=gold_root,
                spark_path=spark_root,
            )
            self.assertEqual(record["status"], "FAIL")
            self.assertEqual(record["target_tail_null_mismatches"], 1)

    def test_missing_spark_dataset_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gold_root = root / "gold"
            gold_dir = gold_root / "AAPL"
            gold_dir.mkdir(parents=True)
            pd.DataFrame({"timestamp": [1]}).to_parquet(
                gold_dir / "AAPL_prices.parquet",
                index=False,
            )
            record = module.validate_materialized_symbol(
                "AAPL",
                gold_path=gold_root,
                spark_path=root / "spark",
            )
            self.assertEqual(record["status"], "FAIL")
            self.assertIn("not found", record["error"])


if __name__ == "__main__":
    unittest.main()
