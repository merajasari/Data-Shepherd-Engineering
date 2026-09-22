import unittest

import pandas as pd

from ml.shared_crypto_v4_net_edge import phase3


class SharedCryptoV4Phase3Test(unittest.TestCase):
    def test_target_weights_respect_cash_and_concentration_limits(self):
        top3 = phase3.build_target_weights(
            "ALT", ["A", "B", "C", "D"], 3, 0.10, 0.25
        )
        self.assertAlmostEqual(top3[phase3.CASH], 0.25)
        self.assertAlmostEqual(sum(top3.values()), 1.0)
        self.assertLessEqual(max(value for key, value in top3.items() if key != phase3.CASH), 0.25)

        top5 = phase3.build_target_weights(
            "ALT", ["A", "B", "C", "D", "E"], 5, 0.10, 0.25
        )
        self.assertAlmostEqual(top5[phase3.CASH], 0.10)
        self.assertAlmostEqual(sum(top5.values()), 1.0)

    def test_turnover_cap_is_enforced(self):
        old = {phase3.CASH: 1.0}
        target = {"A": 0.25, "B": 0.25, "C": 0.25, phase3.CASH: 0.25}
        adjusted, actual = phase3.cap_turnover(old, target, 0.50)
        self.assertAlmostEqual(actual, 0.50)
        self.assertAlmostEqual(sum(adjusted.values()), 1.0)

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({"timestamp_utc": [phase3.HOLDOUT]})
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase3.validate_pre_holdout(frame, "test")

    def test_cash_target_is_fully_uninvested(self):
        weights = phase3.build_target_weights("CASH", ["A"], 3, 0.10, 0.25)
        self.assertEqual(weights, {phase3.CASH: 1.0})


if __name__ == "__main__":
    unittest.main()
