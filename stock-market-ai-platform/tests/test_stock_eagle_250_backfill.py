import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ml.stock_eagle_250.backfill import (
    ADDITION_SYMBOLS,
    build_resume_plan,
    redact_error,
    requested_symbols,
    validate_scope,
    write_state,
)

import sys

INGESTION_ROOT = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from v5_symbols import V5_BENCHMARK_SYMBOL, V5_SYMBOLS  # noqa: E402


class StockEagle250BackfillTest(unittest.TestCase):
    def test_scope_is_exactly_150_additions_and_excludes_frozen_symbols(self):
        validate_scope()

        self.assertEqual(len(ADDITION_SYMBOLS), 150)
        self.assertEqual(len(set(ADDITION_SYMBOLS)), 150)
        self.assertTrue(set(ADDITION_SYMBOLS).isdisjoint(V5_SYMBOLS))
        self.assertNotIn(V5_BENCHMARK_SYMBOL, ADDITION_SYMBOLS)

    def test_requested_symbols_normalizes_and_rejects_outside_scope(self):
        first, second = ADDITION_SYMBOLS[:2]
        self.assertEqual(
            requested_symbols([first.lower(), second, first]),
            [first, second],
        )
        with self.assertRaises(ValueError):
            requested_symbols(["AAPL"])
        with self.assertRaises(ValueError):
            requested_symbols(["SPY"])

    def test_resume_plan_reuses_bronze_and_caps_downloads(self):
        symbols = list(ADDITION_SYMBOLS[:5])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bronze_root = root / "bronze"
            feature_root = root / "features"

            completed = symbols[0]
            feature = feature_root / completed / f"{completed}_features.parquet"
            feature.parent.mkdir(parents=True)
            feature.write_text("complete", encoding="utf-8")

            transform_ready = symbols[1]
            bronze = bronze_root / transform_ready / f"{transform_ready}_prices.csv"
            bronze.parent.mkdir(parents=True)
            bronze.write_text("symbol,timestamp\n", encoding="utf-8")

            plan = build_resume_plan(
                symbols,
                max_requests=2,
                bronze_root=bronze_root,
                feature_root=feature_root,
            )

        self.assertEqual(plan["complete"], [completed])
        self.assertEqual(plan["transform_ready"], [transform_ready])
        self.assertEqual(plan["download_batch"], symbols[2:4])
        self.assertEqual(plan["deferred"], symbols[4:])

    def test_error_text_redacts_environment_and_query_tokens(self):
        secret = "never-print-this-token"
        error = RuntimeError(
            f"request failed?token={secret}&symbol=TEST direct={secret}"
        )
        with patch.dict(os.environ, {"TIINGO_API_KEY": secret}):
            text = redact_error(error)

        self.assertNotIn(secret, text)
        self.assertIn("token=<redacted>", text)

    def test_state_write_is_valid_json_and_leaves_no_fixed_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            write_state({"complete": False, "remaining": 150}, path=path)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '{\n  "complete": false,\n  "remaining": 150\n}\n',
            )
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
