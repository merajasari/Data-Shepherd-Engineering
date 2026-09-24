import json
import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v3 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v3.phase1 import (
    CONTRACT_PATH,
    EXPECTED_V2_FAILED_GATES,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    V3_CANDIDATE,
    build_manifest,
    load_contract,
    validate_v2_evidence,
    volatility_budget_frame,
)


def valid_v2_manifest():
    return {
        "research_version": "stock_eagle_250_v2_risk_controlled_ridge",
        "phase": 2,
        "candidate_id": "ridge_v1_rank_v10_regime_exposure_v2",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": {
            "worst_fold_maximum_drawdown": -0.186,
            "median_fold_excess_vs_v1_ridge": -0.0645,
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


def valid_v2_qualification():
    return {
        "status": "REJECT_CURRENT_STOCK_EAGLE_250_V2_CANDIDATE",
        "candidate_id": "ridge_v1_rank_v10_regime_exposure_v2",
        "gates_passed": 6,
        "gates_total": 11,
        "failed_gates": sorted(EXPECTED_V2_FAILED_GATES),
        "qualified_for_human_review": False,
        "candidate_frozen": False,
        "paper_trading_enabled": False,
        "automatic_promotion": False,
        "brokerage_orders": False,
    }


def valid_v2_regime_summary():
    return pd.DataFrame([
        {
            "market_state": "NEGATIVE_HIGH_VOL",
            "periods": 360,
            "mean_gross_exposure": 0.0,
            "mean_unscaled_ridge_return": 0.0104,
            "mean_v2_net_return": 0.0,
        },
        {
            "market_state": "NEGATIVE_LOW_VOL",
            "periods": 145,
            "mean_gross_exposure": 0.5,
            "mean_unscaled_ridge_return": 0.0076,
            "mean_v2_net_return": 0.0028,
        },
    ])


class StockEagle250V3Phase1Test(unittest.TestCase):
    def test_contract_is_one_fixed_trend_agnostic_candidate(self):
        contract = load_contract()

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertTrue(contract["created_before_v3_results"])
        self.assertEqual(
            contract["fixed_candidate"]["candidate_id"],
            V3_CANDIDATE,
        )
        self.assertFalse(
            contract["fixed_candidate"]["spy_trend_direction_used"]
        )
        self.assertFalse(contract["fixed_candidate"]["exposure_search"])
        self.assertEqual(
            contract["preregistered_development_gates"]["policy"],
            "reuse_v2_gates_without_relaxation",
        )
        self.assertEqual(
            pd.Timestamp(
                contract["data_boundaries"]["new_untouched_future_start_utc"]
            ),
            FUTURE_START_UTC,
        )

    def test_volatility_budget_fails_closed_then_scales_without_trend(self):
        timestamps = pd.date_range(
            "2024-01-02",
            periods=360,
            freq="B",
            tz="UTC",
        )
        returns = np.array(
            [0.004 if i % 2 == 0 else -0.004 for i in range(360)],
            dtype=float,
        )
        returns[-20:] = np.array(
            [0.02 if i % 2 == 0 else -0.02 for i in range(20)],
            dtype=float,
        )
        frame = volatility_budget_frame(pd.DataFrame({
            "timestamp_utc": timestamps,
            "spy_return_1d": returns,
        }))

        self.assertEqual(frame.iloc[0]["gross_exposure"], 0.0)
        ready = frame[
            frame["lagged_rolling_median_spy_volatility_252"].notna()
            & (frame["spy_realized_volatility_20"] > 0.0)
        ]
        self.assertFalse(ready.empty)
        self.assertTrue(ready["gross_exposure"].between(0.0, 1.0).all())
        self.assertTrue((ready["gross_exposure"] > 0.0).all())
        self.assertAlmostEqual(
            float(ready.iloc[0]["gross_exposure"]),
            1.0,
            places=10,
        )
        self.assertLess(float(frame.iloc[-1]["gross_exposure"]), 1.0)
        self.assertGreater(float(frame.iloc[-1]["gross_exposure"]), 0.0)

    def test_volatility_budget_rejects_guard_band_input(self):
        frame = pd.DataFrame({
            "timestamp_utc": [
                "2026-09-22T00:00:00+00:00",
                GUARD_BAND_START_UTC,
            ],
            "spy_return_1d": [0.01, -0.01],
        })
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            volatility_budget_frame(frame)

    def test_v2_rejection_and_zero_exposure_diagnostic_are_required(self):
        summary = validate_v2_evidence(
            valid_v2_manifest(),
            valid_v2_qualification(),
            valid_v2_regime_summary(),
        )
        self.assertEqual(summary["v2_gates_passed"], 6)
        self.assertGreater(
            summary["negative_high_vol_unscaled_ridge_return"],
            0.0,
        )
        self.assertEqual(summary["negative_high_vol_v2_exposure"], 0.0)

        bad = valid_v2_regime_summary()
        bad.loc[
            bad["market_state"] == "NEGATIVE_HIGH_VOL",
            "mean_unscaled_ridge_return",
        ] = -0.01
        with self.assertRaisesRegex(RuntimeError, "positive unscaled Ridge"):
            validate_v2_evidence(
                valid_v2_manifest(),
                valid_v2_qualification(),
                bad,
            )

    def test_v2_evidence_must_remain_pre_guard_and_rejected(self):
        manifest = valid_v2_manifest()
        manifest["guard_band_rows_read"] = 1
        with self.assertRaisesRegex(RuntimeError, "guard-band rows"):
            validate_v2_evidence(
                manifest,
                valid_v2_qualification(),
                valid_v2_regime_summary(),
            )

        qualification = valid_v2_qualification()
        qualification["status"] = "QUALIFIES_FOR_HUMAN_REVIEW"
        with self.assertRaisesRegex(RuntimeError, "not preserved as rejected"):
            validate_v2_evidence(
                valid_v2_manifest(),
                qualification,
                valid_v2_regime_summary(),
            )

    def test_manifest_has_no_v3_scoring_or_trading_authority(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload = build_manifest(contract, {
            "v2_status": "REJECT_CURRENT_STOCK_EAGLE_250_V2_CANDIDATE",
            "v2_gates_passed": 6,
            "v2_gates_total": 11,
            "v2_failed_gates": sorted(EXPECTED_V2_FAILED_GATES),
            "v2_worst_fold_maximum_drawdown": -0.186,
            "v2_median_fold_excess_vs_v1_ridge": -0.0645,
            "negative_high_vol_unscaled_ridge_return": 0.0104,
            "negative_high_vol_v2_exposure": 0.0,
        })
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["guard_band_rows_read"], 0)
        self.assertEqual(payload["future_rows_read"], 0)
        self.assertFalse(payload["v3_performance_calculated"])
        self.assertFalse(payload["safety"]["candidate_frozen"])
        self.assertFalse(payload["safety"]["paper_trading_enabled"])
        self.assertFalse(payload["safety"]["brokerage_orders"])


if __name__ == "__main__":
    unittest.main()
