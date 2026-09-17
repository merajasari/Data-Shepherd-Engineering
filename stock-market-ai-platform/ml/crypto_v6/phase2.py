"""Crypto V6 Phase 2: paired V5-versus-V6 purged walk-forward training.

Both candidates use the same rows, targets, folds, algorithms, horizons, and
random seed.  The only experimental variable is the point-in-time news feature
set.  Outputs are development evidence and cannot activate a dashboard model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, mean_squared_error

from ml.crypto_v5.config import ALL_HORIZONS_DAYS, FUTURE_HOLDOUT_START_UTC
from ml.crypto_v5.phase2 import FEATURES as V5_FEATURES
from ml.crypto_v5.phase2 import PURGE_DAYS, make_folds, model_definitions
from ml.crypto_v6.phase1 import ALLOCATION_PREFIX, DEFAULT_OUTPUT as PHASE1_ROOT, RANKING_PREFIX
from ml.news_intelligence.vector_features import FEATURE_COLUMNS


RESEARCH_VERSION = "crypto_v6"
OUTPUT_ROOT = PHASE1_ROOT.parent / "phase2"
FEATURE_SET_V5 = "v5_market_only"
FEATURE_SET_V6 = "v6_market_news"
ALLOCATION_NEWS_FEATURES = tuple(f"{ALLOCATION_PREFIX}{name}" for name in FEATURE_COLUMNS)
RANKING_NEWS_FEATURES = tuple(f"{RANKING_PREFIX}{name}" for name in FEATURE_COLUMNS)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path, required):
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{path} missing columns: " + ", ".join(missing))
    if (frame["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
        raise RuntimeError("Crypto V6 Phase 2 refuses future-holdout rows")
    order = ["timestamp_utc"] + (["product_id"] if "product_id" in frame else [])
    return frame.sort_values(order).reset_index(drop=True)


def _paired_feature_sets(news_features):
    return {
        FEATURE_SET_V5: tuple(V5_FEATURES),
        FEATURE_SET_V6: tuple(V5_FEATURES) + tuple(news_features),
    }


def validate_paired_predictions(frame, keys):
    """Require one-for-one V5/V6 prediction coverage on the comparison clock."""
    required = set(keys) | {"feature_set"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Prediction frame missing columns: " + ", ".join(missing))
    counts = frame.groupby([*keys, "feature_set"], dropna=False).size().unstack("feature_set", fill_value=0)
    for feature_set in (FEATURE_SET_V5, FEATURE_SET_V6):
        if feature_set not in counts:
            raise RuntimeError(
                "V5 and V6 predictions do not share an identical comparison clock; "
                f"missing {feature_set}"
            )
    if not counts[FEATURE_SET_V5].equals(counts[FEATURE_SET_V6]):
        raise RuntimeError("V5 and V6 predictions do not share an identical comparison clock")


def _append_allocation_predictions(rows, validation, predictions, fold, model_id,
                                   horizon, feature_set):
    validation = validation.reset_index(drop=True)
    for position, row in validation.iterrows():
        scores = {sleeve: float(values[position]) for sleeve, values in predictions.items()}
        choice = max(("btc", "alt", "cash"), key=lambda sleeve: scores[sleeve])
        rows.append({
            "timestamp_utc": row.timestamp_utc,
            "fold_id": fold.fold_id,
            "feature_set": feature_set,
            "model_id": model_id,
            "horizon_days": horizon,
            "predicted_sleeve": choice.upper(),
            **{f"predicted_{sleeve}_return": value for sleeve, value in scores.items()},
            **{
                f"actual_{sleeve}_return": float(row[f"{sleeve}_forward_return_{horizon}d"])
                for sleeve in scores
            },
        })


def _metrics(allocation, ranking):
    rows = []
    for (feature_set, model_id, horizon), group in allocation.groupby(
        ["feature_set", "model_id", "horizon_days"]
    ):
        for sleeve in ("btc", "alt", "cash"):
            actual = group[f"actual_{sleeve}_return"]
            predicted = group[f"predicted_{sleeve}_return"]
            rows.append({
                "layer": "allocation",
                "target": sleeve,
                "feature_set": feature_set,
                "model_id": model_id,
                "horizon_days": int(horizon),
                "observations": len(group),
                "mae": float(mean_absolute_error(actual, predicted)),
                "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
                "correlation": float(actual.corr(predicted)),
            })
    for (feature_set, model_id, horizon), group in ranking.groupby(
        ["feature_set", "model_id", "horizon_days"]
    ):
        actual, predicted = group["actual_risk_adjusted_return"], group["predicted_score"]
        rows.append({
            "layer": "ranking",
            "target": "risk_adjusted_return",
            "feature_set": feature_set,
            "model_id": model_id,
            "horizon_days": int(horizon),
            "observations": len(group),
            "mae": float(mean_absolute_error(actual, predicted)),
            "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
            "correlation": float(actual.corr(predicted)),
        })
    return pd.DataFrame(rows)


def run(allocation_path=PHASE1_ROOT / "allocation_dataset.parquet",
        ranking_path=PHASE1_ROOT / "ranking_dataset.parquet",
        phase1_manifest_path=PHASE1_ROOT / "manifest.json", output_root=OUTPUT_ROOT):
    paths = [Path(allocation_path), Path(ranking_path), Path(phase1_manifest_path)]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
    input_hashes = {str(path): _sha256(path) for path in paths}
    allocation_targets = [
        f"{sleeve}_forward_return_{horizon}d"
        for horizon in ALL_HORIZONS_DAYS
        for sleeve in ("btc", "alt", "cash")
    ]
    ranking_targets = [f"risk_adjusted_forward_return_{horizon}d" for horizon in ALL_HORIZONS_DAYS]
    allocation = _load(paths[0], [
        "timestamp_utc", *V5_FEATURES, *ALLOCATION_NEWS_FEATURES, *allocation_targets
    ])
    ranking = _load(paths[1], [
        "timestamp_utc", "product_id", *V5_FEATURES, *RANKING_NEWS_FEATURES,
        *ranking_targets, *[f"forward_return_{horizon}d" for horizon in ALL_HORIZONS_DAYS],
    ])
    folds, models = make_folds(allocation["timestamp_utc"]), model_definitions()
    allocation_rows, ranking_rows = [], []
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    for fold in folds:
        atrain = allocation[allocation["timestamp_utc"].between(fold.train_start_utc, fold.train_end_utc)]
        aval = allocation[allocation["timestamp_utc"].between(fold.validation_start_utc, fold.validation_end_utc)]
        rtrain = ranking[ranking["timestamp_utc"].between(fold.train_start_utc, fold.train_end_utc)]
        rval = ranking[ranking["timestamp_utc"].between(fold.validation_start_utc, fold.validation_end_utc)]
        if any(frame.empty for frame in (atrain, aval, rtrain, rval)):
            raise ValueError(f"Empty Crypto V6 fold {fold.fold_id}")
        if atrain["timestamp_utc"].max() >= aval["timestamp_utc"].min() - pd.Timedelta(PURGE_DAYS, unit="D"):
            raise RuntimeError("Crypto V6 allocation purge violation")
        for model_id, template in models.items():
            for horizon in ALL_HORIZONS_DAYS:
                for feature_set, features in _paired_feature_sets(ALLOCATION_NEWS_FEATURES).items():
                    predictions = {}
                    for sleeve in ("btc", "alt", "cash"):
                        target = f"{sleeve}_forward_return_{horizon}d"
                        fitted = clone(template).fit(atrain[list(features)], atrain[target])
                        predictions[sleeve] = fitted.predict(aval[list(features)])
                        artifact = output_root / "artifacts" / feature_set / "allocation" / fold.fold_id / model_id / f"{sleeve}_{horizon}d.joblib"
                        artifact.parent.mkdir(parents=True, exist_ok=True)
                        joblib.dump(fitted, artifact)
                    _append_allocation_predictions(
                        allocation_rows, aval, predictions, fold, model_id, horizon, feature_set
                    )
                for feature_set, features in _paired_feature_sets(RANKING_NEWS_FEATURES).items():
                    target = f"risk_adjusted_forward_return_{horizon}d"
                    fitted = clone(template).fit(rtrain[list(features)], rtrain[target])
                    scores = fitted.predict(rval[list(features)])
                    artifact = output_root / "artifacts" / feature_set / "ranking" / fold.fold_id / model_id / f"ranking_{horizon}d.joblib"
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    joblib.dump(fitted, artifact)
                    for position, row in rval.reset_index(drop=True).iterrows():
                        ranking_rows.append({
                            "timestamp_utc": row.timestamp_utc,
                            "product_id": row.product_id,
                            "fold_id": fold.fold_id,
                            "feature_set": feature_set,
                            "model_id": model_id,
                            "horizon_days": horizon,
                            "predicted_score": float(scores[position]),
                            "actual_risk_adjusted_return": float(row[target]),
                            "actual_forward_return": float(row[f"forward_return_{horizon}d"]),
                        })
    allocation_predictions = pd.DataFrame(allocation_rows)
    ranking_predictions = pd.DataFrame(ranking_rows)
    validate_paired_predictions(
        allocation_predictions, ["timestamp_utc", "fold_id", "model_id", "horizon_days"]
    )
    validate_paired_predictions(
        ranking_predictions,
        ["timestamp_utc", "product_id", "fold_id", "model_id", "horizon_days"],
    )
    allocation_output = output_root / "allocation_predictions.parquet"
    ranking_output = output_root / "ranking_predictions.parquet"
    metrics_output = output_root / "paired_metrics.csv"
    allocation_predictions.to_parquet(allocation_output, index=False)
    ranking_predictions.to_parquet(ranking_output, index=False)
    _metrics(allocation_predictions, ranking_predictions).to_csv(metrics_output, index=False)
    if input_hashes != {str(path): _sha256(path) for path in paths}:
        raise RuntimeError("A Crypto V6 Phase 1 input changed during training")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "paired_purged_walk_forward_training",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "experimental_variable": "point-in-time news features only",
        "feature_sets": [FEATURE_SET_V5, FEATURE_SET_V6],
        "models": list(models),
        "horizons_days": list(ALL_HORIZONS_DAYS),
        "purge_days": PURGE_DAYS,
        "folds": [fold.as_json() for fold in folds],
        "identical_comparison_clock_verified": True,
        "inputs": input_hashes,
        "outputs": {
            "allocation_predictions": str(allocation_output),
            "ranking_predictions": str(ranking_output),
            "paired_metrics": str(metrics_output),
        },
        "dashboard_eligibility": False,
        "safety": {
            "crypto_v5_modified": False,
            "holdout_scored": False,
            "paper_state_modified": False,
            "dashboard_modified": False,
            "automatic_promotion": False,
            "brokerage_orders": False,
        },
        "next_step": "Run the paired cost-aware portfolio comparison on the common prediction clock.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allocation", type=Path, default=PHASE1_ROOT / "allocation_dataset.parquet")
    parser.add_argument("--ranking", type=Path, default=PHASE1_ROOT / "ranking_dataset.parquet")
    parser.add_argument("--phase1-manifest", type=Path, default=PHASE1_ROOT / "manifest.json")
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.allocation, args.ranking, args.phase1_manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
