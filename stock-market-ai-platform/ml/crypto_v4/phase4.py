"""Crypto V4 Phase 4: frozen allocator failure diagnostics.

This phase diagnoses *why* the frozen Crypto V4 Phase 2 HGB BTC/ALT/CASH
allocator failed economically in Phase 3.  It performs no fitting, threshold
search, feature search, portfolio-rule changes, or future-holdout evaluation.

Diagnostics include:
* economic confusion matrix: predicted sleeve vs realized best sleeve;
* conditional realized returns for BTC/ALT/CASH predictions;
* opportunity cost of each prediction/outcome pair;
* fold-by-fold class behavior and economics;
* probability calibration bins for each sleeve;
* confidence-vs-economic-outcome diagnostics;
* the same diagnostics on the frozen 7-day Phase 3 rebalance schedule.

The untouched future holdout begins 2026-09-01 UTC.
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

from ml.crypto_v4.phase1 import FUTURE_HOLDOUT_START_UTC, HORIZON_DAYS
from ml.crypto_v4.phase3 import _rebalance_dates

RESEARCH_VERSION = "crypto_v4"
PHASE = 4
PRIMARY_MODEL_ID = "hist_gradient_boosting"
SLEEVES = ("BTC", "ALT", "CASH")
PHASE1_ROOT = Path("data/model/crypto_v4/phase1")
PHASE2_ROOT = Path("data/model/crypto_v4/phase2")
OUTPUT_ROOT = Path("data/model/crypto_v4/phase4")
DATASET_PATH = PHASE1_ROOT / "market_allocation_dataset.parquet"
PHASE1_MANIFEST_PATH = PHASE1_ROOT / "manifest.json"
PREDICTIONS_PATH = PHASE2_ROOT / "predictions.parquet"
PHASE2_MANIFEST_PATH = PHASE2_ROOT / "manifest.json"
CALIBRATION_BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _return_column(sleeve: str) -> str:
    return {
        "BTC": "btc_forward_return_7d",
        "ALT": "alt_forward_return_7d",
        "CASH": "cash_forward_return_7d",
    }[sleeve]


def load_inputs(
    dataset_path=DATASET_PATH,
    phase1_manifest_path=PHASE1_MANIFEST_PATH,
    predictions_path=PREDICTIONS_PATH,
    phase2_manifest_path=PHASE2_MANIFEST_PATH,
):
    paths = {
        "phase1_dataset": Path(dataset_path),
        "phase1_manifest": Path(phase1_manifest_path),
        "phase2_predictions": Path(predictions_path),
        "phase2_manifest": Path(phase2_manifest_path),
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)

    hashes = {name: _sha256(path) for name, path in paths.items()}
    phase1_manifest = json.loads(paths["phase1_manifest"].read_text(encoding="utf-8"))
    phase2_manifest = json.loads(paths["phase2_manifest"].read_text(encoding="utf-8"))

    expected = phase1_manifest.get("dataset_sha256")
    if expected and expected != hashes["phase1_dataset"]:
        raise RuntimeError("Phase 1 dataset hash does not match manifest")
    phase2_inputs = phase2_manifest.get("inputs", {})
    if phase2_inputs.get("phase1_dataset") and phase2_inputs["phase1_dataset"] != hashes["phase1_dataset"]:
        raise RuntimeError("Phase 2 was not built from the current frozen Phase 1 dataset")

    data = pd.read_parquet(paths["phase1_dataset"]).copy()
    pred = pd.read_parquet(paths["phase2_predictions"]).copy()
    for frame in (data, pred):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (data["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any() or (
        pred["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC
    ).any():
        raise RuntimeError("Future holdout leakage detected")

    required_data = {
        "timestamp_utc", "allocation_target", "best_forward_return_7d",
        "btc_forward_return_7d", "alt_forward_return_7d", "cash_forward_return_7d",
    }
    required_pred = {
        "timestamp_utc", "fold_id", "model_id", "actual_label", "predicted_label",
        "prob_btc", "prob_alt", "prob_cash",
    }
    if required_data - set(data.columns):
        raise ValueError("Phase 1 dataset is missing required diagnostic columns")
    if required_pred - set(pred.columns):
        raise ValueError("Phase 2 predictions are missing required probability columns")

    pred = pred[pred["model_id"] == PRIMARY_MODEL_ID].copy()
    if pred.empty:
        raise ValueError(f"No predictions for {PRIMARY_MODEL_ID}")
    if pred.duplicated("timestamp_utc").any():
        raise ValueError("Duplicate HGB prediction timestamps")

    columns = [
        "timestamp_utc", "allocation_target", "best_forward_return_7d",
        "btc_forward_return_7d", "alt_forward_return_7d", "cash_forward_return_7d",
    ]
    frame = pred.merge(data[columns], on="timestamp_utc", how="inner", validate="one_to_one")
    if len(frame) != len(pred):
        raise ValueError("HGB predictions do not align one-to-one with Phase 1 rows")
    if not (frame["actual_label"] == frame["allocation_target"]).all():
        raise RuntimeError("Phase 2 actual labels disagree with Phase 1 targets")

    frame["selected_forward_return_7d"] = [
        float(row[_return_column(row["predicted_label"])]) for _, row in frame.iterrows()
    ]
    frame["opportunity_cost_7d"] = (
        frame["best_forward_return_7d"] - frame["selected_forward_return_7d"]
    )
    frame["prediction_correct"] = frame["predicted_label"] == frame["actual_label"]
    prob_cols = {"BTC": "prob_btc", "ALT": "prob_alt", "CASH": "prob_cash"}
    frame["predicted_confidence"] = [
        float(row[prob_cols[row["predicted_label"]]]) for _, row in frame.iterrows()
    ]
    return paths, hashes, frame.sort_values("timestamp_utc").reset_index(drop=True)


def economic_confusion(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    rows = []
    for predicted in SLEEVES:
        for actual in SLEEVES:
            g = frame[(frame["predicted_label"] == predicted) & (frame["actual_label"] == actual)]
            rows.append({
                "sample": sample,
                "predicted_sleeve": predicted,
                "actual_best_sleeve": actual,
                "observation_count": int(len(g)),
                "fraction_of_sample": float(len(g) / len(frame)) if len(frame) else 0.0,
                "mean_selected_return_7d": float(g["selected_forward_return_7d"].mean()) if len(g) else np.nan,
                "mean_best_return_7d": float(g["best_forward_return_7d"].mean()) if len(g) else np.nan,
                "mean_opportunity_cost_7d": float(g["opportunity_cost_7d"].mean()) if len(g) else np.nan,
                "median_opportunity_cost_7d": float(g["opportunity_cost_7d"].median()) if len(g) else np.nan,
            })
    return pd.DataFrame(rows)


def sleeve_diagnostics(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    rows = []
    for sleeve in SLEEVES:
        g = frame[frame["predicted_label"] == sleeve]
        rows.append({
            "sample": sample,
            "predicted_sleeve": sleeve,
            "observation_count": int(len(g)),
            "prediction_fraction": float(len(g) / len(frame)) if len(frame) else 0.0,
            "accuracy_when_predicted": float(g["prediction_correct"].mean()) if len(g) else np.nan,
            "mean_selected_return_7d": float(g["selected_forward_return_7d"].mean()) if len(g) else np.nan,
            "median_selected_return_7d": float(g["selected_forward_return_7d"].median()) if len(g) else np.nan,
            "positive_selected_return_rate": float((g["selected_forward_return_7d"] > 0).mean()) if len(g) else np.nan,
            "mean_best_return_7d": float(g["best_forward_return_7d"].mean()) if len(g) else np.nan,
            "mean_opportunity_cost_7d": float(g["opportunity_cost_7d"].mean()) if len(g) else np.nan,
            "mean_predicted_confidence": float(g["predicted_confidence"].mean()) if len(g) else np.nan,
        })
    return pd.DataFrame(rows)


def fold_diagnostics(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fold_id, g in frame.groupby("fold_id", sort=True):
        counts = g["predicted_label"].value_counts()
        actual = g["actual_label"].value_counts()
        rows.append({
            "fold_id": fold_id,
            "start_utc": g["timestamp_utc"].min().isoformat(),
            "end_utc": g["timestamp_utc"].max().isoformat(),
            "observation_count": int(len(g)),
            "accuracy": float(g["prediction_correct"].mean()),
            "mean_selected_return_7d": float(g["selected_forward_return_7d"].mean()),
            "mean_best_return_7d": float(g["best_forward_return_7d"].mean()),
            "mean_opportunity_cost_7d": float(g["opportunity_cost_7d"].mean()),
            "btc_prediction_fraction": float(counts.get("BTC", 0) / len(g)),
            "alt_prediction_fraction": float(counts.get("ALT", 0) / len(g)),
            "cash_prediction_fraction": float(counts.get("CASH", 0) / len(g)),
            "btc_actual_fraction": float(actual.get("BTC", 0) / len(g)),
            "alt_actual_fraction": float(actual.get("ALT", 0) / len(g)),
            "cash_actual_fraction": float(actual.get("CASH", 0) / len(g)),
        })
    return pd.DataFrame(rows)


def calibration_diagnostics(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    rows = []
    for sleeve in SLEEVES:
        pcol = f"prob_{sleeve.lower()}"
        tmp = frame[[pcol, "actual_label", _return_column(sleeve)]].copy()
        tmp["bin"] = pd.cut(tmp[pcol], bins=CALIBRATION_BINS, right=False, include_lowest=True)
        for interval, g in tmp.groupby("bin", observed=False, sort=True):
            if len(g) == 0:
                continue
            realized = (g["actual_label"] == sleeve).astype(float)
            rows.append({
                "sample": sample,
                "sleeve": sleeve,
                "probability_bin": str(interval),
                "observation_count": int(len(g)),
                "mean_predicted_probability": float(g[pcol].mean()),
                "realized_winner_rate": float(realized.mean()),
                "calibration_error": float(g[pcol].mean() - realized.mean()),
                "mean_sleeve_forward_return_7d": float(g[_return_column(sleeve)].mean()),
                "positive_sleeve_return_rate": float((g[_return_column(sleeve)] > 0).mean()),
            })
    return pd.DataFrame(rows)


def confidence_diagnostics(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    tmp = frame.copy()
    bins = (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0000001)
    tmp["confidence_bin"] = pd.cut(
        tmp["predicted_confidence"], bins=bins, right=False, include_lowest=True
    )
    rows = []
    for interval, g in tmp.groupby("confidence_bin", observed=False, sort=True):
        if len(g) == 0:
            continue
        rows.append({
            "sample": sample,
            "confidence_bin": str(interval),
            "observation_count": int(len(g)),
            "mean_confidence": float(g["predicted_confidence"].mean()),
            "accuracy": float(g["prediction_correct"].mean()),
            "mean_selected_return_7d": float(g["selected_forward_return_7d"].mean()),
            "positive_selected_return_rate": float((g["selected_forward_return_7d"] > 0).mean()),
            "mean_opportunity_cost_7d": float(g["opportunity_cost_7d"].mean()),
        })
    return pd.DataFrame(rows)


def run_phase4(
    dataset_path=DATASET_PATH,
    phase1_manifest_path=PHASE1_MANIFEST_PATH,
    predictions_path=PREDICTIONS_PATH,
    phase2_manifest_path=PHASE2_MANIFEST_PATH,
    output_root=OUTPUT_ROOT,
):
    paths, hashes_before, frame = load_inputs(
        dataset_path, phase1_manifest_path, predictions_path, phase2_manifest_path
    )
    rebalance_dates = _rebalance_dates(frame["timestamp_utc"])
    rebalance = frame[frame["timestamp_utc"].isin(rebalance_dates)].copy().reset_index(drop=True)

    confusion = pd.concat([
        economic_confusion(frame, "all_oos_rows"),
        economic_confusion(rebalance, "phase3_rebalance_rows"),
    ], ignore_index=True)
    sleeves = pd.concat([
        sleeve_diagnostics(frame, "all_oos_rows"),
        sleeve_diagnostics(rebalance, "phase3_rebalance_rows"),
    ], ignore_index=True)
    folds = fold_diagnostics(frame)
    calibration = pd.concat([
        calibration_diagnostics(frame, "all_oos_rows"),
        calibration_diagnostics(rebalance, "phase3_rebalance_rows"),
    ], ignore_index=True)
    confidence = pd.concat([
        confidence_diagnostics(frame, "all_oos_rows"),
        confidence_diagnostics(rebalance, "phase3_rebalance_rows"),
    ], ignore_index=True)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "economic_confusion": output_root / "economic_confusion.csv",
        "sleeve_diagnostics": output_root / "sleeve_diagnostics.csv",
        "fold_diagnostics": output_root / "fold_diagnostics.csv",
        "probability_calibration": output_root / "probability_calibration.csv",
        "confidence_diagnostics": output_root / "confidence_diagnostics.csv",
    }
    confusion.to_csv(outputs["economic_confusion"], index=False)
    sleeves.to_csv(outputs["sleeve_diagnostics"], index=False)
    folds.to_csv(outputs["fold_diagnostics"], index=False)
    calibration.to_csv(outputs["probability_calibration"], index=False)
    confidence.to_csv(outputs["confidence_diagnostics"], index=False)

    hashes_after = {name: _sha256(path) for name, path in paths.items()}
    if hashes_after != hashes_before:
        raise RuntimeError("Frozen Crypto V4 inputs changed during Phase 4 diagnostics")

    reb_counts = rebalance["predicted_label"].value_counts()
    summary = {
        "all_oos_observations": int(len(frame)),
        "rebalance_observations": int(len(rebalance)),
        "all_oos_accuracy": float(frame["prediction_correct"].mean()),
        "rebalance_accuracy": float(rebalance["prediction_correct"].mean()),
        "all_oos_mean_selected_return_7d": float(frame["selected_forward_return_7d"].mean()),
        "rebalance_mean_selected_return_7d": float(rebalance["selected_forward_return_7d"].mean()),
        "rebalance_mean_opportunity_cost_7d": float(rebalance["opportunity_cost_7d"].mean()),
        "rebalance_prediction_fractions": {
            sleeve: float(reb_counts.get(sleeve, 0) / len(rebalance)) for sleeve in SLEEVES
        },
    }
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "frozen_market_allocator_failure_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "primary_model_id": PRIMARY_MODEL_ID,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "No rows at or after 2026-09-01 UTC are present or evaluated.",
        "policy": (
            "diagnostics only; no fitting, threshold search, probability cutoff search, feature search, "
            "portfolio-rule changes, promotion, live execution, leverage, shorting, derivatives, or "
            "future-holdout evaluation"
        ),
        "diagnostics": [
            "predicted-vs-realized economic confusion",
            "conditional sleeve economics",
            "opportunity cost by error type",
            "fold-by-fold behavior",
            "class probability calibration",
            "prediction confidence versus realized economics",
        ],
        "inputs": hashes_before,
        "summary": summary,
        "outputs": {name: str(path) for name, path in outputs.items()},
        "next_step": (
            "Use these diagnostics only to decide whether the BTC/ALT/CASH architecture is worth "
            "a separately pre-registered successor experiment. Do not alter Phase 2/3 rules in place."
        ),
    }
    manifest_path = output_root / "manifest.json"
    manifest["outputs"]["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, sleeves, folds, confusion, calibration, confidence


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--phase1-manifest", type=Path, default=PHASE1_MANIFEST_PATH)
    ap.add_argument("--predictions", type=Path, default=PREDICTIONS_PATH)
    ap.add_argument("--phase2-manifest", type=Path, default=PHASE2_MANIFEST_PATH)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    manifest, sleeves, folds, confusion, calibration, confidence = run_phase4(
        args.dataset, args.phase1_manifest, args.predictions, args.phase2_manifest, args.output_root
    )
    print("CRYPTO V4 PHASE 4 — FAILURE DIAGNOSTICS")
    print("=" * 80)
    print("Summary:")
    print(json.dumps(manifest["summary"], indent=2))
    print("\nSLEEVE DIAGNOSTICS — PHASE 3 REBALANCE ROWS")
    print(sleeves[sleeves["sample"] == "phase3_rebalance_rows"].to_string(index=False))
    print("\nFOLD DIAGNOSTICS")
    print(folds.to_string(index=False))
    print("\nECONOMIC CONFUSION — PHASE 3 REBALANCE ROWS")
    print(confusion[confusion["sample"] == "phase3_rebalance_rows"].to_string(index=False))
    print("\nPROBABILITY CALIBRATION — PHASE 3 REBALANCE ROWS")
    print(calibration[calibration["sample"] == "phase3_rebalance_rows"].to_string(index=False))
    print("\nCONFIDENCE DIAGNOSTICS — PHASE 3 REBALANCE ROWS")
    print(confidence[confidence["sample"] == "phase3_rebalance_rows"].to_string(index=False))
    print(f"\nOutput: {manifest['outputs']['manifest']}")
    print("Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
