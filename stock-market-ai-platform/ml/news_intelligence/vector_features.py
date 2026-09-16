"""Leakage-safe vector and event features available at each decision timestamp."""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = (
    "news_count_24h", "news_count_72h", "weighted_sentiment_24h",
    "weighted_sentiment_72h", "news_velocity_24h_vs_72h", "mean_relevance_24h",
    "mean_source_reliability_24h", "novelty_24h", "adverse_event_score_24h",
)


def _cosine(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _features_for_window(current, prior):
    if current.empty:
        return {name: 0.0 for name in FEATURE_COLUMNS}
    weights = current["relevance"] * current["source_reliability"]
    sentiment = float(np.average(current["sentiment"], weights=weights)) if weights.sum() else 0.0
    recent_vectors = current["embedding"].tolist()
    historical_vectors = prior["embedding"].tolist()
    similarities = []
    for vector in recent_vectors:
        comparisons = [_cosine(vector, old) for old in historical_vectors]
        similarities.append(max(comparisons) if comparisons else 0.0)
    negative = current["sentiment"].clip(upper=0).abs() * weights
    return {
        "weighted_sentiment_24h": sentiment,
        "mean_relevance_24h": float(current["relevance"].mean()),
        "mean_source_reliability_24h": float(current["source_reliability"].mean()),
        "novelty_24h": float(1 - np.mean(similarities)),
        "adverse_event_score_24h": float(negative.max()) if len(negative) else 0.0,
    }


def build_asset_news_features(news, decisions, lookback_days=30):
    """Create features using rows with available_at_utc <= decision timestamp only."""
    decision_frame = decisions.copy()
    decision_frame["timestamp_utc"] = pd.to_datetime(decision_frame["timestamp_utc"], utc=True)
    exploded = news.explode("asset_ids").rename(columns={"asset_ids": "asset_id"})
    rows = []
    for decision in decision_frame[["timestamp_utc", "asset_id"]].drop_duplicates().itertuples(index=False):
        decision_ts = pd.Timestamp(decision.timestamp_utc)
        available = exploded[(exploded["asset_id"] == decision.asset_id) &
                             (exploded["available_at_utc"] <= decision_ts)]
        start_72 = decision_ts - pd.Timedelta(hours=72)
        start_24 = decision_ts - pd.Timedelta(hours=24)
        current72 = available[available["available_at_utc"] > start_72]
        current24 = available[available["available_at_utc"] > start_24]
        prior = available[(available["available_at_utc"] <= start_24) &
                          (available["available_at_utc"] > decision_ts - pd.Timedelta(days=lookback_days))]
        values = _features_for_window(current24, prior)
        values["news_count_24h"] = float(len(current24))
        values["news_count_72h"] = float(len(current72))
        weights72 = current72["relevance"] * current72["source_reliability"]
        values["weighted_sentiment_72h"] = (
            float(np.average(current72["sentiment"], weights=weights72))
            if len(current72) and weights72.sum() else 0.0)
        values["news_velocity_24h_vs_72h"] = float(len(current24) / max(len(current72) / 3, 1))
        rows.append({"timestamp_utc": decision_ts, "asset_id": decision.asset_id, **values})
    return pd.DataFrame(rows, columns=["timestamp_utc", "asset_id", *FEATURE_COLUMNS])
