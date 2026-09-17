"""Crypto V6 Phase 1: point-in-time news joins onto frozen V5 datasets.

This phase creates research inputs only.  It never scores the future holdout,
mutates V5, changes paper state, updates the dashboard, or contacts a broker.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from ml.crypto_v5.config import FUTURE_HOLDOUT_START_UTC, PHASE1_ROOT as V5_PHASE1_ROOT
from ml.news_intelligence.schema import frame_sha256, read_news, validate_news_frame
from ml.news_intelligence.vector_features import (
    FEATURE_COLUMNS,
    NOVELTY_REFERENCE_LIMIT,
    build_asset_news_features,
    build_market_news_features,
    join_point_in_time_features,
)


RESEARCH_VERSION = "crypto_v6"
DEFAULT_NEWS = Path("data/research/news/gdelt/canonical/canonical_news.parquet")
DEFAULT_OUTPUT = Path("data/research/crypto_ten_year/reconstruction/crypto_v6/phase1")
DEFAULT_ALLOCATION = V5_PHASE1_ROOT / "allocation_dataset.parquet"
DEFAULT_RANKING = V5_PHASE1_ROOT / "ranking_dataset.parquet"
ALLOCATION_PREFIX = "market_news_"
RANKING_PREFIX = "asset_news_"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_news(path):
    path = Path(path)
    if path.is_file():
        return read_news(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    combined = path / "canonical_news.parquet"
    if combined.exists():
        return read_news(combined)
    sources = sorted(path.glob("news_*.parquet"))
    if not sources:
        raise FileNotFoundError(f"No canonical news files found under {path}")
    return validate_news_frame(pd.concat([pd.read_parquet(source) for source in sources], ignore_index=True))


def augment_datasets(news, allocation, ranking, holdout_start=FUTURE_HOLDOUT_START_UTC):
    allocation, ranking = allocation.copy(), ranking.copy()
    for frame in (allocation, ranking):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
        if (frame["timestamp_utc"] >= holdout_start).any():
            raise RuntimeError("Crypto V6 Phase 1 refuses future-holdout rows")
    if "product_id" not in ranking:
        raise ValueError("V5 ranking dataset is missing product_id")
    market = build_market_news_features(news, allocation[["timestamp_utc"]])
    assets = build_asset_news_features(
        news,
        ranking[["timestamp_utc", "product_id"]].rename(columns={"product_id": "asset_id"}),
    )
    augmented_allocation = join_point_in_time_features(
        allocation, market, prefix=ALLOCATION_PREFIX
    )
    augmented_ranking = join_point_in_time_features(
        ranking, assets, asset_column="product_id", prefix=RANKING_PREFIX
    )
    if list(augmented_allocation[allocation.columns].columns) != list(allocation.columns):
        raise RuntimeError("V5 allocation columns changed during V6 augmentation")
    if list(augmented_ranking[ranking.columns].columns) != list(ranking.columns):
        raise RuntimeError("V5 ranking columns changed during V6 augmentation")
    return augmented_allocation, augmented_ranking


def run(news_path=DEFAULT_NEWS, allocation_path=DEFAULT_ALLOCATION,
        ranking_path=DEFAULT_RANKING, output_root=DEFAULT_OUTPUT):
    news_path, allocation_path, ranking_path, output_root = map(
        Path, (news_path, allocation_path, ranking_path, output_root)
    )
    for path in (allocation_path, ranking_path):
        if not path.exists():
            raise FileNotFoundError(path)
    input_hashes = {
        "allocation": _sha256(allocation_path),
        "ranking": _sha256(ranking_path),
    }
    news = load_news(news_path)
    allocation = pd.read_parquet(allocation_path)
    ranking = pd.read_parquet(ranking_path)
    augmented_allocation, augmented_ranking = augment_datasets(news, allocation, ranking)
    output_root.mkdir(parents=True, exist_ok=True)
    allocation_output = output_root / "allocation_dataset.parquet"
    ranking_output = output_root / "ranking_dataset.parquet"
    augmented_allocation.to_parquet(allocation_output, index=False)
    augmented_ranking.to_parquet(ranking_output, index=False)
    if input_hashes != {"allocation": _sha256(allocation_path), "ranking": _sha256(ranking_path)}:
        raise RuntimeError("A frozen V5 Phase 1 input changed during V6 Phase 1")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "point_in_time_news_join",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "news_source": str(news_path),
        "news_frame_sha256": frame_sha256(news),
        "v5_inputs": input_hashes,
        "rows": {"allocation": len(augmented_allocation), "ranking": len(augmented_ranking)},
        "features": {
            "allocation": [f"{ALLOCATION_PREFIX}{name}" for name in FEATURE_COLUMNS],
            "ranking": [f"{RANKING_PREFIX}{name}" for name in FEATURE_COLUMNS],
        },
        "timestamp_rule": "available_at_utc <= decision timestamp",
        "novelty_reference": f"most recent {NOVELTY_REFERENCE_LIMIT} causal prior articles",
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "outputs": {"allocation": str(allocation_output), "ranking": str(ranking_output)},
        "dashboard_eligibility": False,
        "safety": {
            "crypto_v5_modified": False,
            "holdout_scored": False,
            "paper_state_modified": False,
            "dashboard_modified": False,
            "automatic_promotion": False,
            "brokerage_orders": False,
        },
        "next_step": "Train paired V5 market-only and V6 market-plus-news candidates on identical purged folds.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news", type=Path, default=DEFAULT_NEWS)
    parser.add_argument("--allocation", type=Path, default=DEFAULT_ALLOCATION)
    parser.add_argument("--ranking", type=Path, default=DEFAULT_RANKING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.news, args.allocation, args.ranking, args.output), indent=2))


if __name__ == "__main__":
    main()
