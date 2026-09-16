import unittest

import pandas as pd

from ml.news_intelligence.schema import validate_news_frame
from ml.news_intelligence.vector_features import build_asset_news_features


class NewsIntelligenceTest(unittest.TestCase):
    def _news(self):
        return pd.DataFrame([
            {"article_id":"early","source":"wire","headline":"ETF approved",
             "published_at_utc":"2026-01-01T08:00:00Z","ingested_at_utc":"2026-01-01T08:05:00Z",
             "asset_ids":["BTC-USD"],"event_type":"regulation","sentiment":0.8,
             "relevance":1.0,"source_reliability":0.9,"embedding":[1.0,0.0]},
            {"article_id":"late","source":"wire","headline":"Exchange exploit",
             "published_at_utc":"2026-01-02T10:00:00Z","ingested_at_utc":"2026-01-02T10:05:00Z",
             "asset_ids":["BTC-USD"],"event_type":"exploit","sentiment":-1.0,
             "relevance":1.0,"source_reliability":0.9,"embedding":[0.0,1.0]},
        ])

    def test_future_article_cannot_change_earlier_decision(self):
        validated = validate_news_frame(self._news())
        before = build_asset_news_features(validated, pd.DataFrame([
            {"timestamp_utc":"2026-01-02T09:00:00Z","asset_id":"BTC-USD"}]))
        after = build_asset_news_features(validated, pd.DataFrame([
            {"timestamp_utc":"2026-01-02T11:00:00Z","asset_id":"BTC-USD"}]))
        self.assertEqual(before.iloc[0]["news_count_24h"], 0)
        self.assertEqual(after.iloc[0]["news_count_24h"], 1)
        self.assertLess(after.iloc[0]["weighted_sentiment_24h"], 0)

    def test_ingestion_before_publication_is_rejected(self):
        frame = self._news().iloc[[0]].copy()
        frame.loc[:, "ingested_at_utc"] = "2026-01-01T07:59:00Z"
        with self.assertRaisesRegex(ValueError, "before publication"):
            validate_news_frame(frame)


if __name__ == "__main__":
    unittest.main()
