"""Acquire and validate the observed ten-year daily history for the crypto universe.

This pipeline is additive: it writes beneath data/research/crypto_ten_year and
never replaces the frozen V1/V2/V3/V4 artifacts. Assets begin on their actual
available dates; no pre-launch rows, interpolation, or synthetic candles exist.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pandas as pd

from ml.crypto_v1.config import CRYPTO_UNIVERSE
from ml.crypto_v2.canonical_history import run_canonical_history
from ml.crypto_v2.historical_inventory import run_inventory
from ml.crypto_v2.kraken_archive import download_archive, import_archive

DEFAULT_START = "2016-09-15"
DEFAULT_END = "2026-09-16"  # exclusive; includes the 2026-09-15 daily row if available
DEFAULT_ROOT = Path("data/research/crypto_ten_year")
DEFAULT_EXISTING_BRONZE_ROOT = Path("data/bronze/crypto")


def stage_existing_coinbase(source_root: Path, destination_root: Path) -> int:
    """Copy validated Coinbase Bronze into the isolated reconstruction workspace."""
    source = Path(source_root) / "coinbase_exchange"
    destination = Path(destination_root) / "coinbase_exchange"
    if not source.exists():
        return 0
    shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
    return len(list(destination.glob("daily/*/candles.csv")))


def coverage_report(canonical: pd.DataFrame, universe=CRYPTO_UNIVERSE) -> pd.DataFrame:
    """Describe real coverage without implying every asset existed for ten years."""
    rows = []
    for product_id in universe:
        asset = canonical.loc[canonical["product_id"] == product_id].sort_values("timestamp_utc")
        if asset.empty:
            rows.append({"product_id": product_id, "first_available_utc": None,
                         "last_available_utc": None, "observed_days": 0,
                         "missing_calendar_days": None, "history_years": 0.0})
            continue
        first, last = pd.Timestamp(asset.iloc[0]["timestamp_utc"]), pd.Timestamp(asset.iloc[-1]["timestamp_utc"])
        expected = (last.normalize() - first.normalize()).days + 1
        rows.append({"product_id": product_id, "first_available_utc": first.isoformat(),
                     "last_available_utc": last.isoformat(), "observed_days": int(len(asset)),
                     "missing_calendar_days": int(expected - len(asset)),
                     "history_years": round((last - first).days / 365.25, 4)})
    return pd.DataFrame(rows)


def validate_canonical(canonical: pd.DataFrame, start: str, end: str) -> None:
    if canonical.empty:
        raise ValueError("The downloaded archive produced no canonical crypto observations")
    if canonical.duplicated(["product_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate product/timestamp rows found in canonical history")
    timestamps = pd.to_datetime(canonical["timestamp_utc"], utc=True)
    if (timestamps < pd.Timestamp(start, tz="UTC")).any() or (timestamps >= pd.Timestamp(end, tz="UTC")).any():
        raise ValueError("Canonical history contains observations outside the requested clock")
    price_columns = ["open", "high", "low", "close"]
    if (canonical[price_columns] <= 0).any().any() or (canonical["volume"] < 0).any():
        raise ValueError("Canonical history contains invalid OHLCV values")


def clip_canonical_window(canonical: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Restrict combined providers to the registered reconstruction clock."""
    result = canonical.copy()
    timestamps = pd.to_datetime(result["timestamp_utc"], utc=True)
    mask = ((timestamps >= pd.Timestamp(start, tz="UTC")) &
            (timestamps < pd.Timestamp(end, tz="UTC")))
    return result.loc[mask].sort_values(
        ["product_id", "timestamp_utc"], kind="stable").reset_index(drop=True)


