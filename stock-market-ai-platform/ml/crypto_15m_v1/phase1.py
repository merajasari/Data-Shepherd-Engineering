"""Crypto 15m V1 Phase 1: leakage-safe intraday feature/target panels.

This phase performs dataset construction only.  It does not fit models, tune
thresholds, simulate portfolios, inspect future holdout results, or place
orders.

The main research universe deliberately excludes XRP because the completed data
quality audit found a multi-year historical discontinuity.  XRP is processed
into a separate panel with the same feature/target contract so a dedicated XRP
model can be researched independently without contaminating the core universe.

Decision convention
-------------------
Each row represents a completed Coinbase 15-minute candle.  Features use only
same-time or trailing information within a contiguous 15-minute segment.
Forward targets are created only within that same contiguous segment, so no
feature or target may cross a missing-candle gap.

Pre-registered forward horizons
-------------------------------
15 minutes, 1 hour, 4 hours, and 24 hours.  The system may eventually make a
new decision every 15 minutes while evaluating models whose predictive horizon
is longer than a single bar.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from ml.crypto_rt import PRODUCTS
from ml.crypto_15m_v1 import RESEARCH_VERSION, BAR_MINUTES

PHASE = 1
BAR_SECONDS = BAR_MINUTES * 60
SOURCE_ROOT = Path("data/research/crypto_intraday/raw_15m")
AUDIT_PATH = Path("data/research/crypto_intraday/data_quality_audit.csv")
OUTPUT_ROOT = Path("data/model/crypto_15m_v1/phase1")
CORE_PANEL_ROOT = OUTPUT_ROOT / "core_panel"
XRP_PANEL_PATH = OUTPUT_ROOT / "xrp_panel.parquet"
CATALOG_PATH = OUTPUT_ROOT / "panel_catalog.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BTC_PRODUCT = "BTC-USD"
XRP_PRODUCT = "XRP-USD"
CORE_PRODUCTS = tuple(p for p in PRODUCTS if p != XRP_PRODUCT)
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01T00:00:00Z")

# Horizons are frozen before model fitting.
HORIZONS = {
    "15m": 1,
    "1h": 4,
    "4h": 16,
    "24h": 96,
}

TRAILING_RETURN_BARS = (1, 2, 4, 8, 16, 32, 96)
ROLLING_WINDOWS = (4, 16, 96)
MIN_REQUIRED_HISTORY_BARS = 96

BASE_REQUIRED_COLUMNS = {
    "timestamp_utc",
    "product_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


@dataclass
class ProductSummary:
    product_id: str
    panel_group: str
    input_rows: int
    output_rows: int
    contiguous_segments: int
    first_input_utc: str | None
    last_input_utc: str | None
    first_output_utc: str | None
    last_output_utc: str | None
    source_files: int


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


def _read_product(product_id: str, source_root: Path) -> tuple[pd.DataFrame, list[Path]]:
    paths = sorted((source_root / product_id).glob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"No 15-minute Parquet files found for {product_id}")

    frames = [pd.read_parquet(path) for path in paths]
    frame = pd.concat(frames, ignore_index=True)
    missing = BASE_REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"{product_id} missing columns: {sorted(missing)}")

    frame = frame[list(BASE_REQUIRED_COLUMNS)].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = (
        frame.dropna(subset=["timestamp_utc", "open", "high", "low", "close", "volume"])
        .sort_values("timestamp_utc")
        .drop_duplicates(["timestamp_utc", "product_id"], keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        raise ValueError(f"{product_id} has no usable rows")
    if not (frame["product_id"] == product_id).all():
        raise ValueError(f"Unexpected product_id values inside {product_id} archive")

    frame = frame[frame["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    return frame, paths


def _add_segments(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    step = out["timestamp_utc"].diff()
    contiguous = step.eq(pd.Timedelta(minutes=BAR_MINUTES))
    new_segment = ~contiguous
    if len(new_segment):
        new_segment.iloc[0] = True
    out["segment_id"] = new_segment.cumsum().astype("int32")
    return out


def _group_transform(frame: pd.DataFrame, column: str, func) -> pd.Series:
    return frame.groupby("segment_id", sort=False)[column].transform(func)


def _build_base_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = _add_segments(frame)

    # Same-candle shape variables.
    out["candle_return"] = out["close"] / out["open"] - 1.0
    out["range_pct"] = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    out["upper_wick_pct"] = (
        out["high"] - out[["open", "close"]].max(axis=1)
    ) / out["close"].replace(0, np.nan)
    out["lower_wick_pct"] = (
        out[["open", "close"]].min(axis=1) - out["low"]
    ) / out["close"].replace(0, np.nan)
    out["dollar_volume"] = out["close"] * out["volume"]

    grouped = out.groupby("segment_id", sort=False)

    # Trailing returns. pct_change within segment prevents crossing gaps.
    for bars in TRAILING_RETURN_BARS:
        out[f"return_{bars}bar"] = grouped["close"].pct_change(periods=bars, fill_method=None)

    one_bar = out["return_1bar"]
    for window in ROLLING_WINDOWS:
        minp = window
        out[f"realized_volatility_{window}bar"] = grouped["return_1bar"].transform(
            lambda s, w=window, m=minp: s.rolling(w, min_periods=m).std(ddof=0)
        )
        sma = grouped["close"].transform(
            lambda s, w=window, m=minp: s.rolling(w, min_periods=m).mean()
        )
        out[f"close_to_sma_{window}bar"] = out["close"] / sma - 1.0
        avg_volume = grouped["volume"].transform(
            lambda s, w=window, m=minp: s.rolling(w, min_periods=m).mean()
        )
        out[f"volume_to_average_{window}bar"] = out["volume"] / avg_volume.replace(0, np.nan)
        avg_dollar_volume = grouped["dollar_volume"].transform(
            lambda s, w=window, m=minp: s.rolling(w, min_periods=m).mean()
        )
        out[f"dollar_volume_to_average_{window}bar"] = (
            out["dollar_volume"] / avg_dollar_volume.replace(0, np.nan)
        )

    rolling_high = grouped["high"].transform(
        lambda s: s.rolling(96, min_periods=96).max()
    )
    out["drawdown_from_high_96bar"] = out["close"] / rolling_high - 1.0

    # Calendar features are deterministic and known at decision time.
    minute_of_day = out["timestamp_utc"].dt.hour * 60 + out["timestamp_utc"].dt.minute
    angle_day = 2.0 * np.pi * minute_of_day / 1440.0
    out["utc_time_sin"] = np.sin(angle_day)
    out["utc_time_cos"] = np.cos(angle_day)
    dow = out["timestamp_utc"].dt.dayofweek
    angle_week = 2.0 * np.pi * dow / 7.0
    out["utc_dow_sin"] = np.sin(angle_week)
    out["utc_dow_cos"] = np.cos(angle_week)

    # Forward targets only within a contiguous segment.
    for label, bars in HORIZONS.items():
        future_close = grouped["close"].shift(-bars)
        out[f"forward_return_{label}"] = future_close / out["close"] - 1.0

    return out


def _btc_context(btc_features: pd.DataFrame) -> pd.DataFrame:
    keep = ["timestamp_utc"]
    feature_names = [
        "return_1bar",
        "return_4bar",
        "return_16bar",
        "return_96bar",
        "realized_volatility_4bar",
        "realized_volatility_16bar",
        "realized_volatility_96bar",
        "close_to_sma_16bar",
        "close_to_sma_96bar",
        "volume_to_average_16bar",
        "volume_to_average_96bar",
        "drawdown_from_high_96bar",
    ]
    target_names = [f"forward_return_{label}" for label in HORIZONS]
    available = [c for c in feature_names + target_names if c in btc_features.columns]
    context = btc_features[keep + available].copy()
    return context.rename(columns={c: f"btc_{c}" for c in available})


def _feature_columns() -> list[str]:
    columns = [
        "candle_return",
        "range_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "return_1bar",
        "return_2bar",
        "return_4bar",
        "return_8bar",
        "return_16bar",
        "return_32bar",
        "return_96bar",
        "realized_volatility_4bar",
        "realized_volatility_16bar",
        "realized_volatility_96bar",
        "close_to_sma_4bar",
        "close_to_sma_16bar",
        "close_to_sma_96bar",
        "volume_to_average_4bar",
        "volume_to_average_16bar",
        "volume_to_average_96bar",
        "dollar_volume_to_average_4bar",
        "dollar_volume_to_average_16bar",
        "dollar_volume_to_average_96bar",
        "drawdown_from_high_96bar",
        "utc_time_sin",
        "utc_time_cos",
        "utc_dow_sin",
        "utc_dow_cos",
        "btc_return_1bar",
        "btc_return_4bar",
        "btc_return_16bar",
        "btc_return_96bar",
        "btc_realized_volatility_4bar",
        "btc_realized_volatility_16bar",
        "btc_realized_volatility_96bar",
        "btc_close_to_sma_16bar",
        "btc_close_to_sma_96bar",
        "btc_volume_to_average_16bar",
        "btc_volume_to_average_96bar",
        "btc_drawdown_from_high_96bar",
    ]
    # Relative trailing returns are added after BTC context merge.
    columns.extend([
        "btc_relative_return_1bar",
        "btc_relative_return_4bar",
        "btc_relative_return_16bar",
        "btc_relative_return_96bar",
    ])
    return columns


def _target_columns() -> list[str]:
    columns: list[str] = []
    for label in HORIZONS:
        columns.extend([
            f"forward_return_{label}",
            f"btc_forward_return_{label}",
            f"btc_relative_forward_return_{label}",
        ])
    return columns


def _finalize_panel(product_features: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    out = product_features.merge(btc, on="timestamp_utc", how="left", validate="many_to_one")

    for bars in (1, 4, 16, 96):
        out[f"btc_relative_return_{bars}bar"] = (
            out[f"return_{bars}bar"] - out[f"btc_return_{bars}bar"]
        )
    for label in HORIZONS:
        out[f"btc_relative_forward_return_{label}"] = (
            out[f"forward_return_{label}"] - out[f"btc_forward_return_{label}"]
        )

    features = _feature_columns()
    targets = _target_columns()
    required = features + targets
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise RuntimeError(f"Panel construction missing expected columns: {missing}")

    # Requiring the longest trailing and future horizon makes each emitted row
    # complete for all pre-registered Phase 1 experiments.
    out = out.dropna(subset=required).copy()
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    out = out.sort_values("timestamp_utc").reset_index(drop=True)

    keep = [
        "timestamp_utc",
        "product_id",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ] + features + targets
    return out[keep]


def _load_audit(audit_path: Path) -> dict:
    if not audit_path.exists():
        return {}
    audit = pd.read_csv(audit_path)
    if "product" not in audit.columns:
        return {}
    rows = {}
    for record in audit.to_dict("records"):
        rows[str(record["product"])] = record
    return rows


def run_phase1(
    source_root: Path = SOURCE_ROOT,
    audit_path: Path = AUDIT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    source_root = Path(source_root)
    audit_path = Path(audit_path)
    output_root = Path(output_root)
    core_root = output_root / "core_panel"
    core_root.mkdir(parents=True, exist_ok=True)

    audit = _load_audit(audit_path)
    xrp_audit = audit.get(XRP_PRODUCT, {})

    # Build BTC first because all products receive exact-timestamp BTC context.
    btc_raw, btc_paths = _read_product(BTC_PRODUCT, source_root)
    btc_features = _build_base_features(btc_raw)
    btc_context = _btc_context(btc_features)

    summaries: list[ProductSummary] = []
    output_hashes: dict[str, str] = {}

    for product_id in PRODUCTS:
        raw, paths = (btc_raw.copy(), btc_paths) if product_id == BTC_PRODUCT else _read_product(product_id, source_root)
        base = btc_features.copy() if product_id == BTC_PRODUCT else _build_base_features(raw)
        panel = _finalize_panel(base, btc_context)

        panel_group = "xrp_dedicated" if product_id == XRP_PRODUCT else "core"
        if product_id == XRP_PRODUCT:
            path = output_root / "xrp_panel.parquet"
        else:
            path = core_root / f"{product_id}.parquet"
        panel.to_parquet(path, index=False)
        output_hashes[str(path)] = _sha256(path)

        summaries.append(ProductSummary(
            product_id=product_id,
            panel_group=panel_group,
            input_rows=int(len(raw)),
            output_rows=int(len(panel)),
            contiguous_segments=int(base["segment_id"].nunique()),
            first_input_utc=raw["timestamp_utc"].min().isoformat() if len(raw) else None,
            last_input_utc=raw["timestamp_utc"].max().isoformat() if len(raw) else None,
            first_output_utc=panel["timestamp_utc"].min().isoformat() if len(panel) else None,
            last_output_utc=panel["timestamp_utc"].max().isoformat() if len(panel) else None,
            source_files=len(paths),
        ))
        print(
            f"[SUCCESS] {product_id:10s} group={panel_group:13s} "
            f"input={len(raw):7,d} panel={len(panel):7,d} "
            f"segments={base['segment_id'].nunique():4,d}"
        )

    catalog = pd.DataFrame([s.__dict__ for s in summaries])
    catalog_path = output_root / "panel_catalog.csv"
    catalog.to_csv(catalog_path, index=False)

    core_rows = int(catalog.loc[catalog["panel_group"] == "core", "output_rows"].sum())
    xrp_rows = int(catalog.loc[catalog["panel_group"] == "xrp_dedicated", "output_rows"].sum())

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "intraday_feature_target_panel",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "bar_minutes": BAR_MINUTES,
        "decision_frequency": "every completed 15-minute bar",
        "source_root": str(source_root),
        "audit_path": str(audit_path),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": (
            "Phase 1 uses only observations before 2026-09-01 UTC. No model fitting or holdout evaluation occurs."
        ),
        "core_universe": list(CORE_PRODUCTS),
        "core_universe_count": len(CORE_PRODUCTS),
        "excluded_from_core": [XRP_PRODUCT],
        "xrp_policy": {
            "reason": (
                "XRP is excluded from the shared core model because the completed data-quality audit identified "
                "a very large historical discontinuity. A separate XRP panel is produced for a dedicated model."
            ),
            "audit_coverage_pct": xrp_audit.get("coverage_pct"),
            "audit_missing_bars": xrp_audit.get("missing"),
            "audit_largest_gap": str(xrp_audit.get("largest_gap")) if xrp_audit else None,
            "panel_path": str(output_root / "xrp_panel.parquet"),
            "no_gap_crossing": True,
        },
        "continuity_policy": (
            "Rows are segmented whenever adjacent candles are not exactly 15 minutes apart. "
            "Trailing features and forward targets are computed only inside contiguous segments; no candles are synthesized."
        ),
        "pre_registered_horizons": {label: {"bars": bars, "minutes": bars * BAR_MINUTES} for label, bars in HORIZONS.items()},
        "feature_columns": _feature_columns(),
        "target_columns": _target_columns(),
        "target_policy": (
            "Absolute and BTC-relative forward returns at 15m, 1h, 4h, and 24h. "
            "All endpoints remain inside the same contiguous product segment."
        ),
        "core_panel_rows": core_rows,
        "xrp_panel_rows": xrp_rows,
        "catalog_path": str(catalog_path),
        "outputs": {
            "core_panel_root": str(core_root),
            "xrp_panel": str(output_root / "xrp_panel.parquet"),
            "catalog": str(catalog_path),
            "manifest": str(output_root / "manifest.json"),
        },
        "output_sha256": output_hashes,
        "policy": (
            "dataset construction only; no model fitting, feature selection, threshold tuning, portfolio simulation, "
            "promotion, live execution, leverage, shorting, derivatives, or future-holdout evaluation"
        ),
        "next_step": (
            "Audit Phase 1 row counts and horizon coverage, then pre-register walk-forward model candidates for the 24-asset "
            "core universe. Research XRP separately using its dedicated panel and discontinuity-aware validation."
        ),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    ap.add_argument("--audit", type=Path, default=AUDIT_PATH)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)

    manifest = run_phase1(args.source_root, args.audit, args.output_root)
    print("CRYPTO 15M V1 PHASE 1")
    print("=" * 72)
    print(f"Core universe: {manifest['core_universe_count']} products (XRP excluded)")
    print(f"Core panel rows: {manifest['core_panel_rows']:,}")
    print(f"Dedicated XRP panel rows: {manifest['xrp_panel_rows']:,}")
    print(f"Features: {len(manifest['feature_columns'])}")
    print("Horizons: " + ", ".join(manifest["pre_registered_horizons"].keys()))
    print(f"Core output: {manifest['outputs']['core_panel_root']}")
    print(f"XRP output:  {manifest['outputs']['xrp_panel']}")
    print(f"Catalog:     {manifest['outputs']['catalog']}")
    print("No missing candles were synthesized; no feature or target crosses a gap.")
    print("Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
