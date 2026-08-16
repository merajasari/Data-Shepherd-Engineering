"""Crypto XRP V1 Phase 1: discontinuity-aware XRP research dataset.

This phase performs dataset organization and audit only.

It consumes the leakage-safe XRP panel already produced by Crypto 15m V1
Phase 1. It does not rebuild raw features, fit models, tune thresholds,
simulate portfolios, inspect the future holdout, or place orders.

The XRP archive contains a major historical discontinuity. Phase 1 identifies
the largest break between contiguous segments and separates:

- legacy era: history before the largest discontinuity
- primary era: history after the largest discontinuity

The post-gap primary era is the main modeling population for later phases.
Legacy history is retained separately for robustness research.

The future holdout beginning 2026-09-01 00:00 UTC remains untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

from ml.crypto_xrp_v1 import RESEARCH_VERSION


PHASE = 1

SOURCE_PANEL = Path(
    "data/model/crypto_15m_v1/phase1/xrp_panel.parquet"
)

OUTPUT_ROOT = Path(
    "data/model/crypto_xrp_v1/phase1"
)

PRIMARY_PATH = OUTPUT_ROOT / "xrp_primary.parquet"
LEGACY_PATH = OUTPUT_ROOT / "xrp_legacy.parquet"
SEGMENT_CATALOG_PATH = OUTPUT_ROOT / "segment_catalog.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")

PRIMARY_TARGET = "btc_relative_forward_return_4h"

HORIZONS = ("15m", "1h", "4h", "24h")

ID_COLUMNS = {
    "timestamp_utc",
    "product_id",
    "segment_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

TARGET_PREFIXES = (
    "forward_return_",
    "btc_forward_return_",
    "btc_relative_forward_return_",
)


def _git_hash() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_panel(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing XRP source panel: {path}")

    df = pd.read_parquet(path)

    required = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        PRIMARY_TARGET,
    }

    for horizon in HORIZONS:
        required.update(
            {
                f"forward_return_{horizon}",
                f"btc_forward_return_{horizon}",
                f"btc_relative_forward_return_{horizon}",
            }
        )

    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            f"XRP source panel missing required columns: {sorted(missing)}"
        )

    df = df.copy()
    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"],
        utc=True,
    )

    if set(df["product_id"].dropna().unique()) != {"XRP-USD"}:
        raise RuntimeError(
            "Dedicated XRP panel contains non-XRP products"
        )

    # Explicit protection against accidental future-holdout inspection.
    if (df["timestamp_utc"] >= FUTURE_HOLDOUT_START).any():
        df = df[
            df["timestamp_utc"] < FUTURE_HOLDOUT_START
        ].copy()

    df = (
        df.sort_values("timestamp_utc")
        .drop_duplicates(["timestamp_utc", "product_id"])
        .reset_index(drop=True)
    )

    if df.empty:
        raise RuntimeError("XRP panel is empty")

    return df


def _segment_catalog(df: pd.DataFrame) -> pd.DataFrame:
    catalog = (
        df.groupby("segment_id", sort=True)
        .agg(
            rows=("timestamp_utc", "size"),
            start_utc=("timestamp_utc", "min"),
            end_utc=("timestamp_utc", "max"),
        )
        .reset_index()
        .sort_values("start_utc")
        .reset_index(drop=True)
    )

    catalog["previous_end_utc"] = catalog[
        "end_utc"
    ].shift(1)

    catalog["gap_from_previous"] = (
        catalog["start_utc"]
        - catalog["previous_end_utc"]
    )

    catalog["gap_minutes"] = (
        catalog["gap_from_previous"]
        .dt.total_seconds()
        .div(60)
    )

    return catalog


def _largest_discontinuity(
    catalog: pd.DataFrame,
) -> dict:
    candidates = catalog[
        catalog["previous_end_utc"].notna()
    ].copy()

    if candidates.empty:
        raise RuntimeError(
            "Cannot identify XRP discontinuity from fewer than "
            "two segments"
        )

    row = candidates.loc[
        candidates["gap_minutes"].idxmax()
    ]

    return {
        "previous_segment_id": int(
            catalog.loc[
                catalog["end_utc"]
                == row["previous_end_utc"],
                "segment_id",
            ].iloc[0]
        ),
        "next_segment_id": int(row["segment_id"]),
        "previous_segment_end_utc": (
            row["previous_end_utc"].isoformat()
        ),
        "next_segment_start_utc": (
            row["start_utc"].isoformat()
        ),
        "gap_minutes": float(row["gap_minutes"]),
        "gap_days": float(
            row["gap_minutes"] / (60.0 * 24.0)
        ),
    }


def _feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c not in ID_COLUMNS
        and not c.startswith(TARGET_PREFIXES)
    ]


def _target_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c.startswith(TARGET_PREFIXES)
    ]


def build_phase1(
    source_panel: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict,
]:
    df = _load_panel(source_panel)

    catalog = _segment_catalog(df)

    break_info = _largest_discontinuity(catalog)

    primary_start = pd.Timestamp(
        break_info["next_segment_start_utc"]
    )

    legacy = df[
        df["timestamp_utc"] < primary_start
    ].copy()

    primary = df[
        df["timestamp_utc"] >= primary_start
    ].copy()

    if legacy.empty:
        raise RuntimeError("Legacy XRP era is empty")

    if primary.empty:
        raise RuntimeError("Primary XRP era is empty")

    # Ensure the split occurred exactly on a segment boundary.
    legacy_segments = set(legacy["segment_id"].unique())
    primary_segments = set(primary["segment_id"].unique())

    if legacy_segments & primary_segments:
        raise RuntimeError(
            "A contiguous XRP segment was split across eras"
        )

    features = _feature_columns(df)
    targets = _target_columns(df)

    expected_targets = []
    for horizon in HORIZONS:
        expected_targets.extend(
            [
                f"forward_return_{horizon}",
                f"btc_forward_return_{horizon}",
                f"btc_relative_forward_return_{horizon}",
            ]
        )

    missing_targets = [
        c for c in expected_targets
        if c not in targets
    ]

    if missing_targets:
        raise RuntimeError(
            "Missing pre-registered XRP targets: "
            f"{missing_targets}"
        )

    catalog["era"] = catalog["start_utc"].apply(
        lambda x: (
            "primary"
            if x >= primary_start
            else "legacy"
        )
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": (
            "discontinuity_aware_xrp_dataset"
        ),
        "generated_at_utc": (
            datetime.now(timezone.utc).isoformat()
        ),
        "git_commit_hash": _git_hash(),
        "source_panel": str(source_panel),
        "product": "XRP-USD",
        "future_holdout_start_utc": (
            FUTURE_HOLDOUT_START.isoformat()
        ),
        "future_holdout_policy": (
            "All Phase 1 output is restricted to timestamps "
            "strictly before 2026-09-01 00:00 UTC. "
            "No future-holdout results are inspected."
        ),
        "largest_discontinuity": break_info,
        "era_policy": {
            "legacy": (
                "All model-ready XRP history before the "
                "largest discontinuity; retained only for "
                "separate robustness analysis."
            ),
            "primary": (
                "All model-ready XRP history after the "
                "largest discontinuity; primary population "
                "for subsequent walk-forward research."
            ),
            "cross_gap_training_policy": (
                "Primary XRP model research must not treat "
                "the legacy and primary eras as one "
                "continuous time series."
            ),
        },
        "legacy": {
            "rows": int(len(legacy)),
            "segments": int(
                legacy["segment_id"].nunique()
            ),
            "start_utc": (
                legacy["timestamp_utc"]
                .min()
                .isoformat()
            ),
            "end_utc": (
                legacy["timestamp_utc"]
                .max()
                .isoformat()
            ),
        },
        "primary": {
            "rows": int(len(primary)),
            "segments": int(
                primary["segment_id"].nunique()
            ),
            "start_utc": (
                primary["timestamp_utc"]
                .min()
                .isoformat()
            ),
            "end_utc": (
                primary["timestamp_utc"]
                .max()
                .isoformat()
            ),
        },
        "total_rows": int(len(df)),
        "total_segments": int(
            df["segment_id"].nunique()
        ),
        "feature_count": len(features),
        "feature_columns": features,
        "target_columns": targets,
        "primary_target_for_phase2": PRIMARY_TARGET,
        "pre_registered_horizons": list(HORIZONS),
        "phase2_plan": {
            "primary_target": PRIMARY_TARGET,
            "primary_population": "primary",
            "baseline": (
                "btc_relative_return_16bar"
            ),
            "candidate_models": [
                "ridge",
                "hist_gradient_boosting",
            ],
            "validation": (
                "expanding walk-forward validation entirely "
                "within the post-gap primary era"
            ),
            "purge": (
                "minimum 4-hour target horizon purge between "
                "training and validation"
            ),
            "secondary_diagnostics": [
                "15m absolute return",
                "1h absolute return",
                "4h absolute return",
                "24h absolute return",
                "15m BTC-relative return",
                "1h BTC-relative return",
                "24h BTC-relative return",
            ],
        },
        "policy": (
            "dataset audit and era separation only; "
            "no model fitting, threshold tuning, "
            "portfolio simulation, promotion, "
            "brokerage execution, leverage, shorting, "
            "derivatives, or future-holdout evaluation"
        ),
    }

    return primary, legacy, catalog, manifest


def run(
    source_panel: Path = SOURCE_PANEL,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_panel = Path(source_panel)
    output_root = Path(output_root)

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    primary, legacy, catalog, manifest = (
        build_phase1(source_panel)
    )

    primary_path = (
        output_root / "xrp_primary.parquet"
    )
    legacy_path = (
        output_root / "xrp_legacy.parquet"
    )
    catalog_path = (
        output_root / "segment_catalog.csv"
    )
    manifest_path = (
        output_root / "manifest.json"
    )

    primary.to_parquet(
        primary_path,
        index=False,
    )

    legacy.to_parquet(
        legacy_path,
        index=False,
    )

    catalog.to_csv(
        catalog_path,
        index=False,
    )

    manifest["outputs"] = {
        "primary": str(primary_path),
        "legacy": str(legacy_path),
        "segment_catalog": str(catalog_path),
        "manifest": str(manifest_path),
    }

    manifest["output_sha256"] = {
        str(primary_path): _sha256(primary_path),
        str(legacy_path): _sha256(legacy_path),
        str(catalog_path): _sha256(catalog_path),
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return manifest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__
    )

    ap.add_argument(
        "--source-panel",
        type=Path,
        default=SOURCE_PANEL,
    )

    ap.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )

    args = ap.parse_args(argv)

    manifest = run(
        args.source_panel,
        args.output_root,
    )

    gap = manifest[
        "largest_discontinuity"
    ]

    print("CRYPTO XRP V1 PHASE 1")
    print("=" * 80)

    print(
        "Largest discontinuity:"
    )

    print(
        f"  {gap['previous_segment_end_utc']}"
        " -> "
        f"{gap['next_segment_start_utc']}"
    )

    print(
        f"  {gap['gap_days']:.2f} days"
    )

    print()

    print(
        "Legacy era:"
    )

    print(
        f"  rows:     "
        f"{manifest['legacy']['rows']:,}"
    )

    print(
        f"  segments: "
        f"{manifest['legacy']['segments']}"
    )

    print(
        f"  range:    "
        f"{manifest['legacy']['start_utc']}"
        " -> "
        f"{manifest['legacy']['end_utc']}"
    )

    print()

    print(
        "Primary era:"
    )

    print(
        f"  rows:     "
        f"{manifest['primary']['rows']:,}"
    )

    print(
        f"  segments: "
        f"{manifest['primary']['segments']}"
    )

    print(
        f"  range:    "
        f"{manifest['primary']['start_utc']}"
        " -> "
        f"{manifest['primary']['end_utc']}"
    )

    print()

    print(
        f"Features: "
        f"{manifest['feature_count']}"
    )

    print(
        "Primary Phase 2 target: "
        f"{manifest['primary_target_for_phase2']}"
    )

    print()

    print(
        "No models were fit."
    )

    print(
        "No future holdout was evaluated."
    )

    print(
        "Frozen Crypto 15m V2 was not modified."
    )

    print(
        f"Output: "
        f"{manifest['outputs']['primary']}"
    )


if __name__ == "__main__":
    main()
