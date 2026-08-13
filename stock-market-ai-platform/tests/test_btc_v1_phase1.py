import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.btc_v1.phase1 import (
    PRODUCT_ID,
    add_features,
    add_targets,
    build_research_dataset,
    load_btc_history,
)


class TestBtcV1Phase1(unittest.TestCase):
    def _frame(self, periods=140, gap_index=None):
        ts = pd.date_range("2025-01-01", periods=periods, freq="D", tz="UTC")
        if gap_index is not None:
            ts = ts.delete(gap_index)
        n = len(ts)
        return pd.DataFrame({
            "product_id": [PRODUCT_ID] * n,
            "timestamp_utc": ts,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000.0 + i for i in range(n)],
            "source_provider": ["coinbase_exchange"] * n,
            "source_granularity": ["daily"] * n,
        })

    def test_load_selects_only_btc(self):
        frame = self._frame(10)
        other = frame.copy()
        other["product_id"] = "ETH-USD"
        combined = pd.concat([frame, other], ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "canonical.parquet"
            combined.to_parquet(p, index=False)
            out = load_btc_history(p, completed_before_utc="2025-02-01")
        self.assertEqual(set(out["product_id"]), {PRODUCT_ID})
        self.assertEqual(len(out), 10)

    def test_gap_breaks_exact_and_rolling_features(self):
        frame = self._frame(140, gap_index=60)
        out = add_features(frame)
        after_gap = out[out["timestamp_utc"] == pd.Timestamp("2025-03-03", tz="UTC")].iloc[0]
        self.assertTrue(pd.isna(after_gap["return_1d"]))
        self.assertTrue(pd.isna(after_gap["close_to_sma_30"]))

    def test_targets_require_exact_endpoint(self):
        frame = self._frame(20, gap_index=10)
        out = add_targets(frame)
        row = out[out["timestamp_utc"] == pd.Timestamp("2025-01-10", tz="UTC")].iloc[0]
        self.assertTrue(pd.isna(row["forward_return_1d"]))
        self.assertTrue(pd.isna(row["target_positive_1d"]))

    def test_research_dataset_keeps_only_feature_ready_rows(self):
        labeled = add_targets(add_features(self._frame(140)))
        out = build_research_dataset(labeled)
        self.assertFalse(out.empty)
        self.assertTrue(out["has_required_features"].all())
        self.assertEqual(out["timestamp_utc"].min(), pd.Timestamp("2025-04-01", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
