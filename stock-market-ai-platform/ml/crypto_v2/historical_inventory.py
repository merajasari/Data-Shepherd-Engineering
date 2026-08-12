"""Crypto V2 Phase 1A historical source and gap inventory.

This stage is read-only with respect to Bronze. It validates each provider's
native artifact, records coverage/gaps, hashes provenance, and never repairs
missing observations.
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
    BASELINE_MANIFEST_PATH,
    BRONZE_ROOT,
    DEFAULT_GRANULARITY,
    GAP_INVENTORY_PATH,
    HISTORICAL_POLICY,
    MODEL_ROOT,
    RESEARCH_VERSION,
    SOURCE_INVENTORY_PATH,
)

SOURCE_COLUMNS = [
    "provider", "granularity", "product_id", "first_available_utc",
    "last_available_utc", "row_count", "expected_calendar_days",
    "missing_days", "gap_block_count", "history_years", "coverage_fraction",
    "candles_sha256", "metadata_sha256", "candles_path", "metadata_path",
]

GAP_COLUMNS = [
    "provider", "granularity", "product_id", "after_utc", "before_utc",
    "missing_intervals",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_bronze(bronze_root=BRONZE_ROOT, granularity=DEFAULT_GRANULARITY):
    root = Path(bronze_root)
    paths = []
    if not root.exists():
        return paths
    for provider_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        base = provider_dir / granularity
        if not base.exists():
            continue
        paths.extend(sorted(base.glob("*/candles.csv")))
    return paths


def build_inventory(bronze_root=BRONZE_ROOT, granularity=DEFAULT_GRANULARITY):
    source_rows, gap_rows = [], []
    for data_path in discover_bronze(bronze_root, granularity):
        metadata_path = data_path.with_name("metadata.json")
        frame, report = validate_bronze(data_path, metadata_path)
        first = pd.to_datetime(report.first_available_utc, utc=True) if report.first_available_utc else pd.NaT
        last = pd.to_datetime(report.last_available_utc, utc=True) if report.last_available_utc else pd.NaT
        if pd.notna(first) and pd.notna(last):
            expected = int((last.normalize() - first.normalize()).days + 1)
            history_years = float((last - first).days / 365.25)
            coverage = float(len(frame) / expected) if expected else float("nan")
        else:
            expected, history_years, coverage = 0, float("nan"), float("nan")
        source_rows.append({
            "provider": report.provider,
            "granularity": report.granularity,
            "product_id": report.product_id,
            "first_available_utc": first,
            "last_available_utc": last,
            "row_count": int(report.row_count),
            "expected_calendar_days": expected,
            "missing_days": int(report.missing_interval_count),
            "gap_block_count": int(report.gap_count),
            "history_years": history_years,
            "coverage_fraction": coverage,
            "candles_sha256": _sha256(data_path),
            "metadata_sha256": _sha256(metadata_path),
            "candles_path": str(data_path),
            "metadata_path": str(metadata_path),
        })
        for gap in report.gaps:
            gap_rows.append({
                "provider": report.provider,
                "granularity": report.granularity,
                "product_id": report.product_id,
                "after_utc": gap.after_utc,
                "before_utc": gap.before_utc,
                "missing_intervals": int(gap.missing_intervals),
            })
    inventory = pd.DataFrame(source_rows, columns=SOURCE_COLUMNS)
    gaps = pd.DataFrame(gap_rows, columns=GAP_COLUMNS)
    if len(inventory):
        inventory = inventory.sort_values(["provider", "product_id"]).reset_index(drop=True)
    if len(gaps):
        gaps = gaps.sort_values(["provider", "product_id", "after_utc"]).reset_index(drop=True)
    return inventory, gaps


def run_inventory(bronze_root=BRONZE_ROOT, output_root=MODEL_ROOT,
                  granularity=DEFAULT_GRANULARITY):
    inventory, gaps = build_inventory(bronze_root, granularity)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    source_path = output_root / SOURCE_INVENTORY_PATH.name
    gap_path = output_root / GAP_INVENTORY_PATH.name
    manifest_path = output_root / BASELINE_MANIFEST_PATH.name
    inventory.to_csv(source_path, index=False)
    gaps.to_csv(gap_path, index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "stage": "historical_baseline_inventory",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "granularity": granularity,
        "provider_count": int(inventory["provider"].nunique()) if len(inventory) else 0,
        "asset_count": int(inventory["product_id"].nunique()) if len(inventory) else 0,
        "source_series_count": int(len(inventory)),
        "total_rows": int(inventory["row_count"].sum()) if len(inventory) else 0,
        "total_missing_days": int(inventory["missing_days"].sum()) if len(inventory) else 0,
        "sources_with_gaps": int((inventory["missing_days"] > 0).sum()) if len(inventory) else 0,
        "policy": HISTORICAL_POLICY,
        "outputs": {
            "source_inventory": str(source_path),
            "gap_inventory": str(gap_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, inventory, gaps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bronze-root", type=Path, default=BRONZE_ROOT)
    parser.add_argument("--output-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--granularity", default=DEFAULT_GRANULARITY, choices=("daily",))
    args = parser.parse_args(argv)
    manifest, _, _ = run_inventory(args.bronze_root, args.output_root, args.granularity)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
