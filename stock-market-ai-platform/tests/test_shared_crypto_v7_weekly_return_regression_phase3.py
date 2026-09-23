import unittest

import pandas as pd

from ml.shared_crypto_v7_weekly_return_regression import phase3


def summary(primary_overrides=None, diagnostic_overrides=None):
    primary = {
        "model_id": phase3.PRIMARY_MODEL,
        "fold_count": 6,
        "mean_btc_mae_improvement_vs_train_mean": -0.001157,
        "mean_alt_mae_improvement_vs_train_mean": -0.001390,
        "mean_btc_r2": -0.132072,
        "mean_alt_r2": -0.084017,
        "mean_btc_spearman": -0.015079,
        "mean_alt_spearman": 0.020830,
        "mean_sleeve_accuracy": 0.317471,
    }
    diagnostic = {
        **primary,
        "model_id": "ridge_regression_diagnostic",
    }
    primary.update(primary_overrides or {})
    diagnostic.update(diagnostic_overrides or {})
    return pd.DataFrame([primary, diagnostic])


class SharedCryptoV7Phase3Test(unittest.TestCase):
    def test_rejects_observed_consensus_lack_of_predictive_skill(self):
        disposition, decision = phase3.adjudicate(summary())
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V7_MODEL_FAMILY_BEFORE_PORTFOLIO_SIMULATION",
        )
        self.assertFalse(decision["portfolio_simulation_authorized"])
        self.assertTrue(
            decision["primary_model_evidence"]["consensus_no_predictive_skill"]
        )
        self.assertTrue(disposition.iloc[0]["consensus_no_predictive_skill"])

    def test_diagnostic_model_cannot_rescue_primary_model(self):
        strong_diagnostic = {
            "mean_btc_mae_improvement_vs_train_mean": 1.0,
            "mean_alt_mae_improvement_vs_train_mean": 1.0,
            "mean_btc_r2": 1.0,
            "mean_alt_r2": 1.0,
            "mean_sleeve_accuracy": 1.0,
        }
        _, decision = phase3.adjudicate(summary(
            diagnostic_overrides=strong_diagnostic
        ))
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V7_MODEL_FAMILY_BEFORE_PORTFOLIO_SIMULATION",
        )

    def test_nonconsensus_result_still_requires_human_review(self):
        _, decision = phase3.adjudicate(summary(primary_overrides={
            "mean_btc_r2": 0.01,
        }))
        self.assertEqual(
            decision["status"],
            "HUMAN_REVIEW_REQUIRED_BEFORE_PORTFOLIO_SIMULATION",
        )
        self.assertFalse(decision["portfolio_simulation_authorized"])

    def test_missing_primary_model_fails_closed(self):
        frame = summary()
        frame = frame[frame["model_id"] != phase3.PRIMARY_MODEL]
        with self.assertRaisesRegex(RuntimeError, "exactly one primary"):
            phase3.adjudicate(frame)


if __name__ == "__main__":
    unittest.main()
