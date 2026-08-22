import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v10 import auto_tuning_registry as module


class V10TuningRegistryTests(unittest.TestCase):
    def test_registry_is_deterministic_unique_and_bounded(self):
        first = module.build_candidate_registry()
        second = module.build_candidate_registry()

        self.assertEqual(first, second)
        self.assertEqual(len(first), 27)
        self.assertEqual(
            len({row["candidate_id"] for row in first}),
            len(first),
        )
        self.assertTrue(
            all(
                row["status"] == "REGISTERED_UNEVALUATED"
                for row in first
            )
        )

    def test_safety_contract_is_fixed_for_every_candidate(self):
        rows = module.build_candidate_registry()

        for row in rows:
            config = row["config"]
            self.assertEqual(
                config["cost_bps_per_dollar_traded"],
                10,
            )
            self.assertEqual(
                config["development_data_end_exclusive_utc"],
                module.FUTURE_HOLDOUT_START_UTC.isoformat(),
            )
            self.assertEqual(config["entry"], "next_trading_session_open")
            self.assertEqual(config["weighting"], "equal_weight")

    def test_config_change_changes_candidate_id(self):
        row = module.build_candidate_registry()[0]
        changed = dict(row["config"])
        changed["top_n"] += 1

        self.assertNotEqual(
            row["candidate_id"],
            module._candidate_id(changed),
        )

    def test_writer_round_trips_and_refuses_registry_drift(self):
        rows = module.build_candidate_registry()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "candidate_registry.jsonl"
            manifest_path = root / "manifest.json"

            manifest = module.write_registry(rows, registry, manifest_path)
            written = [
                json.loads(line)
                for line in registry.read_text().splitlines()
            ]

            self.assertEqual(written, rows)
            self.assertEqual(manifest["candidate_count"], 27)
            self.assertFalse(manifest["v10_future_holdout_scored"])
            self.assertFalse(manifest["v8_modified"])
            self.assertFalse(manifest["candidate_promoted"])
            self.assertFalse(manifest["production_modified"])
            self.assertFalse(manifest["brokerage_orders"])

            registry.write_text("tampered\n")
            with self.assertRaisesRegex(
                RuntimeError,
                "differs from the declared search space",
            ):
                module.write_registry(rows, registry, manifest_path)


if __name__ == "__main__":
    unittest.main()
