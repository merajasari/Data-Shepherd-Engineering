import json
import unittest

import pandas as pd

from ml.stock_eagle_250.phase2 import (
    CONTRACT_PATH,
    RAW_FEATURE_COLUMNS,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
    add_cross_sectional_ranks,
    add_executable_forward_return,
    generate_folds,
)


class StockEagle250Phase2Test(unittest.TestCase):
    def test_contract_preregisters_learned_candidates_and_future_boundary(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(contract["display_name"], "StockEagle250")
        self.assertEqual(contract["universe"]["candidate_count"], 250)
        self.assertEqual(contract["universe"]["benchmark_symbol"], "SPY")
        self.assertFalse(contract["universe"]["benchmark_is_investable"])
        self.assertEqual(
            contract["target"]["name"],
            "forward_relative_return_5d",
        )
        self.assertIn("next completed session open", contract["target"]["definition"])
        self.assertEqual(
            contract["untouched_future_holdout"]["start_utc"],
            "2026-09-23T00:00:00+00:00",
        )
        self.assertFalse(
            contract["untouched_future_holdout"][
                "development_may_read_decisions_at_or_after_boundary"
            ]
        )
        candidates = contract["development"]["model_candidates"]
        self.assertEqual(
            [candidate["candidate_id"] for candidate in candidates],
            ["ridge_fixed_v1", "hgb_fixed_v1"],
        )
        self.assertFalse(contract["authority"]["paper_trading_enabled"])
        self.assertFalse(contract["authority"]["brokerage_orders"])
        for lane in ("v5", "v8", "v10", "v14", "v15"):
            self.assertFalse(contract["isolation"][f"modify_{lane}"])

    def test_target_matches_next_open_to_fifth_close(self):
        timestamps = pd.date_range(
            "2026-01-02",
            periods=8,
            freq="B",
            tz="UTC",
        )
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "open": [100, 101, 102, 103, 104, 105, 106, 107],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5, 110, 111, 112],
        })

        result = add_executable_forward_return(frame, "stock")

        self.assertEqual(result.loc[0, "stock_entry_timestamp_utc"], timestamps[1])
        self.assertEqual(result.loc[0, "stock_target_endpoint_utc"], timestamps[5])
        self.assertAlmostEqual(
            result.loc[0, "forward_stock_return"],
            110 / 101 - 1,
        )
        self.assertTrue(pd.isna(result.loc[3, "forward_stock_return"]))

    def test_cross_sectional_ranks_use_only_same_timestamp_rows(self):
        first = pd.Timestamp("2026-01-05", tz="UTC")
        second = pd.Timestamp("2026-01-06", tz="UTC")
        panel = pd.DataFrame({
            "timestamp_utc": [first, first, second, second],
            **{
                column: [1.0, 3.0, 10.0, 20.0]
                for column in RAW_FEATURE_COLUMNS
            },
        })

        ranked = add_cross_sectional_ranks(panel)

        for column in RANK_FEATURE_COLUMNS:
            self.assertEqual(
                ranked[column].tolist(),
                [0.5, 1.0, 0.5, 1.0],
            )

    def test_walk_forward_folds_purge_training_and_validation_endpoints(self):
        timestamps = pd.date_range(
            "2019-01-02",
            "2020-12-31",
            freq="B",
            tz="UTC",
        )
        records = []
        for symbol in ("AAA", "BBB"):
            for index in range(len(timestamps) - 5):
                records.append({
                    "symbol": symbol,
                    "timestamp_utc": timestamps[index],
                    "target_endpoint_utc_5d": timestamps[index + 5],
                    TARGET_COLUMN: 0.01,
                    "model_eligible": True,
                })
        panel = pd.DataFrame(records).sort_values(
            ["timestamp_utc", "symbol"]
        ).reset_index(drop=True)

        folds = generate_folds(
            panel,
            validation_start=pd.Timestamp("2020-01-01", tz="UTC"),
            holdout_start=pd.Timestamp("2021-01-01", tz="UTC"),
            validation_months=6,
        )

        self.assertEqual(len(folds), 2)
        for fold in folds:
            self.assertLess(
                pd.Timestamp(fold["max_train_target_endpoint_utc"]),
                pd.Timestamp(fold["validation_start_utc"]),
            )
            self.assertLess(
                pd.Timestamp(fold["max_validation_target_endpoint_utc"]),
                pd.Timestamp(fold["validation_end_exclusive_utc"]),
            )
            self.assertEqual(fold["train_symbols"], 2)
            self.assertEqual(fold["validation_symbols"], 2)


if __name__ == "__main__":
    unittest.main()
