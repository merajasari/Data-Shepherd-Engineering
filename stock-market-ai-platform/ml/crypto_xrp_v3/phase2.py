"""Crypto XRP V3 Phase 2: fresh walk-forward modeling for BTC-default XRP overlay.

Research only. Reuses the leakage-safe XRP V2 Phase 1 feature panel and 1h
BTC-relative target, but does not reuse V2 policy thresholds, score buckets, or
promotion decisions. No policy simulation, holdout inspection, or brokerage
orders occur here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

INPUT = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v3/phase2")
PREDICTIONS = OUTPUT_ROOT / "predictions.parquet"
FOLD_METRICS = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY = OUTPUT_ROOT / "metrics_summary.csv"
MANIFEST = OUTPUT_ROOT / "manifest.json"

TARGET = "btc_relative_forward_return_1h"
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
PURGE = pd.Timedelta(hours=1)
MIN_TRAIN_DAYS = 365
VAL_DAYS = 90
MAX_FOLDS = 8


def _is_forward_outcome_column(name: str) -> bool:
    return (
        name.startswith("forward_return_")
        or name.startswith("btc_forward_return_")
        or name.startswith("btc_relative_forward_return_")
    )


def _load() -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_parquet(INPUT).copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df[df["timestamp_utc"] < HOLDOUT].sort_values("timestamp_utc").reset_index(drop=True)
    if TARGET not in df.columns:
        raise RuntimeError(f"Missing target: {TARGET}")

    excluded = {"timestamp_utc", TARGET}
    features = [
        c
        for c in df.columns
        if c not in excluded
        and not _is_forward_outcome_column(c)
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    if not features:
        raise RuntimeError("No numeric features available")

    leaked = [c for c in features if _is_forward_outcome_column(c)]
    if leaked:
        raise RuntimeError(f"Forward outcome leakage in feature set: {leaked}")

    return df, features


def _folds(df: pd.DataFrame) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    end = min(HOLDOUT, df["timestamp_utc"].max() + pd.Timedelta(minutes=15))
    starts = []
    cursor = end
    for _ in range(MAX_FOLDS):
        start = cursor - pd.Timedelta(days=VAL_DAYS)
        starts.append((start, cursor))
        cursor = start
    starts.reverse()
    out = []
    for i, (vs, ve) in enumerate(starts, start=1):
        train_end = vs - PURGE
        train = df[df["timestamp_utc"] < train_end]
        if train.empty:
            continue
        days = (train["timestamp_utc"].max() - train["timestamp_utc"].min()).days
        if days < MIN_TRAIN_DAYS:
            continue
        out.append((f"fold_{i:02d}", vs, ve))
    return out


def _models(features: list[str]):
    prep = ColumnTransformer([
        (
            "num",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]),
            features,
        )
    ], remainder="drop")
    ridge = Pipeline([
        ("prep", prep),
        ("model", Ridge(alpha=10.0)),
    ])
    hgb = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        (
            "model",
            HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                random_state=42,
            ),
        ),
    ])
    return {"ridge": ridge, "hist_gradient_boosting": hgb}


def _metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    if len(actual) == 0:
        return {}
    sp = spearmanr(actual, pred, nan_policy="omit").statistic
    pear = np.corrcoef(actual, pred)[0, 1] if len(actual) > 1 else np.nan
    return {
        "observation_count": int(len(actual)),
        "spearman": float(sp) if np.isfinite(sp) else np.nan,
        "pearson": float(pear) if np.isfinite(pear) else np.nan,
        "sign_accuracy": float((np.sign(actual) == np.sign(pred)).mean()),
        "mae": float(mean_absolute_error(actual, pred)),
        "rmse": float(mean_squared_error(actual, pred) ** 0.5),
        "prediction_mean": float(np.mean(pred)),
        "actual_mean": float(np.mean(actual)),
        "predicted_positive_fraction": float((pred > 0).mean()),
        "actual_positive_fraction": float((actual > 0).mean()),
    }


def main():
    df, features = _load()
    folds = _folds(df)
    if not folds:
        raise RuntimeError("No valid walk-forward folds")

    pred_rows = []
    metric_rows = []

    for fold_id, vs, ve in folds:
        train_end = vs - PURGE
        train = df[df["timestamp_utc"] < train_end].copy()
        val = df[(df["timestamp_utc"] >= vs) & (df["timestamp_utc"] < ve)].copy()
        if val.empty:
            continue

        X_train = train[features]
        y_train = train[TARGET].to_numpy(float)
        X_val = val[features]
        y_val = val[TARGET].to_numpy(float)

        baseline_col = "btc_relative_return_4bar"
        if baseline_col in val.columns:
            base_pred = pd.to_numeric(val[baseline_col], errors="coerce").fillna(0.0).to_numpy(float)
            m = _metrics(y_val, base_pred)
            metric_rows.append({"fold_id": fold_id, "model_id": "momentum_1h", **m})
            for ts, actual, score in zip(val["timestamp_utc"], y_val, base_pred):
                pred_rows.append({
                    "timestamp_utc": ts,
                    "fold_id": fold_id,
                    "model_id": "momentum_1h",
                    "actual_btc_relative_forward_return_1h": float(actual),
                    "predicted_score": float(score),
                })

        for model_id, model in _models(features).items():
            model.fit(X_train, y_train)
            pred = model.predict(X_val)
            m = _metrics(y_val, pred)
            metric_rows.append({"fold_id": fold_id, "model_id": model_id, **m})
            for ts, actual, score in zip(val["timestamp_utc"], y_val, pred):
                pred_rows.append({
                    "timestamp_utc": ts,
                    "fold_id": fold_id,
                    "model_id": model_id,
                    "actual_btc_relative_forward_return_1h": float(actual),
                    "predicted_score": float(score),
                })
        print(f"[SUCCESS] {fold_id} train={len(train):,} validation={len(val):,} {vs} -> {ve}")

    pred_df = pd.DataFrame(pred_rows)
    metrics = pd.DataFrame(metric_rows)
    if pred_df.empty or metrics.empty:
        raise RuntimeError("No Phase 2 outputs produced")

    summary_rows = []
    for model_id, g in metrics.groupby("model_id", sort=True):
        w = g["observation_count"].to_numpy(float)
        total = float(w.sum())

        def wav(col):
            x = pd.to_numeric(g[col], errors="coerce").to_numpy(float)
            mask = np.isfinite(x) & np.isfinite(w)
            return float(np.average(x[mask], weights=w[mask])) if mask.any() else np.nan

        summary_rows.append({
            "model_id": model_id,
            "fold_count": int(g["fold_id"].nunique()),
            "observation_count": int(total),
            "weighted_spearman": wav("spearman"),
            "weighted_pearson": wav("pearson"),
            "weighted_sign_accuracy": wav("sign_accuracy"),
            "weighted_mae": wav("mae"),
            "weighted_rmse": wav("rmse"),
            "prediction_mean": wav("prediction_mean"),
            "actual_mean": wav("actual_mean"),
            "predicted_positive_fraction": wav("predicted_positive_fraction"),
            "actual_positive_fraction": wav("actual_positive_fraction"),
        })
    summary = pd.DataFrame(summary_rows).sort_values("weighted_spearman", ascending=False)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    pred_df.to_parquet(PREDICTIONS, index=False)
    metrics.to_csv(FOLD_METRICS, index=False)
    summary.to_csv(SUMMARY, index=False)
    MANIFEST.write_text(json.dumps({
        "research_version": "crypto_xrp_v3",
        "phase": 2,
        "stage": "fresh_walk_forward_modeling_leakage_corrected",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective": "Predict 1h XRP-minus-BTC return for a BTC-default selective overlay research track",
        "target": TARGET,
        "feature_count": len(features),
        "features": features,
        "forward_outcome_columns_excluded": True,
        "forward_outcome_exclusion_rule": [
            "forward_return_*",
            "btc_forward_return_*",
            "btc_relative_forward_return_*",
        ],
        "models": ["momentum_1h", "ridge_alpha_10", "hist_gradient_boosting"],
        "walk_forward": {
            "validation_days": VAL_DAYS,
            "max_folds": MAX_FOLDS,
            "minimum_training_days": MIN_TRAIN_DAYS,
            "purge": "1h",
        },
        "invalidated_prior_run": "Any XRP V3 Phase 2 result produced before forward-outcome exclusion is invalid development evidence due to target leakage.",
        "policy_contract": "No policy simulation or threshold selection in Phase 2. BTC remains the pre-registered default state for later phases.",
        "v2_threshold_reuse": False,
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "future_holdout_inspected": False,
        "brokerage_orders": False,
        "next_step": "Re-evaluate corrected model stability. Only if leakage-free predictive evidence is adequate, design a separately pre-registered BTC-default turnover-aware overlay policy.",
    }, indent=2) + "\n")

    print("CRYPTO XRP V3 PHASE 2")
    print("=" * 100)
    print(summary.to_string(index=False))
    print("Forward outcome columns excluded. Prior leaked V3 Phase 2 run is invalid.")
    print("No policy tuning, freeze, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
