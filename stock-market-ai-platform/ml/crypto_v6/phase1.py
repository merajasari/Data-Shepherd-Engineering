"""Crypto V6 Phase 1: build point-in-time news-vector features only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from ml.news_intelligence.schema import frame_sha256, read_news
from ml.news_intelligence.vector_features import FEATURE_COLUMNS, build_asset_news_features

DEFAULT_DECISIONS = Path("data/research/crypto_ten_year/reconstruction/crypto_v5/phase1/ranking_dataset.parquet")
DEFAULT_OUTPUT = Path("data/research/crypto_ten_year/reconstruction/crypto_v6/phase1")
HOLDOUT_START = pd.Timestamp("2026-09-16T00:00:00Z")


def run(news_path, decisions_path=DEFAULT_DECISIONS, output_root=DEFAULT_OUTPUT):
    news_path, decisions_path, output_root = map(Path, (news_path, decisions_path, output_root))
    news = read_news(news_path)
    decisions = pd.read_parquet(decisions_path, columns=["timestamp_utc", "product_id"])
    decisions = decisions.rename(columns={"product_id": "asset_id"})
    decisions["timestamp_utc"] = pd.to_datetime(decisions["timestamp_utc"], utc=True)
    decisions = decisions[decisions["timestamp_utc"] < HOLDOUT_START]
    features = build_asset_news_features(news, decisions)
    if (features["timestamp_utc"] >= HOLDOUT_START).any():
        raise ValueError("Crypto V6 Phase 1 crossed the future holdout boundary")
    output_root.mkdir(parents=True, exist_ok=True)
    feature_path = output_root / "news_vector_features.parquet"
    features.to_parquet(feature_path, index=False)
    manifest = {
        "research_version": "crypto_v6", "phase": 1,
        "stage": "point_in_time_news_vector_features",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "news_source": str(news_path), "news_frame_sha256": frame_sha256(news),
        "decision_source": str(decisions_path), "rows": int(len(features)),
        "feature_columns": list(FEATURE_COLUMNS), "future_holdout_start_utc": str(HOLDOUT_START),
        "safety": {"crypto_v5_modified": False, "holdout_scored": False,
                   "paper_state_modified": False, "brokerage_orders": False},
        "next_step": "Evaluate incremental news signal with purged walk-forward folds.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.news, args.decisions, args.output), indent=2))


if __name__ == "__main__":
    main()

