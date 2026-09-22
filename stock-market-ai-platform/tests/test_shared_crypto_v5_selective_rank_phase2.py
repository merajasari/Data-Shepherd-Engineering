import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v5_selective_rank import phase2


class SharedCryptoV5Phase2Test(unittest.TestCase):
    def test_folds_have_fit_calibration_and_validation_purges(self):
        timestamps = pd.Series(pd.date_range(
            "2021-01-01T00:00:00Z", periods=1500, freq="24h"
        ))
        timestamps = timestamps[timestamps < phase2.HOLDOUT].reset_index(drop=True)
        folds = phase2.make_folds(timestamps)
        self.assertGreaterEqual(len(folds), 1)
        for fold in folds:
            fit = timestamps[fold["fit"]]
            calibration = timestamps[fold["calibration"]]
            validation = timestamps[fold["validation"]]
            self.assertLess(fit.max(), fold["fit_end"])
            self.assertGreaterEqual(calibration.min(), fold["calibration_start"])
            self.assertLess(calibration.max(), fold["train_end"])
            self.assertGreaterEqual(validation.min(), fold["start"])
            self.assertLess(validation.max(), fold["end"])
            self.assertLess(validation.max(), phase2.HOLDOUT)

    def test_conformal_lower_bound_adjustment_is_nonnegative(self):
        actual = np.array([0.01, 0.00, -0.02, 0.03])
        predicted = np.array([0.02, 0.01, 0.00, 0.02])
        adjustment = phase2.one_sided_conformal_adjustment(actual, predicted)
        self.assertGreaterEqual(adjustment, 0.0)
        lower = predicted - adjustment
        self.assertTrue(np.all(lower <= predicted))

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({"timestamp_utc": [phase2.HOLDOUT]})
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase2.validate_pre_holdout(frame, "test")


if __name__ == "__main__":
    unittest.main()
