import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml import run_v8_inference as module


class V8ProductionInferenceTests(unittest.TestCase):
    def market(self):
        ts = pd.Timestamp("2026-08-21T00:00:00Z")
        symbols = [f"S{i:03d}" for i in range(100)]
        frames = {
            symbol: pd.DataFrame(
                {"close": [100.0 + i]},
                index=pd.DatetimeIndex([ts]),
            )
            for i, symbol in enumerate(symbols)
        }
        frames["SPY"] = pd.DataFrame(
            {"close": [650.0]},
            index=pd.DatetimeIndex([ts]),
        )
        ranking = pd.DataFrame(
            {
                "symbol": symbols,
                "raw": [i / 100 for i in range(100)],
                "volatility_20d": [0.02] * 100,
                "beta_60": [1.0] * 100,
                "orthogonal_signal": [1.0 - i / 100 for i in range(100)],
            }
        )
        return ts, symbols, frames, ranking

    def test_publishes_exact_top10_without_holdout_or_orders(self):
        ts, symbols, frames, ranking = self.market()
        with patch.object(
            module,
            "_verify_freeze",
            return_value={"candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS"},
        ), patch.object(
            module,
            "_load_market",
            return_value=(symbols, frames, [ts], {ts: 0}),
        ), patch.object(
            module,
            "_rank_for_date",
            return_value=ranking,
        ):
            payload = module.build_v8_rankings()

        self.assertEqual(payload["research_version"], "v8")
        self.assertEqual(payload["candidate_count"], 100)
        self.assertEqual(payload["top_n"], 10)
        self.assertEqual(
            sum(row["selected_top10"] for row in payload["rankings"]),
            10,
        )
        self.assertFalse(payload["records_holdout_evidence"])
        self.assertFalse(payload["brokerage_orders"])
        self.assertEqual(payload["rankings"][0]["target_weight"], 0.10)
        self.assertEqual(payload["rankings"][10]["target_weight"], 0.0)

    def test_mixed_feature_sessions_fail_closed(self):
        ts, symbols, frames, ranking = self.market()
        frames[symbols[-1]].index = pd.DatetimeIndex(
            [pd.Timestamp("2026-08-20T00:00:00Z")]
        )
        with patch.object(
            module,
            "_verify_freeze",
            return_value={"candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS"},
        ), patch.object(
            module,
            "_load_market",
            return_value=(symbols, frames, [ts], {ts: 0}),
        ), patch.object(
            module,
            "_rank_for_date",
            return_value=ranking,
        ):
            with self.assertRaisesRegex(RuntimeError, "feature sessions are not aligned"):
                module.build_v8_rankings()

    def test_atomic_writer_round_trips_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "v8.json"
            payload = {"research_version": "v8", "rankings": [{"symbol": "AAPL"}]}
            module.write_v8_rankings(payload, output)
            self.assertIn('"research_version": "v8"', output.read_text())
            self.assertFalse(output.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
