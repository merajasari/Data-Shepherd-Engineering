from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from ml.v11 import phase2_registry as registry


class V11Phase2RegistryTests(unittest.TestCase):
    def test_contract_is_deterministic_unique_and_new(self):
        first = registry.build_registry()
        second = registry.build_registry()
        self.assertEqual(first, second)
        signal_ids = [row["signal_id"] for row in first["signals"]]
        self.assertEqual(len(signal_ids), 6)
        self.assertEqual(len(signal_ids), len(set(signal_ids)))
        self.assertFalse(set(signal_ids) & set(registry.PRIOR_SIGNAL_IDS))
        self.assertEqual(len(first["contract_sha256"]), 64)

    def test_phase1_negative_result_is_closed_not_retuned(self):
        payload = registry.build_registry()
        prerequisites = payload["prerequisites"]
        self.assertEqual(
            prerequisites["phase1_status"],
            "NO_SIGNAL_PASSED_DISCOVERY_THRESHOLD_CLOSED",
        )
        self.assertFalse(prerequisites["phase1_signals_reused_as_candidates"])
        self.assertEqual(
            prerequisites["phase1_signal_count"],
            len(registry.PRIOR_SIGNAL_IDS),
        )
        self.assertEqual(
            prerequisites["phase0_contract_sha256"],
            registry.PHASE0_CONTRACT_SHA256,
        )

    def test_all_prior_controls_and_signals_are_residualized(self):
        controls = set(
            registry.DISCOVERY_RULES[
                "cross_sectional_residualization_controls"
            ]
        )
        self.assertTrue(set(registry.PHASE0_CONTROLS).issubset(controls))
        self.assertTrue(set(registry.PRIOR_SIGNAL_IDS).issubset(controls))
        self.assertEqual(
            len(controls),
            len(registry.PHASE0_CONTROLS) + len(registry.PRIOR_SIGNAL_IDS),
        )

    def test_discovery_thresholds_are_stricter_and_predeclared(self):
        rules = registry.DISCOVERY_RULES
        self.assertEqual(
            rules["multiple_testing_adjustment"],
            "benjamini_hochberg_fdr_5pct",
        )
        self.assertEqual(rules["minimum_mean_orthogonal_ic"], 0.01)
        self.assertEqual(rules["minimum_positive_year_rate"], 0.70)
        self.assertEqual(rules["minimum_regime_mean_ic"], 0.0)
        self.assertEqual(rules["minimum_cross_sectional_assets"], 80)
        self.assertTrue(rules["family_selected_before_computation"])
        self.assertFalse(
            rules["signal_selection_performed_in_phase2_registry"]
        )
        self.assertFalse(
            rules["portfolio_simulation_performed_in_phase2_registry"]
        )

    def test_holdout_and_production_safety_are_fixed(self):
        payload = registry.build_registry()
        self.assertEqual(
            pd.Timestamp(payload["future_holdout_start_utc"]),
            pd.Timestamp("2026-11-02T00:00:00Z"),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = registry.write_registry(
                payload,
                root / "registry.json",
                root / "manifest.json",
            )
        for key in (
            "future_holdout_scored",
            "signal_computed",
            "signal_selected",
            "model_fitted",
            "portfolio_simulated",
            "candidate_frozen",
            "candidate_promoted",
            "v8_modified",
            "v8_holdout_scored",
            "v9_results_modified",
            "production_modified",
            "brokerage_orders",
        ):
            self.assertFalse(manifest[key], key)

    def test_writer_is_idempotent_and_refuses_drift(self):
        payload = registry.build_registry()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            manifest_path = root / "manifest.json"
            first = registry.write_registry(
                payload,
                registry_path,
                manifest_path,
            )
            second = registry.write_registry(
                payload,
                registry_path,
                manifest_path,
            )
            self.assertEqual(
                first["contract_sha256"],
                second["contract_sha256"],
            )
            drifted = json.loads(registry_path.read_text())
            drifted["signals"][0]["formula"] = "changed_after_registration"
            registry_path.write_text(json.dumps(drifted))
            with self.assertRaisesRegex(RuntimeError, "frozen contract"):
                registry.write_registry(
                    payload,
                    registry_path,
                    manifest_path,
                )


if __name__ == "__main__":
    unittest.main()
