"""Invariant/regression tests for frozen Crypto 15m V2 forward evaluation.

All filesystem writes are redirected to a temporary directory. These tests must
never touch the live Phase 5 model, state, journal, shadow snapshot, or service
status files.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import ml.crypto_15m_v2.forward_service as fs


JOURNAL_COLUMNS = [
    "decision_timestamp_utc",
    "raw_predicted_label",
    "executed_label_before",
    "executed_label_after",
    "pending_candidate_label",
    "pending_candidate_count",
    "prob_btc",
    "prob_alt",
    "prob_cash",
    "btc_realized_return_1h",
    "alt_realized_return_1h",
    "gross_selected_return_1h",
    "sleeve_switch",
    "cost_bps_assumption",
    "transaction_cost",
    "net_selected_return_1h",
    "equity",
    "realized_through_utc",
    "status",
]


def base_state(**overrides):
    state = {
        "current_executed_label": "BTC",
        "pending_candidate_label": None,
        "pending_candidate_count": 0,
        "last_forward_decision_timestamp_utc": None,
        "last_raw_prediction": None,
        "last_probabilities": None,
        "current_equity": 1.0,
        "last_realized_timestamp_utc": None,
        "brokerage_orders": False,
    }
    state.update(overrides)
    return state


def probabilities(label: str) -> dict[str, float]:
    p = {"BTC": 0.1, "ALT": 0.1, "CASH": 0.1}
    p[label] = 0.8
    return p


class SharedV2ForwardInvariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.phase5 = self.root / "phase5"
        self.phase5.mkdir(parents=True)
        self.journal = self.phase5 / "forward_journal.csv"
        self.state_path = self.phase5 / "forward_state.json"
        self.shadow = self.phase5 / "shadow_latest.json"
        self.status = self.phase5 / "forward_service_status.json"
        self.lock = self.phase5 / "forward_service.lock"
        pd.DataFrame(columns=JOURNAL_COLUMNS).to_csv(self.journal, index=False)
        self.state_path.write_text(json.dumps(base_state()) + "\n", encoding="utf-8")
        self.path_patch = patch.multiple(
            fs,
            PHASE5_ROOT=self.phase5,
            JOURNAL_PATH=self.journal,
            STATE_PATH=self.state_path,
            SHADOW_PATH=self.shadow,
            SERVICE_STATUS_PATH=self.status,
            LOCK_PATH=self.lock,
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.tmp.cleanup()

    def read_journal(self) -> pd.DataFrame:
        return pd.read_csv(self.journal)

    def test_stale_lock_is_recovered_without_touching_live_owner(self):
        self.lock.write_text("424242", encoding="utf-8")
        with patch.object(fs, "_process_is_alive", return_value=False):
            recovered = fs._acquire_lock()
        self.assertTrue(recovered)
        self.assertEqual(self.lock.read_text(encoding="utf-8"), str(os.getpid()))
        fs._release_lock()
        self.assertFalse(self.lock.exists())

    def test_live_lock_is_preserved_and_second_service_exits(self):
        self.lock.write_text("424242", encoding="utf-8")
        with patch.object(fs, "_process_is_alive", return_value=True):
            with self.assertRaises(SystemExit):
                fs._acquire_lock()
        self.assertEqual(self.lock.read_text(encoding="utf-8"), "424242")

    def test_startup_heartbeat_is_published_before_inference(self):
        payload = fs._publish_starting_status(stale_lock_recovered=True)
        persisted = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(persisted, payload)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["mode"], "STARTING")
        self.assertTrue(payload["stale_lock_recovered"])
        self.assertFalse(payload["brokerage_orders"])

    def test_confirm2_requires_two_consecutive_noncurrent_predictions(self):
        state = base_state()
        before, after, state = fs._apply_confirm2(state, "ALT")
        self.assertEqual((before, after), ("BTC", "BTC"))
        self.assertEqual(state["pending_candidate_label"], "ALT")
        self.assertEqual(state["pending_candidate_count"], 1)

        before, after, state = fs._apply_confirm2(state, "ALT")
        self.assertEqual((before, after), ("BTC", "ALT"))
        self.assertEqual(state["current_executed_label"], "ALT")
        self.assertIsNone(state["pending_candidate_label"])
        self.assertEqual(state["pending_candidate_count"], 0)

    def test_confirm2_resets_pending_when_raw_returns_to_current_state(self):
        state = base_state(pending_candidate_label="ALT", pending_candidate_count=1)
        before, after, state = fs._apply_confirm2(state, "BTC")
        self.assertEqual((before, after), ("BTC", "BTC"))
        self.assertIsNone(state["pending_candidate_label"])
        self.assertEqual(state["pending_candidate_count"], 0)

    def test_duplicate_or_older_decision_is_idempotent(self):
        ts = pd.Timestamp("2026-09-01T00:00:00Z")
        state = base_state()
        state = fs._append_forward_decision(ts, "ALT", probabilities("ALT"), state)
        first = self.read_journal()
        self.assertEqual(len(first), 1)

        state = fs._append_forward_decision(ts, "ALT", probabilities("ALT"), state)
        state = fs._append_forward_decision(ts - pd.Timedelta(hours=1), "CASH", probabilities("CASH"), state)
        second = self.read_journal()
        self.assertEqual(len(second), 1)
        self.assertEqual(second.iloc[0]["decision_timestamp_utc"], ts.isoformat())

    def test_first_and_second_confirm2_rows_switch_only_on_second_hour(self):
        state = base_state()
        t0 = pd.Timestamp("2026-09-01T00:00:00Z")
        state = fs._append_forward_decision(t0, "ALT", probabilities("ALT"), state)
        state = fs._append_forward_decision(t0 + pd.Timedelta(hours=1), "ALT", probabilities("ALT"), state)
        journal = self.read_journal()
        self.assertEqual(list(journal["executed_label_after"]), ["BTC", "ALT"])
        self.assertEqual(list(journal["sleeve_switch"].astype(int)), [0, 1])

    def test_hourly_realized_uses_exact_plus_one_hour_endpoint(self):
        decision = pd.Timestamp("2026-09-01T00:00:00Z")
        endpoint = decision + pd.Timedelta(hours=1)
        btc = pd.DataFrame({
            "timestamp_utc": [decision, endpoint],
            "close": [100.0, 101.0],
            "product_id": [fs.BTC, fs.BTC],
        })
        alt = pd.DataFrame({
            "timestamp_utc": [decision, endpoint],
            "close": [50.0, 51.0],
            "product_id": ["ALT", "ALT"],
        })
        with patch.object(fs, "ALT_PRODUCTS", ("A", "B")), \
             patch.object(fs, "MIN_ALT_ASSETS", 2), \
             patch.object(fs, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(fs, "_read_recent", side_effect=lambda product, _end: btc.copy() if product == fs.BTC else alt.assign(product_id=product)):
            realized = fs._hourly_realized(decision)
        self.assertIsNotNone(realized)
        btc_r, alt_r = realized
        self.assertAlmostEqual(btc_r, 0.01)
        self.assertAlmostEqual(alt_r, 0.02)

    def test_hourly_realized_never_fills_missing_exact_endpoint(self):
        decision = pd.Timestamp("2026-09-01T00:00:00Z")
        endpoint = decision + pd.Timedelta(hours=1)
        btc_missing_endpoint = pd.DataFrame({
            "timestamp_utc": [decision, decision + pd.Timedelta(minutes=45)],
            "close": [100.0, 101.0],
            "product_id": [fs.BTC, fs.BTC],
        })
        with patch.object(fs, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(fs, "_read_recent", return_value=btc_missing_endpoint):
            self.assertIsNone(fs._hourly_realized(decision))

    def test_hourly_realized_requires_frozen_minimum_alt_coverage(self):
        decision = pd.Timestamp("2026-09-01T00:00:00Z")
        endpoint = decision + pd.Timedelta(hours=1)
        btc = pd.DataFrame({"timestamp_utc": [decision, endpoint], "close": [100.0, 101.0], "product_id": [fs.BTC, fs.BTC]})
        alt = pd.DataFrame({"timestamp_utc": [decision, endpoint], "close": [50.0, 51.0], "product_id": ["A", "A"]})
        with patch.object(fs, "ALT_PRODUCTS", ("A", "B", "C")), \
             patch.object(fs, "MIN_ALT_ASSETS", 3), \
             patch.object(fs, "_latest_available_timestamp", return_value=endpoint), \
             patch.object(fs, "_read_recent", side_effect=lambda product, _end: btc if product == fs.BTC else (alt if product in {"A", "B"} else (_ for _ in ()).throw(RuntimeError("missing")))):
            self.assertIsNone(fs._hourly_realized(decision))

    def test_finalize_applies_5bps_only_to_actual_switch(self):
        t0 = pd.Timestamp("2026-09-01T00:00:00Z")
        rows = [
            {
                "decision_timestamp_utc": t0.isoformat(), "raw_predicted_label": "BTC",
                "executed_label_before": "BTC", "executed_label_after": "BTC",
                "pending_candidate_label": None, "pending_candidate_count": 0,
                "prob_btc": .8, "prob_alt": .1, "prob_cash": .1,
                "btc_realized_return_1h": np.nan, "alt_realized_return_1h": np.nan,
                "gross_selected_return_1h": np.nan, "sleeve_switch": 0,
                "cost_bps_assumption": fs.COST_BPS, "transaction_cost": np.nan,
                "net_selected_return_1h": np.nan, "equity": np.nan,
                "realized_through_utc": None, "status": "PENDING_REALIZATION",
            },
            {
                "decision_timestamp_utc": (t0 + pd.Timedelta(hours=1)).isoformat(), "raw_predicted_label": "ALT",
                "executed_label_before": "BTC", "executed_label_after": "ALT",
                "pending_candidate_label": None, "pending_candidate_count": 0,
                "prob_btc": .1, "prob_alt": .8, "prob_cash": .1,
                "btc_realized_return_1h": np.nan, "alt_realized_return_1h": np.nan,
                "gross_selected_return_1h": np.nan, "sleeve_switch": 1,
                "cost_bps_assumption": fs.COST_BPS, "transaction_cost": np.nan,
                "net_selected_return_1h": np.nan, "equity": np.nan,
                "realized_through_utc": None, "status": "PENDING_REALIZATION",
            },
        ]
        pd.DataFrame(rows, columns=JOURNAL_COLUMNS).to_csv(self.journal, index=False)
        state = base_state()
        with patch.object(fs, "_hourly_realized", return_value=(0.01, 0.02)):
            changed = fs._finalize_pending_rows(state)
        self.assertEqual(changed, 2)
        journal = self.read_journal()
        self.assertAlmostEqual(float(journal.iloc[0]["transaction_cost"]), 0.0)
        self.assertAlmostEqual(float(journal.iloc[1]["transaction_cost"]), 0.0005)
        self.assertAlmostEqual(float(journal.iloc[0]["net_selected_return_1h"]), 0.01)
        expected_second = (1.0 + 0.02) * (1.0 - 0.0005) - 1.0
        self.assertAlmostEqual(float(journal.iloc[1]["net_selected_return_1h"]), expected_second)

    def test_finalize_is_idempotent_after_row_becomes_realized(self):
        ts = pd.Timestamp("2026-09-01T00:00:00Z")
        state = fs._append_forward_decision(ts, "BTC", probabilities("BTC"), base_state())
        with patch.object(fs, "_hourly_realized", return_value=(0.01, 0.02)):
            self.assertEqual(fs._finalize_pending_rows(state), 1)
            snapshot = self.journal.read_bytes()
            self.assertEqual(fs._finalize_pending_rows(state), 0)
        self.assertEqual(snapshot, self.journal.read_bytes())

    def test_shadow_run_does_not_append_forward_journal_or_mutate_execution_state(self):
        before_journal = self.journal.read_bytes()
        state = base_state(current_executed_label="ALT", pending_candidate_label="CASH", pending_candidate_count=1)
        self.state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        decision = fs.HOLDOUT - pd.Timedelta(hours=1)
        fake_manifest = {"model": {"artifact_sha256": "abc"}, "execution_policy": {"policy_id": "confirm_2", "confirmation_hours": 2}}
        with patch.object(fs, "_load_contract", return_value=(fake_manifest, ["x"], object(), state.copy())), \
             patch.object(fs, "_finalize_pending_rows", return_value=0), \
             patch.object(fs, "_latest_hourly_decision_timestamp", return_value=decision), \
             patch.object(fs, "_build_hourly_feature_row", return_value=(pd.DataFrame({"x": [1.0]}), {"alt_asset_count": 20, "missing_decision_candle_alts": [], "feature_ineligible_alts": []})), \
             patch.object(fs, "_predict", return_value=("CASH", probabilities("CASH"))):
            result = fs.run_once()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["model_sha256_verified"])
        self.assertEqual(result["mode"], "SHADOW")
        self.assertEqual(result["action"], "shadow_snapshot")
        self.assertEqual(before_journal, self.journal.read_bytes())
        after_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(after_state["current_executed_label"], "ALT")
        self.assertEqual(after_state["pending_candidate_label"], "CASH")
        self.assertEqual(after_state["pending_candidate_count"], 1)

    def test_forward_gap_is_detected_and_never_backfilled(self):
        t0 = fs.HOLDOUT
        state = fs._append_forward_decision(t0, "BTC", probabilities("BTC"), base_state())
        self.state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        latest = t0 + pd.Timedelta(hours=2)
        fake_manifest = {"model": {"artifact_sha256": "abc"}, "execution_policy": {"policy_id": "confirm_2", "confirmation_hours": 2}}
        with patch.object(fs, "_load_contract", return_value=(fake_manifest, ["x"], object(), state.copy())), \
             patch.object(fs, "_finalize_pending_rows", return_value=0), \
             patch.object(fs, "_latest_hourly_decision_timestamp", return_value=latest), \
             patch.object(fs, "_build_hourly_feature_row", return_value=(pd.DataFrame({"x": [1.0]}), {"alt_asset_count": 20, "missing_decision_candle_alts": [], "feature_ineligible_alts": []})), \
             patch.object(fs, "_predict", return_value=("ALT", probabilities("ALT"))):
            result = fs.run_once()
        self.assertEqual(result["mode"], "FORWARD")
        self.assertEqual(result["action"], "gap_detected_no_backfill")
        journal = self.read_journal()
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal.iloc[0]["decision_timestamp_utc"], t0.isoformat())

    def test_same_forward_hour_is_processed_at_most_once_across_restarts(self):
        t0 = fs.HOLDOUT
        state = fs._append_forward_decision(t0, "ALT", probabilities("ALT"), base_state())
        self.state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        fake_manifest = {"model": {"artifact_sha256": "abc"}, "execution_policy": {"policy_id": "confirm_2", "confirmation_hours": 2}}
        for _ in range(2):
            current_state = json.loads(self.state_path.read_text(encoding="utf-8"))
            with patch.object(fs, "_load_contract", return_value=(fake_manifest, ["x"], object(), current_state)), \
                 patch.object(fs, "_finalize_pending_rows", return_value=0), \
                 patch.object(fs, "_latest_hourly_decision_timestamp", return_value=t0), \
                 patch.object(fs, "_build_hourly_feature_row", return_value=(pd.DataFrame({"x": [1.0]}), {"alt_asset_count": 20, "missing_decision_candle_alts": [], "feature_ineligible_alts": []})), \
                 patch.object(fs, "_predict", return_value=("ALT", probabilities("ALT"))):
                result = fs.run_once()
            self.assertEqual(result["action"], "already_processed")
        self.assertEqual(len(self.read_journal()), 1)


if __name__ == "__main__":
    unittest.main()
