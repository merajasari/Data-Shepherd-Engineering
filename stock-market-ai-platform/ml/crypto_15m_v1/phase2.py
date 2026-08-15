"""Crypto 15m V1 Phase 2: leakage-safe walk-forward model research.

Core research uses the 24-asset Phase 1 panel and keeps XRP isolated. The
pre-registered primary target is 4-hour BTC-relative forward return. Candidate
models are momentum, Ridge, and HistGradientBoosting. This phase produces
out-of-sample predictions and diagnostics only; it does not simulate or trade.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

PHASE1_ROOT = Path("data/model/crypto_15m_v1/phase1")
OUTPUT_ROOT = Path("data/model/crypto_15m_v1/phase2")
PRIMARY_TARGET = "btc_relative_forward_return_4h"
PRIMARY_HORIZON_BARS = 16
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
VALIDATION_DAYS = 90
MIN_TRAIN_DAYS = 365
MAX_FOLDS = 10

ID_COLUMNS = {"timestamp_utc", "product_id", "segment_id", "open", "high", "low", "close", "volume"}
TARGET_PREFIXES = ("forward_return_", "btc_forward_return_", "btc_relative_forward_return_")


def load_core(root: Path) -> pd.DataFrame:
    paths = sorted((root / "core_panel").glob("*.parquet"))
    if len(paths) != 24:
        raise RuntimeError(f"Expected 24 core panels, found {len(paths)}")
    frames = [pd.read_parquet(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df[df["timestamp_utc"] < FUTURE_HOLDOUT_START].copy()
    if "XRP-USD" in set(df["product_id"]):
        raise RuntimeError("XRP leaked into core Phase 2 universe")
    return df.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ID_COLUMNS and not c.startswith(TARGET_PREFIXES)]


def make_folds(df: pd.DataFrame) -> list[dict]:
    first = df["timestamp_utc"].min().floor("D")
    last = df["timestamp_utc"].max().floor("D")
    first_val = first + pd.Timedelta(days=MIN_TRAIN_DAYS)
    starts = list(pd.date_range(first_val, last, freq=f"{VALIDATION_DAYS}D", tz="UTC"))
    starts = [x for x in starts if x <= last]
    starts = starts[-MAX_FOLDS:]
    folds = []
    purge = pd.Timedelta(minutes=15 * PRIMARY_HORIZON_BARS)
    for i, start in enumerate(starts, 1):
        end = min(start + pd.Timedelta(days=VALIDATION_DAYS), FUTURE_HOLDOUT_START)
        train_end = start - purge
        train = df["timestamp_utc"] < train_end
        val = (df["timestamp_utc"] >= start) & (df["timestamp_utc"] < end)
        if train.sum() and val.sum():
            folds.append({"fold_id": f"fold_{i:02d}", "start": start, "end": end, "train_end": train_end, "train": train, "val": val})
    return folds


def models() -> dict:
    return {
        "ridge": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0, random_state=42)),
        ]),
    }


def daily_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ts, g in frame.groupby("timestamp_utc", sort=True):
        if len(g) < 5:
            continue
        ic = spearmanr(g["predicted_score"], g["actual"], nan_policy="omit").statistic
        ranked = g.sort_values("predicted_score")
        k = max(1, len(ranked) // 5)
        spread = ranked.tail(k)["actual"].mean() - ranked.head(k)["actual"].mean()
        rows.append({"timestamp_utc": ts, "spearman_ic": ic, "top_bottom_spread": spread, "asset_count": len(g)})
    return pd.DataFrame(rows)


def summarize(pred: pd.DataFrame) -> dict:
    dm = daily_metrics(pred)
    err = pred["predicted_score"] - pred["actual"]
    return {
        "observation_count": int(len(pred)),
        "decision_count": int(pred["timestamp_utc"].nunique()),
        "mean_ic": float(dm["spearman_ic"].mean()) if len(dm) else np.nan,
        "median_ic": float(dm["spearman_ic"].median()) if len(dm) else np.nan,
        "ic_hit_rate": float((dm["spearman_ic"] > 0).mean()) if len(dm) else np.nan,
        "mean_top_bottom_spread": float(dm["top_bottom_spread"].mean()) if len(dm) else np.nan,
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt(np.mean(np.square(err)))),
        "sign_accuracy": float((np.sign(pred["predicted_score"]) == np.sign(pred["actual"])).mean()),
    }


def run(phase1_root: Path, output_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    output_root.mkdir(parents=True, exist_ok=True)
    df = load_core(phase1_root)
    features = feature_columns(df)
    folds = make_folds(df)
    if not folds:
        raise RuntimeError("No valid walk-forward folds")
    predictions = []
    fold_rows = []
    for fold in folds:
        tr = df.loc[fold["train"]]
        va = df.loc[fold["val"]]
        Xtr, ytr = tr[features], tr[PRIMARY_TARGET]
        Xv, yv = va[features], va[PRIMARY_TARGET]

        # Baseline: trailing 4-hour BTC-relative momentum.
        base = va[["timestamp_utc", "product_id"]].copy()
        base["actual"] = yv.to_numpy()
        base["predicted_score"] = va["btc_relative_return_16bar"].to_numpy()
        base["model_id"] = "momentum_4h"
        base["fold_id"] = fold["fold_id"]
        predictions.append(base)
        fold_rows.append({"fold_id": fold["fold_id"], "model_id": "momentum_4h", "train_rows": len(tr), "validation_rows": len(va), **summarize(base)})

        for model_id, model in models().items():
            model.fit(Xtr, ytr)
            p = va[["timestamp_utc", "product_id"]].copy()
            p["actual"] = yv.to_numpy()
            p["predicted_score"] = model.predict(Xv)
            p["model_id"] = model_id
            p["fold_id"] = fold["fold_id"]
            predictions.append(p)
            fold_rows.append({"fold_id": fold["fold_id"], "model_id": model_id, "train_rows": len(tr), "validation_rows": len(va), **summarize(p)})
        print(f"[SUCCESS] {fold['fold_id']} train={len(tr):,} validation={len(va):,} {fold['start']} -> {fold['end']}")

    pred = pd.concat(predictions, ignore_index=True)
    fold_metrics = pd.DataFrame(fold_rows)
    summaries = []
    for model_id, g in pred.groupby("model_id"):
        summaries.append({"model_id": model_id, "fold_count": int(g["fold_id"].nunique()), **summarize(g)})
    summary = pd.DataFrame(summaries).sort_values("mean_ic", ascending=False)

    pred.to_parquet(output_root / "predictions.parquet", index=False)
    fold_metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "phase": 2,
        "stage": "walk_forward_model_research",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_target": PRIMARY_TARGET,
        "primary_horizon_bars": PRIMARY_HORIZON_BARS,
        "primary_horizon_minutes": 240,
        "models": ["momentum_4h", "ridge", "hist_gradient_boosting"],
        "feature_count": len(features),
        "features": features,
        "fold_count": len(folds),
        "validation_days": VALIDATION_DAYS,
        "purge_minutes": 15 * PRIMARY_HORIZON_BARS,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "xrp_policy": "XRP excluded entirely; dedicated XRP modeling is a separate research track.",
        "policy": "out-of-sample model research only; no portfolio simulation, threshold tuning, promotion, or live trading",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return summary, fold_metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    summary, _ = run(args.phase1_root, args.output_root)
    print("CRYPTO 15M V1 PHASE 2")
    print("=" * 80)
    print(summary.to_string(index=False))
    print(f"Output: {args.output_root / 'metrics_summary.csv'}")
    print("Primary target: 4h BTC-relative forward return")
    print("XRP remains isolated. Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
