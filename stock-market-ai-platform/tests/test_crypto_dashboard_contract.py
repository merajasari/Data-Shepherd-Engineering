import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CryptoDashboardContractTest(unittest.TestCase):
    def test_dashboard_exposes_only_retained_forward_sections(self):
        template = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
        self.assertNotIn("MODEL COMPARISON", template)
        self.assertNotIn('data-crypto-panel="comparison"', template)
        self.assertNotIn("Historical V5 Reconstruction", template)
        self.assertIn("OVERVIEW", template)
        self.assertIn("CRYPTO V5 V2", template)
        self.assertIn("September 23, 2026 at 12:00 a.m. Pacific", template)
        self.assertIn("First eligible decision candle", template)
        self.assertIn("September 24, 2026 at 00:00 UTC", template)
        self.assertIn("Earliest completed-candle availability", template)
        self.assertIn("September 25 at 00:00 UTC", template)
        self.assertIn("AWAITING FIRST DECISION", template)
        self.assertIn(
            "Initial paper-account state: 100% CASH. This is initialization only "
            "and is not a model decision.",
            template,
        )
        self.assertIn("missed V1 lane remains archived", template)
        self.assertIn("SHARED CRYPTO V4", template)
        self.assertIn("Preserved V3 result", template)

    def test_overview_starts_with_v4_and_v5_paper_progress(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        self.assertIn('id="crypto-paper-progress"', overview)
        self.assertIn("SHARED CRYPTO V4 · HOURLY", overview)
        self.assertIn("interrupted V3", overview)
        self.assertIn("CRYPTO V5 V2 · THREE-DAY", overview)
        self.assertIn("Missed V1 remains archived", overview)
        self.assertLess(overview.index('id="crypto-paper-progress"'), overview.index("COINBASE REAL-TIME MARKET"))
        self.assertIn("Real orders remain OFF", overview)

    def test_duplicate_forward_sections_are_removed_from_overview(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        page = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
        self.assertNotIn("UNTOUCHED FORWARD PERFORMANCE", overview)
        self.assertNotIn("POST-BOUNDARY FORWARD VALIDATION SUMMARY", overview)
        self.assertNotIn("XRP V1 Phase 7", overview)
        self.assertIn("FORWARD SAMPLE", page)
        self.assertIn("{{ shared.realized_count }} / 30", page)

    def test_obsolete_readiness_gate_is_not_rendered(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        self.assertNotIn("FORWARD EVALUATION READINESS", overview)
        self.assertNotIn("Evidence-Lane Integrity Gate", overview)
        self.assertNotIn("forward_evaluation_readiness", overview)

    def test_v2_development_evidence_is_scoped_to_v4_page(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        page = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
        self.assertNotIn("CRYPTO 15M V2 — RESEARCH EVIDENCE", overview)
        self.assertNotIn("Frozen Candidate Development Results", overview)
        self.assertIn('id="v3-historical-development-evidence"', page)
        self.assertIn("HISTORICAL DEVELOPMENT EVIDENCE — NOT PAPER PERFORMANCE", page)
        self.assertIn("September 23, 2026 at 07:00 UTC", page)
        self.assertNotIn("Sep 18+ clean forward evaluation", page)

    def test_archived_xrp_and_rejected_tracks_are_not_on_overview(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        self.assertNotIn("XRP V1 — EXPLORATORY FORWARD MONITOR", overview)
        self.assertNotIn("Dedicated XRP Shadow Decision Center", overview)
        self.assertNotIn("DEVELOPMENT RESEARCH — VERSION STATUS", overview)
        self.assertNotIn("REJECT_CURRENT_POLICY_FAMILY", overview)
        self.assertIn("CRYPTO V1 HISTORICAL RESEARCH", overview)

    def test_overview_uses_active_command_center_and_compact_health(self):
        overview = (ROOT / "webapp/templates/crypto_overview_content.html").read_text(encoding="utf-8")
        service = (ROOT / "webapp/services/crypto_dashboard_service.py").read_text(encoding="utf-8")
        browser = (ROOT / "webapp/static/js/crypto_model_research.js").read_text(encoding="utf-8")
        self.assertIn("PAPER TRADING COMMAND CENTER", overview)
        self.assertIn("NET PAPER P/L", overview)
        self.assertIn("SHOW ALL 25 ASSETS", overview)
        self.assertIn("ACTIVE CRYPTO SERVICES", overview)
        self.assertNotIn("XRP V1 Forward", service[service.index("def _operational_health"):service.index("def _forward_evaluation_readiness")])
        self.assertIn("initPaperCountdowns", browser)

    def test_shared_v4_equity_chart_has_rich_pointer_interaction(self):
        template = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
        browser = (ROOT / "webapp/static/js/crypto_model_research.js").read_text(encoding="utf-8")
        self.assertIn("click chart background to pin", template)
        self.assertIn("hover to identify the nearest hourly point", template)
        self.assertIn("what the paper model bought, sold, held, or rotated during that hour", template)
        self.assertIn("DRILL-IN AVAILABLE", browser)
        self.assertIn("Click either data-point dot at this hour to open the full realization.", browser)
        self.assertIn("press Esc to release or close", template)
        self.assertIn('id="shared-v4-drilldown"', template)
        self.assertIn("SHARED V4 · LAST-HOUR PAPER ACTIVITY + REALIZATION", template)
        self.assertIn("interactive:true", browser)
        self.assertIn("drilldown:true", browser)
        self.assertIn("data-forward-point-index", browser)
        self.assertIn("openSharedV4Drilldown", browser)
        self.assertIn("Decision + execution", browser)
        self.assertIn("What happened during this hour", browser)
        self.assertIn("Paper action", browser)
        self.assertIn("Bought", browser)
        self.assertIn("Sold", browser)
        self.assertIn("Confirm-2 state", browser)
        self.assertIn("NO · PAPER ONLY", browser)
        self.assertIn("sharedV4Activity", browser)
        self.assertIn("pending_candidate_label", browser)
        self.assertIn("Hourly outcome", browser)
        self.assertIn("Risk + relative performance", browser)
        self.assertIn("Model probabilities", browser)
        self.assertIn("V4 edge vs BTC", browser)
        self.assertIn("Executed sleeve", browser)
        self.assertIn("Model signal", browser)
        self.assertIn("probability('BTC',row.prob_btc", browser)
        self.assertIn("probability('ALT',row.prob_alt", browser)
        self.assertIn("probability('CASH',row.prob_cash", browser)
        self.assertIn("stroke-dasharray':'5 4'", browser)
        self.assertIn("event.key==='Escape'", browser)
        self.assertIn("hourlySlots:true", browser)
        self.assertIn("1-HOUR SLOTS · PACIFIC TIME", browser)

    def test_shared_v4_actions_summary_reuses_drilldown_evidence_and_defaults_to_24h(self):
        template = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
        browser = (ROOT / "webapp/static/js/crypto_model_research.js").read_text(encoding="utf-8")
        self.assertIn("Actions Summery", template)
        self.assertIn('id="shared-v4-actions-summary"', template)
        for hours in ("1", "2", "4", "6", "8", "12", "24", "168", "720", "8760"):
            self.assertIn(f'data-shared-v4-range="{hours}"', template)
        self.assertIn("sharedV4SummaryHours=24", browser)
        self.assertIn("sharedV4DrilldownHtml(row)", browser)
        self.assertIn("Period performance + modeled trading impact", browser)
        self.assertIn("SLEEVE SWITCHES", browser)
        self.assertIn("BUY EVENTS", browser)
        self.assertIn("SELL EVENTS", browser)
        self.assertIn("HELD / NO SWITCH", browser)
        self.assertIn("Modeled transaction-cost impact", browser)
        self.assertIn("Executed sleeve hours", browser)
        self.assertIn("Raw model signals", browser)
        self.assertIn("Best / worst completed hour", browser)
        self.assertIn("Hourly action history", browser)
        self.assertIn("Exact paper holdings · ALT", browser)
        self.assertIn("sharedV4HoldingsHtml", browser)
        self.assertIn("held_assets", browser)
        self.assertIn("equal-weight products used by the frozen hourly ALT-return rule", browser)
        self.assertIn("Coin actions in selected range", browser)
        self.assertIn("Held during selected range", browser)
        self.assertIn("Action timeline for selected range", browser)
        self.assertIn("No modeled coin buys or sells occurred in this selected range.", browser)
        self.assertIn("Bought", browser)
        self.assertIn("Sold", browser)
        self.assertIn("ALT basket membership changes · not modeled trades", browser)
        self.assertIn("Coin-level Bought/Sold labels above are only produced by actual sleeve transitions.", browser)
        self.assertNotIn("Current exact paper holdings", browser)

    def test_comparison_api_and_browser_request_are_removed(self):
        app_source = (ROOT / "webapp/app.py").read_text(encoding="utf-8")
        browser_source = (ROOT / "webapp/static/js/crypto_model_research.js").read_text(encoding="utf-8")
        self.assertNotIn("/api/crypto-model-comparison", app_source)
        self.assertNotIn("get_crypto_model_comparison", app_source)
        self.assertNotIn("/api/crypto-model-comparison", browser_source)
        self.assertNotIn("CRYPTO_V5", browser_source)


if __name__ == "__main__":
    unittest.main()
