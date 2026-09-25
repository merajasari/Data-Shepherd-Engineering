import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webapp.services import stock_eagle_autonomous_ml_prospective_service as service


CANDIDATES = (
    "autonomous_ml_v1",
    "autonomous_ml_v2",
    "autonomous_ml_v3",
)


def contract():
    return {
        "prospective_start_utc":
            "2026-10-01T00:00:00+00:00",
        "fixed_source": {
            "development_panel_sha256": "panel-sha",
            "training_rows": 561490,
            "training_decision_end_utc":
                "2026-09-15T00:00:00+00:00",
            "training_target_endpoint_max_utc":
                "2026-09-22T00:00:00+00:00",
            "sealed_guard_band_start_utc":
                "2026-09-23T00:00:00+00:00",
            "sealed_guard_band_end_exclusive_utc":
                "2026-10-01T00:00:00+00:00",
        },
        "formal_review": {
            "minimum_completed_cohorts_per_candidate":
                60,
            "minimum_complete_five_sleeve_blocks":
                12,
        },
        "fixed_snapshots": [
            {
                "candidate_id":
                    "autonomous_ml_v1",
                "snapshot_sha256": "v1-sha",
                "learned_component_count": 3,
                "meta_oos_training_sessions": 2037,
                "training_cutoff_utc":
                    "2026-09-22T00:00:00+00:00",
                "allocation_policy":
                    "learned_active_top10_probability_with_residual_cash",
            },
            {
                "candidate_id":
                    "autonomous_ml_v2",
                "snapshot_sha256": "v2-sha",
                "learned_component_count": 4,
                "meta_oos_training_sessions": 2037,
                "training_cutoff_utc":
                    "2026-09-22T00:00:00+00:00",
                "allocation_policy":
                    "tail_aware_learned_active_top10_probability_with_residual_cash",
            },
            {
                "candidate_id":
                    "autonomous_ml_v3",
                "snapshot_sha256": "v3-sha",
                "learned_component_count": 4,
                "meta_oos_training_sessions": 2037,
                "training_cutoff_utc":
                    "2026-09-22T00:00:00+00:00",
                "allocation_policy":
                    "tail_aware_benchmark_relative_active_probability_with_residual_spy",
            },
        ],
    }


def phase2_manifest():
    return {
        "snapshots": [
            {
                "candidate_id":
                    candidate_id,
                "snapshot_sha256":
                    f"{candidate_id}-sha",
            }
            for candidate_id in CANDIDATES
        ]
    }


def status():
    return {
        "status":
            "WAITING_FOR_PROSPECTIVE_BOUNDARY",
        "checked_at_utc":
            "2026-09-25T05:34:56+00:00",
        "decision_batches": 0,
        "entry_batches": 0,
        "exit_batches": 0,
        "completed_cohorts_per_candidate": 0,
        "complete_five_sleeve_blocks": 0,
        "formal_review_ready": False,
        "formal_review_status":
            "COLLECTING_UNSEEN_EVIDENCE",
        "contract_sha256": "contract-sha",
        "candidate_metrics": {
            candidate_id: {
                "normalized_equity": 100000.0,
                "total_net_return": 0.0,
                "matched_spy_return": 0.0,
                "excess_vs_spy": 0.0,
                "maximum_drawdown": 0.0,
                "stress_20bps_total_net_return":
                    0.0,
                "positive_excess_vs_spy_cohort_fraction":
                    None,
                "mean_active_weight": None,
                "completed_cohorts": 0,
            }
            for candidate_id in CANDIDATES
        },
    }


