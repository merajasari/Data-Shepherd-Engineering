"""Safety and accounting invariants for XRP V1 Phase 7 future evaluation.

These tests use temporary journals and mocked market-data readers. They never
read from or write to the live Phase 7 event journal and do not modify frozen
Phase 6 artifacts.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import ml.crypto_xrp_v1.phase7 as phase7


MODEL_SHA = "a" * 64
POLICY_SHA = "b" * 64


def _manifest():
    return {
        "model": {"artifact_sha256": MODEL_SHA},
        "execution_policy": {"policy_id": phase7.POLICY_ID},
        "brokerage_orders": False,
        "future_holdout_start_utc": phase7.HOLDOUT.isoformat(),
    }


def _decision(ts: pd.Timestamp, *, state="BTC", switched=False):
    return {
        "event_id": f"decision:{ts.isoformat()}",
        "event_type": "DECISION",
        "research_version": "crypto_xrp_v1",
        "phase": 7,
        "recorded_at_utc": ts.isoformat(),
        "decision_timestamp_utc": ts.isoformat(),
        "predicted_btc_relative_return_4h": 0.001,
        "state_before": "BTC",
        "state_after": state,
        "state_since_utc": ts.isoformat(),
        "state_switch": switched,
        "missed_decision_intervals_total": 0,
        "model_sha256": MODEL_SHA,
        "policy_id": phase7.POLICY_ID,
        "policy_sha256": POLICY_SHA,
        "brokerage_orders": False,
    }


class Phase7InvariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            patch.object(phase7, "OUTPUT_ROOT", self.root),
            patch.object(phase7, "EVENT_JOURNAL_PATH", self.root / "events.jsonl"),
            patch.object(phase7, "EVALUATION_STATE_PATH", self.root / "state.json"),
            patch.object(phase7, "EVALUATION_STATUS_PATH", self.root / "status.json"),
            patch.object(phase7, "SUMMARY_PATH", self.root / "summary.json"),
            patch.object(phase7, "EVALUATOR_MANIFEST_PATH", self.root / "manifest.json"),
            patch.object(phase7, "LOCK_PATH", self.root / "lock"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_pre_holdout_event_append_is_impossible(self):
        event = _decision(phase7.HOLDOUT - pd.Timedelta(hours=4))
        with self.assertRaisesRegex(RuntimeError, "pre-holdout"):
            phase7._append_event(event)
        self.assertFalse(phase7.EVENT_JOURNAL_PATH.exists())

    def test_duplicate_event_id_is_rejected_on_load(self):
        ts = phase7.HOLDOUT
        event = _decision(ts)
        phase7.EVENT_JOURNAL_PATH.write_text(
            json.dumps(event) + "\n" + json.dumps(event) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "Duplicate event_id"):
            phase7._load_events()

    def test_first_future_decision_resets_to_btc(self):
        state = phase7._default_eval_state(_manifest(), POLICY_SHA)
        updated, diag = phase7._advance_eval_state(state, phase7.HOLDOUT, score=0.01)
        self.assertTrue(diag["state_reset"])
        self.assertEqual(diag["reset_reason"], "future_holdout_boundary_initialization")
        self.assertEqual(updated["current_state"], phase7.INITIAL_STATE)
        self.assertFalse(diag["state_switch"])

    def test_missed_intervals_reset_without_backfill(self):
        first = phase7.HOLDOUT
        state = phase7._default_eval_state(_manifest(), POLICY_SHA)
        state.update(
            {
                "current_state": "XRP",
                "state_since_utc": first.isoformat(),
                "last_decision_timestamp_utc": first.isoformat(),
                "missed_decision_intervals_total": 0,
            }
        )
        # Skip two 4-hour decisions and arrive 12 hours later.
        later = first + 3 * phase7.EXPECTED_STEP
        updated, diag = phase7._advance_eval_state(state, later, score=0.02)
        self.assertTrue(diag["state_reset"])
        self.assertEqual(diag["reset_reason"], "missed_future_decision_interval")
        self.assertEqual(diag["missed_intervals_this_decision"], 2)
        self.assertEqual(updated["missed_decision_intervals_total"], 2)
        self.assertEqual(updated["current_state"], phase7.INITIAL_STATE)
        self.assertEqual(updated["last_decision_timestamp_utc"], later.isoformat())

    def test_continuity_break_forces_neutral_reset(self):
        first = phase7.HOLDOUT
        state = phase7._default_eval_state(_manifest(), POLICY_SHA)
        state.update(
            {
                "current_state": "XRP",
                "state_since_utc": first.isoformat(),
                "last_decision_timestamp_utc": first.isoformat(),
            }
        )
        later = first + phase7.EXPECTED_STEP
        with patch.object(phase7, "_xrp_continuous_between", return_value=False):
            updated, diag = phase7._advance_eval_state(state, later, score=0.02)
        self.assertTrue(diag["state_reset"])
        self.assertEqual(diag["reset_reason"], "xrp_continuity_break")
        self.assertEqual(updated["current_state"], phase7.INITIAL_STATE)
        self.assertFalse(diag["state_switch"])

    def test_restart_state_rebuilds_from_append_only_decision_journal(self):
        ts = phase7.HOLDOUT + phase7.EXPECTED_STEP
        decision = _decision(ts, state="XRP", switched=True)
        decisions = {ts.isoformat(): decision}
        stale = phase7._default_eval_state(_manifest(), POLICY_SHA)
        stale["last_decision_timestamp_utc"] = phase7.HOLDOUT.isoformat()
        phase7.EVALUATION_STATE_PATH.write_text(json.dumps(stale), encoding="utf-8")

        rebuilt = phase7._load_eval_state(_manifest(), POLICY_SHA, decisions)
        self.assertEqual(rebuilt["last_decision_timestamp_utc"], ts.isoformat())
        self.assertEqual(rebuilt["current_state"], "XRP")
        self.assertEqual(rebuilt["state_since_utc"], ts.isoformat())

    def test_exact_four_hour_window_requires_every_15m_candle(self):
        start = phase7.HOLDOUT
        end = start + phase7.EXPECTED_STEP
        timestamps = pd.date_range(start, end, freq="15min", tz="UTC")
        complete = pd.DataFrame({"timestamp_utc": timestamps, "close": 1.0})
        with patch.object(phase7, "_read_recent", return_value=complete):
            self.assertTrue(phase7._continuous_product_window("XRP-USD", start, end))

        missing = complete.drop(index=5).reset_index(drop=True)
        with patch.object(phase7, "_read_recent", return_value=missing):
            self.assertFalse(phase7._continuous_product_window("XRP-USD", start, end))

    def test_realization_uses_exact_plus_four_hour_endpoint_and_cost_only_on_switch(self):
        ts = phase7.HOLDOUT
        decision = _decision(ts, state="XRP", switched=True)
        events = [decision]
        endpoint = ts + phase7.EXPECTED_STEP

        def fake_close(product, when):
            prices = {
                (phase7.XRP, ts): 100.0,
                (phase7.XRP, endpoint): 110.0,
                (phase7.BTC, ts): 200.0,
                (phase7.BTC, endpoint): 204.0,
            }
            return prices[(product, when)]

        with patch.object(phase7, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(phase7, "_continuous_product_window", return_value=True), \
             patch.object(phase7, "_close_at", side_effect=fake_close):
            appended = phase7._realize_pending(events, _manifest(), POLICY_SHA)

        self.assertEqual(len(appended), 1)
        event = appended[0]
        self.assertEqual(event["target_endpoint_utc"], endpoint.isoformat())
        self.assertEqual(event["realization_status"], "VALID")
        self.assertAlmostEqual(event["xrp_forward_return_4h"], 0.10)
        self.assertAlmostEqual(event["btc_forward_return_4h"], 0.02)
        self.assertEqual(event["switch_cost_0bps"], 0.0)
        self.assertAlmostEqual(event["switch_cost_5bps"], 0.0005)
        self.assertAlmostEqual(event["net_return_5bps"], 0.10 - 0.0005)
        self.assertAlmostEqual(event["equity_5bps"], 1.0 + 0.10 - 0.0005)

    def test_no_switch_means_zero_cost_in_every_scenario(self):
        ts = phase7.HOLDOUT
        decision = _decision(ts, state="BTC", switched=False)
        endpoint = ts + phase7.EXPECTED_STEP

        def fake_close(product, when):
            prices = {
                (phase7.XRP, ts): 100.0,
                (phase7.XRP, endpoint): 101.0,
                (phase7.BTC, ts): 200.0,
                (phase7.BTC, endpoint): 202.0,
            }
            return prices[(product, when)]

        with patch.object(phase7, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(phase7, "_continuous_product_window", return_value=True), \
             patch.object(phase7, "_close_at", side_effect=fake_close):
            event = phase7._realize_pending([decision], _manifest(), POLICY_SHA)[0]

        for bps in phase7.COST_BPS_SCENARIOS:
            self.assertEqual(event[f"switch_cost_{bps}bps"], 0.0)
            self.assertAlmostEqual(event[f"net_return_{bps}bps"], 0.01)

    def test_invalid_data_gap_is_recorded_once_and_never_scored(self):
        ts = phase7.HOLDOUT
        decision = _decision(ts, state="XRP", switched=True)
        endpoint = ts + phase7.EXPECTED_STEP

        with patch.object(phase7, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(phase7, "_continuous_product_window", side_effect=[False, True]):
            appended = phase7._realize_pending([decision], _manifest(), POLICY_SHA)

        self.assertEqual(len(appended), 1)
        invalid = appended[0]
        self.assertEqual(invalid["realization_status"], "INVALID_DATA_GAP")
        self.assertNotIn("equity_5bps", invalid)
        self.assertNotIn("gross_state_return_4h", invalid)

        # Reloading the journal makes that decision permanently realized; a
        # restart cannot append a second realization for the same timestamp.
        reloaded = phase7._load_events()
        with patch.object(phase7, "_latest_available_timestamp", return_value=endpoint):
            second = phase7._realize_pending(reloaded, _manifest(), POLICY_SHA)
        self.assertEqual(second, [])
        self.assertEqual(len(phase7._load_events()), 1)

    def test_summary_counts_valid_invalid_pending_and_switches(self):
        t0 = phase7.HOLDOUT
        t1 = t0 + phase7.EXPECTED_STEP
        t2 = t1 + phase7.EXPECTED_STEP
        decisions = [
            _decision(t0, state="BTC", switched=False),
            _decision(t1, state="XRP", switched=True),
            _decision(t2, state="XRP", switched=False),
        ]
        valid = {
            "event_id": f"realization:{t0.isoformat()}",
            "event_type": "REALIZATION",
            "research_version": "crypto_xrp_v1",
            "phase": 7,
            "decision_timestamp_utc": t0.isoformat(),
            "realization_status": "VALID",
            "always_xrp_equity": 1.01,
            "always_btc_equity": 1.02,
            "equity_0bps": 1.02,
            "equity_5bps": 1.02,
            "equity_10bps": 1.02,
            "equity_20bps": 1.02,
        }
        invalid = {
            "event_id": f"realization:{t1.isoformat()}",
            "event_type": "REALIZATION",
            "research_version": "crypto_xrp_v1",
            "phase": 7,
            "decision_timestamp_utc": t1.isoformat(),
            "realization_status": "INVALID_DATA_GAP",
        }
        summary = phase7._build_summary(decisions + [valid, invalid], _manifest(), POLICY_SHA)
        self.assertEqual(summary["decision_count"], 3)
        self.assertEqual(summary["valid_realization_count"], 1)
        self.assertEqual(summary["invalid_realization_count"], 1)
        self.assertEqual(summary["pending_realization_count"], 1)
        self.assertEqual(summary["state_switch_count"], 1)
        self.assertAlmostEqual(summary["equity_5bps"], 1.02)
        self.assertFalse(summary["brokerage_orders"])


if __name__ == "__main__":
    unittest.main()
