import sys
import unittest
from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from stock_universe_250 import (  # noqa: E402
    STOCK_250_SYMBOLS,
    STOCK_250_SYMBOLS_BY_SECTOR,
    get_stock_250_data_symbols,
)
from v5_symbols import V5_BENCHMARK_SYMBOL, V5_SYMBOLS  # noqa: E402


class StockUniverse250Test(unittest.TestCase):
    def test_has_exactly_250_unique_candidates_plus_spy(self):
        self.assertEqual(len(STOCK_250_SYMBOLS), 250)
        self.assertEqual(len(set(STOCK_250_SYMBOLS)), 250)
        self.assertEqual(len(get_stock_250_data_symbols()), 251)
        self.assertNotIn(V5_BENCHMARK_SYMBOL, STOCK_250_SYMBOLS)
        self.assertEqual(get_stock_250_data_symbols()[-1], V5_BENCHMARK_SYMBOL)

    def test_preserves_every_frozen_v5_candidate(self):
        self.assertTrue(set(V5_SYMBOLS).issubset(STOCK_250_SYMBOLS))
        self.assertEqual(set(STOCK_250_SYMBOLS_BY_SECTOR), {
            "Communication Services", "Consumer Discretionary",
            "Consumer Staples", "Energy", "Financials", "Health Care",
            "Industrials", "Information Technology", "Materials",
            "Real Estate", "Utilities",
        })


if __name__ == "__main__":
    unittest.main()
