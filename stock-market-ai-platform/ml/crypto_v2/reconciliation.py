"""Crypto V2 Phase 1A provider overlap diagnostics.

This module compares overlapping provider observations without selecting a
canonical source. It is deliberately descriptive and preserves provenance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.validation import validate_bronze
from ml.crypto_v2.config import (
    BRONZE_ROOT,
    DEFAULT_GRANULARITY,
    MODEL_ROOT,
    OVERLAP_DIAGNOSTICS_PATH,
    RECONCILIATION_MANIFEST_PATH,
    RECONCILIATION_POLICY,
    RESEARCH_VERSION,
)
from ml.crypto_v2.historical_inventory import discover_bronze

OVERLAP_COLUMNS = [
    "product_id", "provider_a", "provider_b", "overlap_count",
    "overlap_start_utc", "overlap_end_utc", "close_median_abs_diff_bps",
    "close_p95_abs_diff_bps", "close_max_abs_diff_bps",
    "open_median_abs_diff_bps", "high_median_abs_diff_bps",
    "low_median_abs_diff_bps", "volume_median_ratio_b_over_a",
    "exact_close_match_rate",
]


def load_provider_series(bronze_root=BRONZE_ROOT, granularity=DEFAULT_GRANULARITY):
    series = {}
    for data_path in discover_bronze(bronze_root, granularity):
        frame, report = validate_bronze(data_path)
        key = (report.product_id, report.provider)
        if key in series:
            raise ValueError(f"Duplicate Bronze source series for {key}")
        x = frame.copy()
        x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
        series[key] = x.sort_values("timestamp_utc").reset_index(drop=True)
    return series


def _abs_diff_bps(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    denom = (a.abs() + b.abs()) / 2.0
    return ((a - b).abs() / denom.replace(0, np.nan)) * 10000.0


def build_overlap_diagnostics(bronze_root=BRONZE_ROOT,
                              granularity=DEFAULT_GRANULARITY):
    series = load_provider_series(bronze_root, granularity)
    by_product = {}
    for (product_id, provider), frame in series.items():
        by_product.setdefault(product_id, {})[provider] = frame

    rows = []
    for product_id, provider_frames in sorted(by_product.items()):
        providers = sorted(provider_frames)
        for provider_a, provider_b in itertools.combinations(providers, 2):
            a = provider_frames[provider_a][[
                "timestamp_utc", "open", "high", "low", "close", "volume"
            ]].copy()
            b = provider_frames[provider_b][[
                "timestamp_utc", "open", "high", "low", "close", "volume"
            ]].copy()
            joined = a.merge(b, on="timestamp_utc", how="inner", suffixes=("_a", "_b"), validate="one_to_one")
            if joined.empty:
                continue
            close_bps = _abs_diff_bps(joined["close_a"], joined["close_b"])
            open_bps = _abs_diff_bps(joined["open_a"], joined["open_b"])
            high_bps = _abs_diff_bps(joined["high_a"], joined["high_b"])
            low_bps = _abs_diff_bps(joined["low_a"], joined["low_b"])
            volume_a = pd.to_numeric(joined["volume_a"], errors="coerce")
            volume_b = pd.to_numeric(joined["volume_b"], errors="coerce")
            ratio = volume_b / volume_a.replace(0, np.nan)
            rows.append({
                "product_id": product_id,
                "provider_a": provider_a,
                "provider_b": provider_b,
                "overlap_count": int(len(joined)),
                "overlap_start_utc": joined["timestamp_utc"].min(),
                "overlap_end_utc": joined["timestamp_utc"].max(),
                "close_median_abs_diff_bps": float(close_bps.median()),
                "close_p95_abs_diff_bps": float(close_bps.quantile(0.95)),
                "close_max_abs_diff_bps": float(close_bps.max()),
                "open_median_abs_diff_bps": float(open_bps.median()),
                "high_median_abs_diff_bps": float(high_bps.median()),
                "low_median_abs_diff_bps": float(low_bps.median()),
                "volume_median_ratio_b_over_a": float(ratio.median()) if ratio.notna().any() else np.nan,
                "exact_close_match_rate": float((joined["close_a"] == joined["close_b"]).mean()),
            })
    result = pd.DataFrame(rows, columns=OVERLAP_COLUMNS)
    if len(result):
        result = result.sort_values(["product_id", "provider_a", "provider_b"]).reset_index(drop=True)
    return result


def run_reconciliation(bronze_root=BRONZE_ROOT, output_root=MODEL_ROOT,
                       granularity=DEFAULT_GRANULARITY):
    diagnostics = build_overlap_diagnostics(bronze_root, granularity)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    diagnostics_path = output_root / OVERLAP_DIAGNOSTICS_PATH.name
    manifest_path = output_root / RECONCILIATION_MANIFEST_PATH.name
    diagnostics.to_csv(diagnostics_path, index=False)
    if len(diagnostics):
        next_step = (
            "Freeze a deterministic canonical-history source policy before any merge; "
            "provider selection must not use realized returns or model performance."
        )
    else:
        next_step = (
            "Ingest at least one independent provider, rerun overlap diagnostics, "
            "then pre-register a deterministic canonical-history policy before any merge."
        )
    manifest = {
        "research_version": RESEARCH_VERSION,
        "stage": "provider_overlap_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "granularity": granularity,
        "policy": RECONCILIATION_POLICY,
        "canonical_source_selected": False,
        "provider_pair_rows": int(len(diagnostics)),
        "products_with_provider_overlap": int(diagnostics["product_id"].nunique()) if len(diagnostics) else 0,
        "output": str(diagnostics_path),
        "next_step": next_step,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bronze-root", type=Path, default=BRONZE_ROOT)
    parser.add_argument("--output-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--granularity", default=DEFAULT_GRANULARITY, choices=("daily",))
    args = parser.parse_args(argv)
    manifest, _ = run_reconciliation(args.bronze_root, args.output_root, args.granularity)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
