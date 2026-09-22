import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v4_net_edge import phase2


class SharedCryptoV4Phase2Test(unittest.TestCase):
    def test_folds_are_chronological_and_four_hour_purged(self):
        timestamps = pd.Series(pd.date_range(
            "2021-01-01T00:00:00Z", periods=1400, freq="24h"
        ))
        timestamps = timestamps[timestamps < phase2.HOLDOUT].reset_index(drop=True)
        folds = phase2.make_folds(timestamps)
        self.assertGreaterEqual(len(folds), 1)
        for fold in folds:
            train = timestamps[fold["train"]]
            validation = timestamps[fold["validation"]]
            self.assertEqual(fold["train_end"], fold["start"] - phase2.PURGE)
            self.assertLess(train.max(), fold["train_end"])
            self.assertGreaterEqual(validation.min(), fold["start"])
            self.assertLess(validation.max(), fold["end"])
            self.assertLess(validation.max(), phase2.HOLDOUT)

    def test_sleeve_selection_includes_cash_for_negative_edges(self):
        selected = phase2.choose_sleeve(
            np.array([0.02, -0.01, 0.01]),
            np.array([0.01, -0.02, 0.03]),
        )
        self.assertEqual(selected.tolist(), ["BTC", "CASH", "ALT"])

    def test_future_holdout_input_is_rejected(self):
        frame = pd.DataFrame({
            "timestamp_utc": [phase2.HOLDOUT],
            "value": [1.0],
        })
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase2.validate_pre_holdout(frame)


if __name__ == "__main__":
    unittest.main()
