"""Consolidate guarded GDELT CSV exports into a canonical Parquet dataset."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from ml.news_intelligence.gdelt import canonicalize_export

DEFAULT_RAW_ROOT = Path("data/research/news/gdelt/raw")
DEFAULT_OUTPUT_ROOT = Path("data/research/news/gdelt/canonical")
REQUIRED_RAW_COLUMNS = {
    "DATE", "SourceCommonName", "DocumentIdentifier", "V2Organizations", "V2Tone", "asset_ids"
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assets(value):
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("asset_ids must contain a non-empty JSON array")
    return sorted({str(asset) for asset in parsed if str(asset)})


def _first_nonempty(values):
    normalized = sorted({str(value) for value in values if pd.notna(value) and str(value)})
    return normalized[0] if normalized else ""


def _merge_month(frame):
    missing = sorted(REQUIRED_RAW_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError("GDELT export missing columns: " + ", ".join(missing))
    work = frame[list(sorted(REQUIRED_RAW_COLUMNS))].copy()
    work["DATE"] = work["DATE"].astype(str).str.replace(r"\.0$", "", regex=True)
    work["DocumentIdentifier"] = work["DocumentIdentifier"].astype(str)
    work["asset_ids"] = work["asset_ids"].map(_assets)
    rows = []
    for (observed, url), group in work.groupby(
            ["DATE", "DocumentIdentifier"], sort=True, dropna=False):
        assets = sorted({asset for values in group["asset_ids"] for asset in values})
        organizations = sorted({str(value) for value in group["V2Organizations"]
                                if pd.notna(value) and str(value)})
        rows.append({
            "DATE": observed,
            "SourceCommonName": _first_nonempty(group["SourceCommonName"]),
            "DocumentIdentifier": url,
            "V2Organizations": " ".join(organizations),
            "V2Tone": _first_nonempty(group["V2Tone"]),
            "asset_ids": assets,
        })
    return pd.DataFrame(rows, columns=sorted(REQUIRED_RAW_COLUMNS))


def run(raw_root=DEFAULT_RAW_ROOT, output_root=DEFAULT_OUTPUT_ROOT):
    raw_root, output_root = Path(raw_root), Path(output_root)
    sources = sorted(raw_root.glob("gdelt_gkg_*.csv"))
    if not sources:
        raise FileNotFoundError(f"No guarded GDELT exports found under {raw_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    seen_article_ids = set()
    outputs = []
    raw_rows = canonical_rows = duplicate_rows = 0
    for number, source in enumerate(sources, start=1):
        raw = pd.read_csv(source)
        raw_rows += len(raw)
        merged = _merge_month(raw)
        canonical = canonicalize_export(merged, datetime.now(timezone.utc))
        repeated = canonical["article_id"].isin(seen_article_ids)
        duplicate_rows += int(len(raw) - len(merged) + repeated.sum())
        canonical = canonical.loc[~repeated].copy()
        seen_article_ids.update(canonical["article_id"].tolist())
        canonical_rows += len(canonical)
        partition = source.stem.removeprefix("gdelt_gkg_")
        destination = output_root / f"news_{partition}.parquet"
        temporary = destination.with_suffix(".parquet.part")
        canonical.to_parquet(temporary, index=False)
        temporary.replace(destination)
        outputs.append({
            "source": str(source), "source_sha256": _sha256(source),
            "output": str(destination), "output_sha256": _sha256(destination),
            "raw_rows": int(len(raw)), "canonical_rows": int(len(canonical)),
        })
        print(f"[{number}/{len(sources)}] {destination.name}: {len(canonical):,} canonical rows")
    manifest = {
        "stage": "gdelt_canonical_news_consolidation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_root": str(raw_root), "output_root": str(output_root),
        "source_files": len(sources), "raw_rows": int(raw_rows),
        "canonical_rows": int(canonical_rows), "duplicate_rows_removed": int(duplicate_rows),
        "outputs": outputs,
        "timestamp_semantics": "gdelt_first_observed_not_publisher_timestamp",
        "embedding_semantics": "deterministic_metadata_hash_baseline",
        "safety": {"model_artifacts_modified": False, "paper_state_modified": False,
                   "holdout_scored": False, "brokerage_orders": False},
        "next_step": "Build point-in-time news features at pre-holdout decision timestamps.",
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    manifest = run(args.raw_root, args.output_root)
    print(json.dumps({key: manifest[key] for key in (
        "stage", "source_files", "raw_rows", "canonical_rows",
        "duplicate_rows_removed", "output_root", "safety", "next_step")}, indent=2))


if __name__ == "__main__":
    main()
