import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "run_v5_data_refresh",
    PROJECT_ROOT / "ml/run_v5_data_refresh.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class V5RefreshQuotaTests(unittest.TestCase):
    def test_rolling_budget_expires_old_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            now = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)

            module.record_request_attempt(now=now - timedelta(minutes=59), path=ledger)
            module.record_request_attempt(now=now - timedelta(minutes=30), path=ledger)
            module.record_request_attempt(now=now - timedelta(minutes=61), path=ledger)

            available, used = module.available_request_budget(
                hourly_limit=5,
                now=now,
                path=ledger,
            )

            self.assertEqual(used, 2)
            self.assertEqual(available, 3)

    def test_budget_reaches_zero_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            start = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)

            for offset in (0, 5, 10):
                module.record_request_attempt(
                    now=start + timedelta(minutes=offset),
                    path=ledger,
                )

            available, used = module.available_request_budget(
                hourly_limit=3,
                now=start + timedelta(minutes=10),
                path=ledger,
            )
            self.assertEqual((available, used), (0, 3))

            available, used = module.available_request_budget(
                hourly_limit=3,
                now=start + timedelta(minutes=61),
                path=ledger,
            )
            self.assertEqual((available, used), (1, 2))


if __name__ == "__main__":
    unittest.main()