def rewrite_clipped_canonical(model_root: Path, manifest: dict,
                              canonical: pd.DataFrame, start: str, end: str) -> None:
    """Persist clipped history and keep canonical provenance/manifest consistent."""
    history_path = Path(manifest["outputs"]["canonical_history"])
    provenance_path = Path(manifest["outputs"]["canonical_provenance"])
    canonical.to_parquet(history_path, index=False)
    counts = canonical.groupby(["product_id", "source_provider"], sort=True).agg(
        selected_row_count=("timestamp_utc", "size"),
        first_selected_utc=("timestamp_utc", "min"),
        last_selected_utc=("timestamp_utc", "max"),
    ).reset_index()
    totals = canonical.groupby("product_id")["timestamp_utc"].size()
    counts["selected_fraction"] = counts.apply(
        lambda row: float(row["selected_row_count"] / totals.loc[row["product_id"]]), axis=1)
    counts[["product_id", "source_provider", "selected_row_count", "selected_fraction",
            "first_selected_utc", "last_selected_utc"]].to_csv(provenance_path, index=False)
    manifest["canonical_row_count"] = int(len(canonical))
    manifest["product_count"] = int(canonical["product_id"].nunique())
    manifest["selected_rows_by_provider"] = {
        str(k): int(v) for k, v in canonical.groupby("source_provider").size().items()}
    manifest["requested_start_utc"] = pd.Timestamp(start, tz="UTC").isoformat()
    manifest["requested_end_utc_exclusive"] = pd.Timestamp(end, tz="UTC").isoformat()
    (Path(model_root) / "canonical_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")


def run(root=DEFAULT_ROOT, start=DEFAULT_START, end=DEFAULT_END, archive=None,
        force_download=False, existing_bronze_root=DEFAULT_EXISTING_BRONZE_ROOT):
    root = Path(root)
    source_root, bronze_root, model_root = root / "source", root / "bronze", root / "canonical"
    archive_path = Path(archive) if archive else source_root / "Kraken_OHLCVT.zip"
    archive_existed = archive_path.exists()
    if force_download or not archive_path.exists():
        download_archive(archive_path)

    staged_coinbase_series = stage_existing_coinbase(existing_bronze_root, bronze_root)
    ingest = import_archive(archive_path, start, end, CRYPTO_UNIVERSE, bronze_root)
    inventory, _, _ = run_inventory(bronze_root=bronze_root, output_root=model_root)
    canonical_manifest, canonical, _ = run_canonical_history(
        bronze_root=bronze_root, output_root=model_root)
    canonical = clip_canonical_window(canonical, start, end)
    rewrite_clipped_canonical(model_root, canonical_manifest, canonical, start, end)
    validate_canonical(canonical, start, end)
    coverage = coverage_report(canonical)
    coverage_path = root / "asset_coverage.csv"
    root.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False)

    manifest = {
        "stage": "crypto_ten_year_observed_history",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_utc": pd.Timestamp(start, tz="UTC").isoformat(),
        "requested_end_utc_exclusive": pd.Timestamp(end, tz="UTC").isoformat(),
        "configured_universe": list(CRYPTO_UNIVERSE),
        "archive_reused": bool(archive_existed and not force_download),
        "imported_asset_count": ingest["imported_asset_count"],
        "staged_coinbase_series_count": staged_coinbase_series,
        "unavailable_products": ingest["unavailable_products"],
        "canonical_row_count": int(len(canonical)),
        "canonical_product_count": int(canonical["product_id"].nunique()),
        "synthetic_rows_created": False,
        "pre_launch_backfill_created": False,
        "model_artifacts_modified": False,
        "outputs": {"archive": str(archive_path),
                    "canonical_history": canonical_manifest["outputs"]["canonical_history"],
                    "coverage": str(coverage_path)},
        "next_step": "Run causal walk-forward model reconstruction from this frozen canonical input.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END, help="Exclusive UTC end date")
    parser.add_argument("--archive", type=Path, help="Use an existing official Kraken ZIP")
    parser.add_argument("--existing-bronze-root", type=Path,
                        default=DEFAULT_EXISTING_BRONZE_ROOT)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.root, args.start, args.end, args.archive,
                         args.force_download, args.existing_bronze_root), indent=2))


if __name__ == "__main__":
    main()
