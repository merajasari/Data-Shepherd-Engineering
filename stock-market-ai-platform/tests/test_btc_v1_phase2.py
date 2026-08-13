import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.btc_v1.phase1 import REQUIRED_FEATURES
from ml.btc_v1.phase2 import (
    DEVELOPMENT_VALIDATION_START_UTC,
    FUTURE_HOLDOUT_START_UTC,
    HORIZON_DAYS,
    load_dataset,
    make_folds,
    validate_fold,
)


class BTCV1Phase2Tests(unittest.TestCase):
    def sample_frame(self):
        dates = pd.date_range("2020-01-01", "2022-12-31", freq="D", tz="UTC")
        df = pd.DataFrame({"timestamp_utc": dates})
        for i, col in enumerate(REQUIRED_FEATURES):
            df[col] = 0.01 + i * 0.001
        df["forward_return_7d"] = np.linspace(-0.1, 0.1, len(df))
        df["target_endpoint_utc_7d"] = df["timestamp_utc"] + pd.Timedelta(days=7)
        return df

    def test_folds_start_on_preregistered_date_and_purge(self):
        df = self.sample_frame()
        folds = make_folds(df["timestamp_utc"])
        self.assertTrue(folds)
        self.assertEqual(folds[0].validation_start_utc, DEVELOPMENT_VALIDATION_START_UTC)
        self.assertEqual(folds[0].purge_days, HORIZON_DAYS)
        self.assertEqual(
            folds[0].train_end_utc,
            folds[0].validation_start_utc - pd.Timedelta(days=HORIZON_DAYS + 1),
        )

    def test_validate_fold_enforces_target_endpoint_before_validation(self):
        df = self.sample_frame()
        fold = make_folds(df["timestamp_utc"])[0]
        train, val = validate_fold(fold, df)
        self.assertLess(
            pd.to_datetime(train["target_endpoint_utc_7d"], utc=True).max(),
            val["timestamp_utc"].min(),
        )

    def test_future_holdout_not_created_before_holdout_exists(self):
        df = self.sample_frame()
        folds = make_folds(df["timestamp_utc"])
        self.assertFalse(any(f.split == "holdout" for f in folds))
        self.assertGreater(FUTURE_HOLDOUT_START_UTC, df["timestamp_utc"].max())

    def test_load_dataset_rejects_missing_feature(self):
        df = self.sample_frame().drop(columns=[REQUIRED_FEATURES[0]])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "btc.parquet"
            df.to_parquet(p, index=False)
            with self.assertRaises(ValueError):
                load_dataset(p)


if __name__ == "__main__":
    unittest.main()
