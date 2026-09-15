import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_ten_year_reconstruction import build_v3_complete_source
from ml.crypto_v3.phase1 import MODEL_FEATURES


class TenYearReconstructionTest(unittest.TestCase):
    def test_v3_filter_excludes_but_never_imputes_incomplete_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = pd.DataFrame({feature: [1.0, 1.0] for feature in MODEL_FEATURES})
            source.loc[1, MODEL_FEATURES[0]] = np.nan
            source["product_id"] = ["ETH-USD", "SOL-USD"]
            source["timestamp_utc"] = pd.to_datetime(["2021-01-01"] * 2, utc=True)
            source_path, output_path = root / "source.parquet", root / "complete.parquet"
            source.to_parquet(source_path, index=False)
            report = build_v3_complete_source(source_path, output_path)
            result = pd.read_parquet(output_path)
            self.assertEqual(report["source_rows"], 2)
            self.assertEqual(report["complete_rows"], 1)
            self.assertEqual(report["excluded_incomplete_rows"], 1)
            self.assertEqual(report["imputed_rows"], 0)
            self.assertEqual(result.iloc[0]["product_id"], "ETH-USD")


if __name__ == "__main__":
    unittest.main()
