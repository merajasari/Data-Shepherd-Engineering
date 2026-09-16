import unittest
import pandas as pd
from ml.crypto_v5.phase2 import FUTURE_HOLDOUT_START_UTC, PURGE_DAYS, make_folds


class CryptoV5Phase2Test(unittest.TestCase):
    def test_folds_are_chronological_purged_and_pre_holdout(self):
        dates=pd.date_range("2021-01-16","2026-09-07",freq="D",tz="UTC")
        folds=make_folds(dates)
        self.assertGreater(len(folds),1)
        for fold in folds:
            self.assertLess(fold.train_end_utc,fold.validation_start_utc-pd.Timedelta(PURGE_DAYS,unit="D"))
            self.assertLess(fold.validation_end_utc,FUTURE_HOLDOUT_START_UTC)
        self.assertTrue(all(a.validation_end_utc < b.validation_start_utc for a,b in zip(folds,folds[1:])))


if __name__=="__main__":unittest.main()
