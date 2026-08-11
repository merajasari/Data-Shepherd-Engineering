"""Static and pagination contracts for isolated Crypto V1."""

import unittest
from datetime import datetime, timedelta, timezone

from ml.crypto_v1.config import (
    BENCHMARK_PRODUCT, CRYPTO_UNIVERSE, FORWARD_HORIZONS_DAYS,
    TOP_COUNTS, ALLOW_LEVERAGE,
)
from ml.crypto_v1.providers.coinbase import CoinbaseExchangeProvider


class FakeCoinbase(CoinbaseExchangeProvider):
    def __init__(self):
        super().__init__(pause_seconds=0)
        self.calls = []

    def _request_json(self, path, params):
        self.calls.append((path, params))
        start = datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(params["end"].replace("Z", "+00:00"))
        rows = []
        cursor = start
        while cursor <= end:  # exercise boundary filtering/deduplication
            rows.append([int(cursor.timestamp()), 1, 3, 2, 2.5, 10])
            cursor += timedelta(days=1)
        return list(reversed(rows))


class CryptoV1ContractTests(unittest.TestCase):
    def test_universe_and_benchmark(self):
        self.assertGreaterEqual(len(CRYPTO_UNIVERSE), 20)
        self.assertLessEqual(len(CRYPTO_UNIVERSE), 30)
        self.assertEqual(len(CRYPTO_UNIVERSE), len(set(CRYPTO_UNIVERSE)))
        self.assertIn("BTC-USD", CRYPTO_UNIVERSE)
        self.assertIn("ETH-USD", CRYPTO_UNIVERSE)
        self.assertEqual(BENCHMARK_PRODUCT, "BTC-USD")
        self.assertTrue(all(pair.endswith("-USD") for pair in CRYPTO_UNIVERSE))

    def test_research_contract(self):
        self.assertEqual(FORWARD_HORIZONS_DAYS, (1, 3, 7))
        self.assertEqual(TOP_COUNTS, (3, 5))
        self.assertFalse(ALLOW_LEVERAGE)

    def test_daily_pagination_is_sorted_unique_and_end_exclusive(self):
        provider = FakeCoinbase()
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=650)
        candles = provider.get_candles("BTC-USD", start, end, "daily")
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(candles), 650)
        self.assertEqual(candles[0].timestamp_utc, start)
        self.assertEqual(candles[-1].timestamp_utc, end - timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
