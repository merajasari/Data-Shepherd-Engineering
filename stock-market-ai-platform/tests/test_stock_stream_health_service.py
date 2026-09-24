import unittest
from unittest.mock import patch

from webapp.services import stock_stream_health_service as health


class StockStreamHealthServiceTest(unittest.TestCase):
    def test_health_checks_active_runtime_launchagent(self):
        self.assertEqual(health.LABEL, "com.datashepherd.iexstream")

    @patch("webapp.services.stock_stream_health_service.subprocess.run")
    @patch("webapp.services.stock_stream_health_service.os.getuid", return_value=501)
    def test_launchagent_state_queries_active_iexstream_label(self, _getuid, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "state = running\npid = 123\n"
        run.return_value.stderr = ""

        state = health._launchagent_state()

        self.assertTrue(state["loaded"])
        self.assertTrue(state["running"])
        run.assert_called_once_with(
            ["launchctl", "print", "gui/501/com.datashepherd.iexstream"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
