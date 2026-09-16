"""Canonical, provider-neutral contract for archived market news."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = (
    "article_id", "source", "headline", "published_at_utc", "ingested_at_utc",
    "asset_ids", "event_type", "sentiment", "relevance", "source_reliability",
    "embedding",
)


def _parse_list(value, field):
    if isinstance(value, (list, tuple, np.ndarray)):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must be a JSON array") from exc
        if isinstance(parsed, list):
            return parsed
    raise ValueError(f"{field} must be an array")


def validate_news_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError("News feed missing columns: " + ", ".join(missing))
    result = frame.copy()
    for column in ("published_at_utc", "ingested_at_utc"):
        result[column] = pd.to_datetime(result[column], utc=True, errors="raise")
    if result["article_id"].astype(str).duplicated().any():
        raise ValueError("Duplicate article_id values")
    if (result["ingested_at_utc"] < result["published_at_utc"]).any():
        raise ValueError("News cannot be ingested before publication")
    for column in ("sentiment", "relevance", "source_reliability"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    if (~result["sentiment"].between(-1, 1)).any():
        raise ValueError("sentiment must be between -1 and 1")
    for column in ("relevance", "source_reliability"):
        if (~result[column].between(0, 1)).any():
            raise ValueError(f"{column} must be between 0 and 1")
    result["asset_ids"] = result["asset_ids"].map(lambda v: _parse_list(v, "asset_ids"))
    result["embedding"] = result["embedding"].map(lambda v: _parse_list(v, "embedding"))
    dimensions = result["embedding"].map(len)
    if dimensions.empty or dimensions.min() == 0 or dimensions.nunique() != 1:
        raise ValueError("All embeddings must have one non-zero common dimension")
    for vector in result["embedding"]:
        numeric = np.asarray(vector, dtype=float)
        if not np.isfinite(numeric).all() or np.linalg.norm(numeric) == 0:
            raise ValueError("Embeddings must be finite non-zero numeric vectors")
    result["available_at_utc"] = result[["published_at_utc", "ingested_at_utc"]].max(axis=1)
    return result.sort_values(["available_at_utc", "article_id"]).reset_index(drop=True)


def read_news(path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() in {".jsonl", ".ndjson"}:
        frame = pd.read_json(path, lines=True)
    else:
        frame = pd.read_csv(path)
    return validate_news_frame(frame)


def frame_sha256(frame: pd.DataFrame) -> str:
    stable = frame.drop(columns=["available_at_utc"], errors="ignore").copy()
    for column in ("asset_ids", "embedding"):
        stable[column] = stable[column].map(lambda v: json.dumps(list(v), separators=(",", ":")))
    payload = stable.sort_values("article_id").to_json(date_format="iso", orient="records")
    return hashlib.sha256(payload.encode()).hexdigest()

