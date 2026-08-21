import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class V8SiteCutoverTests(unittest.TestCase):
    def test_dashboard_uses_v8_rankings(self):
        app = (PROJECT_ROOT / "webapp/app.py").read_text()
        template = (PROJECT_ROOT / "webapp/templates/index.html").read_text()
        service = (
            PROJECT_ROOT / "webapp/services/prediction_service.py"
        ).read_text()

        self.assertIn("get_v8_rankings", app)
        self.assertIn('/api/v8-rankings', app)
        self.assertIn("data/live/v8_latest_rankings.json", service)
        self.assertIn("V8 FROZEN STRATEGY", template)
        self.assertIn("V8 DISTANCE-ONLY RANK SIGNAL", template)
        self.assertNotIn("V5 FROZEN MODEL", template)
        self.assertNotIn('id="v5-shadow-comparison"', template)

    def test_schedulers_invoke_v8_production_path(self):
        refresh = (PROJECT_ROOT / "ml/run_v5_data_refresh.py").read_text()
        shell = (PROJECT_ROOT / "refresh_pipeline.sh").read_text()

        self.assertIn('"ml/run_v8_inference.py"', refresh)
        self.assertIn('"ml.v8.eod_orchestrator"', refresh)
        self.assertNotIn('"ml/run_v5_inference.py"', refresh)
        self.assertIn("ml/run_v8_data_refresh.py", shell)
        self.assertNotIn("ml/train_all.py", shell)

    def test_v8_cli_bootstraps_project_root_before_ml_import(self):
        source = (PROJECT_ROOT / "ml/run_v8_inference.py").read_text()
        bootstrap = source.index("sys.path.insert")
        package_import = source.index("from ml.v8.holdout_runner")
        self.assertLess(bootstrap, package_import)


if __name__ == "__main__":
    unittest.main()
