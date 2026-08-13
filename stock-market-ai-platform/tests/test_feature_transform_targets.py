import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


DATA_INGESTION = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

from feature_transform import transform_to_features


class FeatureTransformTargetTests(unittest.TestCase):
    def _gold_frame(self, rows: int = 30) -> pd.DataFrame:
        close = pd.Series(np.linspace(100.0, 130.0, rows))
        daily_return = close.pct_change().fillna(0.0)

        return pd.DataFrame(
            {
                "close": close,
                "open": close * 0.995,
                "high": close * 1.01,
                "low": close * 0.99,
                "volume": np.linspace(1_000_000, 1_500_000, rows),
                "volume_sma_20": np.full(rows, 1_200_000.0),
                "daily_return": daily_return,
                "sma_7": close * 0.99,
                "sma_20": close * 0.98,
                "sma_50": close * 0.97,
                "sma_200": close * 0.96,
            }
        )

    def test_last_five_forward_labels_remain_missing(self):
        out = transform_to_features(self._gold_frame())

        self.assertEqual(out["forward_return_5d"].isna().sum(), 5)
        self.assertEqual(out["target_up_5d"].isna().sum(), 5)
        self.assertEqual(out["target_trade_5d"].isna().sum(), 5)
        self.assertTrue(out["target_up_5d"].tail(5).isna().all())
        self.assertTrue(out["target_trade_5d"].tail(5).isna().all())

    def test_known_forward_labels_match_thresholds(self):
        out = transform_to_features(self._gold_frame())
        known = out["forward_return_5d"].notna()

        expected_up = (out.loc[known, "forward_return_5d"] > 0).astype("int8")
        expected_trade = (
            out.loc[known, "forward_return_5d"] > 0.01
        ).astype("int8")

        pd.testing.assert_series_equal(
            out.loc[known, "target_up_5d"].astype("int8"),
            expected_up,
            check_names=False,
        )
        pd.testing.assert_series_equal(
            out.loc[known, "target_trade_5d"].astype("int8"),
            expected_trade,
            check_names=False,
        )

    def test_binary_targets_use_nullable_integer_dtype(self):
        out = transform_to_features(self._gold_frame())

        self.assertEqual(str(out["target_up_5d"].dtype), "Int8")
        self.assertEqual(str(out["target_trade_5d"].dtype), "Int8")


if __name__ == "__main__":
    unittest.main()
