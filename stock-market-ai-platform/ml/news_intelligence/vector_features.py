"""Leakage-safe vector and event features at market decision timestamps."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "news_count_24h",
    "news_count_72h",
    "weighted_sentiment_24h",
    "weighted_sentiment_72h",
    "news_velocity_24h_vs_72h",
    "mean_relevance_24h",
    "mean_source_reliability_24h",
    "novelty_24h",
    "adverse_event_score_24h",
)


def _cosine(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _features_for_window(current, prior):
    if current.empty:
        return {
            "weighted_sentiment_24h": 0.0,
            "mean_relevance_24h": 0.0,
            "mean_source_reliability_24h": 0.0,
            "novelty_24h": 0.0,
            "adverse_event_score_24h": 0.0,
        }
    weights = current["relevance"] * current["source_reliability"]
    sentiment = float(np.average(current["sentiment"], weights=weights)) if weights.sum() else 0.0
    historical_vectors = prior["embedding"].tolist()
    similarities = []
    for vector in current["embedding"].tolist():
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


def _one_feature_row(available, decision_ts, lookback_days):
    start_72 = decision_ts - timedelta(hours=72)
    start_24 = decision_ts - timedelta(hours=24)
    current72 = available[available["available_at_utc"] > start_72]
    current24 = available[available["available_at_utc"] > start_24]
    prior = available[
        (available["available_at_utc"] <= start_24)
        & (available["available_at_utc"] > decision_ts - timedelta(days=int(lookback_days)))
    ]
    values = _features_for_window(current24, prior)
    values["news_count_24h"] = float(len(current24))
    values["news_count_72h"] = float(len(current72))
    weights72 = current72["relevance"] * current72["source_reliability"]
    values["weighted_sentiment_72h"] = (
        float(np.average(current72["sentiment"], weights=weights72))
        if len(current72) and weights72.sum()
        else 0.0
    )
    values["news_velocity_24h_vs_72h"] = float(len(current24) / max(len(current72) / 3, 1))
    return values


def _validated_decisions(decisions, require_asset):
    required = {"timestamp_utc"} | ({"asset_id"} if require_asset else set())
    missing = sorted(required - set(decisions.columns))
    if missing:
        raise ValueError("Decision frame missing columns: " + ", ".join(missing))
    result = decisions.copy()
    result["timestamp_utc"] = pd.to_datetime(result["timestamp_utc"], utc=True, errors="raise")
    keys = ["timestamp_utc", "asset_id"] if require_asset else ["timestamp_utc"]
    return result[keys].drop_duplicates().sort_values(keys).reset_index(drop=True)


def build_asset_news_features(news, decisions, lookback_days=30):
    """Build asset features from news available no later than each decision."""
    decision_frame = _validated_decisions(decisions, require_asset=True)
    exploded = news.explode("asset_ids").rename(columns={"asset_ids": "asset_id"})
    rows = []
    for decision in decision_frame.itertuples(index=False):
        decision_ts = pd.Timestamp(decision.timestamp_utc)
        available = exploded[
            (exploded["asset_id"] == decision.asset_id)
            & (exploded["available_at_utc"] <= decision_ts)
        ]
        rows.append({
            "timestamp_utc": decision_ts,
            "asset_id": decision.asset_id,
            **_one_feature_row(available, decision_ts, lookback_days),
        })
    return pd.DataFrame(rows, columns=["timestamp_utc", "asset_id", *FEATURE_COLUMNS])


def build_market_news_features(news, decisions, lookback_days=30):
    """Build market-wide features from all news known at each decision."""
    decision_frame = _validated_decisions(decisions, require_asset=False)
    rows = []
    for decision in decision_frame.itertuples(index=False):
        decision_ts = pd.Timestamp(decision.timestamp_utc)
        available = news[news["available_at_utc"] <= decision_ts]
        rows.append({
            "timestamp_utc": decision_ts,
            **_one_feature_row(available, decision_ts, lookback_days),
        })
    return pd.DataFrame(rows, columns=["timestamp_utc", *FEATURE_COLUMNS])


def join_point_in_time_features(decisions, features, *, asset_column=None, prefix="news_"):
    """Left join features without changing the decision universe or row order."""
    original = decisions.copy()
    original["timestamp_utc"] = pd.to_datetime(original["timestamp_utc"], utc=True, errors="raise")
    right = features.copy()
    right["timestamp_utc"] = pd.to_datetime(right["timestamp_utc"], utc=True, errors="raise")
    keys = ["timestamp_utc"]
    if asset_column:
        if asset_column not in original:
            raise ValueError(f"Decision frame missing asset column: {asset_column}")
        right = right.rename(columns={"asset_id": asset_column})
        keys.append(asset_column)
    if right.duplicated(keys).any():
        raise ValueError("Point-in-time feature keys must be unique")
    rename = {column: f"{prefix}{column}" for column in FEATURE_COLUMNS}
    joined = original.merge(right.rename(columns=rename), on=keys, how="left", validate="many_to_one", sort=False)
    if len(joined) != len(original):
        raise RuntimeError("Point-in-time join changed the decision row count")
    joined[list(rename.values())] = joined[list(rename.values())].fillna(0.0)
    return joined
