import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webapp.services import crypto_dashboard_service as dashboard


class CryptoForwardDashboardTest(unittest.TestCase):
    def test_shared_v4_translates_post_boundary_equity_to_100k_paper_account(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "forward.csv"
            journal.write_text(
                "decision_timestamp_utc,raw_predicted_label,executed_label_before,executed_label_after,"
                "pending_candidate_label,pending_candidate_count,prob_btc,prob_alt,prob_cash,"
                "btc_realized_return_1h,alt_realized_return_1h,gross_selected_return_1h,"
                "sleeve_switch,cost_bps_assumption,transaction_cost,net_selected_return_1h,"
                "equity,realized_through_utc,status\n"
                "2026-09-23T07:00:00Z,ALT,CASH,ALT,,0,.2,.6,.2,.01,.02,.02,1,5,.0005,.01949,"
                "1.01949,2026-09-23T08:00:00Z,REALIZED\n",
                encoding="utf-8",
            )
            with patch.multiple(
                dashboard,
                V2_JOURNAL_PATH=journal,
                V2_ARCHIVED_JOURNAL_PATH=Path(directory) / "archived-v2.csv",
                V3_ARCHIVED_JOURNAL_PATH=Path(directory) / "archived-v3.csv",
            ):
                payload = dashboard._shared_v2_forward_performance("2026-09-23T09:00:00Z")
            self.assertEqual(payload["name"], "Shared Crypto V2 Clean Forward V4")
            self.assertEqual(payload["holdout_start_utc"], "2026-09-23T07:00:00+00:00")
            self.assertEqual(
                payload["archived_v3"]["classification"],
                "PRESERVED_INTERRUPTED_NO_BACKFILL",
            )
            self.assertEqual(payload["starting_equity_dollars"], 100_000.0)
            self.assertAlmostEqual(payload["candidate_equity_dollars"], 101_949.0)
            self.assertEqual(payload["realized_count"], 1)
            self.assertEqual(len(payload["chart_points"]), 2)
            self.assertEqual(len(payload["probability_points"]), 1)


    def test_gap_error_preserves_heartbeat_observability(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "status.json"
            status_path.write_text("{}", encoding="utf-8")
            payload = {
                "status": "ok",
                "generated_at_utc": "2099-01-01T00:00:00+00:00",
            }
            health = dashboard._service_health(
                "Shared Crypto V4",
                status_path,
                payload,
                90,
                "gap_detected_no_backfill",
            )
            self.assertEqual(health["status"], "ERROR")
            self.assertEqual(health["detail"], "gap_detected_no_backfill")
            self.assertEqual(
                health["heartbeat_at_utc"],
                "2099-01-01T00:00:00+00:00",
            )
            self.assertEqual(health["age_minutes"], 0.0)


    def test_v5_dashboard_reads_decisions_and_realizations_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            state = root / "state.json"
            status = root / "status.json"
            journal = root / "events.jsonl"
            manifest.write_text(json.dumps({
                "preregistered_start_utc": "2026-09-23T07:00:00+00:00",
                "first_eligible_decision_utc": "2026-09-24T00:00:00+00:00",
            }))
            state.write_text(json.dumps({
                "paper_equity": 102_500.0, "selected_regime": "RISK_ON",
                "weights": {"BTC-USD": 0.3, "ETH-USD": 0.6, "CASH": 0.1},
            }))
            status.write_text(json.dumps({
                "status": "ok", "mode": "CLEAN_FORWARD", "contract_verified": True,
                "brokerage_orders": False,
            }))
            events = [
                {"event_type": "DECISION", "decision_timestamp_utc": "2026-09-24T00:00:00Z",
                 "selected_regime": "RISK_ON", "model_id": "ridge",
                 "top_ranked_assets": [{"product_id": "ETH-USD", "predicted_score": .03}],
                 "target_weights": {"ETH-USD": .6, "BTC-USD": .3, "CASH": .1}},
                {"event_type": "REALIZATION", "decision_timestamp_utc": "2026-09-24T00:00:00Z",
                 "realized_through_utc": "2026-09-27T00:00:00Z", "selected_regime": "RISK_ON",
                 "gross_return": .03, "net_return": .025, "paper_equity_after": 102_500.0},
            ]
            journal.write_text("\n".join(json.dumps(row) for row in events) + "\n")
            with patch.multiple(
                dashboard, V5_MANIFEST_PATH=manifest, V5_STATE_PATH=state,
                V5_STATUS_PATH=status, V5_JOURNAL_PATH=journal,
            ):
                payload = dashboard._v5_forward_performance()
            self.assertEqual(payload["name"], "Crypto V5 Clean Paper V2")
            self.assertEqual(payload["archived_lane_name"], "Crypto V5 Clean Paper V1")
            self.assertFalse(payload["archived_lane_mutated"])
            self.assertEqual(payload["decision_count"], 1)
            self.assertEqual(payload["realized_count"], 1)
            self.assertEqual(payload["current_equity_dollars"], 102_500.0)
            self.assertTrue(payload["contract_verified"])
            self.assertFalse(payload["brokerage_orders"])


if __name__ == "__main__":
    unittest.main()
