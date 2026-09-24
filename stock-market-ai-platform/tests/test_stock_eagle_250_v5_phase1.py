import json
import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v5 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v5.phase1 import (
    CONTRACT_PATH,
    EXPECTED_V4_FAILED_GATES,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    V5_CANDIDATE,
    build_manifest,
    load_contract,
    self_drawdown_exposure_frame,
    validate_v1_period_source,
    validate_v4_evidence,
)


def period_frame(
    gross_returns=None,
    periods=14,
    start="2026-01-02",
):
    if gross_returns is None:
        gross_returns = [0.01] * periods
    timestamps = pd.date_range(start, periods=periods, freq="B", tz="UTC")
    rows = []
    for index, timestamp in enumerate(timestamps):
        target_index = min(index + 5, periods - 1)
        target = timestamps[target_index]
        gross = float(gross_returns[index])
        rows.append({
            "fold_id": f"dev_{index % 14 + 1:02d}",
            "portfolio_id": "ridge_fixed_v1",
            "timestamp_utc": timestamp,
            "entry_timestamp_utc_5d": timestamp,
            "target_endpoint_utc_5d": (
                "2026-09-22T00:00:00+00:00"
                if index == periods - 1
                else target
            ),
            "selected_symbols": "A,B,C,D,E,F,G,H,I,J",
            "selected_count": 10,
            "gross_return": gross,
            "net_return": (
                (1.0 + gross) * (1.0 - 0.001) ** 2 - 1.0
            ),
        })
    return pd.DataFrame(rows)


def single_fold_periods(gross_returns):
    timestamps = pd.date_range(
        "2026-01-02",
        periods=len(gross_returns),
        freq="B",
        tz="UTC",
    )
    rows = []
    for index, (timestamp, gross) in enumerate(zip(timestamps, gross_returns)):
        target = timestamp + pd.offsets.BDay(5)
        rows.append({
            "fold_id": "dev_01",
            "portfolio_id": "ridge_fixed_v1",
            "timestamp_utc": timestamp,
            "entry_timestamp_utc_5d": timestamp + pd.offsets.BDay(1),
            "target_endpoint_utc_5d": target,
            "selected_symbols": "A,B,C,D,E,F,G,H,I,J",
            "selected_count": 10,
            "gross_return": float(gross),
            "net_return": (
                (1.0 + float(gross)) * (1.0 - 0.001) ** 2 - 1.0
            ),
        })
    return pd.DataFrame(rows)


def valid_v4_manifest():
    return {
        "research_version": "stock_eagle_250_v4_confidence_conditioned_ridge",
        "phase": 2,
        "candidate_id": "ridge_v1_rank_cross_sectional_confidence_v4",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": {
            "median_fold_excess_vs_v1_ridge": -0.02586212035236013,
            "median_fold_drawdown_improvement_vs_v1_ridge":
                0.023550146832795715,
            "drawdown_improvement_fold_fraction": 1.0,
            "median_fold_calmar": 1.9695578395425675,
            "median_v1_ridge_calmar": 1.978763119139701,
            "median_gross_exposure": 0.7619776971824994,
        },
        "safety": {
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
    }


def valid_v4_qualification():
    return {
        "status": "REJECT_CURRENT_STOCK_EAGLE_250_V4_CANDIDATE",
        "candidate_id": "ridge_v1_rank_cross_sectional_confidence_v4",
        "gates_passed": 8,
        "gates_total": 11,
        "failed_gates": sorted(EXPECTED_V4_FAILED_GATES),
        "qualified_for_human_review": False,
        "candidate_frozen": False,
        "paper_trading_enabled": False,
        "automatic_promotion": False,
        "brokerage_orders": False,
    }


