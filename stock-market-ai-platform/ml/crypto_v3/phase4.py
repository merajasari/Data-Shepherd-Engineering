"""Crypto V3 Phase 4: classifier-only gate and ranking portfolio diagnostics.

Consumes only frozen Crypto V3 Phase 2 classifier development predictions plus
frozen Phase 1/source data. The rule was pre-registered after Phase 3 diagnosed
Ridge as the failing rank component:

* Gate: HGB positive-return probability > 0.50.
* Rank passing assets by the same HGB positive-return probability, descending.
* Evaluate top-3, top-5, and top-quintile equal-weight long-only portfolios.
* If no asset passes, hold 100% cash.
* Rebalance every 7 calendar days.
* Evaluate fixed 0/10/25/50 bps transaction-cost scenarios.
* Compare with BTC buy-and-hold, equal-weight non-BTC universe, and cash.

No fitting, threshold search, hyperparameter tuning, BTC V1 signal injection,
leverage, shorting, derivatives, live execution, or future-holdout evaluation occurs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pandas as pd

from ml.crypto_v3.phase1 import DATASET_PATH, FUTURE_HOLDOUT_START_UTC, HORIZON_DAYS, RESEARCH_VERSION, SOURCE_PANEL_PATH
from ml.crypto_v3.phase2 import CLASSIFIER_MODEL_ID, PHASE2_ROOT
from ml.crypto_v3.phase3 import (
    BENCHMARKS,
    CLASSIFIER_THRESHOLD,
    ROUND_TRIP_COST_BPS,
    VARIANTS,
    _sha256,
    simulate_alt_strategy,
    simulate_btc_benchmark,
    summarize,
)

PHASE4_ROOT = Path("data/model/crypto_v3/phase4")
BTC_PRODUCT = "BTC-USD"


def _git_hash():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_inputs(phase2_root=PHASE2_ROOT, dataset_path=DATASET_PATH, source_panel_path=SOURCE_PANEL_PATH):
    phase2_root = Path(phase2_root)
    dataset_path = Path(dataset_path)
    source_panel_path = Path(source_panel_path)
    classifier_path = phase2_root / "classifier_predictions.parquet"
    for path in (classifier_path, dataset_path, source_panel_path):
        if not path.exists():
            raise FileNotFoundError(path)

    clf = pd.read_parquet(classifier_path).copy()
    alt = pd.read_parquet(dataset_path).copy()
    source = pd.read_parquet(source_panel_path).copy()
    for frame in (clf, alt, source):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)

    required = {"timestamp_utc", "product_id", "predicted_positive_probability", "model_id", "fold_id", "split"}
    missing = required - set(clf.columns)
    if missing:
        raise ValueError("Classifier predictions missing required columns: " + ", ".join(sorted(missing)))
    clf = clf[
        (clf["model_id"] == CLASSIFIER_MODEL_ID)
        & (clf["split"] == "development")
        & (clf["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
    ].copy()
    if clf.empty:
        raise ValueError("Frozen HGB development classifier predictions are required")
    key = ["timestamp_utc", "product_id", "fold_id"]
    if clf.duplicated(key).any():
        raise ValueError("Duplicate Crypto V3 classifier prediction keys")
    if (clf["product_id"] == BTC_PRODUCT).any():
        raise ValueError("BTC must not appear in Crypto V3 investable signals")

    signals = clf[["timestamp_utc", "product_id", "fold_id", "split", "predicted_positive_probability"]].copy()
    signals["passes_classifier_gate"] = signals["predicted_positive_probability"] > CLASSIFIER_THRESHOLD
    # Reuse Phase 3 simulator contract, but point its rank column to classifier probability.
    signals["predicted_risk_adjusted_return_7d"] = signals["predicted_positive_probability"]

    return {
        "classifier_predictions": classifier_path,
        "phase1_dataset": dataset_path,
        "source_panel": source_panel_path,
    }, signals.sort_values(["timestamp_utc", "product_id"]), alt, source


def run_phase4(phase2_root=PHASE2_ROOT, dataset_path=DATASET_PATH, source_panel_path=SOURCE_PANEL_PATH, output_root=PHASE4_ROOT):
    paths, signals, alt, source = load_inputs(phase2_root, dataset_path, source_panel_path)
    before = {name: _sha256(path) for name, path in paths.items()}

    paths_out = []
    for variant in VARIANTS + ("equal_weight_non_btc_universe", "cash"):
        for cost in ROUND_TRIP_COST_BPS:
            paths_out.append(simulate_alt_strategy(signals, alt, variant, cost))
    for cost in ROUND_TRIP_COST_BPS:
        paths_out.append(simulate_btc_benchmark(signals, source, cost))

    daily = pd.concat(paths_out, ignore_index=True)
    metrics = pd.DataFrame([
        summarize(g) for _, g in daily.groupby(["variant", "cost_bps_round_trip"], sort=True)
    ])

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    signal_path = output_root / "classifier_only_signals.parquet"
    daily_path = output_root / "portfolio_daily.csv"
    metrics_path = output_root / "portfolio_metrics.csv"
    signals.to_parquet(signal_path, index=False)
    daily.to_csv(daily_path, index=False)
    metrics.to_csv(metrics_path, index=False)

    after = {name: _sha256(path) for name, path in paths.items()}
    if after != before:
        raise RuntimeError("Frozen Crypto V3 inputs changed during Phase 4")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 4,
        "stage": "classifier_only_gate_and_rank_portfolio_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "rule": {
            "classifier_model": CLASSIFIER_MODEL_ID,
            "classifier_threshold": CLASSIFIER_THRESHOLD,
            "classifier_operator": ">",
            "rank_signal": "predicted_positive_probability",
            "rank_direction": "descending",
            "if_no_assets_pass": "100% cash",
            "rebalance_days": HORIZON_DAYS,
        },
        "portfolio_variants": list(VARIANTS),
        "benchmarks": list(BENCHMARKS),
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": "development-only frozen classifier diagnostics; no fitting, threshold search, hyperparameter tuning, BTC V1 signal, leverage, shorting, derivatives, live execution, or future-holdout evaluation",
        "inputs": {name: {"path": str(path), "sha256": before[name]} for name, path in paths.items()},
        "signal_rows": int(len(signals)),
        "gate_pass_rate": float(signals["passes_classifier_gate"].mean()),
        "outputs": {
            "classifier_only_signals": str(signal_path),
            "portfolio_daily": str(daily_path),
            "portfolio_metrics": str(metrics_path),
        },
        "next_step": "Review classifier-only ranking economics versus frozen benchmarks. Do not tune threshold, portfolio size, cadence, or future holdout based on Phase 4 results."
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--source-panel", type=Path, default=SOURCE_PANEL_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE4_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase4(args.phase2_root, args.dataset, args.source_panel, args.output_root), indent=2))


if __name__ == "__main__":
    main()
