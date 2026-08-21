import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


DATA_INGESTION = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

import feature_pipeline


class FeatureBackendRoutingTests(unittest.TestCase):
    def test_default_backend_is_pandas(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(feature_pipeline.get_feature_backend(), "pandas")

    def test_backend_is_normalized(self):
        self.assertEqual(feature_pipeline.get_feature_backend(" Spark "), "spark")
        self.assertEqual(feature_pipeline.get_feature_backend("PANDAS"), "pandas")

    def test_invalid_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported FEATURE_BACKEND"):
            feature_pipeline.get_feature_backend("unknown")

    def test_main_routes_to_pandas_by_default(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(feature_pipeline, "run_pandas_pipeline") as pandas_run,
        ):
            feature_pipeline.main()

        pandas_run.assert_called_once_with()

    def test_main_routes_to_spark(self):
        spark_run = Mock()
        fake_module = SimpleNamespace(main=spark_run)

        with (
            patch.dict(os.environ, {"FEATURE_BACKEND": "spark"}, clear=True),
            patch.dict(sys.modules, {"spark_feature_pipeline": fake_module}),
            patch.object(feature_pipeline, "run_pandas_pipeline") as pandas_run,
        ):
            feature_pipeline.main()

        spark_run.assert_called_once_with()
        pandas_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
