import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LoginOverviewLandingContractTest(unittest.TestCase):
    def test_successful_authentication_lands_on_overview_tab(self):
        app = (ROOT / "webapp/app.py").read_text(encoding="utf-8")
        tabs = (ROOT / "webapp/static/js/model_research_tabs.js").read_text(encoding="utf-8")

        self.assertIn(
            'def _dashboard_overview_url(): return url_for("dashboard",_anchor="research-overview")',
            app,
        )
        self.assertIn('return redirect(_dashboard_overview_url())', app)
        self.assertIn(
            'return redirect(url_for("change_member_password") if session["must_change_password"] else _dashboard_overview_url())',
            app,
        )
        self.assertIn(
            'requested = location.hash.match(/^#research-(overview|v8|v10|v14|v15|v13)$/)?.[1]',
            tabs,
        )
        self.assertLess(
            tabs.index("requested = location.hash.match"),
            tabs.index("sessionStorage.getItem('data-shepherd-research-tab')"),
        )


if __name__ == "__main__":
    unittest.main()
