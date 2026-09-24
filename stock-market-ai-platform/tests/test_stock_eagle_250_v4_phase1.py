import json
import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v4 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v4.phase1 import (
    CONFIDENCE_MINIMUM_PRIOR,
    CONTRACT_PATH,
    EXPECTED_V3_FAILED_GATES,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    V4_CANDIDATE,
    build_manifest,
    confidence_exposure_frame,
    load_contract,
    validate_prediction_source,
    validate_v3_evidence,
)


def prediction_frame(session_count=70):
    rows = []
    timestamps = pd.date_range(
        "2026-01-02",
        periods=session_count,
        freq="B",
        tz="UTC",
    )
    for session_index, timestamp in enumerate(timestamps):
        fold_id = f"dev_{min(14, session_index // 5 + 1):02d}"
        for symbol_index in range(25):
            rows.append({
                "fold_id": fold_id,
                "timestamp_utc": timestamp,
                "entry_timestamp_utc_5d": timestamp,
                "target_endpoint_utc_5d": (
                    "2026-09-22T00:00:00+00:00"
                    if session_index == session_count - 1
                    else timestamp
                ),
                "symbol": f"S{symbol_index:03d}",
                "prediction_ridge_fixed_v1":
                    0.02 - symbol_index * (0.0002 + session_index * 0.000001),
            })
    # The source validator requires all 14 folds in the saved development source.
    unique_sessions = sorted(set(row["timestamp_utc"] for row in rows))
    for index, timestamp in enumerate(unique_sessions):
        fold_id = f"dev_{index % 14 + 1:02d}"
        for row in rows:
            if row["timestamp_utc"] == timestamp:
                row["fold_id"] = fold_id
    return pd.DataFrame(rows)


