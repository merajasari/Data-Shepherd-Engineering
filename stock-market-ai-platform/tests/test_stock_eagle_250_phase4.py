import unittest

import pandas as pd

from ml.stock_eagle_250.phase3 import CANDIDATE_IDS
from ml.stock_eagle_250.phase4 import (
    adjudicate,
    validate_phase3_manifest,
)


GATE_COLUMNS = (
    "gate_median_fold_net_return_gt_zero",
    "gate_positive_fold_fraction_gte_70pct",
    "gate_median_fold_excess_vs_spy_gt_zero",
    "gate_positive_excess_vs_spy_fold_fraction_gte_60pct",
    "gate_median_fold_excess_vs_equal_weight_gt_zero",
    "gate_median_fold_mean_rank_ic_gt_zero",
    "gate_positive_mean_rank_ic_fold_fraction_gte_60pct",
    "gate_worst_fold_maximum_drawdown_gte_minus_35pct",
)


def summary_frame():
    return pd.DataFrame([
        {
            "candidate_id": candidate_id,
            "fold_count": 14,
            "median_fold_net_return": 0.10,
            "mean_fold_net_return": 0.09,
            "positive_fold_fraction": 0.78,
            "median_fold_excess_vs_spy": 0.05,
            "positive_excess_vs_spy_fold_fraction": 0.70,
            "median_fold_excess_vs_equal_weight": 0.08,
            "median_fold_excess_vs_return_20d_rank": 0.04,
            "median_fold_mean_rank_ic": 0.02,
            "positive_mean_rank_ic_fold_fraction": 0.85,
            "mean_row_mae": 0.03,
            "mean_row_rmse": 0.04,
            "worst_fold_maximum_drawdown": -0.42,
        }
        for candidate_id in CANDIDATE_IDS
    ])


def gate_frame(drawdown_pass=False):
    rows = []
    for candidate_id in CANDIDATE_IDS:
        values = {column: True for column in GATE_COLUMNS}
        values[
            "gate_worst_fold_maximum_drawdown_gte_minus_35pct"
        ] = drawdown_pass
        passed = sum(values.values())
        rows.append({
            "candidate_id": candidate_id,
            **values,
            "passed_gate_count": passed,
            "total_gate_count": len(values),
            "qualified_for_human_review":
                passed == len(values),
        })
    return pd.DataFrame(rows)


class StockEagle250Phase4Test(unittest.TestCase):
    def test_failed_drawdown_gate_rejects_both_candidates(self):
        qualification = {
            "status": "NO_CANDIDATE_QUALIFIED",
            "qualified_candidate_count": 0,
            "qualified_candidates": [],
            "candidate_frozen": False,
            "paper_trading_enabled": False,
        }
        disposition, decision = adjudicate(
            summary_frame(),
            gate_frame(drawdown_pass=False),
            qualification,
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_STOCK_EAGLE_250_V1_CANDIDATES",
        )
        self.assertEqual(decision["qualified_candidate_count"], 0)
        self.assertTrue(
            (
                disposition["passed_gate_count"] == 7
            ).all()
        )
        self.assertTrue(
            disposition["failed_gates"].str.contains(
                "maximum_drawdown"
            ).all()
        )
        self.assertTrue(
            (
                disposition["disposition"]
                == "REJECT_CURRENT_CANDIDATE"
            ).all()
        )

    def test_all_gates_pass_only_qualifies_for_human_review(self):
        qualification = {
            "status": "QUALIFIES_FOR_HUMAN_REVIEW",
            "qualified_candidate_count": 2,
            "qualified_candidates": list(CANDIDATE_IDS),
            "candidate_frozen": False,
            "paper_trading_enabled": False,
        }
        disposition, decision = adjudicate(
            summary_frame(),
            gate_frame(drawdown_pass=True),
            qualification,
        )

        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(decision["qualified_candidate_count"], 2)
        self.assertTrue(
            disposition["qualified_for_human_review"].all()
        )

    def test_inconsistent_gate_count_fails_closed(self):
        gates = gate_frame(drawdown_pass=False)
        gates.loc[0, "passed_gate_count"] = 8
        qualification = {
            "status": "NO_CANDIDATE_QUALIFIED",
            "qualified_candidate_count": 0,
            "qualified_candidates": [],
            "candidate_frozen": False,
            "paper_trading_enabled": False,
        }
        with self.assertRaisesRegex(RuntimeError, "inconsistent"):
            adjudicate(summary_frame(), gates, qualification)

    def test_manifest_rejects_any_holdout_or_trading_activity(self):
        manifest = {
            "display_name": "StockEagle250",
            "model_id": "stock_eagle_250",
            "research_version": "stock_eagle_250_v1",
            "phase": 3,
            "candidate_count": 2,
            "candidate_ids": list(CANDIDATE_IDS),
            "fold_count": 14,
            "future_holdout_start_utc": "2026-09-23T00:00:00+00:00",
            "future_holdout_rows_read": 0,
            "maximum_target_endpoint_utc":
                "2026-09-22T00:00:00+00:00",
            "safety": {
                "hyperparameter_search_performed": False,
                "future_holdout_scored": False,
                "candidate_frozen": False,
                "paper_trading_enabled": False,
                "live_trading_enabled": False,
                "brokerage_orders": False,
                "automatic_promotion": False,
                "existing_model_artifacts_modified": False,
                "existing_forward_journals_modified": False,
            },
        }
        validate_phase3_manifest(manifest)

        manifest["future_holdout_rows_read"] = 1
        with self.assertRaisesRegex(RuntimeError, "manifest mismatch"):
            validate_phase3_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
