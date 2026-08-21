import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


DATA_INGESTION = Path(__file__).resolve().parents[1] / "data-ingestion"
if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

from validate_spark_feature_parity import (
    PARITY_COLUMNS,
    compare_feature_frames,
)


def parity_frame(rows: int = 8) -> pd.DataFrame:
    data = {"timestamp": np.arange(rows, dtype=np.int64)}
    for index, column in enumerate(PARITY_COLUMNS):
        values = np.arange(rows, dtype=float) + index / 100.0
        data[column] = values

    frame = pd.DataFrame(data)
    frame.loc[frame.index[-5:], "forward_return_5d"] = np.nan
    frame.loc[frame.index[-5:], "target_up_5d"] = np.nan
    frame.loc[frame.index[-5:], "target_trade_5d"] = np.nan
    return frame


class ProductionParityComparisonTests(unittest.TestCase):
    def test_identical_frames_pass(self):
        expected = parity_frame()
        actual = expected.sample(frac=1.0, random_state=7)

        summary = compare_feature_frames(expected, actual)

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["value_mismatches"], 0)
        self.assertEqual(summary["null_pattern_mismatches"], 0)

    def test_numeric_difference_fails(self):
        expected = parity_frame()
        actual = expected.copy()
        actual.loc[2, "return_5d"] += 0.1

        summary = compare_feature_frames(expected, actual)

        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["value_mismatches"], 1)
        self.assertGreater(summary["max_absolute_error"], 0.09)

    def test_null_pattern_difference_fails(self):
        expected = parity_frame()
        actual = expected.copy()
        actual.loc[actual.index[-1], "target_trade_5d"] = 0

        summary = compare_feature_frames(expected, actual)

        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["null_pattern_mismatches"], 1)

    def test_missing_column_fails(self):
        expected = parity_frame()
        actual = expected.drop(columns=["rsi_14"])

        summary = compare_feature_frames(expected, actual)

        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("rsi_14", summary["missing_columns"])


if __name__ == "__main__":
    unittest.main()