class StockEagle250V5Phase1Test(unittest.TestCase):
    def test_contract_is_one_fixed_final_self_drawdown_candidate(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_v5_results"])
        self.assertEqual(
            contract["fixed_candidate"]["candidate_id"],
            V5_CANDIDATE,
        )
        self.assertEqual(
            contract["fixed_candidate"]["minimum_gross_exposure"],
            0.5,
        )
        self.assertEqual(
            contract["fixed_candidate"]["maximum_gross_exposure"],
            1.0,
        )
        self.assertFalse(contract["fixed_candidate"]["spy_trend_used"])
        self.assertFalse(contract["fixed_candidate"]["spy_volatility_used"])
        self.assertFalse(
            contract["fixed_candidate"]["prediction_confidence_used"]
        )
        self.assertFalse(contract["fixed_candidate"]["exposure_search"])
        self.assertEqual(
            contract["preregistered_development_gates"]["policy"],
            "reuse_v2_v3_v4_gates_without_relaxation",
        )
        self.assertEqual(
            pd.Timestamp(
                contract["data_boundaries"]["new_untouched_future_start_utc"]
            ),
            FUTURE_START_UTC,
        )

    def test_v4_rejection_is_required(self):
        evidence = validate_v4_evidence(
            valid_v4_manifest(),
            valid_v4_qualification(),
        )
        self.assertEqual(evidence["v4_gates_passed"], 8)
        self.assertEqual(
            set(evidence["v4_failed_gates"]),
            EXPECTED_V4_FAILED_GATES,
        )

        qualification = valid_v4_qualification()
        qualification["status"] = "QUALIFIES_FOR_HUMAN_REVIEW"
        with self.assertRaisesRegex(RuntimeError, "not preserved as rejected"):
            validate_v4_evidence(valid_v4_manifest(), qualification)

    def test_v1_period_source_rejects_guard_band_rows(self):
        frame = period_frame()
        # Make a source-shaped frame with all 14 folds and fixed final dates.
        frame.loc[frame.index[-1], "timestamp_utc"] = (
            "2026-09-15T00:00:00+00:00"
        )
        ridge, summary = validate_v1_period_source(frame)
        self.assertEqual(summary["fold_count"], 14)
        self.assertEqual(len(ridge), 14)

        bad = frame.copy()
        bad.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_v1_period_source(bad)

    def test_self_drawdown_uses_only_strictly_prior_completed_cohorts(self):
        frame = single_fold_periods([
            -0.50, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01,
        ])
        result = self_drawdown_exposure_frame(frame)

        # The first cohort targets the sixth business-day offset. Its loss is
        # not visible at that same target timestamp because completion must be
        # strictly earlier than the current decision.
        target = pd.Timestamp(frame.iloc[0]["target_endpoint_utc_5d"])
        at_target = result.loc[result["timestamp_utc"] == target].iloc[0]
        self.assertEqual(at_target["shadow_completed_cohort_count"], 0)
        self.assertAlmostEqual(at_target["gross_exposure"], 1.0)

        after_target = result.loc[result["timestamp_utc"] > target].iloc[0]
        self.assertGreater(after_target["shadow_completed_cohort_count"], 0)
        self.assertLess(after_target["gross_exposure"], 1.0)
        self.assertGreaterEqual(after_target["gross_exposure"], 0.5)

    def test_current_and_future_return_cannot_change_current_exposure(self):
        base = single_fold_periods([0.0] * 10)
        changed = base.copy()
        changed.loc[5:, "gross_return"] = -0.9
        changed["net_return"] = (
            (1.0 + changed["gross_return"])
            * (1.0 - 0.001) ** 2
            - 1.0
        )

        left = self_drawdown_exposure_frame(base)
        right = self_drawdown_exposure_frame(changed)

        cutoff = base.loc[5, "timestamp_utc"]
        left_now = left.loc[left["timestamp_utc"] <= cutoff, "gross_exposure"]
        right_now = right.loc[right["timestamp_utc"] <= cutoff, "gross_exposure"]
        self.assertTrue(np.allclose(left_now, right_now))

    def test_drawdown_formula_reaches_fixed_floor(self):
        frame = single_fold_periods([
            -1.00, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        ])
        result = self_drawdown_exposure_frame(frame)
        self.assertTrue(result["gross_exposure"].between(0.5, 1.0).all())
        self.assertAlmostEqual(float(result["gross_exposure"].min()), 0.5)

    def test_manifest_has_no_v5_scoring_or_trading_authority(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload = build_manifest(
            contract,
            {
                "v4_status": "REJECT_CURRENT_STOCK_EAGLE_250_V4_CANDIDATE",
                "v4_gates_passed": 8,
                "v4_gates_total": 11,
                "v4_failed_gates": sorted(EXPECTED_V4_FAILED_GATES),
                "v4_median_fold_excess_vs_v1_ridge": -0.02586,
                "v4_median_drawdown_improvement_vs_v1_ridge": 0.02355,
                "v4_drawdown_improvement_fold_fraction": 1.0,
                "v4_median_fold_calmar": 1.96956,
                "v1_ridge_median_fold_calmar": 1.97876,
                "v4_median_gross_exposure": 0.76198,
            },
            {
                "source_rows": 100,
                "fold_count": 14,
                "development_decision_start_utc":
                    "2020-01-02T00:00:00+00:00",
                "development_decision_end_utc":
                    "2026-09-15T00:00:00+00:00",
                "maximum_development_target_endpoint_utc":
                    "2026-09-22T00:00:00+00:00",
                "minimum_selected_count": 10,
                "maximum_selected_count": 10,
            },
        )
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["guard_band_rows_read"], 0)
        self.assertEqual(payload["future_rows_read"], 0)
        self.assertFalse(payload["v5_performance_calculated"])
        self.assertFalse(payload["safety"]["candidate_frozen"])
        self.assertFalse(payload["safety"]["paper_trading_enabled"])
        self.assertFalse(payload["safety"]["brokerage_orders"])
        self.assertIn("stop development iteration", payload["next_step"])


if __name__ == "__main__":
    unittest.main()
