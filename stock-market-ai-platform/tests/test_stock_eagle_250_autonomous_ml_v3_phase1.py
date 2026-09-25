import json
import unittest

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from ml.stock_eagle_250_autonomous_ml_v3 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_v3.phase1 import (
    CONTRACT_PATH,
    EXPECTED_COMPONENTS,
    EXPECTED_V2_FAILED_GATES,
    REQUIRED_COLUMNS,
    SOURCE_CONTRACT_PATH,
    V2_CONTRACT_PATH,
    load_contract,
    model_templates,
    sha256,
    validate_source,
    validate_v2_evidence,
)


def source_manifest():
    fold_ids = [
        f"dev_{index:02d}"
        for index in range(1, 15)
    ]
    return {
        "candidate_count": 250,
        "fold_count": 14,
        "fold_ids": fold_ids,
        "future_holdout_rows_read": 0,
        "future_holdout_start_utc":
            "2026-09-23T00:00:00+00:00",
        "maximum_development_target_endpoint_utc":
            "2026-09-22T00:00:00+00:00",
        "development_start_utc":
            "2016-08-01T00:00:00+00:00",
        "development_end_utc":
            "2026-09-15T00:00:00+00:00",
        "source_rows": 624240,
        "model_eligible_rows": 561490,
        "contract_sha256":
            sha256(SOURCE_CONTRACT_PATH),
    }


def folds():
    return [
        {"fold_id": f"dev_{index:02d}"}
        for index in range(1, 15)
    ]


def v2_manifest():
    return {
        "research_version":
            "stock_eagle_250_autonomous_ml_v2_tail_aware",
        "phase": 2,
        "fold_count": 14,
        "learned_components": 4,
        "tail_quantile": 0.10,
        "meta_allocator_training_source":
            "inner_walk_forward_oos_only",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": {
            "median_fold_net_return":
                0.07038813753693451,
            "positive_fold_fraction":
                0.7857142857142857,
            "median_fold_excess_vs_spy":
                0.010193272495154337,
            "positive_excess_vs_spy_fold_fraction":
                0.5714285714285714,
            "median_fold_excess_vs_equal_weight":
                0.048574439256864776,
            "median_fold_rank_ic":
                0.025158328438543688,
            "positive_rank_ic_fold_fraction":
                0.9285714285714286,
            "worst_fold_maximum_drawdown":
                -0.27953452703039583,
            "median_fold_stress_20bps_net_return":
                0.04915964173830556,
            "median_mean_gross_exposure":
                0.5407206802737363,
        },
        "safety": {
            "model_frozen": False,
            "autonomous_paper_runtime_enabled":
                False,
            "live_execution_enabled": False,
        },
    }


def v2_qualification():
    return {
        "status": "REJECT_DEVELOPMENT_CANDIDATE",
        "gates_passed": 8,
        "gates_total": 9,
        "failed_gates": [
            "positive_excess_vs_spy_fold_fraction_gte"
        ],
        "autonomous_paper_runtime_enabled": False,
        "model_frozen": False,
    }


class StockEagle250AutonomousMLV3Phase1Test(
    unittest.TestCase
):
    def test_contract_has_fixed_benchmark_relative_architecture(self):
        contract = load_contract()

        self.assertEqual(
            contract["display_name"],
            DISPLAY_NAME,
        )
        self.assertEqual(
            contract["model_id"],
            MODEL_ID,
        )
        self.assertEqual(
            contract["research_version"],
            RESEARCH_VERSION,
        )
        self.assertTrue(
            contract["created_before_model_results"]
        )
        self.assertEqual(
            tuple(contract["architecture"]),
            EXPECTED_COMPONENTS,
        )

        meta = contract["architecture"][
            "meta_allocator"
        ]
        self.assertEqual(
            meta["target"],
            "tail_aware_top10_net_return_10bps_each_side_gt_forward_spy_return",
        )
        self.assertTrue(
            meta[
                "future_spy_return_is_label_only_not_feature"
            ]
        )

        policy = contract["portfolio_policy"]
        self.assertEqual(
            policy["spy_weight"],
            "1_minus_active_weight",
        )
        self.assertEqual(
            policy["cash_fraction"],
            0.0,
        )
        self.assertEqual(
            policy["total_gross_exposure"],
            1.0,
        )
        self.assertFalse(
            contract[
                "nested_walk_forward"
            ]["benchmark_mix_search"]
        )

    def test_templates_remain_four_actual_learned_estimators(self):
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
            templates[
                "tail_model"
            ].get_params()["quantile"],
            0.10,
        )

    def test_v2_rejection_and_single_failed_spy_gate_are_required(self):
        evidence = validate_v2_evidence(
            v2_manifest(),
            v2_qualification(),
        )

        self.assertEqual(
            evidence["v2_gates_passed"],
            8,
        )
        self.assertEqual(
            evidence["v2_gates_total"],
            9,
        )
        self.assertEqual(
            set(evidence["v2_failed_gates"]),
            EXPECTED_V2_FAILED_GATES,
        )
        self.assertAlmostEqual(
            evidence[
                "v2_positive_excess_vs_spy_fold_fraction"
            ],
            8 / 14,
        )

        qualification = v2_qualification()
        qualification["status"] = (
            "QUALIFIES_FOR_AUTONOMOUS_PAPER_BUILD"
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "preserved as rejected",
        ):
            validate_v2_evidence(
                v2_manifest(),
                qualification,
            )

    def test_v3_reuses_v2_gates_without_relaxation(self):
        v3 = json.loads(
            CONTRACT_PATH.read_text(
                encoding="utf-8"
            )
        )
        v2 = json.loads(
            V2_CONTRACT_PATH.read_text(
                encoding="utf-8"
            )
        )

        v3_gates = {
            key: value
            for key, value in v3[
                "development_gates"
            ].items()
            if key != "policy"
        }
        v2_gates = {
            key: value
            for key, value in v2[
                "development_gates"
            ].items()
            if key != "policy"
        }

        self.assertEqual(
            v3_gates,
            v2_gates,
        )
        self.assertEqual(
            v3_gates[
                "positive_excess_vs_spy_fold_fraction_gte"
            ],
            0.60,
        )
        self.assertEqual(
            v3_gates[
                "worst_fold_maximum_drawdown_gte"
            ],
            -0.30,
        )

    def test_source_requires_spy_return_and_preserves_boundary(self):
        summary = validate_source(
            source_manifest(),
            folds(),
            set(REQUIRED_COLUMNS),
        )

        self.assertEqual(
            summary["candidate_count"],
            250,
        )
        self.assertEqual(
            summary["fold_count"],
            14,
        )
        self.assertEqual(
            summary[
                "future_holdout_rows_read"
            ],
            0,
        )

        columns = set(REQUIRED_COLUMNS)
        columns.remove("forward_spy_return")
        with self.assertRaisesRegex(
            RuntimeError,
            "forward_spy_return",
        ):
            validate_source(
                source_manifest(),
                folds(),
                columns,
            )

    def test_phase1_keeps_runtime_and_execution_disabled(self):
        contract = load_contract()
        authority = contract["authority"]

        self.assertFalse(
            authority[
                "autonomous_paper_runtime_enabled"
            ]
        )
        self.assertFalse(
            authority[
                "model_freezing_enabled"
            ]
        )
        self.assertFalse(
            authority[
                "live_execution_enabled"
            ]
        )


if __name__ == "__main__":
    unittest.main()
