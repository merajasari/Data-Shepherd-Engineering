import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from ml.crypto_v5 import forward_service as service


class CryptoV5ForwardServiceTest(unittest.TestCase):
    def _paths(self, root):
        return patch.multiple(
            service,
            ARCHIVED_ROOT=root.parent / "clean_forward_v1",
            ROOT=root,
            STATE_PATH=root / "paper_state.json",
            STATUS_PATH=root / "forward_service_status.json",
            JOURNAL_PATH=root / "paper_events.jsonl",
            MANIFEST_PATH=root / "clean_lane_manifest.json",
            LOCK_PATH=root / "forward_service.lock",
        )

    def test_clean_lane_initializes_only_before_observation_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clean"
            with self._paths(root):
                manifest, state = service._ensure_lane(
                    pd.Timestamp("2026-09-21T12:00:00Z"), "contract-hash")
                self.assertEqual(manifest["lane_id"], service.LANE_ID)
                self.assertEqual(manifest["supersedes_missed_lane_id"], service.ARCHIVED_LANE_ID)
                self.assertEqual(
                    manifest["preregistered_observation_start_utc"],
                    service.OBSERVATION_START_UTC.isoformat(),
                )
                self.assertEqual(
                    manifest["first_eligible_decision_utc"],
                    service.FIRST_ELIGIBLE_DECISION_UTC.isoformat(),
                )
                self.assertEqual(manifest["starting_paper_equity"], 100_000.0)
                self.assertEqual(state["paper_equity"], 100_000.0)
                self.assertFalse(manifest["brokerage_orders"])
                self.assertFalse(manifest["archived_lane_mutated"])
                self.assertTrue((root / "paper_events.jsonl").exists())
                self.assertFalse((root.parent / "clean_forward_v1").exists())

    def test_late_initialization_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clean"
            with self._paths(root):
                with self.assertRaisesRegex(RuntimeError, "missed"):
                    service._ensure_lane(service.OBSERVATION_START_UTC, "contract-hash")

    def test_realization_updates_paper_equity_and_appends_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "clean"
            root.mkdir(parents=True)
            state = {
                "paper_equity": 100_000.0,
                "last_event_hash": "decision-hash",
                "realization_count": 0,
                "pending_decisions": [{
                    "decision_id": "crypto_v5_clean:2026-09-23",
                    "decision_timestamp_utc": "2026-09-23T00:00:00+00:00",
                    "selected_regime": "RISK_ON",
                    "target_weights": {"BTC-USD": 0.5, "ETH-USD": 0.5},
                    "estimated_transaction_cost": 250.0,
                    "decision_event_hash": "decision-hash",
                }],
            }
            history = pd.DataFrame([
                {"product_id": "BTC-USD", "timestamp_utc": pd.Timestamp("2026-09-23T00:00:00Z"), "close": 100.0},
                {"product_id": "BTC-USD", "timestamp_utc": pd.Timestamp("2026-09-26T00:00:00Z"), "close": 110.0},
                {"product_id": "ETH-USD", "timestamp_utc": pd.Timestamp("2026-09-23T00:00:00Z"), "close": 100.0},
                {"product_id": "ETH-USD", "timestamp_utc": pd.Timestamp("2026-09-26T00:00:00Z"), "close": 90.0},
            ])
            with self._paths(root):
                count = service._finalize_pending(
                    history, pd.Timestamp("2026-09-26T00:00:00Z"), state)
                self.assertEqual(count, 1)
                self.assertAlmostEqual(state["paper_equity"], 99_750.0)
                self.assertEqual(state["pending_decisions"], [])
                event = json.loads((root / "paper_events.jsonl").read_text())
                self.assertEqual(event["event_type"], "REALIZATION")
                self.assertEqual(event["previous_event_hash"], "decision-hash")
                self.assertFalse(event["brokerage_orders"])

    def test_decision_clock_is_three_days_and_never_backfilled(self):
        state = {"last_decision_utc": None}
        self.assertEqual(service._next_required_decision(state), service.FIRST_ELIGIBLE_DECISION_UTC)
        state["last_decision_utc"] = service.FIRST_ELIGIBLE_DECISION_UTC.isoformat()
        self.assertEqual(
            service._next_required_decision(state),
            service.FIRST_ELIGIBLE_DECISION_UTC + pd.Timedelta(days=3),
        )


if __name__ == "__main__":
    unittest.main()
