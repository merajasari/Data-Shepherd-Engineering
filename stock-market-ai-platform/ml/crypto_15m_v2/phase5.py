"""Crypto 15m V2 Phase 5: freeze HGB + confirm_2 for future paper evaluation.

Phase 4 was exploratory and selected confirm_2 as the only turnover policy that
remained above starting equity at the 5 bps sleeve-switch cost assumption. This
phase DOES NOT evaluate that policy again. Instead it freezes the exact model
specification, execution policy, inputs, final development fit, and forward
journal contract before the untouched future evaluation beginning 2026-09-01
UTC.

Research status
---------------
* HGB hyperparameters are unchanged from Phase 2.
* confirm_2 is frozen exactly as defined in Phase 4: a new BTC/ALT/CASH sleeve
  must be predicted for two consecutive hourly decisions before switching.
* The final HGB artifact is fit once on all available Phase 1 development rows
  strictly before the holdout boundary. This is a deployment refit, not another
  validation result.
* No row at or after 2026-09-01 UTC is evaluated here.
* XRP remains excluded and on a separate research track.
* Simulation/paper evaluation only; no brokerage orders are placed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

PHASE1_ROOT = Path("data/model/crypto_15m_v2/phase1")
DATASET_PATH = PHASE1_ROOT / "market_allocation_1h.parquet"
PHASE1_MANIFEST_PATH = PHASE1_ROOT / "manifest.json"
PHASE2_ROOT = Path("data/model/crypto_15m_v2/phase2")
PHASE2_PREDICTIONS_PATH = PHASE2_ROOT / "predictions.parquet"
PHASE2_MANIFEST_PATH = PHASE2_ROOT / "manifest.json"
PHASE4_ROOT = Path("data/model/crypto_15m_v2/phase4")
PHASE4_SUMMARY_PATH = PHASE4_ROOT / "policy_summary.csv"
PHASE4_MANIFEST_PATH = PHASE4_ROOT / "manifest.json"
OUTPUT_ROOT = Path("data/model/crypto_15m_v2/phase5")

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
MODEL_ID = "hist_gradient_boosting"
POLICY_ID = "confirm_2"
CONFIRMATION_HOURS = 2
MINIMUM_HOLD_HOURS = 0
DECISION_FREQUENCY = "1 hour"
ECONOMIC_HORIZON = "4 hours"
FROZEN_COST_REFERENCE_BPS = 5.0
RANDOM_SEED = 1729
LABELS = ("BTC", "ALT", "CASH")

MODEL_FILENAME = "frozen_hgb.joblib"
FREEZE_MANIFEST_FILENAME = "freeze_manifest.json"
STATE_FILENAME = "forward_state.json"
JOURNAL_FILENAME = "forward_journal.csv"

JOURNAL_COLUMNS = [
    "decision_timestamp_utc",
    "raw_predicted_label",
    "executed_label_before",
    "executed_label_after",
    "pending_candidate_label",
    "pending_candidate_count",
    "prob_btc",
    "prob_alt",
    "prob_cash",
    "btc_realized_return_1h",
    "alt_realized_return_1h",
    "gross_selected_return_1h",
    "sleeve_switch",
    "cost_bps_assumption",
    "transaction_cost",
    "net_selected_return_1h",
    "equity",
    "realized_through_utc",
    "status",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
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


def _model() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=150,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=RANDOM_SEED,
        )),
    ])


def _load_inputs():
    paths = [
        DATASET_PATH,
        PHASE1_MANIFEST_PATH,
        PHASE2_PREDICTIONS_PATH,
        PHASE2_MANIFEST_PATH,
        PHASE4_SUMMARY_PATH,
        PHASE4_MANIFEST_PATH,
    ]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)

    phase1 = json.loads(PHASE1_MANIFEST_PATH.read_text(encoding="utf-8"))
    phase2 = json.loads(PHASE2_MANIFEST_PATH.read_text(encoding="utf-8"))
    phase4 = json.loads(PHASE4_MANIFEST_PATH.read_text(encoding="utf-8"))
    data = pd.read_parquet(DATASET_PATH).copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    if (data["timestamp_utc"] >= HOLDOUT).any():
        raise RuntimeError("Holdout rows found in Phase 1 dataset; freeze aborted")

    features = list(phase1["feature_columns"])
    missing = sorted(set(features + ["timestamp_utc", "allocation_target"]) - set(data.columns))
    if missing:
        raise RuntimeError("Phase 1 dataset missing freeze columns: " + ", ".join(missing))

    summary = pd.read_csv(PHASE4_SUMMARY_PATH)
    row = summary[summary["policy"] == POLICY_ID]
    if len(row) != 1:
        raise RuntimeError("Phase 4 confirm_2 policy row not found exactly once")
    row = row.iloc[0]
    # Guard against silently freezing a different exploratory result.
    if int(row["executed_switches"]) != 2505:
        raise RuntimeError("Unexpected confirm_2 switch count; review Phase 4 before freezing")
    if not np.isclose(float(row["ending_equity_5bps"]), 1.213351, atol=5e-6):
        raise RuntimeError("Unexpected confirm_2 5 bps result; review Phase 4 before freezing")

    return data.sort_values("timestamp_utc").reset_index(drop=True), features, phase1, phase2, phase4


def _initial_operational_state(model: Pipeline, data: pd.DataFrame, features: list[str]) -> dict:
    # This is deployment initialization only, not a validation statistic. Use the
    # latest completed pre-holdout row to establish the starting sleeve, then
    # require confirm_2 for every subsequent forward switch.
    latest = data.iloc[[-1]].copy()
    pred = str(model.predict(latest[features])[0])
    proba = model.predict_proba(latest[features])[0]
    classes = list(model.named_steps["model"].classes_)
    probs = {label: float(proba[classes.index(label)]) for label in LABELS}
    ts = pd.Timestamp(latest.iloc[0]["timestamp_utc"])
    return {
        "initialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_development_timestamp_utc": ts.isoformat(),
        "current_executed_label": pred,
        "pending_candidate_label": None,
        "pending_candidate_count": 0,
        "confirmation_hours_required": CONFIRMATION_HOURS,
        "minimum_hold_hours": MINIMUM_HOLD_HOURS,
        "latest_development_raw_prediction": pred,
        "latest_development_probabilities": probs,
        "forward_evaluation_start_utc": HOLDOUT.isoformat(),
        "starting_equity": 1.0,
        "current_equity": 1.0,
        "last_realized_timestamp_utc": None,
        "research_note": (
            "Operational state initialization is not a validation result. Future switches require two consecutive hourly predictions."
        ),
    }


def run(output_root: Path = OUTPUT_ROOT) -> dict:
    data, features, phase1, phase2, phase4 = _load_inputs()
    input_paths = {
        "phase1_dataset": DATASET_PATH,
        "phase1_manifest": PHASE1_MANIFEST_PATH,
        "phase2_predictions": PHASE2_PREDICTIONS_PATH,
        "phase2_manifest": PHASE2_MANIFEST_PATH,
        "phase4_policy_summary": PHASE4_SUMMARY_PATH,
        "phase4_manifest": PHASE4_MANIFEST_PATH,
    }
    hashes_before = {name: _sha256(path) for name, path in input_paths.items()}

    model = _model()
    model.fit(data[features], data["allocation_target"])

    output_root.mkdir(parents=True, exist_ok=True)
    model_path = output_root / MODEL_FILENAME
    joblib.dump(model, model_path)
    model_hash = _sha256(model_path)

    state = _initial_operational_state(model, data, features)
    state_path = output_root / STATE_FILENAME
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    journal_path = output_root / JOURNAL_FILENAME
    if journal_path.exists() and journal_path.stat().st_size > 0:
        existing = pd.read_csv(journal_path)
        if list(existing.columns) != JOURNAL_COLUMNS:
            raise RuntimeError("Existing Phase 5 forward journal schema differs from frozen contract")
        if len(existing):
            raise RuntimeError("Forward journal already contains observations; Phase 5 freeze will not overwrite it")
    else:
        pd.DataFrame(columns=JOURNAL_COLUMNS).to_csv(journal_path, index=False)

    hashes_after = {name: _sha256(path) for name, path in input_paths.items()}
    if hashes_before != hashes_after:
        raise RuntimeError("A frozen research input changed while Phase 5 was being created")

    class_counts = data["allocation_target"].value_counts().reindex(LABELS, fill_value=0)
    manifest = {
        "research_version": "crypto_15m_v2",
        "phase": 5,
        "stage": "frozen_forward_candidate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "research_status": (
            "FROZEN CANDIDATE FOR FUTURE PAPER EVALUATION. confirm_2 was selected after exploratory Phase 4 and is not an untouched historical result."
        ),
        "future_evaluation_start_utc": HOLDOUT.isoformat(),
        "model": {
            "model_id": MODEL_ID,
            "artifact": str(model_path),
            "artifact_sha256": model_hash,
            "training_rows": int(len(data)),
            "training_start_utc": data["timestamp_utc"].min().isoformat(),
            "training_end_utc": data["timestamp_utc"].max().isoformat(),
            "feature_count": len(features),
            "feature_columns": features,
            "hyperparameters": {
                "learning_rate": 0.05,
                "max_iter": 150,
                "max_leaf_nodes": 15,
                "l2_regularization": 1.0,
                "random_state": RANDOM_SEED,
                "imputer": "median",
            },
            "deployment_refit_policy": (
                "Single final fit on all available development rows strictly before 2026-09-01 UTC after model/policy selection; no future results used."
            ),
        },
        "execution_policy": {
            "policy_id": POLICY_ID,
            "decision_frequency": DECISION_FREQUENCY,
            "economic_horizon": ECONOMIC_HORIZON,
            "confirmation_hours": CONFIRMATION_HOURS,
            "minimum_hold_hours": MINIMUM_HOLD_HOURS,
            "rule": (
                "Maintain the current sleeve unless a different raw BTC/ALT/CASH prediction occurs for two consecutive hourly decisions; switch on the second confirmation."
            ),
            "allowed_sleeves": list(LABELS),
            "frozen_cost_reference_bps": FROZEN_COST_REFERENCE_BPS,
        },
        "development_target_counts": {k: int(v) for k, v in class_counts.items()},
        "input_sha256": hashes_before,
        "xrp_policy": "XRP is excluded from this shared model and remains on a separate research track.",
        "cost_limitation": (
            "The 5 bps reference is sleeve-switch cost only. Equal-weight ALT constituent-level rebalance costs remain unmodeled and must be addressed before any real-money interpretation."
        ),
        "forward_journal_contract": {
            "path": str(journal_path),
            "columns": JOURNAL_COLUMNS,
            "starting_equity": 1.0,
            "append_only_after_freeze": True,
            "evaluation_policy": (
                "Only genuinely new completed hourly decisions at or after 2026-09-01 UTC may enter the forward journal. Historical rows must never be backfilled into the forward evaluation."
            ),
        },
        "state": {
            "path": str(state_path),
            "initial_current_executed_label": state["current_executed_label"],
            "initial_pending_candidate_label": None,
            "initial_pending_candidate_count": 0,
        },
        "freeze_policy": (
            "No model hyperparameter, feature set, class definition, confirmation rule, holding rule, cost reference, or XRP inclusion rule may change after this freeze without creating a new research version."
        ),
        "prohibited": [
            "future-holdout tuning",
            "backfilling the forward journal",
            "brokerage order placement",
            "leverage",
            "shorting",
            "derivatives",
        ],
        "outputs": {
            "model": str(model_path),
            "state": str(state_path),
            "forward_journal": str(journal_path),
            "freeze_manifest": str(output_root / FREEZE_MANIFEST_FILENAME),
        },
    }
    manifest_path = output_root / FREEZE_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    m = run(args.output_root)
    print("CRYPTO 15M V2 PHASE 5")
    print("=" * 100)
    print("FROZEN FOR FUTURE PAPER EVALUATION")
    print(f"Model: {m['model']['model_id']}")
    print(f"Training rows: {m['model']['training_rows']:,}")
    print(f"Training through: {m['model']['training_end_utc']}")
    print(f"Features: {m['model']['feature_count']}")
    print(f"Execution policy: {m['execution_policy']['policy_id']} ({m['execution_policy']['confirmation_hours']} consecutive hourly predictions)")
    print(f"Initial sleeve: {m['state']['initial_current_executed_label']}")
    print(f"Future evaluation begins: {m['future_evaluation_start_utc']}")
    print(f"Model SHA256: {m['model']['artifact_sha256']}")
    print(f"Forward journal: {m['forward_journal_contract']['path']}")
    print("XRP remains separate. No future-holdout result was evaluated.")
    print("No real brokerage orders are placed.")


if __name__ == "__main__":
    main()
