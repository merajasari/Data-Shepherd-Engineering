from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OverviewLivePaperDashboardTest(unittest.TestCase):
    def test_overview_uses_genuine_v8_holdout_source(self):
        source = (
            ROOT / "webapp/static/js/overview_live_paper_dashboard.js"
        ).read_text(encoding="utf-8")

        self.assertIn("fetch('/api/v8/holdout'", source)
        self.assertIn("function v8Series(payload)", source)
        self.assertIn("payload.current_equity", source)
        self.assertIn("row.strategy_normalized", source)

        # V8 must no longer be sourced from V10's paired-control fields.
        v10_start = source.index("function v10Series(payload)")
        v8_start = source.index("function v8Series(payload)")
        v10_source = source[v10_start:v8_start]
        self.assertNotIn("current_v8_equity", v10_source)
        self.assertNotIn("v8_normalized", v10_source)

    def test_overview_renders_v8_summary_card(self):
        source = (
            ROOT / "webapp/static/js/overview_live_paper_dashboard.js"
        ).read_text(encoding="utf-8")

        self.assertIn("label:'V8 frozen'", source)
        self.assertIn("['v8','v10','v14','v15'].includes(item.id)", source)
        self.assertIn("repeat(4,minmax(0,1fr))", source)
        self.assertIn("All four paper sources read successfully", source)


if __name__ == "__main__":
    unittest.main()
