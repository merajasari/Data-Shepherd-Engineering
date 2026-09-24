from pathlib import Path
import unittest

from webapp.services.crypto_history_service import HISTORY_RANGE_DAYS, _normalize_range_key
from webapp.services.crypto_history_web_cache_service import normalize_history_range


ROOT = Path(__file__).resolve().parents[1]


class CryptoHistoryShortRangesTest(unittest.TestCase):
    def test_services_accept_24h_and_two_week_ranges(self):
        self.assertEqual(HISTORY_RANGE_DAYS["24H"], 1)
        self.assertEqual(HISTORY_RANGE_DAYS["14D"], 14)
        self.assertEqual(_normalize_range_key("24h"), "24H")
        self.assertEqual(_normalize_range_key("14d"), "14D")
        self.assertEqual(normalize_history_range("24h"), "24H")
        self.assertEqual(normalize_history_range("14d"), "14D")

    def test_crypto_visual_exposes_short_range_buttons(self):
        template = (ROOT / "webapp/templates/crypto_visual.html").read_text(encoding="utf-8")
        browser = (ROOT / "webapp/static/js/crypto_history_chart.js").read_text(encoding="utf-8")

        self.assertIn('data-history-range="14D">2W</button>', template)
        self.assertIn('data-history-range="24H">24H</button>', template)
        self.assertIn("'24H','14D','30D'", template)
        self.assertIn("if(range==='24H') return endMs-day;", browser)
        self.assertIn("if(range==='14D') return endMs-14*day;", browser)
        self.assertIn("'24H':1,'14D':14", browser)


if __name__ == "__main__":
    unittest.main()
