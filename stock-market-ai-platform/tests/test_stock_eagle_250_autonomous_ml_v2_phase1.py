import json
import unittest

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from ml.stock_eagle_250_autonomous_ml_v2 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_v2.phase1 import (
    CONTRACT_PATH,
    EXPECTED_COMPONENTS,
    EXPECTED_V1_FAILED_GATES,
    REQUIRED_COLUMNS,
    SOURCE_CONTRACT_PATH,
    V1_CONTRACT_PATH,
    load_contract,
    model_templates,
    sha256,
    validate_source,
    validate_v1_evidence,
)


def source_manifest():
    fold_ids = [f"dev_{index:02d}" for index in range(1, 15)]
    return {
        "candidate_count": 250,
        "fold_count": 14,
        "fold_ids": fold_ids,
        "future_holdout_rows_read": 0,
        "future_holdout_start_utc": "2026-09-23T00:00:00+00:00",
        "maximum_development_target_endpoint_utc":
            "2026-09-22T00:00:00+00:00",
        "development_start_utc": "2016-08-01T00:00:00+00:00",
        "development_end_utc": "2026-09-15T00:00:00+00:00",
        "source_rows": 624240,
        "model_eligible_rows": 561490,
        "contract_sha256": sha256(SOURCE_CONTRACT_PATH),
    }


def folds():
    return [
        {"fold_id": f"dev_{index:02d}"}
        for index in range(1, 15)
    ]


def v1_manifest():
    return {
        "research_version": "stock_eagle_250_autonomous_ml_v1",
        "phase": 2,
        "fold_count": 14,
        "learned_components": 3,
        "meta_allocator_training_source": "inner_walk_forward_oos_only",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": {
            "median_fold_net_return": 0.08118495219595567,
            "median_fold_excess_vs_spy": 0.022505170263224517,
            "positive_rank_ic_fold_fraction": 0.9285714285714286,
            "worst_fold_maximum_drawdown": -0.43458294422261523,
            "median_fold_stress_20bps_net_return":
                0.05992576600525645,
        },
        "safety": {
            "model_frozen": False,
            "autonomous_paper_runtime_enabled": False,
            "live_execution_enabled": False,
        },
    }


def v1_qualification():
    return {
        "status": "REJECT_DEVELOPMENT_CANDIDATE",
        "gates_passed": 8,
        "gates_total": 9,
        "failed_gates": ["worst_fold_maximum_drawdown_gte"],
        "autonomous_paper_runtime_enabled": False,
        "model_frozen": False,
    }


class StockEagle250AutonomousMLV2Phase1Test(unittest.TestCase):
    def test_contract_has_four_fixed_learned_components(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_model_results"])
        self.assertEqual(tuple(contract["architecture"]), EXPECTED_COMPONENTS)
        self.assertEqual(
            contract["architecture"]["tail_model"]["parameters"]["loss"],
            "quantile",
        )
        self.assertEqual(
            contract["architecture"]["tail_model"]["parameters"]["quantile"],
            0.10,
        )
        self.assertFalse(
            contract["nested_walk_forward"]["quantile_search"]
        )

    def test_templates_are_four_actual_learned_estimators(self):
        templates = model_templates()

        self.assertIsInstance(
            templates["alpha_model"],
            HistGradientBoostingRegressor,
        )
        self.assertIsInstance(
            templates["downside_model"],
            HistGradientBoostingClassifier,
        )
        self.assertIsInstance(
            templates["tail_model"],
            HistGradientBoostingRegressor,
        )
        self.assertIsInstance(
            templates["meta_allocator"],
            HistGradientBoostingClassifier,
        )
        self.assertEqual(
            templates["tail_model"].get_params()["quantile"],
            0.10,
        )

    def test_v1_rejection_and_single_failed_gate_are_required(self):
        evidence = validate_v1_evidence(
            v1_manifest(),
            v1_qualification(),
        )

        self.assertEqual(evidence["v1_gates_passed"], 8)
        self.assertEqual(evidence["v1_gates_total"], 9)
        self.assertEqual(
            set(evidence["v1_failed_gates"]),
            EXPECTED_V1_FAILED_GATES,
        )

        qualification = v1_qualification()
        qualification["status"] = "QUALIFIES_FOR_AUTONOMOUS_PAPER_BUILD"
        with self.assertRaisesRegex(RuntimeError, "preserved as rejected"):
            validate_v1_evidence(v1_manifest(), qualification)

    def test_v2_reuses_v1_gates_without_relaxation(self):
        v2 = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        v1 = json.loads(V1_CONTRACT_PATH.read_text(encoding="utf-8"))
        v2_gates = {
            key: value
            for key, value in v2["development_gates"].items()
            if key != "policy"
        }

        self.assertEqual(v2_gates, v1["development_gates"])
        self.assertEqual(
            v2["development_gates"]["worst_fold_maximum_drawdown_gte"],
            -0.30,
        )

    def test_source_boundary_is_fail_closed(self):
        summary = validate_source(
            source_manifest(),
            folds(),
            set(REQUIRED_COLUMNS),
        )
        self.assertEqual(summary["candidate_count"], 250)
        self.assertEqual(summary["fold_count"], 14)
        self.assertEqual(summary["future_holdout_rows_read"], 0)

        bad = source_manifest()
        bad["future_holdout_rows_read"] = 1
        with self.assertRaisesRegex(RuntimeError, "future_holdout_rows_read"):
            validate_source(bad, folds(), set(REQUIRED_COLUMNS))

    def test_phase1_keeps_runtime_and_execution_disabled(self):
        contract = load_contract()
        authority = contract["authority"]

        self.assertFalse(authority["autonomous_paper_runtime_enabled"])
        self.assertFalse(authority["model_freezing_enabled"])
        self.assertFalse(authority["live_execution_enabled"])


if __name__ == "__main__":
    unittest.main()
