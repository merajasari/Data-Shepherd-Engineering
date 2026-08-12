import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from ml.crypto_v1.validation import validate_bronze
from ml.crypto_v2.kraken_archive import import_archive


class CryptoV2KrakenArchiveTests(unittest.TestCase):
    def _write_archive(self, path: Path):
        btc = pd.DataFrame([
            [1470960000, 100.0, 110.0, 90.0, 105.0, 10.0, 3],
            [1471046400, 105.0, 112.0, 101.0, 108.0, 11.0, 4],
            # Preserve one missing calendar day on purpose.
            [1471219200, 108.0, 115.0, 106.0, 111.0, 12.0, 5],
        ])
        xrp = pd.DataFrame([
            [1470960000, 0.01, 0.02, 0.009, 0.015, 1000.0, 10],
            [1471046400, 0.015, 0.021, 0.014, 0.018, 1100.0, 11],
        ])
        with tempfile.TemporaryDirectory() as staging:
            staging = Path(staging)
            btc.to_csv(staging / "XBTUSD_1440.csv", index=False, header=False)
            xrp.to_csv(staging / "XRPUSD_1440.csv", index=False, header=False)
            # Must be ignored because only native daily USD files are imported.
            btc.to_csv(staging / "XBTUSD_60.csv", index=False, header=False)
            with zipfile.ZipFile(path, "w") as zf:
                zf.write(staging / "XBTUSD_1440.csv", "OHLCVT/XBTUSD_1440.csv")
                zf.write(staging / "XRPUSD_1440.csv", "OHLCVT/XRPUSD_1440.csv")
                zf.write(staging / "XBTUSD_60.csv", "OHLCVT/XBTUSD_60.csv")

    def test_import_writes_provider_separated_valid_bronze(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "Kraken_OHLCVT.zip"
            bronze = tmp / "bronze"
            self._write_archive(archive)
            manifest = import_archive(
                archive, "2016-08-12", "2016-08-16",
                products=["BTC-USD", "XRP-USD"], output_root=bronze,
            )
            self.assertEqual(manifest["provider"], "kraken_exchange")
            self.assertEqual(manifest["imported_asset_count"], 2)
            self.assertFalse(manifest["canonical_source_selected"])

            btc_path = bronze / "kraken_exchange" / "daily" / "BTC-USD" / "candles.csv"
            frame, report = validate_bronze(btc_path)
            self.assertEqual(len(frame), 3)
            self.assertEqual(report.missing_interval_count, 1)
            self.assertEqual(report.gap_count, 1)

            meta = json.loads(btc_path.with_name("metadata.json").read_text())
            self.assertEqual(meta["archive_pair"], "XBTUSD")
            self.assertEqual(meta["archive_interval_minutes"], 1440)
            self.assertIn("archive_sha256", meta)

    def test_missing_pair_is_reported_not_synthesized(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "Kraken_OHLCVT.zip"
            bronze = tmp / "bronze"
            self._write_archive(archive)
            manifest = import_archive(
                archive, "2016-08-12", "2016-08-16",
                products=["BTC-USD", "SUI-USD"], output_root=bronze,
            )
            self.assertEqual(manifest["imported_asset_count"], 1)
            self.assertEqual(manifest["unavailable_products"], ["SUI-USD"])
            self.assertFalse((bronze / "kraken_exchange" / "daily" / "SUI-USD").exists())

    def test_requested_half_open_range_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "Kraken_OHLCVT.zip"
            bronze = tmp / "bronze"
            self._write_archive(archive)
            import_archive(
                archive, "2016-08-13", "2016-08-15",
                products=["BTC-USD"], output_root=bronze,
            )
            p = bronze / "kraken_exchange" / "daily" / "BTC-USD" / "candles.csv"
            frame = pd.read_csv(p)
            self.assertEqual(len(frame), 1)
            self.assertTrue(frame.iloc[0]["timestamp_utc"].startswith("2016-08-13"))

    def test_non_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not.zip"
            path.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_archive(path, "2016-08-12", "2016-08-13", products=["BTC-USD"])


if __name__ == "__main__":
    unittest.main()
