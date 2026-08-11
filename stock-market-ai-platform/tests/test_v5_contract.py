"""Static contract tests for the isolated V5 research foundation."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))

from symbols import SYMBOLS as V4_SYMBOLS  # noqa: E402
from v5_symbols import (  # noqa: E402
    V5_BENCHMARK_SYMBOL,
    V5_SYMBOLS,
    V5_SYMBOLS_BY_SECTOR,
    get_v5_data_symbols,
)
from ml.v5.config import (  # noqa: E402
    CORE_ALLOCATION,
    FORWARD_HORIZONS,
    POSITION_ALLOCATION,
    STRATEGY_ALLOCATION,
    TOP_COUNT,
)


class V5UniverseContractTests(unittest.TestCase):
    def test_candidate_universe_has_exactly_100_unique_equities(self):
        self.assertEqual(len(V5_SYMBOLS), 100)
        self.assertEqual(len(set(V5_SYMBOLS)), 100)

    def test_spy_is_benchmark_not_candidate(self):
        self.assertEqual(V5_BENCHMARK_SYMBOL, "SPY")
        self.assertNotIn(V5_BENCHMARK_SYMBOL, V5_SYMBOLS)
        self.assertEqual(len(get_v5_data_symbols()), 101)

    def test_universe_has_broad_sector_coverage(self):
        self.assertGreaterEqual(len(V5_SYMBOLS_BY_SECTOR), 10)
        self.assertTrue(all(V5_SYMBOLS_BY_SECTOR.values()))

    def test_v4_universe_remains_the_original_26(self):
        self.assertEqual(len(V4_SYMBOLS), 26)
        self.assertEqual(
            V4_SYMBOLS,
            [
                "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
                "TSLA", "AVGO", "AMD", "ORCL", "CRM", "JPM", "BAC",
                "V", "MA", "WMT", "COST", "HD", "JNJ", "UNH", "LLY",
                "XOM", "CVX", "CAT", "NFLX", "DIS",
            ],
        )


class V5ResearchContractTests(unittest.TestCase):
    def test_horizons_and_initial_portfolio_structure(self):
        self.assertEqual(FORWARD_HORIZONS, (5, 10, 20))
        self.assertEqual(TOP_COUNT, 5)
        self.assertAlmostEqual(CORE_ALLOCATION, 0.60)
        self.assertAlmostEqual(STRATEGY_ALLOCATION, 0.40)
        self.assertAlmostEqual(POSITION_ALLOCATION, 0.08)
        self.assertAlmostEqual(
            CORE_ALLOCATION + TOP_COUNT * POSITION_ALLOCATION,
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
