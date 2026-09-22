import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


DATA_INGESTION = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

try:
    from pyspark.sql import SparkSession
except ImportError:
    SparkSession = None

from feature_transform import transform_to_features

if SparkSession is not None:
    from spark_feature_transform import transform_to_features_spark


GENERATED_COLUMNS = [
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_14",
    "rsi_centered",
    "momentum_10d",
    "forward_return_5d",
    "target_up_5d",
    "target_trade_5d",
]


@unittest.skipIf(SparkSession is None, "pyspark is not installed")
class SparkFeatureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder
            .master("local[2]")
            .appName("spark-feature-parity-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.session.timeZone", "UTC")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    @staticmethod
    def _gold_frame(rows: int = 90) -> pd.DataFrame:
        index = np.arange(rows, dtype=float)
        close = pd.Series(
            100.0 + index * 0.18 + np.sin(index / 2.3) * 3.0,
            dtype=float,
        )
        volume = pd.Series(
            1_000_000.0 + index * 2_500.0 + np.cos(index / 3.0) * 40_000.0,
            dtype=float,
        )

        return pd.DataFrame(
            {
                "symbol": ["AAPL"] * rows,
                "timestamp": (index.astype(np.int64) + 1) * 86_400_000,
                "timestamp_utc": pd.date_range(
                    "2025-01-01",
                    periods=rows,
                    freq="D",
                    tz="UTC",
                ).astype(str),
                "close": close,
                "open": close * (0.995 + np.sin(index) * 0.001),
                "high": close * 1.012,
                "low": close * 0.988,
                "volume": volume,
                "volume_sma_20": volume.rolling(20, min_periods=1).mean(),
                "daily_return": close.pct_change(),
                "sma_7": close.rolling(7, min_periods=1).mean(),
                "sma_20": close.rolling(20, min_periods=1).mean(),
                "sma_50": close.rolling(50, min_periods=1).mean(),
                "sma_200": close.rolling(200, min_periods=1).mean(),
            }
        )

    def test_spark_matches_pandas_feature_contract(self):
        gold = self._gold_frame()
        pandas_out = transform_to_features(gold).sort_values("timestamp")
        spark_input = self.spark.createDataFrame(gold)
        spark_out = (
            transform_to_features_spark(spark_input)
            .orderBy("timestamp")
            .toPandas()
        )

        self.assertEqual(len(spark_out), len(pandas_out))
        self.assertEqual(spark_out["timestamp"].tolist(), pandas_out["timestamp"].tolist())

        for column in GENERATED_COLUMNS:
            expected = pd.to_numeric(
                pandas_out[column],
                errors="coerce",
            ).to_numpy(dtype=float, na_value=np.nan)
            actual = pd.to_numeric(
                spark_out[column],
                errors="coerce",
            ).to_numpy(dtype=float, na_value=np.nan)

            np.testing.assert_allclose(
                actual,
                expected,
                rtol=1e-9,
                atol=1e-11,
                equal_nan=True,
                err_msg=f"Spark/Pandas mismatch in {column}",
            )

    def test_zero_denominators_return_null_without_ansi_failure(self):
        gold = self._gold_frame()
        gold.loc[30, [
            "close",
            "open",
            "volume",
            "volume_sma_20",
            "sma_7",
            "sma_20",
            "sma_50",
            "sma_200",
        ]] = 0.0

        output = (
            transform_to_features_spark(self.spark.createDataFrame(gold))
            .orderBy("timestamp")
            .toPandas()
        )

        generated = output[GENERATED_COLUMNS].apply(
            pd.to_numeric,
            errors="coerce",
        )
        self.assertFalse(np.isinf(generated.to_numpy(dtype=float)).any())
        self.assertTrue(pd.isna(output.loc[30, "intraday_range"]))
        self.assertTrue(pd.isna(output.loc[32, "return_2d"]))
        self.assertTrue(pd.isna(output.loc[35, "volume_change_5d"]))

    def test_spark_preserves_unknown_tail_targets(self):
        output = (
            transform_to_features_spark(
                self.spark.createDataFrame(self._gold_frame())
            )
            .orderBy("timestamp")
            .toPandas()
        )

        for column in (
            "forward_return_5d",
            "target_up_5d",
            "target_trade_5d",
        ):
            self.assertTrue(output[column].tail(5).isna().all())
            self.assertEqual(int(output[column].isna().sum()), 5)


if __name__ == "__main__":
    unittest.main()
