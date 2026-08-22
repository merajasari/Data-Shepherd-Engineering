import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v11 import discovery_registry as module


class V11DiscoveryRegistryTests(unittest.TestCase):
    def test_contract_is_deterministic_and_unique(self):
        first = module.build_registry()
        second = module.build_registry()

        self.assertEqual(first, second)
        self.assertEqual(len(first["signals"]), 6)
        ids = [signal["signal_id"] for signal in first["signals"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(first["contract_sha256"]), 64)

    def test_controls_include_frozen_v8_and_exhausted_v9_family(self):
        controls = set(module.CONTROLS)

        self.assertIn("distance_from_low_20d", controls)
        self.assertIn("volatility_20d", controls)
        self.assertIn("beta_60", controls)
        self.assertIn("downside_vol_ratio_20", controls)
        self.assertIn("volume_trend_5_20", controls)

    def test_discovery_rules_are_predeclared(self):
        rules = module.DISCOVERY_RULES

        self.assertEqual(
            rules["multiple_testing_adjustment"],
            "benjamini_hochberg_fdr_10pct",
        )
        self.assertEqual(rules["minimum_cross_sectional_assets"], 80)
        self.assertEqual(rules["hac_lag_sessions"], 5)
        self.assertFalse(rules["selection_performed_in_phase0"])
        self.assertFalse(rules["portfolio_simulation_performed_in_phase0"])

    def test_v11_holdout_is_later_and_untouched(self):
        registry = module.build_registry()

        self.assertEqual(
            registry["future_holdout_start_utc"],
            "2026-11-02T00:00:00+00:00",
        )
        self.assertEqual(
            registry["prior_research_status"]["v9_cycle2"],
            "NO_ELIGIBLE_CANDIDATE_CLOSED",
        )

    def test_writer_is_idempotent_and_refuses_drift(self):
        registry = module.build_registry()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            manifest_path = root / "manifest.json"

            manifest = module.write_registry(
                registry,
                registry_path,
                manifest_path,
            )
            written = json.loads(registry_path.read_text())

            self.assertEqual(written, registry)
            self.assertFalse(manifest["future_holdout_scored"])
            self.assertFalse(manifest["signal_selected"])
            self.assertFalse(manifest["production_modified"])

            registry_path.write_text("{}\n")
            with self.assertRaisesRegex(RuntimeError, "differs"):
                module.write_registry(
                    registry,
                    registry_path,
                    manifest_path,
                )


if __name__ == "__main__":
    unittest.main()
