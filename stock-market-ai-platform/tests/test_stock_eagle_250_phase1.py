import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.stock_eagle_250 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250.phase1 import (
    CONTRACT_PATH,
    MINIMUM_ELIGIBLE_SESSIONS,
    PROTECTED_MODEL_LANES,
    build_manifest,
    inspect_history,
    validate_universe,
)

import sys

INGESTION_ROOT = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from stock_universe_250 import (  # noqa: E402
    STOCK_250_SYMBOLS,
    get_stock_250_data_symbols,
)
from v5_symbols import V5_BENCHMARK_SYMBOL  # noqa: E402


class StockEagle250Phase1Test(unittest.TestCase):
    def test_contract_is_isolated_research_only(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(contract["display_name"], DISPLAY_NAME)
        self.assertEqual(contract["model_id"], MODEL_ID)
        self.assertEqual(contract["research_version"], RESEARCH_VERSION)
        self.assertEqual(contract["universe"]["candidate_count"], 250)
        self.assertEqual(contract["universe"]["benchmark_symbol"], "SPY")
        self.assertFalse(contract["universe"]["benchmark_is_investable"])
        self.assertTrue(contract["authority"]["research_only"])
        self.assertFalse(contract["authority"]["paper_trading_enabled"])
        self.assertFalse(contract["authority"]["live_trading_enabled"])
        self.assertFalse(contract["authority"]["brokerage_orders"])
        for lane in PROTECTED_MODEL_LANES:
            self.assertFalse(contract["isolation"][f"modify_{lane}"])

    def test_universe_is_exactly_250_candidates_plus_spy(self):
        summary = validate_universe()

        self.assertEqual(summary["candidate_count"], 250)
        self.assertEqual(summary["data_symbol_count"], 251)
        self.assertEqual(len(STOCK_250_SYMBOLS), 250)
        self.assertEqual(len(set(STOCK_250_SYMBOLS)), 250)
        self.assertNotIn(V5_BENCHMARK_SYMBOL, STOCK_250_SYMBOLS)
        self.assertEqual(get_stock_250_data_symbols()[-1], V5_BENCHMARK_SYMBOL)

    def test_history_inspection_applies_252_session_eligibility(self):
        timestamps = pd.date_range(
            "2025-01-02",
            periods=MINIMUM_ELIGIBLE_SESSIONS,
            freq="B",
            tz="UTC",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "AAPL" / "AAPL_features.parquet"
            path.parent.mkdir(parents=True)
            path.touch()

            record = inspect_history(
                "AAPL",
                feature_root=root,
                reader=lambda *_args, **_kwargs: pd.DataFrame(
                    {"timestamp_utc": timestamps}
                ),
            )

        self.assertEqual(record["status"], "ELIGIBLE")
        self.assertEqual(record["observed_sessions"], MINIMUM_ELIGIBLE_SESSIONS)
        self.assertTrue(record["eligible_after_minimum_history"])
        self.assertEqual(record["duplicate_timestamps"], 0)

    def test_manifest_fails_closed_when_a_history_is_missing(self):
        records = [
            {
                "symbol": symbol,
                "status": "ELIGIBLE",
                "rows": MINIMUM_ELIGIBLE_SESSIONS,
                "observed_sessions": MINIMUM_ELIGIBLE_SESSIONS,
                "eligible_after_minimum_history": True,
                "duplicate_timestamps": 0,
                "start_utc": "2025-01-02T00:00:00+00:00",
                "end_utc": "2025-12-19T00:00:00+00:00",
                "is_benchmark": symbol == V5_BENCHMARK_SYMBOL,
                "path": f"data/features/stocks/{symbol}/{symbol}_features.parquet",
            }
            for symbol in get_stock_250_data_symbols()
        ]
        records[0] = {
            **records[0],
            "status": "MISSING",
            "rows": 0,
            "observed_sessions": 0,
            "eligible_after_minimum_history": False,
            "duplicate_timestamps": 0,
            "start_utc": None,
            "end_utc": None,
        }

        manifest = build_manifest(records)

        self.assertFalse(manifest["ready_for_phase2_dataset_construction"])
        self.assertEqual(manifest["missing_symbol_count"], 1)
        self.assertEqual(manifest["candidate_feature_files_present"], 249)
        self.assertFalse(manifest["paper_trading_enabled"])
        self.assertFalse(manifest["brokerage_orders"])
        self.assertFalse(manifest["existing_model_artifacts_modified"])


if __name__ == "__main__":
    unittest.main()
