import importlib.util
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

MODULE_PATH = DATA_INGESTION / "spark_feature_pipeline.py"

try:
    spec = importlib.util.spec_from_file_location(
        "spark_feature_pipeline",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
except ImportError:
    module = None


@unittest.skipIf(module is None, "pyspark is not installed")
class SparkFeaturePublicationTests(unittest.TestCase):
    def test_spark_master_defaults_to_local_all(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module.get_spark_master(), "local[*]")

    def test_spark_master_can_be_constrained_by_environment(self):
        with patch.dict(
            os.environ,
            {"SPARK_MASTER": "local[1]"},
            clear=True,
        ):
            self.assertEqual(module.get_spark_master(), "local[1]")

    def test_blank_spark_master_preserves_default(self):
        with patch.dict(
            os.environ,
            {"SPARK_MASTER": "   "},
            clear=True,
        ):
            self.assertEqual(module.get_spark_master(), "local[*]")

    def test_complete_staging_root_replaces_previous_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "stocks"
            staging = root / ".stocks.staging-test"
            output.mkdir()
            staging.mkdir()
            (output / "old.txt").write_text("old", encoding="utf-8")
            (staging / "new.txt").write_text("new", encoding="utf-8")

            module._publish_staged_root(staging, output)

            self.assertFalse(staging.exists())
            self.assertFalse((output / "old.txt").exists())
            self.assertEqual(
                (output / "new.txt").read_text(encoding="utf-8"),
                "new",
            )
            self.assertEqual(list(root.glob(".stocks.backup-*")), [])

    def test_failed_publication_restores_previous_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "stocks"
            staging = root / ".stocks.staging-test"
            output.mkdir()
            staging.mkdir()
            (output / "old.txt").write_text("old", encoding="utf-8")
            (staging / "new.txt").write_text("new", encoding="utf-8")

            real_replace = os.replace
            calls = 0

            def fail_second_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated publication failure")
                return real_replace(source, destination)

            with (
                patch.object(module.os, "replace", side_effect=fail_second_replace),
                self.assertRaisesRegex(OSError, "simulated"),
            ):
                module._publish_staged_root(staging, output)

            self.assertTrue(output.exists())
            self.assertEqual(
                (output / "old.txt").read_text(encoding="utf-8"),
                "old",
            )
            self.assertTrue(staging.exists())
            self.assertEqual(list(root.glob(".stocks.backup-*")), [])


if __name__ == "__main__":
    unittest.main()
