"""Crypto XRP V2 Phase 2: leakage-safe 15-minute / 1-hour walk-forward research.

Primary target is one-hour BTC-relative XRP return. This phase measures raw
predictive signal only; it does not select turnover thresholds, simulate a
portfolio, promote a model, inspect the future holdout, or place orders.
Frozen XRP V1 Phase 6 remains unchanged as the benchmark.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_xrp_v2 import RESEARCH_VERSION

DATASET = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
PHASE1_MANIFEST = Path("data/model/crypto_xrp_v2/phase1/manifest.json")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v2/phase2")
PREDICTIONS_PATH = OUTPUT_ROOT / "predictions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

PRIMARY_TARGET = "btc_relative_forward_return_1h"
BASELINE_FEATURE = "btc_relative_return_4bar"
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
PURGE = pd.Timedelta(hours=1)
MIN_TRAIN_DAYS = 365
VALIDATION_DAYS = 90
MAX_FOLDS = 8

ID_COLUMNS = {"timestamp_utc", "product_id", "segment_id", "open", "high", "low", "close", "volume"}
TARGET_PREFIXES = ("forward_return_", "btc_forward_return_", "btc_relative_forward_return_")


def feature_columns(df: pd.DataFrame) -> list[str]:
    features = [c for c in df.columns if c not in ID_COLUMNS and not c.startswith(TARGET_PREFIXES)]
    if BASELINE_FEATURE not in features:
        raise RuntimeError(f"Expected 1-hour momentum baseline missing: {BASELINE_FEATURE}")
    return features


def model_candidates() -> dict:
    return {
        "ridge": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                max_iter=150,
                learning_rate=0.05,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                random_state=42,
            )),
        ]),
    }


def make_folds(df: pd.DataFrame) -> list[dict]:
    first = df["timestamp_utc"].min().floor("D")
    last = df["timestamp_utc"].max().floor("D")
    starts = list(pd.date_range(
        first + pd.Timedelta(days=MIN_TRAIN_DAYS),
        last,
        freq=f"{VALIDATION_DAYS}D",
        tz="UTC",
    ))[-MAX_FOLDS:]
    folds = []
    for start in starts:
        end = min(start + pd.Timedelta(days=VALIDATION_DAYS), HOLDOUT)
        train_end = start - PURGE
        train = df["timestamp_utc"] < train_end
        validation = (df["timestamp_utc"] >= start) & (df["timestamp_utc"] < end)
        if train.any() and validation.any():
            folds.append({"start": start, "end": end, "train_end": train_end, "train": train, "validation": validation})
    for i, fold in enumerate(folds, 1):
        fold["fold_id"] = f"fold_{i:02d}"
    if not folds:
        raise RuntimeError("No valid XRP V2 walk-forward folds")
    return folds


def correlation_safe(a: pd.Series, b: pd.Series) -> float:
    x = pd.to_numeric(a, errors="coerce")
    y = pd.to_numeric(b, errors="coerce")
    ok = x.notna() & y.notna()
    if ok.sum() < 2 or x[ok].nunique() < 2 or y[ok].nunique() < 2:
        return np.nan
    return float(x[ok].corr(y[ok], method="spearman"))


def summarize(frame: pd.DataFrame) -> dict:
    actual = frame["actual"].astype(float)
    predicted = frame["predicted_score"].astype(float)
    return {
        "observation_count": int(len(frame)),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "spearman": correlation_safe(predicted, actual),
        "pearson": float(predicted.corr(actual)) if predicted.nunique() > 1 and actual.nunique() > 1 else np.nan,
        "sign_accuracy": float((np.sign(predicted) == np.sign(actual)).mean()),
        "prediction_mean": float(predicted.mean()),
        "actual_mean": float(actual.mean()),
        "predicted_positive_fraction": float((predicted > 0).mean()),
        "actual_positive_fraction": float((actual > 0).mean()),
    }


def weighted_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_id, group in metrics.groupby("model_id"):
        weights = group["observation_count"].to_numpy(float)
        def wa(col):
            values = pd.to_numeric(group[col], errors="coerce").to_numpy(float)
            ok = np.isfinite(values)
            return float(np.average(values[ok], weights=weights[ok])) if ok.any() else np.nan
        rows.append({
            "model_id": model_id,
            "fold_count": int(len(group)),
            "observation_count": int(group["observation_count"].sum()),
            "weighted_spearman": wa("spearman"),
            "weighted_pearson": wa("pearson"),
            "weighted_sign_accuracy": wa("sign_accuracy"),
            "weighted_mae": wa("mae"),
            "weighted_rmse": wa("rmse"),
            "prediction_mean": wa("prediction_mean"),
            "actual_mean": wa("actual_mean"),
            "predicted_positive_fraction": wa("predicted_positive_fraction"),
            "actual_positive_fraction": wa("actual_positive_fraction"),
        })
    return pd.DataFrame(rows).sort_values("model_id").reset_index(drop=True)


def run() -> pd.DataFrame:
    phase1_meta = json.loads(PHASE1_MANIFEST.read_text())
    df = pd.read_parquet(DATASET).copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if set(df["product_id"].dropna().unique()) != {"XRP-USD"}:
        raise RuntimeError("XRP V2 input contains non-XRP products")
    if (df["timestamp_utc"] >= HOLDOUT).any():
        raise RuntimeError("XRP V2 Phase 2 input contains future-holdout rows")
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    features = list(phase1_meta.get("feature_columns") or feature_columns(df))
    folds = make_folds(df)

    predictions = []
    metric_rows = []
    for fold in folds:
        fold_id = fold["fold_id"]
        train = df.loc[fold["train"]].copy()
        validation = df.loc[fold["validation"]].copy()
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold_id}: training extends into 1-hour purge zone")

        baseline = validation[BASELINE_FEATURE].astype(float).to_numpy()
        baseline_frame = validation[["timestamp_utc", "product_id", "segment_id"]].copy()
        baseline_frame["actual"] = validation[PRIMARY_TARGET].to_numpy(float)
        baseline_frame["predicted_score"] = baseline
        baseline_frame["model_id"] = "momentum_1h"
        baseline_frame["fold_id"] = fold_id
        predictions.append(baseline_frame)
        metric_rows.append({"fold_id": fold_id, "model_id": "momentum_1h", **summarize(baseline_frame)})

        for model_id, model in model_candidates().items():
            model.fit(train[features], train[PRIMARY_TARGET])
            predicted = model.predict(validation[features])
            frame = validation[["timestamp_utc", "product_id", "segment_id"]].copy()
            frame["actual"] = validation[PRIMARY_TARGET].to_numpy(float)
            frame["predicted_score"] = np.asarray(predicted, dtype=float)
            frame["model_id"] = model_id
            frame["fold_id"] = fold_id
            predictions.append(frame)
            metric_rows.append({"fold_id": fold_id, "model_id": model_id, **summarize(frame)})

        print(f"[SUCCESS] {fold_id} train={len(train):,} validation={len(validation):,} {fold['start']} -> {fold['end']}")

    pred = pd.concat(predictions, ignore_index=True)
    metrics = pd.DataFrame(metric_rows)
    summary = weighted_summary(metrics)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(PREDICTIONS_PATH, index=False)
    metrics.to_csv(FOLD_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    MANIFEST_PATH.write_text(json.dumps({
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "15m_1h_xrp_walk_forward_signal_research",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_target": PRIMARY_TARGET,
        "baseline": BASELINE_FEATURE,
        "models": ["momentum_1h", "ridge", "hist_gradient_boosting"],
        "decision_frequency_minutes": 15,
        "economic_horizon": "1h",
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "purge_minutes": 60,
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "turnover_policy_status": "NOT YET SELECTED",
        "turnover_rule": "A raw 15-minute score never directly triggers a sell or switch. Phase 3 must evaluate positive expected net edge after cost, slippage, safety buffer, confirmation, hysteresis, and minimum hold.",
        "frozen_benchmark": "Crypto XRP V1 Phase 6 remains unchanged",
        "policy": "signal research only; no portfolio simulation, threshold tuning, promotion, holdout evaluation, or orders",
        "outputs": {"predictions": str(PREDICTIONS_PATH), "fold_metrics": str(FOLD_METRICS_PATH), "summary": str(SUMMARY_PATH)},
    }, indent=2) + "\n")
    return summary


def main():
    summary = run()
    print("CRYPTO XRP V2 PHASE 2")
    print("=" * 100)
    print(summary.to_string(index=False))
    print("Turnover policy not selected. Frozen XRP V1 Phase 6 unchanged. Future holdout untouched.")


if __name__ == "__main__":
    main()
