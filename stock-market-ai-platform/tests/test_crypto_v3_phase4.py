import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.crypto_v3.phase2 import CLASSIFIER_MODEL_ID
from ml.crypto_v3.phase3 import CLASSIFIER_THRESHOLD
from ml.crypto_v3.phase4 import load_inputs


class CryptoV3Phase4Tests(unittest.TestCase):
    def test_classifier_only_rank_signal_is_probability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p2 = root / "phase2"
            p2.mkdir()
            dates = pd.date_range("2022-01-01", periods=2, freq="D", tz="UTC")
            clf = pd.DataFrame({
                "timestamp_utc": [dates[0], dates[0]],
                "product_id": ["ETH-USD", "SOL-USD"],
                "predicted_positive_probability": [0.7, 0.6],
                "model_id": [CLASSIFIER_MODEL_ID, CLASSIFIER_MODEL_ID],
                "fold_id": ["dev_01", "dev_01"],
                "split": ["development", "development"],
            })
            clf.to_parquet(p2 / "classifier_predictions.parquet", index=False)

            alt = pd.DataFrame({
                "timestamp_utc": [dates[0], dates[0]],
                "product_id": ["ETH-USD", "SOL-USD"],
                "return_1d": [0.01, 0.02],
            })
            source = pd.concat([
                alt,
                pd.DataFrame({
                    "timestamp_utc": [dates[0]],
                    "product_id": ["BTC-USD"],
                    "return_1d": [0.005],
                }),
            ], ignore_index=True)
            alt_path = root / "alt.parquet"
            src_path = root / "src.parquet"
            alt.to_parquet(alt_path, index=False)
            source.to_parquet(src_path, index=False)

            _, signals, _, _ = load_inputs(p2, alt_path, src_path)
            self.assertTrue((signals["predicted_risk_adjusted_return_7d"] == signals["predicted_positive_probability"]).all())
            self.assertTrue((signals["passes_classifier_gate"] == (signals["predicted_positive_probability"] > CLASSIFIER_THRESHOLD)).all())

    def test_btc_rejected_from_classifier_signals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p2 = root / "phase2"
            p2.mkdir()
            ts = pd.Timestamp("2022-01-01", tz="UTC")
            pd.DataFrame({
                "timestamp_utc": [ts],
                "product_id": ["BTC-USD"],
                "predicted_positive_probability": [0.8],
                "model_id": [CLASSIFIER_MODEL_ID],
                "fold_id": ["dev_01"],
                "split": ["development"],
            }).to_parquet(p2 / "classifier_predictions.parquet", index=False)
            pd.DataFrame({"timestamp_utc": [ts], "product_id": ["ETH-USD"], "return_1d": [0.01]}).to_parquet(root / "alt.parquet", index=False)
            pd.DataFrame({"timestamp_utc": [ts], "product_id": ["BTC-USD"], "return_1d": [0.01]}).to_parquet(root / "src.parquet", index=False)
            with self.assertRaises(ValueError):
                load_inputs(p2, root / "alt.parquet", root / "src.parquet")


if __name__ == "__main__":
    unittest.main()
