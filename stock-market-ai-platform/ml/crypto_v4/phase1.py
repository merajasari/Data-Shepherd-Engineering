"""Crypto V4 Phase 1: pre-registered BTC / ALT / CASH allocation dataset.

Motivation
----------
Crypto V2/V3 showed that cross-sectional altcoin selection can fail badly when
the non-BTC universe itself is in a hostile regime.  Crypto V4 therefore asks
an upstream question first: should capital be allocated to BTC, to an equal-
weight eligible non-BTC sleeve, or to cash?

This phase performs DATASET CONSTRUCTION ONLY.  It does not fit a model, tune a
threshold, choose a portfolio, inspect the future holdout, or execute trades.
The untouched future holdout begins 2026-09-01 UTC.

Decision convention
-------------------
All features are known at completed UTC close t.  Labels use frozen 7-day
forward returns already present in the Crypto V2 research panel.  The ALT label
is the equal-weight mean future 7-day return of eligible non-BTC assets present
at t.  CASH has a fixed 0% seven-day return.  The winning sleeve is the largest
of BTC / ALT / CASH with deterministic tie-breaking BTC -> ALT -> CASH.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

RESEARCH_VERSION = "crypto_v4"
PHASE = 1
SOURCE_PANEL_PATH = Path("data/model/crypto_v2/research_panel_7d.parquet")
OUTPUT_ROOT = Path("data/model/crypto_v4/phase1")
DATASET_PATH = OUTPUT_ROOT / "market_allocation_dataset.parquet"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01T00:00:00Z")
BTC_PRODUCT = "BTC-USD"
HORIZON_DAYS = 7
MIN_NON_BTC_ASSETS = 10

# Pre-registered feature candidates.  The resolver below deliberately accepts
# only same-time or trailing BTC state variables.  It never substitutes future
# return or target columns.
FEATURE_CANDIDATES = {
    "btc_return_1d": ("btc_return_1d", "return_1d"),
    "btc_return_3d": ("btc_return_3d", "return_3d"),
    "btc_return_7d": ("btc_return_7d", "return_7d"),
    "btc_return_14d": ("btc_return_14d", "return_14d"),
    "btc_return_30d": ("btc_return_30d", "return_30d"),
    "btc_realized_volatility_7d": (
        "btc_realized_volatility_7d", "realized_volatility_7d"
    ),
    "btc_realized_volatility_14d": (
        "btc_realized_volatility_14d", "realized_volatility_14d"
    ),
    "btc_realized_volatility_30d": (
        "btc_realized_volatility_30d", "realized_volatility_30d"
    ),
    "btc_close_to_sma_7": ("btc_close_to_sma_7", "close_to_sma_7"),
    "btc_close_to_sma_14": ("btc_close_to_sma_14", "close_to_sma_14"),
    "btc_close_to_sma_30": ("btc_close_to_sma_30", "close_to_sma_30"),
    "btc_drawdown_from_high_30d": (
        "btc_drawdown_from_high_30d", "drawdown_from_high_30d"
    ),
    "btc_volume_to_average_30d": (
        "btc_volume_to_average_30d", "volume_to_average_30d"
    ),
}

FORBIDDEN_FEATURE_TOKENS = (
    "forward_", "target_", "future_", "endpoint", "label", "actual_"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _resolve_forward_return_column(frame: pd.DataFrame) -> str:
    candidates = (
        "forward_return_7d",
        "absolute_forward_return_7d",
        "target_forward_return_7d",
    )
    for column in candidates:
        if column in frame.columns:
            return column
    raise ValueError(
        "Crypto V2 panel does not contain a recognized absolute 7-day forward return column. "
        f"Tried: {', '.join(candidates)}"
    )


def _eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "is_eligible" in frame.columns:
        return frame["is_eligible"].fillna(False).astype(bool)
    # The authoritative research panel is already eligibility-filtered.  This
    # fallback therefore treats rows present in that panel as eligible.
    return pd.Series(True, index=frame.index)


def _resolve_btc_features(btc: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    resolved: dict[str, str] = {}
    out = btc[["timestamp_utc"]].copy()
    for output_name, candidates in FEATURE_CANDIDATES.items():
        source = next((c for c in candidates if c in btc.columns), None)
        if source is None:
            continue
        lowered = source.lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            raise ValueError(f"Future-looking feature rejected: {source}")
        out[output_name] = pd.to_numeric(btc[source], errors="coerce")
        resolved[output_name] = source
    if len(resolved) < 6:
        raise ValueError(
            "Insufficient pre-registered BTC state features were found. "
            f"Resolved only {len(resolved)}: {resolved}"
        )
    return out, resolved


def build_market_allocation_dataset(source_panel_path=SOURCE_PANEL_PATH) -> tuple[pd.DataFrame, dict]:
    path = Path(source_panel_path)
    if not path.exists():
        raise FileNotFoundError(path)

    source_hash_before = _sha256(path)
    panel = pd.read_parquet(path).copy()
    required = {"timestamp_utc", "product_id"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError("Source panel missing columns: " + ", ".join(sorted(missing)))

    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    if panel.empty:
        raise ValueError("No development rows before future holdout boundary")

    if panel.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate timestamp/product rows in Crypto V2 source panel")

    forward_col = _resolve_forward_return_column(panel)
    panel[forward_col] = pd.to_numeric(panel[forward_col], errors="coerce")
    eligible = _eligible_mask(panel)

    btc = panel[(panel["product_id"] == BTC_PRODUCT) & eligible].copy()
    if btc.empty:
        raise ValueError("BTC-USD rows are required for Crypto V4 market allocation")
    btc = btc.sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    btc_features, resolved_features = _resolve_btc_features(btc)
    btc_targets = btc[["timestamp_utc", forward_col]].rename(
        columns={forward_col: "btc_forward_return_7d"}
    )

    alt = panel[(panel["product_id"] != BTC_PRODUCT) & eligible].copy()
    alt = alt[alt[forward_col].notna()].copy()
    alt_by_day = alt.groupby("timestamp_utc", sort=True).agg(
        alt_forward_return_7d=(forward_col, "mean"),
        non_btc_asset_count=("product_id", "nunique"),
    ).reset_index()

    data = btc_features.merge(
        btc_targets, on="timestamp_utc", how="inner", validate="one_to_one"
    ).merge(
        alt_by_day, on="timestamp_utc", how="inner", validate="one_to_one"
    )
    data = data[data["non_btc_asset_count"] >= MIN_NON_BTC_ASSETS].copy()
    data = data[
        data["btc_forward_return_7d"].notna()
        & data["alt_forward_return_7d"].notna()
    ].copy()
    if data.empty:
        raise ValueError("No valid Crypto V4 allocation rows after eligibility checks")

    data["cash_forward_return_7d"] = 0.0
    # Deterministic tie breaking follows column order: BTC, ALT, CASH.
    returns = data[[
        "btc_forward_return_7d", "alt_forward_return_7d", "cash_forward_return_7d"
    ]].to_numpy(dtype=float)
    winner_index = np.argmax(returns, axis=1)
    labels = np.array(["BTC", "ALT", "CASH"], dtype=object)
    data["allocation_target"] = labels[winner_index]
    data["allocation_target_code"] = winner_index.astype("int8")
    data["best_forward_return_7d"] = returns[np.arange(len(data)), winner_index]
    data["btc_minus_alt_forward_return_7d"] = (
        data["btc_forward_return_7d"] - data["alt_forward_return_7d"]
    )
    data["best_risky_minus_cash_return_7d"] = data[[
        "btc_forward_return_7d", "alt_forward_return_7d"
    ]].max(axis=1)

    feature_columns = list(resolved_features)
    data = data.dropna(subset=feature_columns).sort_values("timestamp_utc").reset_index(drop=True)
    if data.empty:
        raise ValueError("All rows were removed by trailing-feature completeness checks")
    if (data["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
        raise RuntimeError("Future holdout leakage detected")

    source_hash_after = _sha256(path)
    if source_hash_before != source_hash_after:
        raise RuntimeError("Frozen Crypto V2 source panel changed during Crypto V4 Phase 1")

    counts = data["allocation_target"].value_counts().reindex(["BTC", "ALT", "CASH"], fill_value=0)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "market_allocation_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "hypothesis": (
            "Crypto cross-sectional selection should be conditioned on an upstream "
            "BTC-vs-ALT-vs-CASH market allocation decision."
        ),
        "architecture": {
            "layer_1": "BTC / ALT / CASH market allocation",
            "layer_2": "future phase: cross-sectional altcoin ranking only when ALT is selected",
            "benchmark": BTC_PRODUCT,
            "horizon_days": HORIZON_DAYS,
        },
        "source": {
            "path": str(path),
            "sha256": source_hash_before,
            "source_research_version": "crypto_v2",
        },
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": (
            "All rows at or after 2026-09-01 UTC are excluded and must remain untouched "
            "for future evaluation."
        ),
        "feature_policy": (
            "Only BTC same-time/trailing state features known at completed UTC close t; "
            "no target, forward, future, endpoint, label, or actual-return columns may be features."
        ),
        "resolved_features": resolved_features,
        "feature_columns": feature_columns,
        "target_definition": {
            "BTC": "BTC absolute forward 7-day return",
            "ALT": "equal-weight mean absolute forward 7-day return across eligible non-BTC assets present at t",
            "CASH": "fixed 0% seven-day return",
            "label": "argmax(BTC, ALT, CASH), deterministic tie order BTC -> ALT -> CASH",
        },
        "minimum_non_btc_assets": MIN_NON_BTC_ASSETS,
        "row_count": int(len(data)),
        "date_range": {
            "start_utc": data["timestamp_utc"].min().isoformat(),
            "end_utc": data["timestamp_utc"].max().isoformat(),
        },
        "target_counts": {k: int(v) for k, v in counts.items()},
        "target_fractions": {k: float(v / len(data)) for k, v in counts.items()},
        "policy": (
            "dataset construction only; no model fitting, threshold search, feature search, "
            "portfolio simulation, promotion, live execution, leverage, shorting, derivatives, "
            "or future-holdout evaluation"
        ),
        "next_step": (
            "Inspect dataset integrity and class balance, then pre-register Crypto V4 Phase 2 "
            "market-allocation model candidates and validation rules before fitting."
        ),
    }
    return data, manifest


def run_phase1(source_panel_path=SOURCE_PANEL_PATH, output_root=OUTPUT_ROOT) -> dict:
    data, manifest = build_market_allocation_dataset(source_panel_path)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_path = output_root / "market_allocation_dataset.parquet"
    manifest_path = output_root / "manifest.json"
    data.to_parquet(dataset_path, index=False)
    manifest["outputs"] = {
        "dataset": str(dataset_path),
        "manifest": str(manifest_path),
    }
    manifest["dataset_sha256"] = _sha256(dataset_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-panel", type=Path, default=SOURCE_PANEL_PATH)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    manifest = run_phase1(args.source_panel, args.output_root)
    print("CRYPTO V4 PHASE 1")
    print("=" * 64)
    print(f"Rows: {manifest['row_count']}")
    print(f"Date range: {manifest['date_range']['start_utc']} -> {manifest['date_range']['end_utc']}")
    print(f"Features ({len(manifest['feature_columns'])}): {', '.join(manifest['feature_columns'])}")
    print("Target counts:")
    for label in ("BTC", "ALT", "CASH"):
        count = manifest["target_counts"][label]
        fraction = manifest["target_fractions"][label]
        print(f"  {label:4s} {count:5d} ({fraction:.2%})")
    print(f"Output: {manifest['outputs']['dataset']}")
    print("Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