def valid_v3_manifest():
    return {
        "research_version": "stock_eagle_250_v3_volatility_budgeted_ridge",
        "phase": 2,
        "candidate_id": "ridge_v1_rank_volatility_budget_v3",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": {
            "positive_excess_vs_spy_fold_fraction": 0.5714285714285714,
            "median_fold_drawdown_improvement_vs_v1_ridge":
                0.003878595123979145,
            "median_fold_calmar": 1.7243077752326137,
            "median_v1_ridge_calmar": 1.978763119139701,
            "median_gross_exposure": 0.9076302788598335,
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


def valid_v3_qualification():
    return {
        "status": "REJECT_CURRENT_STOCK_EAGLE_250_V3_CANDIDATE",
        "candidate_id": "ridge_v1_rank_volatility_budget_v3",
        "gates_passed": 8,
        "gates_total": 11,
        "failed_gates": sorted(EXPECTED_V3_FAILED_GATES),
        "qualified_for_human_review": False,
        "candidate_frozen": False,
        "paper_trading_enabled": False,
        "automatic_promotion": False,
        "brokerage_orders": False,
    }


class StockEagle250V4Phase1Test(unittest.TestCase):
    def test_contract_is_one_fixed_confidence_candidate(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_v4_results"])
        self.assertEqual(
            contract["fixed_candidate"]["candidate_id"],
            V4_CANDIDATE,
        )
        self.assertFalse(contract["fixed_candidate"]["spy_trend_used"])
        self.assertFalse(contract["fixed_candidate"]["spy_volatility_used"])
        self.assertFalse(contract["fixed_candidate"]["exposure_search"])
        self.assertEqual(
            contract["fixed_candidate"]["minimum_gross_exposure"],
            0.5,
        )
        self.assertEqual(
            contract["preregistered_development_gates"]["policy"],
            "reuse_v2_v3_gates_without_relaxation",
        )
        self.assertEqual(
            pd.Timestamp(
                contract["data_boundaries"]["new_untouched_future_start_utc"]
            ),
            FUTURE_START_UTC,
        )

    def test_prediction_source_rejects_guard_band_rows(self):
        frame = prediction_frame()
        summary = validate_prediction_source(frame)
        self.assertEqual(summary["fold_count"], 14)
        self.assertGreaterEqual(summary["minimum_symbols_per_decision"], 20)

        frame.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_prediction_source(frame)

    def test_confidence_uses_only_prior_sessions_and_stays_in_fixed_band(self):
        frame = prediction_frame()
        result = confidence_exposure_frame(frame)

        self.assertTrue(result["gross_exposure"].between(0.5, 1.0).all())
        self.assertTrue(
            (
                result.iloc[:CONFIDENCE_MINIMUM_PRIOR]["gross_exposure"]
                == 0.5
            ).all()
        )
        self.assertTrue(
            result.iloc[:CONFIDENCE_MINIMUM_PRIOR][
                "confidence_percentile"
            ].isna().all()
        )
        ready = result.iloc[CONFIDENCE_MINIMUM_PRIOR:]
        self.assertFalse(ready.empty)
        self.assertTrue(ready["confidence_percentile"].between(0.0, 1.0).all())
        self.assertTrue(
            (
                ready["gross_exposure"]
                == 0.5 + 0.5 * ready["confidence_percentile"]
            ).all()
        )

    def test_confidence_signal_is_cross_sectional_not_spy_based(self):
        frame = prediction_frame()
        result = confidence_exposure_frame(frame)

        self.assertIn("selection_margin", result.columns)
        self.assertIn("cross_sectional_prediction_mad", result.columns)
        self.assertIn("standardized_confidence", result.columns)
        self.assertNotIn("spy_return_1d", result.columns)
        self.assertNotIn("spy_realized_volatility_20", result.columns)

    def test_v3_rejection_is_required(self):
        evidence = validate_v3_evidence(
            valid_v3_manifest(),
            valid_v3_qualification(),
        )
        self.assertEqual(evidence["v3_gates_passed"], 8)
        self.assertEqual(
            set(evidence["v3_failed_gates"]),
            EXPECTED_V3_FAILED_GATES,
        )

        qualification = valid_v3_qualification()
        qualification["status"] = "QUALIFIES_FOR_HUMAN_REVIEW"
        with self.assertRaisesRegex(RuntimeError, "not preserved as rejected"):
            validate_v3_evidence(valid_v3_manifest(), qualification)

    def test_manifest_has_no_v4_scoring_or_trading_authority(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload = build_manifest(
            contract,
            {
                "v3_status": "REJECT_CURRENT_STOCK_EAGLE_250_V3_CANDIDATE",
                "v3_gates_passed": 8,
                "v3_gates_total": 11,
                "v3_failed_gates": sorted(EXPECTED_V3_FAILED_GATES),
                "v3_positive_excess_vs_spy_fold_fraction": 0.5714,
                "v3_median_drawdown_improvement_vs_v1_ridge": 0.0039,
                "v3_median_fold_calmar": 1.7243,
                "v1_ridge_median_fold_calmar": 1.9788,
                "v3_median_gross_exposure": 0.9076,
            },
            {
                "source_rows": 100,
                "fold_count": 14,
                "decision_sessions": 70,
                "development_decision_start_utc":
                    "2020-01-02T00:00:00+00:00",
                "development_decision_end_utc":
                    "2026-09-15T00:00:00+00:00",
                "maximum_development_target_endpoint_utc":
                    "2026-09-22T00:00:00+00:00",
                "minimum_symbols_per_decision": 20,
            },
        )

        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["guard_band_rows_read"], 0)
        self.assertEqual(payload["future_rows_read"], 0)
        self.assertFalse(payload["v4_performance_calculated"])
        self.assertFalse(payload["safety"]["candidate_frozen"])
        self.assertFalse(payload["safety"]["paper_trading_enabled"])
        self.assertFalse(payload["safety"]["brokerage_orders"])


if __name__ == "__main__":
    unittest.main()
