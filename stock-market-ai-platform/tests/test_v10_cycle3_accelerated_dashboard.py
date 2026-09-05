from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ml.v10.cycle3_accelerated_forward_contract import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
)
from ml.v10.cycle3_accelerated_forward_journal import (
    AcceleratedEvidenceJournal,
)
from ml.v10.cycle3_accelerated_forward_runner import promotion_summary
from webapp.services import v10_cycle3_accelerated_service as dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def exit_event(offset: int, block: int) -> dict[str, object]:
    decision = datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(
        days=block * 5 + offset
    )
    return {
        "event_type": "EXIT",
        "decision_timestamp_utc": decision.isoformat(),
        "exit_timestamp_utc": (decision + timedelta(days=6)).isoformat(),
        "cohort_offset": offset,
        "created_at_utc": (decision + timedelta(days=6, minutes=5)).isoformat(),
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "frozen_sha256": EXPECTED_FROZEN_SHA256,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "january_confirmation_modified": False,
        "net_portfolio_return": 0.02,
        "v8_control_net_portfolio_return": 0.01,
        "v10_minus_v8_net_return": 0.01,
        "spy_return": 0.005,
        "net_relative_return": 0.015,
        "defensive_active": block == 0,
    }


class V10Cycle3AcceleratedDashboardTests(unittest.TestCase):
    def setUp(self):
        dashboard._CACHE.update(
            {"at": 0.0, "signature": None, "payload": None}
        )

    def test_partial_sleeves_never_enter_promotion_metrics_or_charts(self):
        events = [exit_event(offset, 0) for offset in range(4)]
        summary = dashboard._summarize_events(events)
        self.assertEqual(summary["completed_exits"], 4)
        self.assertEqual(summary["promotion_scored_exits"], 0)
        self.assertEqual(summary["complete_five_sleeve_blocks"], 0)
        self.assertEqual(len(summary["block_curve"]), 1)
        self.assertEqual(summary["block_edges"], [])
        self.assertIsNone(summary["mean_net_return_after_cost"])

    def test_dashboard_math_matches_canonical_promotion_summary(self):
        events = [
            exit_event(offset, block)
            for block in range(12)
            for offset in range(5)
        ]
        canonical = promotion_summary(events)
        projected = dashboard._summarize_events(events)
        review = dashboard._review_projection(projected, True)

        exact_fields = (
            "completed_exits",
            "promotion_scored_exits",
            "completed_exits_by_cohort",
            "complete_five_sleeve_blocks",
            "completed_defensive_exits",
        )
        for field in exact_fields:
            self.assertEqual(projected[field], canonical[field])
        numeric_fields = (
            "mean_net_return_after_cost",
            "mean_v10_minus_v8_net_return",
            "mean_v10_minus_spy_return",
            "v10_max_cohort_drawdown",
            "v8_max_cohort_drawdown",
            "mean_defensive_v10_minus_v8_net_return",
        )
        for field in numeric_fields:
            self.assertAlmostEqual(projected[field], canonical[field])
        self.assertEqual(review["review_status"], canonical["review_status"])
        self.assertTrue(review["stronger_review_eligible"])
        self.assertFalse(review["automatic_promotion"])
        self.assertTrue(review["human_review_required"])
        self.assertEqual(len(projected["block_curve"]), 13)
        self.assertEqual(len(projected["block_edges"]), 12)

    def test_endpoint_projection_is_read_only_and_january_isolated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            journal_path = root / "journal.jsonl"
            status_path = root / "status.json"
            events = [
                exit_event(offset, block)
                for block in range(8)
                for offset in range(5)
            ]
            journal = AcceleratedEvidenceJournal(journal_path)
            for event in events:
                self.assertTrue(journal.append(event))
            status_path.write_text(
                json.dumps(
                    {
                        "status": "PROVISIONAL_PAPER_CHAMPION_REVIEW_ELIGIBLE",
                        "checked_at_utc": "2026-11-06T21:10:00+00:00",
                        "contract_sha256": EXPECTED_CONTRACT_SHA256,
                        "frozen_sha256": EXPECTED_FROZEN_SHA256,
                        "paper_trading_only": True,
                        "live_trading_enabled": False,
                        "brokerage_orders": False,
                        "v8_modified": False,
                        "january_confirmation_modified": False,
                        "promotion": promotion_summary(events),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(dashboard, "DEFAULT_JOURNAL_PATH", journal_path),
                patch.object(dashboard, "STATUS_PATH", status_path),
            ):
                payload = dashboard.get_v10_cycle3_accelerated_dashboard()

        self.assertEqual(
            payload["classification"],
            "AUTHORIZED_PROSPECTIVE_PAPER_FORWARD",
        )
        self.assertEqual(payload["complete_five_sleeve_blocks"], 8)
        self.assertTrue(payload["provisional_review_eligible"])
        self.assertFalse(payload["stronger_review_eligible"])
        self.assertTrue(payload["operational_integrity"])
        self.assertEqual(payload["operational_failures"], [])
        self.assertEqual(
            payload["independent_confirmation_start_utc"],
            "2027-01-04T00:00:00+00:00",
        )
        self.assertTrue(payload["read_only_dashboard"])
        self.assertFalse(payload["runner_invoked"])
        self.assertFalse(payload["historical_reconstruction_read"])
        self.assertFalse(payload["january_holdout_outcomes_read"])
        self.assertFalse(payload["v8_production_invoked"])
        self.assertFalse(payload["v8_modified"])
        self.assertFalse(payload["january_confirmation_modified"])
        self.assertFalse(payload["live_trading_enabled"])
        self.assertFalse(payload["brokerage_orders"])

    def test_current_pre_boundary_status_is_healthy_and_empty(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            status_path = root / "status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "status": "WAITING_FOR_ACCELERATED_BOUNDARY",
                        "checked_at_utc": "2026-09-05T02:07:35+00:00",
                        "contract_sha256": EXPECTED_CONTRACT_SHA256,
                        "frozen_sha256": EXPECTED_FROZEN_SHA256,
                        "paper_trading_only": True,
                        "live_trading_enabled": False,
                        "brokerage_orders": False,
                        "v8_modified": False,
                        "january_confirmation_modified": False,
                        "promotion": promotion_summary([]),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(
                    dashboard, "DEFAULT_JOURNAL_PATH", root / "missing.jsonl"
                ),
                patch.object(dashboard, "STATUS_PATH", status_path),
            ):
                payload = dashboard.get_v10_cycle3_accelerated_dashboard()
        self.assertEqual(payload["status"], "WAITING_FOR_ACCELERATED_BOUNDARY")
        self.assertEqual(payload["evidence_status"], "NO_COMPLETE_FIVE_SLEEVE_BLOCKS")
        self.assertEqual(payload["decisions"], 0)
        self.assertEqual(payload["entries"], 0)
        self.assertEqual(payload["completed_exits"], 0)
        self.assertEqual(payload["complete_five_sleeve_blocks"], 0)
        self.assertEqual(len(payload["block_curve"]), 1)
        self.assertTrue(payload["operational_integrity"])
        self.assertEqual(payload["operational_failures"], [])
        self.assertFalse(payload["automatic_promotion"])

    def test_corrupt_journal_fails_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            journal_path = root / "journal.jsonl"
            journal_path.write_text("not-json\n", encoding="utf-8")
            with (
                patch.object(dashboard, "DEFAULT_JOURNAL_PATH", journal_path),
                patch.object(dashboard, "STATUS_PATH", root / "missing.json"),
            ):
                payload = dashboard.get_v10_cycle3_accelerated_dashboard()
        self.assertEqual(payload["operational_status"], "ALERT")
        self.assertFalse(payload["operational_integrity"])
        self.assertEqual(payload["complete_five_sleeve_blocks"], 0)
        self.assertTrue(
            any(
                str(item).startswith("JOURNAL_INVALID:")
                for item in payload["operational_failures"]
            )
        )
        self.assertFalse(payload["brokerage_orders"])

    def test_dashboard_wiring_and_evidence_labels(self):
        app = (PROJECT_ROOT / "webapp/app.py").read_text(encoding="utf-8")
        tabs = (
            PROJECT_ROOT / "webapp/static/js/model_research_tabs.js"
        ).read_text(encoding="utf-8")
        accelerated = (
            PROJECT_ROOT
            / "webapp/static/js/v10_cycle3_accelerated_dashboard.js"
        ).read_text(encoding="utf-8")
        january = (
            PROJECT_ROOT / "webapp/static/js/v10_cycle3_holdout_monitor.js"
        ).read_text(encoding="utf-8")
        legacy = (
            PROJECT_ROOT / "webapp/static/js/v10_confirmation_dashboard.js"
        ).read_text(encoding="utf-8")
        service = Path(dashboard.__file__).read_text(encoding="utf-8")

        self.assertIn("/api/v10/cycle3/accelerated", app)
        self.assertIn("v10_cycle3_accelerated_dashboard.js", app)
        self.assertIn("v10_confirmation_dashboard.js", app)
        self.assertIn("v10_cycle3_holdout_monitor.js", app)
        self.assertLess(
            tabs.index("'v10-cycle3-accelerated-monitor'"),
            tabs.index("'v10-cycle3-holdout-monitor'"),
        )
        self.assertLess(
            tabs.index("'v10-cycle3-holdout-monitor'"),
            tabs.index("'v10-confirmation-card'"),
        )
        self.assertIn("Complete-block normalized comparison", accelerated)
        self.assertIn("Paired edge by complete block", accelerated)
        self.assertIn("Preregistered promotion gates", accelerated)
        self.assertIn("@media(max-width:700px)", accelerated)
        self.assertIn("Accelerated September–December evidence never enters", january)
        self.assertIn("<details>", legacy)
        self.assertNotIn("cycle3_holdout_runner", service)
        self.assertNotIn("cycle3_accelerated_forward_runner", service)
        self.assertIn('"runner_invoked": False', service)
        self.assertIn('"january_holdout_outcomes_read": False', service)
        self.assertIn('"brokerage_orders": False', service)


if __name__ == "__main__":
    unittest.main()
