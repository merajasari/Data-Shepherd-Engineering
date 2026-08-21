import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ML_ROOT = PROJECT_ROOT / "ml"
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from feature_source import (
    feature_dataset_exists,
    feature_dataset_mtime_ns,
    get_feature_backend,
    get_feature_dataset_path,
    require_feature_dataset,
)


CONSUMER_FILES = [
    "build_stock_model_comparison.py",
    "build_v4_dataset.py",
    "check_v5_dashboard_integrity.py",
    "predict.py",
    "run_v5_data_refresh.py",
    "run_v5_inference.py",
    "train_model.py",
    "train_model_v3.py",
]


class FeatureSourceTests(unittest.TestCase):
    def test_default_backend_remains_pandas(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_feature_backend(), "pandas")

    def test_pandas_path_preserves_single_file_contract(self):
        path = get_feature_dataset_path(
            "aapl",
            project_root=Path("/project"),
            backend="pandas",
        )
        self.assertEqual(
            path,
            Path("/project/data/features/stocks/AAPL/AAPL_features.parquet"),
        )

    def test_spark_path_uses_parquet_dataset_directory(self):
        path = get_feature_dataset_path(
            "aapl",
            project_root=Path("/project"),
            backend="spark",
        )
        self.assertEqual(
            path,
            Path("/project/data/features_spark/stocks/AAPL"),
        )

    def test_invalid_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported FEATURE_BACKEND"):
            get_feature_backend("invalid")

    def test_file_and_directory_datasets_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pandas_path = (
                root
                / "data/features/stocks/AAPL/AAPL_features.parquet"
            )
            pandas_path.parent.mkdir(parents=True)
            pandas_path.write_bytes(b"parquet")
            self.assertTrue(feature_dataset_exists(pandas_path))

            spark_path = root / "data/features_spark/stocks/AAPL"
            spark_path.mkdir(parents=True)
            self.assertFalse(feature_dataset_exists(spark_path))
            (spark_path / "part-00000.parquet").write_bytes(b"parquet")
            self.assertTrue(feature_dataset_exists(spark_path))

    def test_dataset_mtime_uses_newest_spark_part(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "AAPL"
            dataset.mkdir()
            older = dataset / "part-00000.parquet"
            newer = dataset / "part-00001.parquet"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            os.utime(older, ns=(100, 100))
            os.utime(newer, ns=(200, 200))
            self.assertEqual(feature_dataset_mtime_ns(dataset), 200)

    def test_require_reports_selected_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                FileNotFoundError,
                "spark feature dataset not found for AAPL",
            ):
                require_feature_dataset(
                    "AAPL",
                    project_root=Path(directory),
                    backend="spark",
                )

    def test_migrated_consumers_do_not_hardcode_pandas_root(self):
        for filename in CONSUMER_FILES:
            content = (ML_ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn(
                "data/features/stocks",
                content,
                msg=f"{filename} bypasses feature_source",
            )


if __name__ == "__main__":
    unittest.main()
