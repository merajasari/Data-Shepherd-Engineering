import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v9 import tuning_cycle2_registry as module


class V9TuningCycle2RegistryTests(unittest.TestCase):
    def test_registry_is_deterministic_unique_and_complete(self):
        first = module.build_candidate_registry()
        second = module.build_candidate_registry()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 54)
        self.assertEqual(
            len({row["candidate_id"] for row in first}),
            54,
        )
        self.assertTrue(
            all(
                row["status"] == "REGISTERED_UNEVALUATED"
                for row in first
            )
        )

    def test_risk_overlay_contracts_are_explicit(self):
        rows = module.build_candidate_registry()
        exposure_by_overlay = {
            row["config"]["risk_overlay"]:
            row["config"]["below_sma200_target_exposure"]
            for row in rows
        }

        self.assertEqual(exposure_by_overlay["NONE"], 1.0)
        self.assertEqual(
            exposure_by_overlay["SPY_SMA200_HALF_EXPOSURE"],
            0.5,
        )
        self.assertEqual(exposure_by_overlay["SPY_SMA200_CASH"], 0.0)
        self.assertTrue(
            all(
                not row["config"]["leverage_allowed"]
                and not row["config"]["shorting_allowed"]
                for row in rows
            )
        )

    def test_failed_cycle_one_gates_are_not_relaxed(self):
        gates = module.MANDATORY_CONFIRMATION_GATES

        self.assertEqual(gates["minimum_worst_fold_sharpe"], 0.0)
        self.assertEqual(gates["minimum_primary_max_drawdown"], -0.25)
        self.assertEqual(
            gates["minimum_spy_down_regime_max_drawdown"],
            -0.35,
        )
        self.assertEqual(
            gates["minimum_30bps_mean_relative_return"],
            0.0,
        )

    def test_cost_is_fixed_and_holdout_is_excluded(self):
        rows = module.build_candidate_registry()
        for row in rows:
            config = row["config"]
            self.assertEqual(config["cost_bps_per_dollar_traded"], 10)
            self.assertEqual(
                config["development_data_end_exclusive_utc"],
                module.FUTURE_HOLDOUT_START_UTC.isoformat(),
            )

    def test_writer_refuses_registry_drift(self):
        rows = module.build_candidate_registry()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "registry.jsonl"
            manifest = root / "manifest.json"
            payload = module.write_registry(rows, registry, manifest)

            self.assertEqual(payload["candidate_count"], 54)
            self.assertEqual(
                payload["cycle1_status"],
                "NOT_CONFIRMED_CLOSED",
            )
            self.assertFalse(payload["v9_future_holdout_scored"])
            self.assertFalse(payload["production_modified"])

            registry.write_text("tampered\n")
            with self.assertRaisesRegex(RuntimeError, "differs"):
                module.write_registry(rows, registry, manifest)


if __name__ == "__main__":
    unittest.main()
