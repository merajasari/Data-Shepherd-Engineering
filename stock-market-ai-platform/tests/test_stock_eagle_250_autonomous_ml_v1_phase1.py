import json
import unittest

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from ml.stock_eagle_250_autonomous_ml_v1 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_v1.phase1 import (
    CONTRACT_PATH,
    EXPECTED_COMPONENTS,
    REQUIRED_COLUMNS,
    SOURCE_CONTRACT_PATH,
    load_contract,
    model_templates,
    sha256,
    validate_source,
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
        "development_start_utc": "2016-01-01T00:00:00+00:00",
        "development_end_utc": "2026-09-15T00:00:00+00:00",
        "source_rows": 401253,
        "model_eligible_rows": 300000,
        "contract_sha256": sha256(SOURCE_CONTRACT_PATH),
    }


def folds():
    return [
        {
            "fold_id": f"dev_{index:02d}",
            "max_train_target_endpoint_utc": "2019-12-20T00:00:00+00:00",
            "validation_start_utc": "2020-01-01T00:00:00+00:00",
            "max_validation_target_endpoint_utc": "2020-06-20T00:00:00+00:00",
            "validation_end_exclusive_utc": "2020-07-01T00:00:00+00:00",
        }
        for index in range(1, 15)
    ]


class StockEagle250AutonomousMLV1Phase1Test(unittest.TestCase):
    def test_contract_has_three_fixed_learned_components(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_model_results"])
        self.assertEqual(tuple(contract["architecture"]), EXPECTED_COMPONENTS)
        self.assertFalse(
            contract["nested_walk_forward"]["hyperparameter_search"]
        )
        self.assertFalse(
            contract["nested_walk_forward"]["allocator_threshold_search"]
        )
        self.assertFalse(
            contract["isolation"]["consume_stock_eagle_250_v5_phase2"]
        )

    def test_templates_are_actual_learned_estimators(self):
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
            templates["meta_allocator"],
            HistGradientBoostingClassifier,
        )

    def test_meta_allocator_requires_inner_oos_predictions(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertTrue(
            contract["architecture"]["meta_allocator"][
                "training_features_must_be_inner_walk_forward_oos"
            ]
        )
        self.assertEqual(
            contract["portfolio_policy"]["gross_exposure"],
            "clip(meta_allocator_probability_positive, 0.0, 1.0)",
        )
        self.assertFalse(contract["portfolio_policy"]["leverage"])
        self.assertFalse(contract["portfolio_policy"]["short_sales"])

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

    def test_phase1_does_not_enable_runtime_or_execution(self):
        contract = load_contract()
        authority = contract["authority"]

        self.assertFalse(authority["autonomous_paper_runtime_enabled"])
        self.assertFalse(authority["model_freezing_enabled"])
        self.assertFalse(authority["live_execution_enabled"])


if __name__ == "__main__":
    unittest.main()
