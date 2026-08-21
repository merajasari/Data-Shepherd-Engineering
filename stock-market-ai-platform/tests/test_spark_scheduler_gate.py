import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ML_ROOT = PROJECT_ROOT / "ml"
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

spec = importlib.util.spec_from_file_location(
    "run_v5_data_refresh_scheduler_gate",
    ML_ROOT / "run_v5_data_refresh.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SparkSchedulerGateTests(unittest.TestCase):
    def test_pandas_default_does_not_run_spark_gate(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            module, "run_command"
        ) as run_command:
            module.rebuild_data_layers()

        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(len(commands), 3)
        self.assertTrue(commands[-1][-1].endswith("feature_pipeline.py"))

    def test_spark_runs_validation_before_returning(self):
        with patch.dict(os.environ, {"FEATURE_BACKEND": "spark"}, clear=True), patch.object(
            module, "run_command"
        ) as run_command:
            module.rebuild_data_layers()

        commands = [call.args[0] for call in run_command.call_args_list]
        self.assertEqual(len(commands), 4)
        self.assertTrue(commands[-2][-1].endswith("feature_pipeline.py"))
        self.assertTrue(
            commands[-1][-1].endswith("validate_spark_feature_outputs.py")
        )


if __name__ == "__main__":
    unittest.main()
