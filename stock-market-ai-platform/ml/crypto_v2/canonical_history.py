"""Crypto V2 Phase 1B deterministic canonical-history construction.

This stage applies the pre-registered provider-priority policy to validated
provider-specific Bronze observations. It never modifies Bronze, averages
providers, fabricates candles, or uses return/model outcomes to select a source.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from ml.crypto_v1.validation import validate_bronze
from ml.crypto_v2.config import (
    BRONZE_ROOT,
    CANONICAL_HISTORY_PATH,
    CANONICAL_HISTORY_POLICY,
    CANONICAL_MANIFEST_PATH,
    CANONICAL_PROVENANCE_PATH,
    CANONICAL_PROVIDER_PRIORITY,
    DEFAULT_GRANULARITY,
    MODEL_ROOT,
    RESEARCH_VERSION,
)
from ml.crypto_v2.historical_inventory import discover_bronze

CANONICAL_COLUMNS = [
    "product_id",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "source_granularity",
]

PROVENANCE_COLUMNS = [
    "product_id",
    "source_provider",
    "selected_row_count",
    "selected_fraction",
    "first_selected_utc",
    "last_selected_utc",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate_rows(
    bronze_root=BRONZE_ROOT,
    granularity=DEFAULT_GRANULARITY,
    provider_priority=CANONICAL_PROVIDER_PRIORITY,
):
    """Load validated rows from only the pre-registered candidate providers."""
    priority = tuple(provider_priority)
    if not priority or len(set(priority)) != len(priority):
        raise ValueError("provider_priority must contain unique provider names")

    rank = {provider: index for index, provider in enumerate(priority)}
    frames = []
    sources = []
    seen = set()

    for data_path in discover_bronze(bronze_root, granularity):
        metadata_path = data_path.with_name("metadata.json")
        frame, report = validate_bronze(data_path, metadata_path)
        if report.provider not in rank:
            continue
        key = (report.product_id, report.provider)
        if key in seen:
            raise ValueError(f"Duplicate Bronze source series for {key}")
        seen.add(key)

        x = frame[[
            "product_id", "timestamp_utc", "open", "high", "low", "close", "volume"
        ]].copy()
        x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
        x["source_provider"] = report.provider
        x["source_granularity"] = report.granularity
        x["_provider_rank"] = rank[report.provider]
        frames.append(x)
        sources.append({
            "product_id": report.product_id,
            "provider": report.provider,
            "row_count": int(report.row_count),
            "candles_path": str(data_path),
            "candles_sha256": _sha256(data_path),
            "metadata_path": str(metadata_path),
            "metadata_sha256": _sha256(metadata_path),
        })

    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS + ["_provider_rank"]), sources

    candidates = pd.concat(frames, ignore_index=True)
    candidates = candidates.sort_values(
        ["product_id", "timestamp_utc", "_provider_rank", "source_provider"],
        kind="stable",
    ).reset_index(drop=True)
    return candidates, sources


def build_canonical_history(
    bronze_root=BRONZE_ROOT,
    granularity=DEFAULT_GRANULARITY,
    provider_priority=CANONICAL_PROVIDER_PRIORITY,
):
    candidates, sources = load_candidate_rows(
        bronze_root=bronze_root,
        granularity=granularity,
        provider_priority=provider_priority,
    )
    if candidates.empty:
        empty = pd.DataFrame(columns=CANONICAL_COLUMNS)
        provenance = pd.DataFrame(columns=PROVENANCE_COLUMNS)
        return empty, provenance, sources

    canonical = candidates.drop_duplicates(
        subset=["product_id", "timestamp_utc"], keep="first"
    ).copy()
    canonical = canonical[CANONICAL_COLUMNS].sort_values(
        ["product_id", "timestamp_utc"], kind="stable"
    ).reset_index(drop=True)

    if canonical.duplicated(["product_id", "timestamp_utc"]).any():
        raise RuntimeError("Canonical history contains duplicate product/timestamp rows")

    counts = canonical.groupby(
        ["product_id", "source_provider"], sort=True, dropna=False
    ).agg(
        selected_row_count=("timestamp_utc", "size"),
        first_selected_utc=("timestamp_utc", "min"),
        last_selected_utc=("timestamp_utc", "max"),
    ).reset_index()
    totals = canonical.groupby("product_id")["timestamp_utc"].size()
    counts["selected_fraction"] = counts.apply(
        lambda row: float(row["selected_row_count"] / totals.loc[row["product_id"]]),
        axis=1,
    )
    provenance = counts[PROVENANCE_COLUMNS].sort_values(
        ["product_id", "source_provider"]
    ).reset_index(drop=True)
    return canonical, provenance, sources


def run_canonical_history(
    bronze_root=BRONZE_ROOT,
    output_root=MODEL_ROOT,
    granularity=DEFAULT_GRANULARITY,
    provider_priority=CANONICAL_PROVIDER_PRIORITY,
):
    source_paths = []
    for data_path in discover_bronze(bronze_root, granularity):
        metadata_path = data_path.with_name("metadata.json")
        source_paths.extend([data_path, metadata_path])
    before = {str(path): _sha256(path) for path in source_paths}

    canonical, provenance, sources = build_canonical_history(
        bronze_root=bronze_root,
        granularity=granularity,
        provider_priority=provider_priority,
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    history_path = output_root / CANONICAL_HISTORY_PATH.name
    provenance_path = output_root / CANONICAL_PROVENANCE_PATH.name
    manifest_path = output_root / CANONICAL_MANIFEST_PATH.name

    canonical.to_parquet(history_path, index=False)
    provenance.to_csv(provenance_path, index=False)

    after = {str(path): _sha256(path) for path in source_paths}
    if before != after:
        raise RuntimeError("Bronze source artifacts changed during canonical construction")

    selected_by_provider = (
        canonical.groupby("source_provider").size().sort_index().to_dict()
        if len(canonical) else {}
    )
    manifest = {
        "research_version": RESEARCH_VERSION,
        "stage": "canonical_history_construction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "granularity": granularity,
        "policy": CANONICAL_HISTORY_POLICY,
        "provider_priority": list(provider_priority),
        "selection_uses_performance": False,
        "provider_values_averaged": False,
        "synthetic_rows_created": False,
        "canonical_row_count": int(len(canonical)),
        "product_count": int(canonical["product_id"].nunique()) if len(canonical) else 0,
        "selected_rows_by_provider": {
            str(provider): int(count) for provider, count in selected_by_provider.items()
        },
        "source_series": sources,
        "outputs": {
            "canonical_history": str(history_path),
            "canonical_provenance": str(provenance_path),
        },
        "next_step": (
            "Validate canonical coverage and provenance, freeze the Phase 1B artifact, "
            "then define leakage-safe Crypto V2 dataset construction before modeling."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest, canonical, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bronze-root", type=Path, default=BRONZE_ROOT)
    parser.add_argument("--output-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--granularity", default=DEFAULT_GRANULARITY, choices=("daily",))
    args = parser.parse_args(argv)
    manifest, _, _ = run_canonical_history(
        bronze_root=args.bronze_root,
        output_root=args.output_root,
        granularity=args.granularity,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
