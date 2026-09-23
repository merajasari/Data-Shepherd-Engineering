import json
import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v2 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v2.phase1 import (
    CONTRACT_PATH,
    EXPOSURE_BY_STATE,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    V2_CANDIDATE,
    build_manifest,
    load_contract,
    market_state_frame,
    validate_source_predictions,
    validate_v1_evidence,
)


def valid_adjudication():
    return {
        "research_version": "stock_eagle_250_v1",
        "status": "REJECT_CURRENT_STOCK_EAGLE_250_V1_CANDIDATES",
        "qualified_candidate_count": 0,
        "failed_gates_by_candidate": {
            "ridge_fixed_v1": [
                "gate_worst_fold_maximum_drawdown_gte_minus_35pct"
            ]
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


def valid_phase3_manifest():
    return {
        "research_version": "stock_eagle_250_v1",
        "future_holdout_rows_read": 0,
        "maximum_target_endpoint_utc": "2026-09-22T00:00:00+00:00",
    }


class StockEagle250V2Phase1Test(unittest.TestCase):
    def test_contract_is_one_fixed_v10_inspired_challenger(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_v2_results"])
        self.assertEqual(
            contract["fixed_candidate"]["candidate_id"],
            V2_CANDIDATE,
        )
        self.assertFalse(
            contract["fixed_candidate"]["threshold_search"]
        )
        self.assertFalse(
            contract["fixed_candidate"]["exposure_search"]
        )
        self.assertEqual(
            contract["portfolio"]["all_cohort_offsets_required"],
            [0, 1, 2, 3, 4],
        )
        self.assertEqual(
            pd.Timestamp(
                contract["data_boundaries"]["new_untouched_future_start_utc"]
            ),
            FUTURE_START_UTC,
        )
        self.assertFalse(
            contract["authority"]["paper_trading_enabled"]
        )
        self.assertFalse(contract["authority"]["brokerage_orders"])

    def test_market_state_uses_fixed_exposures_and_fails_closed(self):
        timestamps = pd.date_range(
            "2024-01-02",
            periods=340,
            freq="B",
            tz="UTC",
        )
        returns = np.full(len(timestamps), 0.001)
        returns[-20:] = -0.01
        frame = market_state_frame(pd.DataFrame({
            "timestamp_utc": timestamps,
            "spy_return_1d": returns,
        }))

        self.assertTrue(
            set(frame["market_state"]).issubset(EXPOSURE_BY_STATE)
        )
        self.assertEqual(frame.iloc[0]["market_state"], "NOT_READY")
        self.assertEqual(frame.iloc[0]["gross_exposure"], 0.0)
        self.assertEqual(
            frame.iloc[-1]["gross_exposure"],
            EXPOSURE_BY_STATE[frame.iloc[-1]["market_state"]],
        )
        self.assertLess(frame.iloc[-1]["gross_exposure"], 1.0)

    def test_prediction_source_cannot_enter_guard_band(self):
        rows = []
        for fold_index in range(14):
            rows.append({
                "fold_id": f"fold_{fold_index + 1:02d}",
                "timestamp_utc": "2026-09-15T00:00:00+00:00",
                "entry_timestamp_utc_5d": "2026-09-16T00:00:00+00:00",
                "target_endpoint_utc_5d": "2026-09-22T00:00:00+00:00",
                "symbol": f"S{fold_index:03d}",
                "forward_stock_return": 0.01,
                "forward_spy_return": 0.005,
                "prediction_ridge_fixed_v1": 0.002,
            })
        frame = pd.DataFrame(rows)
        summary = validate_source_predictions(frame)
        self.assertEqual(summary["fold_count"], 14)

        frame.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_source_predictions(frame)

    def test_v1_rejection_and_drawdown_failure_are_required(self):
        validate_v1_evidence(
            valid_adjudication(),
            valid_phase3_manifest(),
        )
        adjudication = valid_adjudication()
        adjudication["failed_gates_by_candidate"]["ridge_fixed_v1"] = []
        with self.assertRaisesRegex(RuntimeError, "drawdown failure"):
            validate_v1_evidence(
                adjudication,
                valid_phase3_manifest(),
            )

    def test_manifest_has_no_scoring_or_trading_authority(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload = build_manifest(contract, {
            "source_rows": 100,
            "fold_count": 14,
            "development_decision_start_utc":
                "2020-01-02T00:00:00+00:00",
            "development_decision_end_utc":
                "2026-09-15T00:00:00+00:00",
            "maximum_development_target_endpoint_utc":
                "2026-09-22T00:00:00+00:00",
        })

        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["guard_band_rows_read"], 0)
        self.assertEqual(payload["future_rows_read"], 0)
        self.assertFalse(payload["v2_performance_calculated"])
        self.assertFalse(payload["safety"]["candidate_frozen"])
        self.assertFalse(payload["safety"]["paper_trading_enabled"])
        self.assertFalse(payload["safety"]["brokerage_orders"])


if __name__ == "__main__":
    unittest.main()
