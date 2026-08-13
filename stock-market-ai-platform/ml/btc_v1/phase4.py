"""BTC V1 Phase 4: audit whether scheduled rebalances create avoidable turnover.

Phase 3 already targets binary 100% BTC / 100% cash weights. This audit verifies
whether turnover occurs only when the frozen HGB signal changes state. It does
not introduce a new threshold, holding period, model, or portfolio rule.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.btc_v1.phase1 import MODEL_ROOT, LABELED_DATASET_PATH, RESEARCH_VERSION
from ml.btc_v1.phase2 import PHASE2_ROOT, FUTURE_HOLDOUT_START_UTC
from ml.btc_v1.phase3 import (
    PRIMARY_MODEL_ID,
    SIGNAL_THRESHOLD,
    REBALANCE_DAYS,
    ROUND_TRIP_COST_BPS,
    load_inputs,
    rebalance_dates,
    simulate,
    summarize,
)

PHASE4_ROOT = MODEL_ROOT / "phase4"
VARIANT = "hgb_positive_else_cash"


def build_transition_audit(predictions):
    signal = predictions.set_index("timestamp_utc")["predicted_return_7d"].sort_index()
    schedule = rebalance_dates(signal.index)
    rows = []
    previous_state = None
    for timestamp in schedule:
        score = float(signal.loc[timestamp])
        state = "btc" if score > SIGNAL_THRESHOLD else "cash"
        changed = previous_state is None or state != previous_state
        rows.append({
            "timestamp_utc": timestamp,
            "predicted_return_7d": score,
            "target_state": state,
            "previous_target_state": previous_state,
            "state_changed": bool(changed),
        })
        previous_state = state
    return pd.DataFrame(rows)


def run_phase4(phase2_root=PHASE2_ROOT, dataset_path=LABELED_DATASET_PATH, output_root=PHASE4_ROOT):
    _, _, pred, data = load_inputs(phase2_root, dataset_path)
    audit = build_transition_audit(pred)

    paths = []
    metrics = []
    for cost in ROUND_TRIP_COST_BPS:
        path = simulate(pred, data, VARIANT, cost)
        paths.append(path)
        metrics.append(summarize(path.sort_values("timestamp_utc")))

    daily = pd.concat(paths, ignore_index=True)
    metrics = pd.DataFrame(metrics)

    zero = daily[daily["cost_bps_round_trip"] == 0.0].copy()
    rebalances = zero[zero["is_rebalance"]].copy().reset_index(drop=True)
    if len(rebalances) != len(audit):
        raise RuntimeError("Phase 3 schedule and Phase 4 transition audit disagree")

    audit["turnover"] = rebalances["turnover"].to_numpy()
    audit["turnover_positive"] = audit["turnover"] > 1e-12
    first = audit.index == 0
    redundant_turnover = audit[~first & ~audit["state_changed"] & audit["turnover_positive"]]
    missed_transition = audit[~first & audit["state_changed"] & ~audit["turnover_positive"]]
    if len(redundant_turnover) or len(missed_transition):
        raise RuntimeError("Turnover is not aligned exactly with frozen signal state changes")

    transition_count = int((audit["state_changed"] & ~first).sum())
    positive_turnover_after_initial = int((audit["turnover_positive"] & ~first).sum())
    total_turnover_zero_cost = float(audit["turnover"].sum())

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    audit_path = output_root / "transition_audit.csv"
    metrics_path = output_root / "portfolio_metrics.csv"
    audit.to_csv(audit_path, index=False)
    metrics.to_csv(metrics_path, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 4,
        "stage": "frozen_signal_turnover_state_change_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_model_id": PRIMARY_MODEL_ID,
        "signal_rule": "predicted_return_7d > 0 => 100% BTC; otherwise 100% cash",
        "rebalance_days": REBALANCE_DAYS,
        "scheduled_rebalances": int(len(audit)),
        "signal_state_transitions_after_initial": transition_count,
        "positive_turnover_events_after_initial": positive_turnover_after_initial,
        "zero_cost_total_turnover": total_turnover_zero_cost,
        "redundant_same_state_turnover_events": int(len(redundant_turnover)),
        "finding": "Phase 3 already incurs turnover only when the binary BTC/cash target state changes; skipping same-state scheduled rebalances cannot reduce turnover or change economics.",
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": "development-only audit of frozen Phase 3 mechanics; no fitting, retuning, threshold search, holding-period search, feature changes, leverage, shorting, derivatives, live execution, or future-holdout evaluation",
        "outputs": {"transition_audit": str(audit_path), "portfolio_metrics": str(metrics_path)},
        "next_step": "Do not create a duplicate state-change strategy: Phase 3 already implements it economically. Decide whether to freeze BTC V1 or pre-register a genuinely distinct turnover-control rule before evaluating it."
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    ap.add_argument("--dataset", type=Path, default=LABELED_DATASET_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE4_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase4(args.phase2_root, args.dataset, args.output_root), indent=2))


if __name__ == "__main__":
    main()
