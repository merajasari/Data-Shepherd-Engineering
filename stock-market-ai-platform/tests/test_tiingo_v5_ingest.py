import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


INGESTION_ROOT = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

spec = importlib.util.spec_from_file_location(
    "tiingo_v5_ingest",
    INGESTION_ROOT / "tiingo_v5_ingest.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TiingoV5IngestTests(unittest.TestCase):
    def test_requested_symbols_deduplicates_and_normalizes(self):
        out = module.requested_symbols(["aapl", "MSFT", "AAPL", "spy"])
        self.assertEqual(out, ["AAPL", "MSFT", "SPY"])

    def test_requested_symbols_rejects_outside_universe(self):
        with self.assertRaises(ValueError):
            module.requested_symbols(["NOT_A_REAL_V5_SYMBOL"])

    def test_build_resume_plan_skips_existing_and_caps_requests(self):
        symbols = ["AAPL", "MSFT", "NVDA", "SPY"]
        with patch.object(module, "has_local_bronze", side_effect=lambda s: s in {"AAPL", "SPY"}):
            skipped, batch, deferred = module.build_resume_plan(
                symbols,
                force=False,
                max_requests=1,
            )
        self.assertEqual(skipped, ["AAPL", "SPY"])
        self.assertEqual(batch, ["MSFT"])
        self.assertEqual(deferred, ["NVDA"])

    def test_force_redownloads_existing_symbols(self):
        symbols = ["AAPL", "MSFT"]
        with patch.object(module, "has_local_bronze", return_value=True):
            skipped, batch, deferred = module.build_resume_plan(
                symbols,
                force=True,
                max_requests=5,
            )
        self.assertEqual(skipped, [])
        self.assertEqual(batch, symbols)
        self.assertEqual(deferred, [])

    def test_max_requests_must_be_positive(self):
        with self.assertRaises(ValueError):
            module.build_resume_plan(["AAPL"], max_requests=0)

    def test_has_local_bronze_requires_nonempty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(module, "BRONZE_ROOT", root):
                self.assertFalse(module.has_local_bronze("AAPL"))
                path = root / "AAPL" / "AAPL_prices.csv"
                path.parent.mkdir(parents=True)
                path.write_text("")
                self.assertFalse(module.has_local_bronze("AAPL"))
                path.write_text("symbol,timestamp\nAAPL,1\n")
                self.assertTrue(module.has_local_bronze("AAPL"))


if __name__ == "__main__":
    unittest.main()
