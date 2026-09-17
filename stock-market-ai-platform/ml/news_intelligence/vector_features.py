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
NOVELTY_REFERENCE_LIMIT = 256


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
    historical_vectors = prior.tail(NOVELTY_REFERENCE_LIMIT)["embedding"].tolist()
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


def _one_feature_row(sorted_news, available_nanoseconds, decision_ts, lookback_days):
    """Use binary-search window boundaries instead of rescanning all news."""
    decision_ns = decision_ts.value
    end = int(np.searchsorted(available_nanoseconds, decision_ns, side="right"))
    start_72 = int(np.searchsorted(
        available_nanoseconds, (decision_ts - timedelta(hours=72)).value, side="right"
    ))
    start_24 = int(np.searchsorted(
        available_nanoseconds, (decision_ts - timedelta(hours=24)).value, side="right"
    ))
    start_prior = int(np.searchsorted(
        available_nanoseconds,
        (decision_ts - timedelta(days=int(lookback_days))).value,
        side="right",
    ))
    current72 = sorted_news.iloc[start_72:end]
    current24 = sorted_news.iloc[start_24:end]
    prior = sorted_news.iloc[start_prior:start_24]
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


def _sorted_news(news):
    result = news.sort_values(["available_at_utc", "article_id"]).reset_index(drop=True)
    timestamps = pd.DatetimeIndex(pd.to_datetime(result["available_at_utc"], utc=True)).asi8
    return result, timestamps


def build_asset_news_features(news, decisions, lookback_days=30):
    """Build asset features from news available no later than each decision."""
    decision_frame = _validated_decisions(decisions, require_asset=True)
    exploded = news.explode("asset_ids").rename(columns={"asset_ids": "asset_id"})
    grouped_news = {
        asset_id: _sorted_news(group)
        for asset_id, group in exploded.groupby("asset_id", sort=False)
    }
    rows = []
    for decision in decision_frame.itertuples(index=False):
        decision_ts = pd.Timestamp(decision.timestamp_utc)
        sorted_news, timestamps = grouped_news.get(
            decision.asset_id, (exploded.iloc[0:0], np.asarray([], dtype=np.int64))
        )
        rows.append({
            "timestamp_utc": decision_ts,
            "asset_id": decision.asset_id,
            **_one_feature_row(sorted_news, timestamps, decision_ts, lookback_days),
        })
    return pd.DataFrame(rows, columns=["timestamp_utc", "asset_id", *FEATURE_COLUMNS])


def build_market_news_features(news, decisions, lookback_days=30):
    """Build market-wide features from all news known at each decision."""
    decision_frame = _validated_decisions(decisions, require_asset=False)
    sorted_news, timestamps = _sorted_news(news)
    rows = []
    for decision in decision_frame.itertuples(index=False):
        decision_ts = pd.Timestamp(decision.timestamp_utc)
        rows.append({
            "timestamp_utc": decision_ts,
            **_one_feature_row(sorted_news, timestamps, decision_ts, lookback_days),
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
