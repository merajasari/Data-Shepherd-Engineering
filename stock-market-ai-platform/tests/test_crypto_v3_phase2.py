import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v3.phase1 import MODEL_FEATURES, TARGET_POSITIVE, TARGET_RISK_ADJUSTED
from ml.crypto_v3.phase2 import (
    DEVELOPMENT_VALIDATION_START_UTC,
    FUTURE_HOLDOUT_START_UTC,
    HORIZON_DAYS,
    load_dataset,
    make_folds,
    summarize_classifier,
    summarize_regressor,
    validate_fold,
)


class CryptoV3Phase2Tests(unittest.TestCase):
    def sample_frame(self):
        dates = pd.date_range("2020-01-01", "2022-12-31", freq="D", tz="UTC")
        rows = []
        for ts in dates:
            for product in ("ETH-USD", "SOL-USD", "ADA-USD"):
                row = {
                    "timestamp_utc": ts,
                    "product_id": product,
                    "target_endpoint_utc_7d": ts + pd.Timedelta(days=7),
                    TARGET_POSITIVE: bool((ts.dayofyear + len(product)) % 2),
                    TARGET_RISK_ADJUSTED: np.sin(ts.dayofyear / 20.0) * 0.1,
                }
                for i, col in enumerate(MODEL_FEATURES):
                    row[col] = 0.01 + i * 0.001
                rows.append(row)
        return pd.DataFrame(rows)

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

    def test_validate_fold_enforces_endpoint_before_validation(self):
        df = self.sample_frame()
        fold = make_folds(df["timestamp_utc"])[0]
        train, val = validate_fold(fold, df)
        self.assertLess(
            pd.to_datetime(train["target_endpoint_utc_7d"], utc=True).max(),
            val["timestamp_utc"].min(),
        )

    def test_future_holdout_not_evaluated_before_it_exists(self):
        df = self.sample_frame()
        folds = make_folds(df["timestamp_utc"])
        self.assertFalse(any(f.split == "holdout" for f in folds))
        self.assertGreater(FUTURE_HOLDOUT_START_UTC, df["timestamp_utc"].max())

    def test_load_dataset_rejects_btc(self):
        df = self.sample_frame()
        df.loc[df.index[0], "product_id"] = "BTC-USD"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "v3.parquet"
            df.to_parquet(p, index=False)
            with self.assertRaises(ValueError):
                load_dataset(p)

    def test_classifier_summary_supports_probabilities(self):
        pred = pd.DataFrame({
            "model_id": ["x"] * 4,
            "split": ["development"] * 4,
            "actual_positive_absolute_7d": [False, False, True, True],
            "predicted_positive_probability": [0.1, 0.4, 0.6, 0.9],
        })
        out = summarize_classifier(pred)
        self.assertEqual(len(out), 1)
        self.assertGreater(out.iloc[0]["roc_auc"], 0.99)
        self.assertEqual(out.iloc[0]["accuracy_at_0_5"], 1.0)

    def test_regressor_summary_supports_scores(self):
        pred = pd.DataFrame({
            "model_id": ["x"] * 4,
            "split": ["development"] * 4,
            "actual_risk_adjusted_return_7d": [-0.2, -0.1, 0.1, 0.2],
            "predicted_risk_adjusted_return_7d": [-0.15, -0.05, 0.05, 0.15],
        })
        out = summarize_regressor(pred)
        self.assertEqual(len(out), 1)
        self.assertGreater(out.iloc[0]["pearson_correlation"], 0.99)
        self.assertEqual(out.iloc[0]["directional_sign_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
