import unittest

import numpy as np
import pandas as pd

from ml.crypto_v2.phase3 import (
    DEVELOPMENT_VALIDATION_START_UTC,
    FUTURE_HOLDOUT_START_UTC,
    MIN_CROSS_SECTION_ASSETS,
    _stable_random_scores,
    enforce_cross_section_breadth,
    make_folds,
    validate_fold,
)


class CryptoV2Phase3Tests(unittest.TestCase):
    def test_cross_section_breadth_filter(self):
        rows = []
        d1 = pd.Timestamp("2021-01-01", tz="UTC")
        d2 = pd.Timestamp("2021-01-02", tz="UTC")
        for i in range(MIN_CROSS_SECTION_ASSETS - 1):
            rows.append({"timestamp_utc": d1, "product_id": f"A{i}"})
        for i in range(MIN_CROSS_SECTION_ASSETS):
            rows.append({"timestamp_utc": d2, "product_id": f"B{i}"})
        out = enforce_cross_section_breadth(pd.DataFrame(rows))
        self.assertEqual(set(out["timestamp_utc"]), {d2})
        self.assertTrue((out["eligible_asset_count"] == MIN_CROSS_SECTION_ASSETS).all())

    def test_development_folds_start_at_preregistered_date(self):
        dates = pd.date_range("2020-07-28", "2026-08-04", freq="D", tz="UTC")
        folds = make_folds(dates, 7)
        self.assertGreater(len(folds), 0)
        self.assertEqual(folds[0].validation_start_utc, DEVELOPMENT_VALIDATION_START_UTC)
        self.assertTrue(all(f.split == "development" for f in folds))
        self.assertTrue(all(f.validation_end_utc < FUTURE_HOLDOUT_START_UTC for f in folds))

    def test_future_holdout_is_not_created_before_future_data_exists(self):
        dates = pd.date_range("2020-07-28", "2026-08-04", freq="D", tz="UTC")
        folds = make_folds(dates, 3)
        self.assertNotIn("holdout", [f.fold_id for f in folds])

    def test_holdout_is_created_only_with_future_data(self):
        dates = pd.date_range("2020-07-28", "2026-10-15", freq="D", tz="UTC")
        folds = make_folds(dates, 1)
        hold = [f for f in folds if f.fold_id == "holdout"]
        self.assertEqual(len(hold), 1)
        self.assertEqual(hold[0].validation_start_utc, FUTURE_HOLDOUT_START_UTC)

    def test_validate_fold_enforces_strict_target_endpoint_boundary(self):
        dates = pd.date_range("2020-07-28", "2021-12-31", freq="D", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": dates,
            "product_id": "BTC-USD",
            "target_endpoint_utc_7d": dates + pd.Timedelta(days=7),
        })
        fold = make_folds(dates, 7)[0]
        train, validation = validate_fold(fold, frame)
        self.assertLess(train["target_endpoint_utc_7d"].max(), validation["timestamp_utc"].min())

    def test_random_control_is_deterministic(self):
        frame = pd.DataFrame({
            "timestamp_utc": pd.to_datetime(["2024-01-01", "2024-01-01"], utc=True),
            "product_id": ["BTC-USD", "ETH-USD"],
        })
        a = _stable_random_scores(frame, 7, "dev_01")
        b = _stable_random_scores(frame, 7, "dev_01")
        np.testing.assert_array_equal(a, b)


if __name__ == "__main__":
    unittest.main()
