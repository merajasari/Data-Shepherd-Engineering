import unittest
import numpy as np
import pandas as pd

from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES
from ml.crypto_v5.phase1 import build_datasets


class CryptoV5Phase1Test(unittest.TestCase):
    def test_builds_dual_layer_datasets_without_future_features(self):
        rows=[]
        for day in pd.date_range("2025-01-01", periods=2, tz="UTC"):
            for i in range(12):
                row={"timestamp_utc":day,"product_id":"BTC-USD" if i==0 else f"ALT{i}-USD",
                     "is_eligible":True,"close":100+i}
                row.update({f:0.01+i/1000 for f in REQUIRED_FEATURES})
                for h in (1,3,7):
                    row[f"forward_return_{h}d"]=0.01*i
                    row[f"target_endpoint_utc_{h}d"]=day+pd.Timedelta(h, unit="D")
                rows.append(row)
        allocation,ranking=build_datasets(pd.DataFrame(rows))
        self.assertEqual(len(allocation),2)
        self.assertEqual(ranking.groupby("timestamp_utc")["product_id"].nunique().min(),11)
        self.assertFalse(any(c.startswith("future_") for c in allocation.columns))
        self.assertTrue(np.isfinite(allocation.select_dtypes("number")).all().all())


if __name__ == "__main__":
    unittest.main()
