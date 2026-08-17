"""Crypto 15m V3 Phase 2: leakage-safe 15-minute / 1-hour walk-forward modeling.

Research only. This phase measures raw regime signal before any turnover policy
is selected. Frozen Crypto 15m V2 remains unchanged. No portfolio simulation,
threshold tuning, promotion, future-holdout evaluation, or brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_15m_v3 import RESEARCH_VERSION

DATASET = Path("data/model/crypto_15m_v3/phase1/market_allocation_15m_1h.parquet")
PHASE1_MANIFEST = Path("data/model/crypto_15m_v3/phase1/manifest.json")
OUTPUT_ROOT = Path("data/model/crypto_15m_v3/phase2")
PREDICTIONS_PATH = OUTPUT_ROOT / "predictions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
LABELS = ("BTC", "ALT", "CASH")
PURGE = pd.Timedelta(hours=1)
MIN_TRAIN_DAYS = 365
VALIDATION_DAYS = 90
MAX_FOLDS = 8


def model_candidates() -> dict:
    return {
        "multinomial_logistic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(C=1.0, max_iter=3000, solver="lbfgs", random_state=1729)),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=15,
                l2_regularization=1.0,
                random_state=1729,
            )),
        ]),
    }


def choose_return(df: pd.DataFrame, pred) -> np.ndarray:
    values = {
        "BTC": df["btc_forward_return_1h"].to_numpy(float),
        "ALT": df["alt_forward_return_1h"].to_numpy(float),
        "CASH": df["cash_forward_return_1h"].to_numpy(float),
    }
    return np.array([values[label][i] for i, label in enumerate(pred)], dtype=float)


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
        raise RuntimeError("No valid Shared Crypto V3 walk-forward folds")
    return folds


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
            "weighted_accuracy": wa("accuracy"),
            "weighted_balanced_accuracy": wa("balanced_accuracy"),
            "weighted_log_loss": wa("log_loss"),
            "mean_selected_forward_return_1h": wa("mean_selected_forward_return_1h"),
            "mean_excess_vs_btc": wa("mean_excess_vs_btc"),
            "mean_excess_vs_alt": wa("mean_excess_vs_alt"),
            "btc_prediction_fraction": wa("btc_prediction_fraction"),
            "alt_prediction_fraction": wa("alt_prediction_fraction"),
            "cash_prediction_fraction": wa("cash_prediction_fraction"),
        })
    return pd.DataFrame(rows).sort_values("model_id").reset_index(drop=True)


def run() -> pd.DataFrame:
    meta = json.loads(PHASE1_MANIFEST.read_text())
    df = pd.read_parquet(DATASET).copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if (df["timestamp_utc"] >= HOLDOUT).any():
        raise RuntimeError("Shared Crypto V3 Phase 2 input contains future-holdout rows")
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    features = list(meta["feature_columns"])
    folds = make_folds(df)

    metric_rows = []
    prediction_frames = []
    for fold in folds:
        fold_id = fold["fold_id"]
        train = df.loc[fold["train"]].copy()
        validation = df.loc[fold["validation"]].copy()
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold_id}: training extends into 1-hour purge zone")

        actual = validation["allocation_target"].to_numpy(object)
        candidates = {"majority_class": None, **model_candidates()}
        for model_id, model in candidates.items():
            if model is None:
                pred = np.repeat(train["allocation_target"].value_counts().idxmax(), len(validation)).astype(object)
                proba = None
                classes = None
            else:
                model.fit(train[features], train["allocation_target"])
                pred = model.predict(validation[features])
                proba = model.predict_proba(validation[features])
                classes = model.named_steps["model"].classes_

            selected = choose_return(validation, pred)
            ll = np.nan
            if proba is not None:
                try:
                    ll = float(log_loss(actual, proba, labels=list(classes)))
                except ValueError:
                    pass
            counts = pd.Series(pred).value_counts()
            metric_rows.append({
                "fold_id": fold_id,
                "model_id": model_id,
                "observation_count": int(len(validation)),
                "accuracy": float(accuracy_score(actual, pred)),
                "balanced_accuracy": float(balanced_accuracy_score(actual, pred)),
                "log_loss": ll,
                "mean_selected_forward_return_1h": float(selected.mean()),
                "mean_excess_vs_btc": float(np.mean(selected - validation["btc_forward_return_1h"].to_numpy(float))),
                "mean_excess_vs_alt": float(np.mean(selected - validation["alt_forward_return_1h"].to_numpy(float))),
                "btc_prediction_fraction": float(counts.get("BTC", 0) / len(validation)),
                "alt_prediction_fraction": float(counts.get("ALT", 0) / len(validation)),
                "cash_prediction_fraction": float(counts.get("CASH", 0) / len(validation)),
            })

            out = validation[["timestamp_utc", "allocation_target", "btc_forward_return_1h", "alt_forward_return_1h", "cash_forward_return_1h"]].copy()
            out["fold_id"] = fold_id
            out["model_id"] = model_id
            out["predicted_label"] = pred
            out["selected_forward_return_1h"] = selected
            if proba is not None:
                index = {c: i for i, c in enumerate(classes)}
                for label in LABELS:
                    out[f"prob_{label.lower()}"] = proba[:, index[label]] if label in index else np.nan
            prediction_frames.append(out)
        print(f"[SUCCESS] {fold_id} train={len(train):,} validation={len(validation):,} {fold['start']} -> {fold['end']}")

    metrics = pd.DataFrame(metric_rows)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    summary = weighted_summary(metrics)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS_PATH, index=False)
    metrics.to_csv(FOLD_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    MANIFEST_PATH.write_text(json.dumps({
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "15m_1h_walk_forward_signal_research",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "models": ["majority_class", "multinomial_logistic", "hist_gradient_boosting"],
        "decision_frequency_minutes": 15,
        "economic_horizon": "1h",
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "purge_minutes": 60,
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "turnover_policy_status": "NOT YET SELECTED",
        "turnover_rule": "No raw model prediction may directly trigger a switch. Phase 3 must evaluate positive net edge after cost, slippage, safety buffer, confirmation, hysteresis, and minimum hold.",
        "frozen_benchmark": "Crypto 15m V2 remains unchanged",
        "policy": "signal research only; no portfolio simulation, threshold tuning, promotion, holdout evaluation, or orders",
        "outputs": {"predictions": str(PREDICTIONS_PATH), "fold_metrics": str(FOLD_METRICS_PATH), "summary": str(SUMMARY_PATH)},
    }, indent=2) + "\n")
    return summary


def main():
    summary = run()
    print("CRYPTO 15M V3 PHASE 2")
    print("=" * 100)
    print(summary.to_string(index=False))
    print("Turnover policy not selected. Frozen V2 unchanged. Future holdout untouched.")


if __name__ == "__main__":
    main()
