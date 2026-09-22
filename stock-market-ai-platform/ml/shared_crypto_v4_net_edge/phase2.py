"""Shared Crypto V4 Net-Edge Phase 2: purged walk-forward return models.

Fits preregistered Ridge and HistGradientBoosting regressors to the isolated
Phase 1 regime and ranking datasets.  Every fold is chronological and has a
four-hour purge before validation.  Only observations strictly before the
2026-09-01 future holdout are accepted.

This phase measures signal quality.  It does not select an execution policy,
compound overlapping returns, inspect future observations, modify paper state,
or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v4_net_edge"
PHASE1_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase1")
REGIME_DATASET = PHASE1_ROOT / "regime_dataset.parquet"
RANKING_DATASET = PHASE1_ROOT / "ranking_dataset.parquet"
CONTRACT_PATH = PHASE1_ROOT / "preregistered_contract.json"
OUTPUT_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase2")

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
PURGE = timedelta(hours=4)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 90
MAX_FOLDS = 6
HORIZONS = ("1h", "4h")
MODEL_IDS = ("ridge", "hist_gradient_boosting_regressor")
RANDOM_STATE = 1729


def model_candidates(layer: str) -> dict[str, Pipeline]:
    min_leaf = 50 if layer == "regime" else 200
    return {
        "ridge": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
        "hist_gradient_boosting_regressor": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_iter=100,
                max_leaf_nodes=15,
                min_samples_leaf=min_leaf,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
    }


def _load(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, str(path))
    return frame.sort_values("timestamp_utc").reset_index(drop=True)


def validate_pre_holdout(frame: pd.DataFrame, source: str = "dataset") -> None:
    """Refuse any observation at or beyond the untouched future boundary."""
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def make_folds(timestamps: pd.Series) -> list[dict]:
    unique = pd.Series(pd.to_datetime(timestamps, utc=True).drop_duplicates()).sort_values()
    if unique.empty:
        raise RuntimeError("Cannot construct folds from an empty timestamp series")
    first = unique.iloc[0].floor("D")
    last = unique.iloc[-1]
    starts = list(pd.date_range(
        first + timedelta(days=MIN_TRAIN_DAYS),
        last,
        freq=f"{VALIDATION_DAYS}D",
        tz="UTC",
    ))[-MAX_FOLDS:]
    folds = []
    for start in starts:
        end = min(start + timedelta(days=VALIDATION_DAYS), HOLDOUT)
        train_end = start - PURGE
        train = timestamps < train_end
        validation = (timestamps >= start) & (timestamps < end)
        if train.any() and validation.any():
            folds.append({
                "fold_id": f"fold_{len(folds) + 1:02d}",
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })
    if not folds:
        raise RuntimeError("No valid purged walk-forward folds were constructed")
    return folds


def choose_sleeve(predicted_btc: np.ndarray, predicted_alt: np.ndarray) -> np.ndarray:
    values = np.column_stack([predicted_btc, predicted_alt, np.zeros(len(predicted_btc))])
    labels = np.array(["BTC", "ALT", "CASH"], dtype=object)
    return labels[np.argmax(values, axis=1)]


def _safe_correlation(actual, predicted) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) < 2 or np.std(actual) == 0 or np.std(predicted) == 0:
        return np.nan
    return float(np.corrcoef(actual, predicted)[0, 1])


def _regime_walk_forward(data: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = make_folds(data["timestamp_utc"])
    metrics = []
    predictions = []
    for fold in folds:
        train = data.loc[fold["train"]].copy()
        validation = data.loc[fold["validation"]].copy()
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold['fold_id']} violates the four-hour purge")
        for horizon in HORIZONS:
            btc_target = f"btc_forward_return_{horizon}"
            alt_target = f"alt_forward_return_{horizon}"
            for model_id, template in model_candidates("regime").items():
                btc_model = clone(template).fit(train[features], train[btc_target])
                alt_model = clone(template).fit(train[features], train[alt_target])
                pred_btc = btc_model.predict(validation[features])
                pred_alt = alt_model.predict(validation[features])
                proposed = choose_sleeve(pred_btc, pred_alt)
                actual_btc = validation[btc_target].to_numpy(float)
                actual_alt = validation[alt_target].to_numpy(float)
                selected = np.select(
                    [proposed == "BTC", proposed == "ALT"],
                    [actual_btc, actual_alt],
                    default=0.0,
                ).astype(float)
                counts = pd.Series(proposed).value_counts()
                metrics.append({
                    "layer": "regime", "fold_id": fold["fold_id"],
                    "model_id": model_id, "horizon": horizon,
                    "train_rows": int(len(train)), "validation_rows": int(len(validation)),
                    "validation_start_utc": fold["start"].isoformat(),
                    "validation_end_utc": fold["end"].isoformat(),
                    "btc_mae": float(np.mean(np.abs(pred_btc - actual_btc))),
                    "alt_mae": float(np.mean(np.abs(pred_alt - actual_alt))),
                    "btc_correlation": _safe_correlation(actual_btc, pred_btc),
                    "alt_correlation": _safe_correlation(actual_alt, pred_alt),
                    "mean_selected_return": float(np.mean(selected)),
                    "mean_excess_vs_btc": float(np.mean(selected - actual_btc)),
                    "mean_excess_vs_equal_alt": float(np.mean(selected - actual_alt)),
                    "positive_period_fraction": float(np.mean(selected > 0)),
                    "btc_fraction": float(counts.get("BTC", 0) / len(validation)),
                    "alt_fraction": float(counts.get("ALT", 0) / len(validation)),
                    "cash_fraction": float(counts.get("CASH", 0) / len(validation)),
                })
                out = validation[["timestamp_utc", btc_target, alt_target]].copy()
                out["layer"] = "regime"
                out["fold_id"] = fold["fold_id"]
                out["model_id"] = model_id
                out["horizon"] = horizon
                out["predicted_btc_return"] = pred_btc
                out["predicted_alt_return"] = pred_alt
                out["proposed_sleeve"] = proposed
                out["selected_actual_return"] = selected
                predictions.append(out)
        print(f"[SUCCESS] regime {fold['fold_id']} train={len(train):,} validation={len(validation):,}")
    return pd.DataFrame(metrics), pd.concat(predictions, ignore_index=True)


def _rank_ic(group: pd.DataFrame) -> float:
    if (len(group) < 2
            or group["predicted_score"].nunique(dropna=True) < 2
            or group["actual_return"].nunique(dropna=True) < 2):
        return np.nan
    return float(group["predicted_score"].corr(group["actual_return"], method="spearman"))


def _ranking_walk_forward(data: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = make_folds(data["timestamp_utc"])
    metrics = []
    predictions = []
    for fold in folds:
        train = data.loc[fold["train"]].copy()
        validation = data.loc[fold["validation"]].copy()
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold['fold_id']} violates the four-hour purge")
        for horizon in HORIZONS:
            target = f"forward_return_{horizon}"
            for model_id, template in model_candidates("ranking").items():
                model = clone(template).fit(train[features], train[target])
                score = model.predict(validation[features])
                out = validation[["timestamp_utc", "product_id", target]].copy()
                out = out.rename(columns={target: "actual_return"})
                out["layer"] = "ranking"
                out["fold_id"] = fold["fold_id"]
                out["model_id"] = model_id
                out["horizon"] = horizon
                out["predicted_score"] = score
                daily_ic = out.groupby("timestamp_utc", sort=True).apply(_rank_ic, include_groups=False)
                ordered = out.sort_values(["timestamp_utc", "predicted_score"], ascending=[True, False])
                top3 = ordered.groupby("timestamp_utc", sort=False).head(3)
                top5 = ordered.groupby("timestamp_utc", sort=False).head(5)
                equal_alt = out.groupby("timestamp_utc")["actual_return"].mean()
                top3_mean = top3.groupby("timestamp_utc")["actual_return"].mean()
                top5_mean = top5.groupby("timestamp_utc")["actual_return"].mean()
                metrics.append({
                    "layer": "ranking", "fold_id": fold["fold_id"],
                    "model_id": model_id, "horizon": horizon,
                    "train_rows": int(len(train)), "validation_rows": int(len(validation)),
                    "validation_start_utc": fold["start"].isoformat(),
                    "validation_end_utc": fold["end"].isoformat(),
                    "mae": float(np.mean(np.abs(score - out["actual_return"].to_numpy(float)))),
                    "correlation": _safe_correlation(out["actual_return"], score),
                    "mean_rank_ic": float(daily_ic.mean()),
                    "positive_rank_ic_fraction": float((daily_ic > 0).mean()),
                    "top3_mean_return": float(top3_mean.mean()),
                    "top5_mean_return": float(top5_mean.mean()),
                    "equal_alt_mean_return": float(equal_alt.mean()),
                    "top3_excess_vs_equal_alt": float((top3_mean - equal_alt).mean()),
                    "top5_excess_vs_equal_alt": float((top5_mean - equal_alt).mean()),
                })
                predictions.append(out)
        print(f"[SUCCESS] ranking {fold['fold_id']} train={len(train):,} validation={len(validation):,}")
    return pd.DataFrame(metrics), pd.concat(predictions, ignore_index=True)


def _summary(metrics: pd.DataFrame) -> pd.DataFrame:
    numeric = [column for column in metrics.columns if column not in {
        "layer", "fold_id", "model_id", "horizon", "validation_start_utc", "validation_end_utc"
    }]
    rows = []
    for keys, group in metrics.groupby(["layer", "model_id", "horizon"], sort=True):
        row = {"layer": keys[0], "model_id": keys[1], "horizon": keys[2],
               "fold_count": int(group["fold_id"].nunique())}
        for column in numeric:
            row[f"mean_{column}"] = float(pd.to_numeric(group[column], errors="coerce").mean())
        rows.append(row)
    return pd.DataFrame(rows)


def run(phase1_root: Path = PHASE1_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    phase1_root = Path(phase1_root)
    output_root = Path(output_root)
    contract = json.loads((phase1_root / "preregistered_contract.json").read_text(encoding="utf-8"))
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("Phase 1 holdout boundary differs from Phase 2 contract")
    regime = _load(phase1_root / "regime_dataset.parquet")
    ranking = _load(phase1_root / "ranking_dataset.parquet")
    regime_features = list(contract["regime_feature_columns"])
    ranking_features = list(contract["ranking_feature_columns"])
    regime_metrics, regime_predictions = _regime_walk_forward(regime, regime_features)
    ranking_metrics, ranking_predictions = _ranking_walk_forward(ranking, ranking_features)
    metrics = pd.concat([regime_metrics, ranking_metrics], ignore_index=True, sort=False)
    summary = _summary(metrics)

    output_root.mkdir(parents=True, exist_ok=True)
    regime_predictions.to_parquet(output_root / "regime_predictions.parquet", index=False)
    ranking_predictions.to_parquet(output_root / "ranking_predictions.parquet", index=False)
    metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "purged_walk_forward_return_regression",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "purge_hours": int(PURGE.total_seconds() // 3600),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "horizons": list(HORIZONS),
        "models": list(MODEL_IDS),
        "regime_rows": int(len(regime)),
        "ranking_rows": int(len(ranking)),
        "regime_prediction_rows": int(len(regime_predictions)),
        "ranking_prediction_rows": int(len(ranking_predictions)),
        "outputs": {
            "regime_predictions": str(output_root / "regime_predictions.parquet"),
            "ranking_predictions": str(output_root / "ranking_predictions.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "metrics_summary": str(output_root / "metrics_summary.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "execution_policy_selected": False,
            "portfolio_compounded": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": "Review fold stability, then run preregistered cost-aware portfolio candidates in Phase 3.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase1_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
