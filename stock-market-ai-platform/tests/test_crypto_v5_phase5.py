import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from ml.crypto_v5.phase5 import _canonical_hash, append_event, score_snapshot


class _Model:
    def __init__(self, values):
        self.values = values

    def predict(self, frame):
        if np.isscalar(self.values):
            return np.repeat(float(self.values), len(frame))
        return np.asarray(self.values, dtype=float)


class CryptoV5Phase5Test(unittest.TestCase):
    def test_score_snapshot_is_paper_weight_decision_only(self):
        allocation = pd.DataFrame([{column: 0.1 for column in self._features()}])
        ranking = pd.DataFrame([
            {**{column: 0.1 for column in self._features()}, "product_id": product}
            for product in ("ETH-USD", "SOL-USD", "ADA-USD", "XRP-USD")
        ])
        models = {
            "allocation_btc": _Model(.01), "allocation_alt": _Model(.03),
            "allocation_cash": _Model(0), "ranking": _Model([4, 3, 2, 1]),
        }
        state = {"paper_equity": 100000, "weights": {"CASH": 1.0},
                 "selected_regime": "CASH", "last_regime_switch_utc": None}
        result = score_snapshot(allocation, ranking, models, state,
                                pd.Timestamp("2026-09-16", tz="UTC"))
        self.assertEqual(result["selected_regime"], "RISK_ON")
        self.assertEqual(len(result["top_ranked_assets"]), 3)
        self.assertAlmostEqual(sum(result["target_weights"].values()), 1.0)
        self.assertLessEqual(result["turnover"], .60)

    def test_append_event_creates_hash_chained_jsonl_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            event = {"decision_id": "one", "previous_event_hash": None,
                     "paper_only": True, "brokerage_orders": False}
            event_hash = append_event(path, event)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["event_hash"], event_hash)
            self.assertEqual(event_hash, _canonical_hash(event))
            self.assertFalse(stored["brokerage_orders"])

    @staticmethod
    def _features():
        from ml.crypto_v5.phase2 import FEATURES
        return FEATURES


if __name__ == "__main__":
    unittest.main()