class StockEagleAutonomousMLProspectiveDashboardTest(
    unittest.TestCase
):
    def _paths(self, root):
        return {
            "STATUS_PATH": root / "status.json",
            "JOURNAL_PATH": root / "journal.jsonl",
            "CONTRACT_PATH": root / "phase3_contract.json",
            "PHASE2_MANIFEST_PATH": root / "phase2_manifest.json",
        }

    def _write_base(self, root):
        paths = self._paths(root)
        paths["STATUS_PATH"].write_text(
            json.dumps(status()),
            encoding="utf-8",
        )
        paths["CONTRACT_PATH"].write_text(
            json.dumps(contract()),
            encoding="utf-8",
        )
        paths["PHASE2_MANIFEST_PATH"].write_text(
            json.dumps(phase2_manifest()),
            encoding="utf-8",
        )
        return paths

    def _patch_paths(self, paths):
        return patch.multiple(
            service,
            STATUS_PATH=paths["STATUS_PATH"],
            JOURNAL_PATH=paths["JOURNAL_PATH"],
            CONTRACT_PATH=paths["CONTRACT_PATH"],
            PHASE2_MANIFEST_PATH=
                paths["PHASE2_MANIFEST_PATH"],
        )

    def test_waiting_payload_is_read_only_and_exposes_three_fixed_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self._write_base(
                Path(temp)
            )
            with self._patch_paths(paths):
                service._cache.update({
                    "signature": None,
                    "expires_at": 0.0,
                    "payload": None,
                })
                payload = (
                    service
                    .get_stock_eagle_autonomous_ml_prospective_dashboard()
                )

            self.assertEqual(
                payload["state"],
                "WAITING_FOR_PROSPECTIVE_BOUNDARY",
            )
            self.assertEqual(
                tuple(
                    row["candidate_id"]
                    for row in payload["candidates"]
                ),
                CANDIDATES,
            )
            self.assertEqual(
                payload["training_rows"],
                561490,
            )
            self.assertEqual(
                payload[
                    "formal_review_minimum_completed_cohorts"
                ],
                60,
            )
            self.assertEqual(
                payload[
                    "formal_review_minimum_complete_blocks"
                ],
                12,
            )
            self.assertFalse(
                payload["retraining_enabled"]
            )
            self.assertFalse(
                payload[
                    "automatic_model_promotion"
                ]
            )
            self.assertFalse(
                payload["brokerage_orders"]
            )
            self.assertFalse(
                payload["live_execution_enabled"]
            )
            self.assertFalse(
                payload["dashboard_invoked_runner"]
            )

    def test_decision_and_exit_are_rendered_on_same_candidate_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = self._write_base(root)
            events = [
                {
                    "event_type":
                        "DECISION_BATCH",
                    "decision_timestamp_utc":
                        "2026-10-01T00:00:00+00:00",
                    "cohort_offset": 0,
                    "candidates": {
                        candidate_id: {
                            "active_weight": 0.6,
                            "spy_weight":
                                0.4
                                if candidate_id
                                == "autonomous_ml_v3"
                                else 0.0,
                            "cash_fraction":
                                0.0
                                if candidate_id
                                == "autonomous_ml_v3"
                                else 0.4,
                            "selected_symbols":
                                ["AAA", "BBB"],
                        }
                        for candidate_id
                        in CANDIDATES
                    },
                },
                {
                    "event_type":
                        "EXIT_BATCH",
                    "decision_timestamp_utc":
                        "2026-10-01T00:00:00+00:00",
                    "exit_timestamp_utc":
                        "2026-10-08T00:00:00+00:00",
                    "cohort_offset": 0,
                    "candidates": {
                        candidate_id: {
                            "primary_net_return": 0.01,
                            "stress_20bps_net_return":
                                0.009,
                            "spy_return": 0.005,
                            "excess_vs_spy": 0.005,
                        }
                        for candidate_id
                        in CANDIDATES
                    },
                },
            ]
            paths["JOURNAL_PATH"].write_text(
                "\n".join(
                    json.dumps(row)
                    for row in events
                )
                + "\n",
                encoding="utf-8",
            )

            with self._patch_paths(paths):
                service._cache.update({
                    "signature": None,
                    "expires_at": 0.0,
                    "payload": None,
                })
                payload = (
                    service
                    .get_stock_eagle_autonomous_ml_prospective_dashboard()
                )

            self.assertEqual(
                payload[
                    "latest_decision_timestamp_utc"
                ],
                "2026-10-01T00:00:00+00:00",
            )
            self.assertEqual(
                payload["candidates"][0][
                    "latest_selected_symbols"
                ],
                ["AAA", "BBB"],
            )
            self.assertEqual(
                len(payload["curve"]),
                2,
            )
            self.assertAlmostEqual(
                payload["curve"][-1][
                    "autonomous_ml_v1_normalized"
                ],
                100200.0,
            )
            self.assertAlmostEqual(
                payload["curve"][-1][
                    "spy_normalized"
                ],
                100100.0,
            )

    def test_corrupt_journal_surfaces_error_without_running_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = self._write_base(root)
            paths["JOURNAL_PATH"].write_text(
                "{not-json}\n",
                encoding="utf-8",
            )

            with self._patch_paths(paths):
                service._cache.update({
                    "signature": None,
                    "expires_at": 0.0,
                    "payload": None,
                })
                payload = (
                    service
                    .get_stock_eagle_autonomous_ml_prospective_dashboard()
                )

            self.assertEqual(
                payload["state"],
                "JOURNAL_ERROR",
            )
            self.assertEqual(
                payload["journal_error"],
                "JOURNAL_CORRUPT_LINE_1",
            )
            self.assertFalse(
                payload["dashboard_invoked_runner"]
            )

    def test_stock_research_tab_and_api_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        tabs = (
            root
            / "webapp/static/js/model_research_tabs.js"
        ).read_text(encoding="utf-8")
        dashboard = (
            root
            / "webapp/static/js/stock_eagle_autonomous_ml_prospective_dashboard.js"
        ).read_text(encoding="utf-8")
        app = (
            root
            / "webapp/app.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "id:'eagle'",
            tabs,
        )
        self.assertIn(
            "#research-(overview|v8|v10|v14|v15|eagle|v13)",
            tabs,
        )
        self.assertIn(
            "/api/stock-eagle/autonomous-ml/prospective-v1",
            dashboard,
        )
        self.assertIn(
            '@app.get("/api/stock-eagle/autonomous-ml/prospective-v1")',
            app,
        )
        self.assertIn(
            "stock_eagle_autonomous_ml_prospective_dashboard.js",
            app,
        )


if __name__ == "__main__":
    unittest.main()
