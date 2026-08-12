import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ml.crypto_v2.canonical_history import build_canonical_history, run_canonical_history


class CryptoV2CanonicalHistoryTests(unittest.TestCase):
    def write_source(self, root, provider, product, rows):
        folder = Path(root) / provider / "daily" / product
        folder.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(rows)
        frame.insert(0, "granularity", "daily")
        frame.insert(0, "provider", provider)
        frame.insert(0, "product_id", product)
        frame.to_csv(folder / "candles.csv", index=False)
        timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
        metadata = {
            "product_id": product,
            "provider": provider,
            "granularity": "daily",
            "requested_start_utc": timestamps.min().isoformat(),
            "requested_end_utc_exclusive": (timestamps.max() + pd.Timedelta(days=1)).isoformat(),
            "first_available_utc": timestamps.min().isoformat(),
            "last_available_utc": timestamps.max().isoformat(),
            "row_count": len(frame),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    @staticmethod
    def candle(ts, close):
        close = float(close)
        return {
            "timestamp_utc": pd.Timestamp(ts, tz="UTC").isoformat(),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 10.0,
        }

    def test_coinbase_wins_on_overlap(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "coinbase_exchange", "BTC-USD", [
                self.candle("2020-01-01", 100),
                self.candle("2020-01-02", 101),
            ])
            self.write_source(root, "kraken_exchange", "BTC-USD", [
                self.candle("2020-01-01", 200),
                self.candle("2020-01-02", 201),
            ])
            canonical, _, _ = build_canonical_history(root)
            self.assertEqual(len(canonical), 2)
            self.assertTrue((canonical["source_provider"] == "coinbase_exchange").all())
            self.assertEqual(canonical["close"].tolist(), [100.0, 101.0])

    def test_kraken_extends_and_fills_missing_coinbase_dates(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "coinbase_exchange", "BTC-USD", [
                self.candle("2020-01-02", 101),
                self.candle("2020-01-04", 103),
            ])
            self.write_source(root, "kraken_exchange", "BTC-USD", [
                self.candle("2020-01-01", 90),
                self.candle("2020-01-02", 91),
                self.candle("2020-01-03", 92),
            ])
            canonical, _, _ = build_canonical_history(root)
            self.assertEqual(len(canonical), 4)
            providers = canonical.set_index("timestamp_utc")["source_provider"]
            self.assertEqual(providers.loc[pd.Timestamp("2020-01-01", tz="UTC")], "kraken_exchange")
            self.assertEqual(providers.loc[pd.Timestamp("2020-01-02", tz="UTC")], "coinbase_exchange")
            self.assertEqual(providers.loc[pd.Timestamp("2020-01-03", tz="UTC")], "kraken_exchange")
            self.assertEqual(providers.loc[pd.Timestamp("2020-01-04", tz="UTC")], "coinbase_exchange")

    def test_provider_values_are_not_averaged(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "coinbase_exchange", "BTC-USD", [self.candle("2020-01-01", 100)])
            self.write_source(root, "kraken_exchange", "BTC-USD", [self.candle("2020-01-01", 200)])
            canonical, _, _ = build_canonical_history(root)
            self.assertEqual(float(canonical.iloc[0]["close"]), 100.0)
            self.assertNotEqual(float(canonical.iloc[0]["close"]), 150.0)

    def test_custom_priority_is_deterministic(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "coinbase_exchange", "BTC-USD", [self.candle("2020-01-01", 100)])
            self.write_source(root, "kraken_exchange", "BTC-USD", [self.candle("2020-01-01", 200)])
            canonical, _, _ = build_canonical_history(
                root, provider_priority=("kraken_exchange", "coinbase_exchange")
            )
            self.assertEqual(canonical.iloc[0]["source_provider"], "kraken_exchange")
            self.assertEqual(float(canonical.iloc[0]["close"]), 200.0)

    def test_duplicate_priority_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                build_canonical_history(
                    root, provider_priority=("coinbase_exchange", "coinbase_exchange")
                )

    def test_run_writes_outputs_and_preserves_bronze(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as output:
            self.write_source(root, "coinbase_exchange", "BTC-USD", [
                self.candle("2020-01-01", 100),
                self.candle("2020-01-02", 101),
            ])
            self.write_source(root, "kraken_exchange", "BTC-USD", [
                self.candle("2019-12-31", 90),
                self.candle("2020-01-01", 99),
            ])
            coinbase_path = Path(root) / "coinbase_exchange" / "daily" / "BTC-USD" / "candles.csv"
            before = coinbase_path.read_bytes()
            manifest, canonical, provenance = run_canonical_history(root, output)
            after = coinbase_path.read_bytes()

            self.assertEqual(before, after)
            self.assertEqual(manifest["stage"], "canonical_history_construction")
            self.assertFalse(manifest["selection_uses_performance"])
            self.assertFalse(manifest["provider_values_averaged"])
            self.assertFalse(manifest["synthetic_rows_created"])
            self.assertEqual(len(canonical), 3)
            self.assertEqual(int(provenance["selected_row_count"].sum()), 3)
            self.assertTrue((Path(output) / "canonical_history.parquet").exists())
            self.assertTrue((Path(output) / "canonical_provenance.csv").exists())
            self.assertTrue((Path(output) / "canonical_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
