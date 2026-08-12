import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v2.prepare_dataset import (
    REQUIRED_FEATURES,
    add_features_and_eligibility,
    add_targets,
    build_horizon_research_panel,
    load_canonical_history,
)


def make_history(days=100, products=("BTC-USD", "ETH-USD"), gap=None):
    rows = []
    dates = pd.date_range("2020-01-01", periods=days, freq="D", tz="UTC")
    for product_index, product in enumerate(products):
        for i, ts in enumerate(dates):
            if gap is not None and product == gap[0] and ts == pd.Timestamp(gap[1], tz="UTC"):
                continue
            base = 100.0 + product_index * 20.0 + i
            rows.append({
                "product_id": product,
                "timestamp_utc": ts,
                "open": base,
                "high": base * 1.01,
                "low": base * 0.99,
                "close": base,
                "volume": 20000.0,
                "source_provider": "coinbase_exchange" if i % 2 == 0 else "kraken_exchange",
                "source_granularity": "daily",
            })
    return pd.DataFrame(rows).sort_values(["product_id", "timestamp_utc"]).reset_index(drop=True)


class CryptoV2PrepareDatasetTests(unittest.TestCase):
    def test_load_retains_provenance_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canonical.parquet"
            frame = make_history(days=4)
            frame.to_parquet(path, index=False)
            loaded = load_canonical_history(path, completed_before_utc="2021-01-01")
            self.assertIn("source_provider", loaded.columns)
            self.assertIn("source_granularity", loaded.columns)
            self.assertEqual(len(loaded), len(frame))

            duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
            duplicate.to_parquet(path, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate product/timestamp"):
                load_canonical_history(path, completed_before_utc="2021-01-01")

    def test_trailing_features_do_not_bridge_gap(self):
        frame = make_history(days=100, gap=("ETH-USD", "2020-03-10"))
        frame["dollar_volume"] = frame["close"] * frame["volume"]
        frame["first_available_timestamp"] = frame.groupby("product_id")["timestamp_utc"].transform("min")
        featured = add_features_and_eligibility(frame)
        after_gap = featured[
            (featured["product_id"] == "ETH-USD")
            & (featured["timestamp_utc"] == pd.Timestamp("2020-03-11", tz="UTC"))
        ].iloc[0]
        self.assertTrue(pd.isna(after_gap["return_1d"]))
        self.assertFalse(bool(after_gap["has_required_trailing_windows"]))

    def test_exact_forward_target_requires_observed_endpoint(self):
        frame = make_history(days=100, gap=("ETH-USD", "2020-03-12"))
        frame["dollar_volume"] = frame["close"] * frame["volume"]
        frame["first_available_timestamp"] = frame.groupby("product_id")["timestamp_utc"].transform("min")
        featured = add_features_and_eligibility(frame)
        labeled = add_targets(featured)
        row = labeled[
            (labeled["product_id"] == "ETH-USD")
            & (labeled["timestamp_utc"] == pd.Timestamp("2020-03-11", tz="UTC"))
        ].iloc[0]
        self.assertTrue(pd.isna(row["forward_return_1d"]))
        self.assertTrue(pd.isna(row["forward_return_relative_to_btc_1d"]))

    def test_provider_provenance_is_not_a_required_feature(self):
        self.assertNotIn("source_provider", REQUIRED_FEATURES)
        self.assertNotIn("source_granularity", REQUIRED_FEATURES)

    def test_horizon_panel_preserves_provenance(self):
        frame = make_history(days=120)
        frame["dollar_volume"] = frame["close"] * frame["volume"]
        frame["first_available_timestamp"] = frame.groupby("product_id")["timestamp_utc"].transform("min")
        featured = add_features_and_eligibility(frame)
        labeled = add_targets(featured)
        panel = build_horizon_research_panel(labeled, 1, generated_at_utc=pd.Timestamp("2026-01-01", tz="UTC"))
        self.assertIn("source_provider", panel.columns)
        self.assertIn("source_granularity", panel.columns)
        self.assertTrue(set(panel["source_provider"]).issubset({"coinbase_exchange", "kraken_exchange"}))

    def test_btc_relative_feature_is_zero_for_btc_when_defined(self):
        frame = make_history(days=100)
        frame["dollar_volume"] = frame["close"] * frame["volume"]
        frame["first_available_timestamp"] = frame.groupby("product_id")["timestamp_utc"].transform("min")
        featured = add_features_and_eligibility(frame)
        btc = featured[(featured["product_id"] == "BTC-USD") & featured["btc_relative_return_30d"].notna()]
        self.assertGreater(len(btc), 0)
        self.assertTrue(np.allclose(btc["btc_relative_return_30d"], 0.0))


if __name__ == "__main__":
    unittest.main()
