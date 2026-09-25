from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V10Cycle3AcceleratedV2OfficialV8Test(unittest.TestCase):
    def test_live_panel_uses_official_v8_holdout_endpoint(self):
        source = (
            ROOT
            / "webapp/static/js/v10_cycle3_accelerated_v2_dashboard.js"
        ).read_text(encoding="utf-8")

        self.assertIn("Official V8 return", source)
        self.assertIn("Current return gap vs official V8", source)
        self.assertIn("V8 official", source)
        self.assertIn("/api/v8/holdout", source)
        self.assertIn("DataShepherdV8Snapshot", source)
        self.assertIn("officialV8.current_equity", source)
        self.assertIn("officialV8.current_return", source)
        self.assertIn("row.strategy_normalized", source)
        self.assertIn("v8.holdout_start_utc", source)

    def test_live_panel_does_not_use_paired_v8_current_for_official_metric(self):
        source = (
            ROOT
            / "webapp/static/js/v10_cycle3_accelerated_v2_dashboard.js"
        ).read_text(encoding="utf-8")

        render_start = source.index("function renderDashboard(data,officialV8)")
        render_end = source.index("function renderError", render_start)
        render_block = source[render_start:render_end]

        self.assertNotIn(
            "pct4(data.current_v8_return)",
            render_block,
        )
        self.assertNotIn(
            "pct4(data.current_excess_vs_v8)",
            render_block,
        )
        self.assertIn(
            "pct4(officialV8Return)",
            render_block,
        )
        self.assertIn(
            "pct4(currentExcessVsOfficialV8)",
            render_block,
        )

    def test_paired_v8_remains_separate_for_promotion_evidence(self):
        source = (
            ROOT
            / "webapp/static/js/v10_cycle3_accelerated_v2_dashboard.js"
        ).read_text(encoding="utf-8")

        # The lower promotion diagnostics intentionally remain the same-date
        # paired V8 control. Only the live account comparison uses official V8.
        self.assertIn("Mean paired V10 − V8 edge", source)
        self.assertIn("Complete-block normalized comparison", source)
        self.assertIn("V8 control", source)
        self.assertIn("Paired edge by complete block", source)


if __name__ == "__main__":
    unittest.main()
