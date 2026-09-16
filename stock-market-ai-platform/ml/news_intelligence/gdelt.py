"""GDELT GKG acquisition contract for point-in-time market-news research.

The global GKG is too large for an indiscriminate local download. This module
generates partition-pruned monthly BigQuery SQL and canonicalizes the filtered
CSV exports. It does not execute a billable query or require cloud credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from ml.news_intelligence.schema import validate_news_frame

GDELT_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
CRYPTO_ALIASES = {
    "BTC-USD": ("bitcoin", "btc"), "ETH-USD": ("ethereum", "ether"),
    "SOL-USD": ("solana",), "XRP-USD": ("ripple", "xrp"),
    "DOGE-USD": ("dogecoin",), "ADA-USD": ("cardano",),
    "AVAX-USD": ("avalanche blockchain", "avalanche crypto"),
    "LINK-USD": ("chainlink",), "LTC-USD": ("litecoin",),
    "BCH-USD": ("bitcoin cash",), "DOT-USD": ("polkadot",),
    "UNI-USD": ("uniswap",), "AAVE-USD": ("aave",),
    "ATOM-USD": ("cosmos blockchain", "cosmos crypto"),
    "NEAR-USD": ("near protocol",), "ICP-USD": ("internet computer",),
    "FIL-USD": ("filecoin",), "ETC-USD": ("ethereum classic",),
    "XLM-USD": ("stellar cryptocurrency", "stellar lumens"),
    "HBAR-USD": ("hedera", "hbar"), "SHIB-USD": ("shiba inu",),
    "SUI-USD": ("sui blockchain",), "OP-USD": ("optimism blockchain",),
    "ARB-USD": ("arbitrum",), "INJ-USD": ("injective protocol",),
}


def _sql(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def build_query(start, end, aliases=CRYPTO_ALIASES):
    """Return GoogleSQL for a half-open UTC interval [start, end)."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    if end <= start:
        raise ValueError("end must be after start")
    structs = []
    for asset_id, names in sorted(aliases.items()):
        pattern = r"(^|[^a-z0-9])(" + "|".join(re.escape(name.lower()) for name in names) + r")([^a-z0-9]|$)"
        structs.append(f"STRUCT('{_sql(asset_id)}' AS asset_id, r'{_sql(pattern)}' AS pattern)")
    alias_sql = ",\n    ".join(structs)
    start_sql, end_sql = start.strftime("%Y-%m-%d %H:%M:%S%z"), end.strftime("%Y-%m-%d %H:%M:%S%z")
    return f"""-- Standard SQL; dry-run before execution to inspect bytes processed.
WITH aliases AS (
  SELECT * FROM UNNEST([\n    {alias_sql}\n  ])
), source AS (
  SELECT DATE, SourceCommonName, DocumentIdentifier, V2Organizations, V2Tone
  FROM `{GDELT_TABLE}`
  WHERE _PARTITIONTIME >= TIMESTAMP('{start_sql}')
    AND _PARTITIONTIME < TIMESTAMP('{end_sql}')
), matched AS (
  SELECT s.*,
         ARRAY(SELECT a.asset_id FROM aliases a
               WHERE REGEXP_CONTAINS(LOWER(CONCAT(
                 COALESCE(s.DocumentIdentifier,''), ' ', COALESCE(s.V2Organizations,''))),
                 a.pattern)) AS asset_ids
  FROM source s
)
SELECT * FROM matched WHERE ARRAY_LENGTH(asset_ids) > 0
"""


def write_monthly_queries(start, end, output_dir, aliases=CRYPTO_ALIASES):
    start, end, output_dir = pd.Timestamp(start), pd.Timestamp(end), Path(output_dir)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    output_dir.mkdir(parents=True, exist_ok=True)
    cursor = start
    paths = []
    while cursor < end:
        boundary = min(cursor + pd.offsets.MonthBegin(1), end)
        path = output_dir / f"gdelt_gkg_{cursor:%Y_%m}.sql"
        path.write_text(build_query(cursor, boundary, aliases), encoding="utf-8")
        paths.append(path)
        cursor = boundary
    return paths


def _tone(value):
    try:
        return float(str(value).split(",", 1)[0]) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _embedding(text, dimensions=256):
    """Deterministic metadata-vector baseline; not claimed as a semantic model."""
    vector = np.zeros(dimensions, dtype=float)
    for token in re.findall(r"[a-z0-9_]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] % 2 else -1.0
    if np.linalg.norm(vector) == 0:
        vector[0] = 1.0
    return vector.tolist()


def canonicalize_export(frame, retrieved_at_utc=None):
    required = {"DATE", "SourceCommonName", "DocumentIdentifier", "V2Organizations",
                "V2Tone", "asset_ids"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("GDELT export missing columns: " + ", ".join(missing))
    observed = pd.to_datetime(frame["DATE"].astype(str), format="%Y%m%d%H%M%S", utc=True)
    retrieved = pd.Timestamp(retrieved_at_utc or datetime.now(timezone.utc))
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    rows = []
    for position, row in frame.reset_index(drop=True).iterrows():
        assets = row["asset_ids"]
        if isinstance(assets, str):
            assets = json.loads(assets)
        url = str(row["DocumentIdentifier"])
        metadata = " ".join((url, str(row.get("V2Organizations", ""))))
        article_id = hashlib.sha256(f"{row['DATE']}|{url}".encode()).hexdigest()
        rows.append({
            "article_id": article_id, "source": str(row["SourceCommonName"] or urlparse(url).netloc),
            "headline": "", "published_at_utc": observed.iloc[position],
            "ingested_at_utc": observed.iloc[position], "asset_ids": list(assets),
            "event_type": "gdelt_gkg_observation", "sentiment": float(np.clip(_tone(row["V2Tone"]), -1, 1)),
            "relevance": 1.0, "source_reliability": 0.5, "embedding": _embedding(metadata),
            "url": url, "retrieved_at_utc": retrieved,
            "timestamp_semantics": "gdelt_first_observed_not_publisher_timestamp",
            "embedding_semantics": "deterministic_metadata_hash_baseline",
        })
    return validate_news_frame(pd.DataFrame(rows))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2016-09-15T00:00:00Z")
    parser.add_argument("--end", default="2026-09-16T00:00:00Z")
    parser.add_argument("--sql-output", type=Path,
                        default=Path("data/research/news/gdelt/sql"))
    args = parser.parse_args(argv)
    paths = write_monthly_queries(args.start, args.end, args.sql_output)
    print(json.dumps({"provider":"gdelt_gkg_2_1", "queries":len(paths),
                      "first":str(paths[0]), "last":str(paths[-1]),
                      "queries_executed":False, "billable_action":False}, indent=2))


if __name__ == "__main__":
    main()
