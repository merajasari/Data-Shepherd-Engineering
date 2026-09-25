import json
import unittest

from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase1 import (
    CONTRACT_PATH,
    EXPECTED_CANDIDATE_ORDER,
    EXPECTED_GUARD_START,
    EXPECTED_PROSPECTIVE_START,
    _validate_candidate_result,
    git_blob_sha1,
    load_contract,
)


def manifest(version, summary):
    return {
        "research_version": version,
        "phase": 2,
        "fold_count": 14,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": summary,
        "safety": {
            "live_execution_enabled": False,
        },
    }


def qualification(passed, failed):
    return {
        "status": "REJECT_DEVELOPMENT_CANDIDATE",
        "gates_passed": passed,
        "gates_total": 9,
        "failed_gates": failed,
        "autonomous_paper_runtime_enabled": False,
        "model_frozen": False,
    }


class StockEagle250AutonomousMLProspectiveV1Phase1Test(
    unittest.TestCase
):
    def test_contract_seals_boundaries_and_review_threshold(self):
        contract = load_contract()
        self.assertEqual(
            tuple(
                row["candidate_id"]
                for row in contract["candidate_snapshots"]
            ),
            EXPECTED_CANDIDATE_ORDER,
        )
        self.assertEqual(
            contract["snapshot_build"]["sealed_guard_band_start_utc"],
            EXPECTED_GUARD_START,
        )
        self.assertEqual(
            contract["snapshot_build"]["prospective_start_utc"],
            EXPECTED_PROSPECTIVE_START,
        )
        protocol = contract["prospective_protocol"]
        self.assertEqual(
            protocol[
                "minimum_completed_cohorts_for_formal_review_per_candidate"
            ],
            60,
        )
        self.assertEqual(
            protocol[
                "minimum_complete_five_sleeve_blocks_for_formal_review"
            ],
            12,
        )
        self.assertFalse(
            protocol["automatic_winner_selection"]
        )
        self.assertFalse(
            protocol["automatic_model_promotion"]
        )

    def test_candidate_contract_and_code_blobs_are_bound(self):
        contract = load_contract()
        for candidate in contract["candidate_snapshots"]:
            self.assertEqual(
                git_blob_sha1(
                    candidate["phase1_contract_path"]
                ),
                candidate[
                    "phase1_contract_git_blob_sha1"
                ],
            )
            self.assertEqual(
                git_blob_sha1(
                    candidate["phase2_code_path"]
                ),
                candidate[
                    "phase2_code_git_blob_sha1"
                ],
            )

    def test_v1_v2_v3_required_results_are_distinct_and_preserved(self):
        contract = load_contract()
        by_id = {
            row["candidate_id"]: row
            for row in contract["candidate_snapshots"]
        }

        v1 = _validate_candidate_result(
            by_id["autonomous_ml_v1"],
            manifest(
                "stock_eagle_250_autonomous_ml_v1",
                {
                    "median_fold_net_return": 0.08118495219595567,
                    "median_fold_excess_vs_spy": 0.022505170263224517,
                    "positive_excess_vs_spy_fold_fraction":
                        0.6428571428571429,
                    "worst_fold_maximum_drawdown":
                        -0.43458294422261523,
                },
            ),
            qualification(
                8,
                ["worst_fold_maximum_drawdown_gte"],
            ),
        )
        self.assertEqual(v1["gates_passed"], 8)

        v2 = _validate_candidate_result(
            by_id["autonomous_ml_v2"],
            manifest(
                "stock_eagle_250_autonomous_ml_v2_tail_aware",
                {
                    "median_fold_net_return": 0.07038813753693451,
                    "median_fold_excess_vs_spy": 0.010193272495154337,
                    "positive_excess_vs_spy_fold_fraction":
                        0.5714285714285714,
                    "worst_fold_maximum_drawdown":
                        -0.27953452703039583,
                },
            ),
            qualification(
                8,
                ["positive_excess_vs_spy_fold_fraction_gte"],
            ),
        )
        self.assertEqual(
            v2["failed_gates"],
            ["positive_excess_vs_spy_fold_fraction_gte"],
        )

        v3 = _validate_candidate_result(
            by_id["autonomous_ml_v3"],
            manifest(
                "stock_eagle_250_autonomous_ml_v3_benchmark_relative",
                {
                    "median_fold_net_return": 0.0708731554709543,
                    "median_fold_excess_vs_spy":
                        -0.006803736486117984,
                    "positive_excess_vs_spy_fold_fraction": 0.5,
                    "worst_fold_maximum_drawdown":
                        -0.38308663952794586,
                },
            ),
            qualification(
                6,
                [
                    "median_fold_excess_vs_spy_gt_zero",
                    "positive_excess_vs_spy_fold_fraction_gte",
                    "worst_fold_maximum_drawdown_gte",
                ],
            ),
        )
        self.assertEqual(v3["gates_passed"], 6)

    def test_result_mismatch_fails_closed(self):
        contract = load_contract()
        v2 = next(
            row
            for row in contract["candidate_snapshots"]
            if row["candidate_id"] == "autonomous_ml_v2"
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "evidence changed",
        ):
            _validate_candidate_result(
                v2,
                manifest(
                    "stock_eagle_250_autonomous_ml_v2_tail_aware",
                    {
                        "median_fold_net_return": 0.07,
                        "median_fold_excess_vs_spy": 0.01,
                        "positive_excess_vs_spy_fold_fraction":
                            9 / 14,
                        "worst_fold_maximum_drawdown":
                            -0.27953452703039583,
                    },
                ),
                qualification(
                    8,
                    ["positive_excess_vs_spy_fold_fraction_gte"],
                ),
            )

    def test_guardrails_forbid_preboundary_peeking_and_model_changes(self):
        contract = load_contract()
        guardrails = contract["guardrails"]
        for key in (
            "september_23_through_30_training_use",
            "september_23_through_30_evaluation_use",
            "october_1_plus_read_before_prospective_runner",
            "modify_v1",
            "modify_v2",
            "modify_v3",
            "modify_existing_forward_journals",
            "automatic_promotion",
            "real_orders",
        ):
            self.assertFalse(guardrails[key])


if __name__ == "__main__":
    unittest.main()
