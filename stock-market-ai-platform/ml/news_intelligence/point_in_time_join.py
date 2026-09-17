"""Join canonical news features to stock or crypto decision datasets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from ml.news_intelligence.schema import read_news
from ml.news_intelligence.vector_features import (
    FEATURE_COLUMNS,
    build_asset_news_features,
    build_market_news_features,
    join_point_in_time_features,
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_table(path):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def build_joined_dataset(news, decisions, *, scope="asset", asset_column="product_id",
                         prefix="news_", lookback_days=30):
    """Return a causal news augmentation without changing decision coverage."""
    if scope not in {"asset", "market"}:
        raise ValueError("scope must be 'asset' or 'market'")
    if scope == "asset":
        if asset_column not in decisions:
            raise ValueError(f"Decision frame missing asset column: {asset_column}")
        feature_decisions = decisions[["timestamp_utc", asset_column]].rename(
            columns={asset_column: "asset_id"}
        )
        features = build_asset_news_features(news, feature_decisions, lookback_days)
        return join_point_in_time_features(
            decisions, features, asset_column=asset_column, prefix=prefix
        )
    features = build_market_news_features(news, decisions[["timestamp_utc"]], lookback_days)
    return join_point_in_time_features(decisions, features, prefix=prefix)


def run(news_path, decisions_path, output_path, *, scope="asset",
        asset_column="product_id", prefix="news_", lookback_days=30):
    news_path, decisions_path, output_path = map(
        Path, (news_path, decisions_path, output_path)
    )
    news, decisions = read_news(news_path), _read_table(decisions_path)
    joined = build_joined_dataset(
        news,
        decisions,
        scope=scope,
        asset_column=asset_column,
        prefix=prefix,
        lookback_days=lookback_days,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    if output_path.suffix.lower() == ".parquet":
        joined.to_parquet(temporary, index=False)
    else:
        joined.to_csv(temporary, index=False)
    temporary.replace(output_path)
    manifest = {
        "stage": "point_in_time_news_decision_join",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "asset_column": asset_column if scope == "asset" else None,
        "timestamp_rule": "available_at_utc <= decision timestamp",
        "lookback_days": int(lookback_days),
        "input_rows": len(decisions),
        "output_rows": len(joined),
        "feature_columns": [f"{prefix}{name}" for name in FEATURE_COLUMNS],
        "inputs": {
            "news": {"path": str(news_path), "sha256": _sha256(news_path)},
            "decisions": {"path": str(decisions_path), "sha256": _sha256(decisions_path)},
        },
        "output": {"path": str(output_path), "sha256": _sha256(output_path)},
        "safety": {
            "source_decisions_modified": False,
            "model_artifacts_modified": False,
            "paper_state_modified": False,
            "dashboard_modified": False,
            "brokerage_orders": False,
        },
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=("asset", "market"), default="asset")
    parser.add_argument("--asset-column", default="product_id")
    parser.add_argument("--prefix", default="news_")
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        args.news,
        args.decisions,
        args.output,
        scope=args.scope,
        asset_column=args.asset_column,
        prefix=args.prefix,
        lookback_days=args.lookback_days,
    ), indent=2))


if __name__ == "__main__":
    main()
