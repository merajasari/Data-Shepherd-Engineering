"""Contracts and leakage traps for Crypto V1 Phase 3."""

import unittest

import numpy as np
import pandas as pd

from ml.crypto_v1.phase3 import (
    HOLDOUT_START_UTC, MODEL_FEATURES, Fold, add_ranks, daily_metrics,
    make_folds, model_definitions, prediction_frame, validate_fold,
)


def synthetic_panel(horizon=3):
    dates = pd.date_range("2020-02-29", "2026-08-10", tz="UTC")
    rows = []
    for date_index, timestamp in enumerate(dates):
        for asset_index, product in enumerate(("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LTC-USD")):
            row = {feature: np.sin((date_index + asset_index + position) / 17)
                   for position, feature in enumerate(MODEL_FEATURES)}
            row.update({
                "timestamp_utc": timestamp, "product_id": product,
                f"target_endpoint_utc_{horizon}d": timestamp + pd.Timedelta(days=horizon),
                f"forward_return_relative_to_btc_{horizon}d": row[MODEL_FEATURES[0]] * .02,
                "btc_regime": "neutral",
            })
            rows.append(row)
    return pd.DataFrame(rows)


class Phase3SplitTests(unittest.TestCase):
    def test_folds_are_chronological_deterministic_and_purged(self):
        frame = synthetic_panel()
        first = make_folds(frame["timestamp_utc"], 3)
        second = make_folds(frame["timestamp_utc"], 3)
        self.assertEqual(first, second)
        for fold in first:
            train, validation = validate_fold(fold, frame)
            self.assertLess(train["timestamp_utc"].max(), validation["timestamp_utc"].min())
            self.assertLess(train["target_endpoint_utc_3d"].max(), validation["timestamp_utc"].min())
            self.assertFalse(set(train.index) & set(validation.index))
            self.assertEqual((fold.validation_start_utc - fold.train_end_utc).days - 1, 3)

    def test_holdout_is_excluded_from_all_development_folds(self):
        folds = make_folds(synthetic_panel()["timestamp_utc"], 3)
        development = [fold for fold in folds if fold.split == "development"]
        holdout = [fold for fold in folds if fold.split == "holdout"]
        self.assertEqual(len(holdout), 1)
        self.assertEqual(holdout[0].validation_start_utc, HOLDOUT_START_UTC)
        self.assertTrue(all(fold.validation_end_utc < HOLDOUT_START_UTC for fold in development))
        self.assertTrue(all(fold.train_end_utc < HOLDOUT_START_UTC for fold in development))

    def test_feature_list_has_no_target_or_forward_columns(self):
        self.assertFalse(any(name.startswith(("target_", "forward_")) for name in MODEL_FEATURES))

    def test_preprocessing_is_fit_only_on_training_data(self):
        frame = synthetic_panel()
        fold = make_folds(frame["timestamp_utc"], 3)[0]
        train, validation = validate_fold(fold, frame)
        model = model_definitions()["ridge"].fit(train[list(MODEL_FEATURES)], train["forward_return_relative_to_btc_3d"])
        expected = train[list(MODEL_FEATURES)].median().to_numpy()
        np.testing.assert_allclose(model.named_steps["imputer"].statistics_, expected)
        self.assertFalse(np.allclose(expected, validation[list(MODEL_FEATURES)].median().to_numpy()))

    def test_future_mutation_does_not_change_earlier_fit_or_predictions(self):
        frame = synthetic_panel()
        fold = make_folds(frame["timestamp_utc"], 3)[0]
        train, validation = validate_fold(fold, frame)
        target = "forward_return_relative_to_btc_3d"
        original = model_definitions()["ridge"].fit(train[list(MODEL_FEATURES)], train[target])
        original_scores = original.predict(validation[list(MODEL_FEATURES)])
        mutated = frame.copy()
        future = mutated["timestamp_utc"] > fold.validation_end_utc
        mutated.loc[future, list(MODEL_FEATURES)] = 1e9
        mutated.loc[future, target] = -1e9
        changed_train, changed_validation = validate_fold(fold, mutated)
        changed = model_definitions()["ridge"].fit(changed_train[list(MODEL_FEATURES)], changed_train[target])
        np.testing.assert_allclose(original_scores, changed.predict(changed_validation[list(MODEL_FEATURES)]))


class Phase3MetricTests(unittest.TestCase):
    def test_ranking_and_ic_are_correct(self):
        date = pd.Timestamp("2024-01-01", tz="UTC")
        raw = pd.DataFrame({
            "timestamp_utc": [date] * 4, "product_id": list("ABCD"),
            "actual_btc_relative_forward_return": [.4, .3, .2, .1],
            "predicted_score": [4., 3., 2., 1.], "fold_id": ["x"] * 4,
            "split": ["development"] * 4, "model_id": ["ridge"] * 4,
            "horizon_days": [1] * 4, "btc_regime": ["risk_on"] * 4,
        })
        ranked = add_ranks(raw)
        self.assertEqual(ranked["actual_cross_sectional_rank"].tolist(), [1, 2, 3, 4])
        self.assertEqual(ranked["predicted_cross_sectional_rank"].tolist(), [1, 2, 3, 4])
        metrics = daily_metrics(ranked)
        self.assertAlmostEqual(metrics.loc[0, "ic"], 1.0)
        self.assertAlmostEqual(metrics.loc[0, "top_minus_bottom_spread"], .3)

    def test_prediction_output_keys_are_unique(self):
        frame = synthetic_panel(1)
        fold = make_folds(frame["timestamp_utc"], 1)[0]
        _, validation = validate_fold(fold, frame)
        result = prediction_frame(validation, np.arange(len(validation)), 1, fold, "test")
        self.assertFalse(result.duplicated(["timestamp_utc", "product_id", "fold_id", "model_id", "horizon_days"]).any())


if __name__ == "__main__":
    unittest.main()
