import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INGESTION_ROOT = PROJECT_ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

spec = importlib.util.spec_from_file_location(
    "backfill_iex_24h_cache",
    PROJECT_ROOT / "scripts" / "backfill_iex_24h_cache.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IexBackfillSecurityTest(unittest.TestCase):
    def test_request_failure_never_returns_api_token(self):
        secret = "test-secret-that-must-not-appear"
        error = requests.HTTPError(
            "failed URL contained token=" + secret
        )
        with patch.object(module.requests, "get", side_effect=error):
            _, rows, detail = module.fetch_symbol("TEST", secret)
        self.assertEqual(rows, [])
        self.assertNotIn(secret, detail)
        self.assertIn("credentials redacted", detail)


if __name__ == "__main__":
    unittest.main()
