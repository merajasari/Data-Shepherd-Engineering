import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
sys.path.insert(0, str(DATA_INGESTION))

spec = importlib.util.spec_from_file_location(
    "tiingo_v5_incremental",
    DATA_INGESTION / "tiingo_v5_incremental.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get_daily_prices(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        return self.frames[symbol].copy()


class TiingoV5IncrementalTests(unittest.TestCase):
    def test_merge_prefers_incoming_duplicate_timestamp(self):
        existing = pd.DataFrame(
            [
                {"symbol": "AAA", "timestamp": 1, "close": 10.0},
                {"symbol": "AAA", "timestamp": 2, "close": 20.0},
            ]
        )
        incoming = pd.DataFrame(
            [
                {"symbol": "AAA", "timestamp": 2, "close": 21.0},
                {"symbol": "AAA", "timestamp": 3, "close": 30.0},
            ]
        )

        out = module.merge_price_frames(existing, incoming)

        self.assertEqual(out["timestamp"].tolist(), [1, 2, 3])
        self.assertEqual(out.loc[out["timestamp"] == 2, "close"].iloc[0], 21.0)

    def test_incremental_refresh_respects_total_request_budget_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_root = module.BRONZE_ROOT
            original_state = module.STATE_PATH
            original_get_symbols = module.get_v5_data_symbols
            try:
                module.BRONZE_ROOT = Path(tmp) / "bronze"
                module.STATE_PATH = Path(tmp) / "state.json"
                module.get_v5_data_symbols = lambda: ["AAA", "BBB", "SPY"]

                old_ts = 1_700_000_000_000
                new_ts = 1_700_086_400_000

                for symbol in ["AAA", "BBB", "SPY"]:
                    path = module.bronze_file(symbol)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    pd.DataFrame(
                        [{
                            "symbol": symbol,
                            "timestamp": old_ts,
                            "open": 1.0,
                            "high": 1.0,
                            "low": 1.0,
                            "close": 1.0,
                            "volume": 1,
                            "vwap": None,
                        }]
                    ).to_csv(path, index=False)

                frames = {
                    symbol: pd.DataFrame(
                        [{
                            "symbol": symbol,
                            "timestamp": new_ts,
                            "open": 2.0,
                            "high": 2.0,
                            "low": 2.0,
                            "close": 2.0,
                            "volume": 2,
                            "vwap": None,
                        }]
                    )
                    for symbol in ["AAA", "BBB", "SPY"]
                }
                client = FakeClient(frames)

                first = module.run_incremental_refresh(
                    max_requests=2,
                    today=date(2026, 8, 13),
                    client=client,
                )
                self.assertEqual(first["requests_used"], 2)
                self.assertFalse(first["complete"])
                self.assertEqual(len(first["remaining_symbols"]), 1)

                second = module.run_incremental_refresh(
                    max_requests=2,
                    today=date(2026, 8, 13),
                    client=client,
                )
                self.assertTrue(second["complete"])
                self.assertEqual(second["remaining_symbols"], [])
                self.assertEqual(module.latest_timestamp_ms("AAA"), new_ts)
                self.assertEqual(module.latest_timestamp_ms("BBB"), new_ts)
                self.assertEqual(module.latest_timestamp_ms("SPY"), new_ts)
            finally:
                module.BRONZE_ROOT = original_root
                module.STATE_PATH = original_state
                module.get_v5_data_symbols = original_get_symbols


if __name__ == "__main__":
    unittest.main()
