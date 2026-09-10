"""V10 prospective confirmation monitor.

Locks the Phase-4 primary challenger without changing it and evaluates only
future, post-development decisions. The confirmation window is separate from
V10's untouched formal holdout beginning 2026-11-02 UTC.

In addition to the latest status, this module writes a deterministic cumulative
progress-history artifact derived only from completed matched confirmation
periods. The history is display-only and never changes the frozen contract,
formal holdout, production state, or brokerage state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10.config import FUTURE_HOLDOUT_START_UTC
from ml.v10.phase3 import V8_ID, SWITCH_NEG, _build_periods

BASELINE = V8_ID
PRIMARY = SWITCH_NEG
CONFIRMATION_START_UTC = pd.Timestamp("2026-08-24T00:00:00Z")
POSITIVE_REGIME_NONINFERIORITY_TOLERANCE = 0.00025
OUTPUT_ROOT = Path("data/model/v10/confirmation")
STATUS_PATH = OUTPUT_ROOT / "status.json"
RESULTS_PATH = OUTPUT_ROOT / "confirmation_results.csv"
HISTORY_PATH = OUTPUT_ROOT / "confirmation_history.json"
CONTRACT_PATH = OUTPUT_ROOT / "contract.json"

CONTRACT = {
    "research_version": "stock_v10",
    "candidate": PRIMARY,
    "baseline": BASELINE,
    "confirmation_start_utc": CONFIRMATION_START_UTC.isoformat(),
    "formal_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
    "switch_rule": "use fixed V9 defensive 50/50 rank blend iff SPY trailing 20-session return < 0; else V8 distance-only",
    "top_n": 10,
    "equal_weight": True,
    "entry": "next_session_open",
    "hold_sessions": 5,
    "cohort_offsets": [0, 1, 2, 3, 4],
    "cost_bps_per_dollar_traded": 10,
    "benchmark": "SPY",
    "positive_regime_noninferiority_tolerance_per_period": POSITIVE_REGIME_NONINFERIORITY_TOLERANCE,
    "criteria": [
        "overall_mean_net_relative_return_improvement_vs_v8 > 0",
        "negative_spy_mean_net_relative_return_improvement_vs_v8 > 0",
        "positive_spy_mean_net_relative_return_improvement_vs_v8 >= -0.00025",
    ],
    "candidate_frozen_for_confirmation": True,
    "formal_holdout_scored": False,
    "production_modified": False,
    "brokerage_orders": False,
}


def _sha(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _decision_regime(x):
    if "decision_regime" in x.columns:
        return x["decision_regime"].astype(str)
    raise ValueError("V10 Phase-3 periods must contain decision_regime")


def _json_number(value):
    value = float(value) if value is not None else np.nan
    return value if np.isfinite(value) else None


def _write_history(results: pd.DataFrame | None, contract_sha256: str):
    """Write cumulative, point-in-time confirmation progress for the dashboard.

    Each point includes all completed matched periods whose exit timestamp is at
    or before that point. Re-running this function is deterministic for the same
    completed evidence and cannot add pre-confirmation/development observations.
    """
    payload = {
        "schema_version": 1,
        "research_version": "stock_v10",
        "candidate": PRIMARY,
        "baseline": BASELINE,
        "contract_sha256": contract_sha256,
        "confirmation_start_utc": CONFIRMATION_START_UTC.isoformat(),
        "formal_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "history": [],
        "formal_holdout_scored": False,
        "production_modified": False,
        "brokerage_orders": False,
    }

    if results is not None and not results.empty:
        ordered = results.copy()
        ordered["exit_timestamp_utc"] = pd.to_datetime(ordered["exit_timestamp_utc"], utc=True)
        ordered = ordered.sort_values(["exit_timestamp_utc", "decision_timestamp_utc", "cohort_offset"])
        for exit_ts in ordered["exit_timestamp_utc"].drop_duplicates().sort_values():
            cumulative = ordered[ordered["exit_timestamp_utc"] <= exit_ts]
            neg = cumulative[cumulative["decision_regime"].str.startswith("NEGATIVE_")]
            pos = cumulative[cumulative["decision_regime"].str.startswith("POSITIVE_")]
            payload["history"].append({
                "as_of_exit_timestamp_utc": pd.Timestamp(exit_ts).isoformat(),
                "matched_periods": int(len(cumulative)),
                "negative_regime_periods": int(len(neg)),
                "positive_regime_periods": int(len(pos)),
                "overall_mean_delta_net_relative_return_vs_v8": _json_number(cumulative["delta_net_relative_return_vs_v8"].mean()),
                "negative_spy_mean_delta_net_relative_return_vs_v8": _json_number(neg["delta_net_relative_return_vs_v8"].mean()) if len(neg) else None,
                "positive_spy_mean_delta_net_relative_return_vs_v8": _json_number(pos["delta_net_relative_return_vs_v8"].mean()) if len(pos) else None,
            })

    HISTORY_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    contract = dict(CONTRACT)
    contract["contract_sha256"] = _sha(CONTRACT)
    CONTRACT_PATH.write_text(json.dumps(contract, indent=2) + "\n")

    periods = _build_periods().copy()
    periods["decision_timestamp_utc"] = pd.to_datetime(periods["decision_timestamp_utc"], utc=True)
    periods["exit_timestamp_utc"] = pd.to_datetime(periods["exit_timestamp_utc"], utc=True)
    periods = periods[
        (periods["decision_timestamp_utc"] >= CONFIRMATION_START_UTC)
        & (periods["exit_timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
        & (periods["candidate_id"].isin([BASELINE, PRIMARY]))
    ].copy()

    if periods.empty:
        _write_history(None, contract["contract_sha256"])
        status = {
            "status": "WAITING_FOR_CONFIRMATION_EVIDENCE",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "contract_sha256": contract["contract_sha256"],
            "confirmation_start_utc": CONFIRMATION_START_UTC.isoformat(),
            "formal_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
            "completed_candidate_periods": 0,
            "completed_baseline_periods": 0,
            "decision": "PENDING",
            "formal_holdout_scored": False,
            "production_modified": False,
            "brokerage_orders": False,
        }
        STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n")
        print("V10 PROSPECTIVE CONFIRMATION")
        print("=" * 88)
        print("Status: WAITING_FOR_CONFIRMATION_EVIDENCE")
        print(f"Starts: {CONFIRMATION_START_UTC.isoformat()}")
        print(f"Formal holdout remains untouched from: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
        print("No confirmation periods have completed yet. No orders. No production changes.")
        return

    periods["decision_regime"] = _decision_regime(periods)
    keys = ["decision_timestamp_utc", "cohort_offset"]
    base = periods[periods.candidate_id == BASELINE].set_index(keys)
    cand = periods[periods.candidate_id == PRIMARY].set_index(keys)
    common = base.index.intersection(cand.index)
    if len(common) == 0:
        raise RuntimeError("No matched V8/V10 confirmation periods")

    rows = []
    for idx in common:
        b = base.loc[idx]
        c = cand.loc[idx]
        rows.append({
            "decision_timestamp_utc": idx[0],
            "cohort_offset": int(idx[1]),
            "exit_timestamp_utc": c["exit_timestamp_utc"],
            "decision_regime": c["decision_regime"],
            "v10_net_relative_return": float(c["net_relative_return"]),
            "v8_net_relative_return": float(b["net_relative_return"]),
            "delta_net_relative_return_vs_v8": float(c["net_relative_return"] - b["net_relative_return"]),
        })
    results = pd.DataFrame(rows).sort_values(keys)
    results.to_csv(RESULTS_PATH, index=False)
    _write_history(results, contract["contract_sha256"])

    neg = results[results.decision_regime.str.startswith("NEGATIVE_")]
    pos = results[results.decision_regime.str.startswith("POSITIVE_")]
    overall_delta = float(results.delta_net_relative_return_vs_v8.mean())
    neg_delta = float(neg.delta_net_relative_return_vs_v8.mean()) if len(neg) else np.nan
    pos_delta = float(pos.delta_net_relative_return_vs_v8.mean()) if len(pos) else np.nan

    criterion_overall = bool(overall_delta > 0)
    criterion_negative = bool(len(neg) > 0 and neg_delta > 0)
    criterion_positive = bool(len(pos) > 0 and pos_delta >= -POSITIVE_REGIME_NONINFERIORITY_TOLERANCE)
    criteria_observable = len(neg) > 0 and len(pos) > 0
    passed = criterion_overall and criterion_negative and criterion_positive and criteria_observable

    latest_exit = results.exit_timestamp_utc.max()
    final_window_reached = bool(latest_exit >= pd.Timestamp("2026-10-30T00:00:00Z"))
    decision = "PASS" if passed and final_window_reached else ("FAIL" if final_window_reached else "PENDING")

    status = {
        "status": "COMPLETE" if final_window_reached else "ACCUMULATING_CONFIRMATION_EVIDENCE",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract["contract_sha256"],
        "confirmation_start_utc": CONFIRMATION_START_UTC.isoformat(),
        "formal_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "matched_periods": int(len(results)),
        "negative_regime_periods": int(len(neg)),
        "positive_regime_periods": int(len(pos)),
        "overall_mean_delta_net_relative_return_vs_v8": overall_delta,
        "negative_spy_mean_delta_net_relative_return_vs_v8": neg_delta,
        "positive_spy_mean_delta_net_relative_return_vs_v8": pos_delta,
        "criteria": {
            "overall_positive": criterion_overall,
            "negative_spy_positive": criterion_negative,
            "positive_spy_noninferior": criterion_positive,
        },
        "decision": decision,
        "candidate_frozen_for_confirmation": True,
        "formal_holdout_scored": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n")

    print("V10 PROSPECTIVE CONFIRMATION")
    print("=" * 88)
    print(f"Status: {status['status']} | decision: {decision}")
    print(f"Matched periods: {len(results)} | negative={len(neg)} positive={len(pos)}")
    print(f"Overall delta vs V8: {overall_delta:+.6f}")
    print(f"Negative-SPY delta vs V8: {neg_delta:+.6f}" if np.isfinite(neg_delta) else "Negative-SPY delta vs V8: awaiting evidence")
    print(f"Positive-SPY delta vs V8: {pos_delta:+.6f}" if np.isfinite(pos_delta) else "Positive-SPY delta vs V8: awaiting evidence")
    print("V10 confirmation rule locked. Formal holdout untouched. No orders. No production changes.")


if __name__ == "__main__":
    main()
