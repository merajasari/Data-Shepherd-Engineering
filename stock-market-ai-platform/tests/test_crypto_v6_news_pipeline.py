import unittest

import pandas as pd

from ml.crypto_v6.phase1 import augment_datasets
from ml.crypto_v6.phase2 import (
    FEATURE_SET_V5,
    FEATURE_SET_V6,
    validate_paired_predictions,
)
from ml.crypto_v6.phase3 import compare_candidates
from ml.news_intelligence.schema import validate_news_frame
from ml.news_intelligence.vector_features import (
    build_asset_news_features,
    join_point_in_time_features,
)


class CryptoV6NewsPipelineTest(unittest.TestCase):
    def _news(self):
        return validate_news_frame(pd.DataFrame([
            {
                "article_id": "early",
                "source": "wire",
                "headline": "ETF approved",
                "published_at_utc": "2025-01-01T08:00:00Z",
                "ingested_at_utc": "2025-01-01T08:05:00Z",
                "asset_ids": ["BTC-USD"],
                "event_type": "regulation",
                "sentiment": 0.8,
                "relevance": 1.0,
                "source_reliability": 0.9,
                "embedding": [1.0, 0.0],
            },
            {
                "article_id": "future",
                "source": "wire",
                "headline": "Exploit",
                "published_at_utc": "2025-01-02T10:00:00Z",
                "ingested_at_utc": "2025-01-02T10:05:00Z",
                "asset_ids": ["BTC-USD"],
                "event_type": "exploit",
                "sentiment": -1.0,
                "relevance": 1.0,
                "source_reliability": 0.9,
                "embedding": [0.0, 1.0],
            },
        ]))

    def test_future_news_cannot_change_earlier_decision(self):
        decisions = pd.DataFrame([
            {"timestamp_utc": "2025-01-02T09:00:00Z", "asset_id": "BTC-USD"},
            {"timestamp_utc": "2025-01-02T11:00:00Z", "asset_id": "BTC-USD"},
        ])
        features = build_asset_news_features(self._news(), decisions)
        self.assertEqual(features.iloc[0]["news_count_24h"], 0.0)
        self.assertEqual(features.iloc[1]["news_count_24h"], 1.0)
        self.assertLess(features.iloc[1]["weighted_sentiment_24h"], 0.0)

    def test_join_preserves_every_decision_and_zero_fills_no_news(self):
        decisions = pd.DataFrame([
            {"timestamp_utc": "2025-01-02T09:00:00Z", "product_id": "ETH-USD", "value": 1},
            {"timestamp_utc": "2025-01-02T09:00:00Z", "product_id": "BTC-USD", "value": 2},
        ])
        features = build_asset_news_features(
            self._news(),
            decisions.rename(columns={"product_id": "asset_id"})[["timestamp_utc", "asset_id"]],
        )
        joined = join_point_in_time_features(
            decisions, features, asset_column="product_id", prefix="asset_news_"
        )
        self.assertEqual(len(joined), len(decisions))
        self.assertEqual(joined["value"].tolist(), [1, 2])
        self.assertEqual(joined.iloc[0]["asset_news_news_count_72h"], 0.0)
        self.assertEqual(joined.iloc[1]["asset_news_news_count_72h"], 1.0)

    def test_phase1_augments_v5_without_changing_its_universe(self):
        allocation = pd.DataFrame([
            {"timestamp_utc": "2025-01-02T09:00:00Z", "market_feature": 1.0},
            {"timestamp_utc": "2025-01-02T11:00:00Z", "market_feature": 2.0},
        ])
        ranking = pd.DataFrame([
            {"timestamp_utc": "2025-01-02T09:00:00Z", "product_id": "BTC-USD", "market_feature": 1.0},
            {"timestamp_utc": "2025-01-02T09:00:00Z", "product_id": "ETH-USD", "market_feature": 1.0},
            {"timestamp_utc": "2025-01-02T11:00:00Z", "product_id": "BTC-USD", "market_feature": 2.0},
            {"timestamp_utc": "2025-01-02T11:00:00Z", "product_id": "ETH-USD", "market_feature": 2.0},
        ])
        augmented_allocation, augmented_ranking = augment_datasets(
            self._news(), allocation, ranking
        )
        self.assertEqual(len(augmented_allocation), 2)
        self.assertEqual(len(augmented_ranking), 4)
        self.assertEqual(augmented_allocation["market_feature"].tolist(), [1.0, 2.0])
        eth = augmented_ranking[augmented_ranking["product_id"] == "ETH-USD"]
        self.assertTrue((eth["asset_news_news_count_72h"] == 0.0).all())

    def test_paired_prediction_clock_mismatch_fails_closed(self):
        base = {
            "timestamp_utc": pd.Timestamp("2025-01-01T00:00:00Z"),
            "fold_id": "dev_01",
            "model_id": "ridge",
            "horizon_days": 3,
        }
        paired = pd.DataFrame([
            {**base, "feature_set": FEATURE_SET_V5},
            {**base, "feature_set": FEATURE_SET_V6},
        ])
        keys = ["timestamp_utc", "fold_id", "model_id", "horizon_days"]
        validate_paired_predictions(paired, keys)
        with self.assertRaisesRegex(RuntimeError, "identical comparison clock"):
            validate_paired_predictions(paired.iloc[[0]], keys)

    def test_passing_development_comparison_never_auto_validates(self):
        rows = []
        for feature_set, primary, stress, sharpe, drawdown in (
            (FEATURE_SET_V5, 1.10, 1.02, 0.4, -0.20),
            (FEATURE_SET_V6, 1.20, 1.05, 0.6, -0.15),
        ):
            for cost, equity in ((25.0, primary), (50.0, stress)):
                rows.append({
                    "feature_set": feature_set,
                    "model_id": "ridge",
                    "horizon_days": 3,
                    "top_n": 3,
                    "cost_bps_round_trip": cost,
                    "ending_equity": equity,
                    "sharpe": sharpe,
                    "maximum_drawdown": drawdown,
                })
        result = compare_candidates(pd.DataFrame(rows))
        self.assertTrue(result["passed_all_development_checks"])
        self.assertFalse(result["automatic_promotion"])
        self.assertEqual(
            result["dashboard_validation_status"],
            "NOT_VALIDATED_REQUIRES_HUMAN_REVIEW",
        )


if __name__ == "__main__":
    unittest.main()
