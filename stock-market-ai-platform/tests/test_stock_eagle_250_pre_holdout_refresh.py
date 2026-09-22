import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from ml.stock_eagle_250.pre_holdout_refresh import (
    HOLDOUT_START_DATE,
    PRE_HOLDOUT_END_DATE,
    atomic_write_bronze,
    build_refresh_plan,
    latest_bronze_session,
    merge_bronze_history,
    requested_symbols,
    validate_end_date,
)


class StockEagle250PreHoldoutRefreshTest(unittest.TestCase):
    def test_cutoff_is_fixed_before_untouched_holdout(self):
        self.assertEqual(validate_end_date("2026-09-22"), PRE_HOLDOUT_END_DATE)
        self.assertLess(PRE_HOLDOUT_END_DATE, HOLDOUT_START_DATE)

        with self.assertRaises(ValueError):
            validate_end_date("2026-09-21")
        with self.assertRaises(ValueError):
            validate_end_date("2026-09-23")
        with self.assertRaises(ValueError):
            validate_end_date("2026-09-24")

    def test_default_scope_is_250_candidates_plus_spy(self):
        symbols = requested_symbols()
        self.assertEqual(len(symbols), 251)
        self.assertEqual(len(set(symbols)), 251)
        self.assertEqual(symbols[-1], "SPY")

        self.assertEqual(
            requested_symbols([symbols[0].lower(), symbols[1], symbols[0]]),
            [symbols[0], symbols[1]],
        )
        with self.assertRaises(ValueError):
            requested_symbols(["NOT_A_CONTRACTED_SYMBOL"])

    def test_refresh_plan_separates_current_rebuild_download_and_deferred(self):
        symbols = requested_symbols()[:4]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bronze_root = root / "bronze"
            feature_root = root / "features"

            def write_bronze(symbol, session):
                path = bronze_root / symbol / f"{symbol}_prices.csv"
                path.parent.mkdir(parents=True)
                millis = int(
                    pd.Timestamp(session, tz="UTC").timestamp() * 1000
                )
                pd.DataFrame({
                    "symbol": [symbol],
                    "timestamp": [millis],
                }).to_csv(path, index=False)

            def write_feature(symbol, session):
                path = feature_root / symbol / f"{symbol}_features.parquet"
                path.parent.mkdir(parents=True)
                pd.DataFrame({
                    "timestamp_utc": [pd.Timestamp(session, tz="UTC")],
                }).to_parquet(path, index=False)

            write_bronze(symbols[0], "2026-09-22")
            write_feature(symbols[0], "2026-09-22")

            write_bronze(symbols[1], "2026-09-22")
            write_feature(symbols[1], "2026-09-21")

            write_bronze(symbols[2], "2026-09-21")
            write_feature(symbols[2], "2026-09-21")

            plan = build_refresh_plan(
                symbols,
                max_requests=1,
                bronze_root=bronze_root,
                feature_root=feature_root,
            )

        self.assertEqual(plan["complete"], [symbols[0]])
        self.assertEqual(plan["transform_ready"], [symbols[1]])
        self.assertEqual(plan["download_batch"], [symbols[2]])
        self.assertEqual(plan["deferred"], [symbols[3]])

    def test_merge_replaces_overlap_and_preserves_full_history(self):
        symbol = "TEST"
        first = int(pd.Timestamp("2026-09-21", tz="UTC").timestamp() * 1000)
        second = int(pd.Timestamp("2026-09-22", tz="UTC").timestamp() * 1000)

        existing = pd.DataFrame({
            "symbol": [symbol],
            "timestamp": [first],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.0],
            "volume": [100],
            "vwap": [None],
        })
        incoming = pd.DataFrame({
            "symbol": [symbol, symbol],
            "timestamp": [first, second],
            "open": [10.0, 12.0],
            "high": [12.0, 13.0],
            "low": [9.0, 11.0],
            "close": [11.0, 12.5],
            "volume": [110, 120],
            "vwap": [None, None],
        })

        merged = merge_bronze_history(existing, incoming, symbol)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged["timestamp"].tolist(), [first, second])
        self.assertEqual(merged.loc[0, "close"], 11.0)
        self.assertEqual(merged.loc[1, "close"], 12.5)

    def test_atomic_bronze_write_has_no_fixed_temp_collision(self):
        symbol = "TEST"
        session = int(
            pd.Timestamp("2026-09-22", tz="UTC").timestamp() * 1000
        )
        frame = pd.DataFrame({
            "symbol": [symbol],
            "timestamp": [session],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100],
            "vwap": [None],
        })

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = atomic_write_bronze(frame, symbol, bronze_root=root)

            self.assertTrue(path.exists())
            self.assertEqual(latest_bronze_session(symbol, root), date(2026, 9, 22))
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
