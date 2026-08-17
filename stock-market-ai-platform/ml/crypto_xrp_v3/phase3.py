"""Crypto XRP V3 Phase 3: BTC-default selective XRP overlay simulation.

Research only. Uses leakage-corrected XRP V3 Phase 2 OOS scores. BTC is the
pre-registered default state. XRP exposure is permitted only when a fresh score
clears a pre-registered edge hurdle after explicit switching cost, safety buffer,
confirmation, hysteresis, and minimum-hold requirements.

This phase does not fit models, inspect the future holdout, place brokerage
orders, or reuse XRP V2 thresholds/score buckets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1_DATASET = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
PHASE2_PREDICTIONS = Path("data/model/crypto_xrp_v3/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v3/phase3")
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
DETAIL_PATH = OUTPUT_ROOT / "decision_metrics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

MODEL_ID = "ridge"
COST_BPS = (0, 5, 10, 25)


@dataclass(frozen=True)
class Policy:
    policy_id: str
    entry_edge_bps: float
    exit_edge_bps: float
    confirmation: int
    min_hold_bars: int
    safety_buffer_bps: float


# Fresh V3 grid. These are deliberately few and are not copied from V2.
POLICIES = (
    Policy("btc_default_c2_1h", 7.5, 2.5, 2, 4, 2.5),
    Policy("btc_default_c3_2h", 10.0, 3.0, 3, 8, 5.0),
    Policy("btc_default_c4_4h", 12.5, 4.0, 4, 16, 7.5),
)


def _load() -> pd.DataFrame:
    data = pd.read_parquet(PHASE1_DATASET).copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)

    pred = pd.read_parquet(PHASE2_PREDICTIONS).copy()
    pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True)
    pred = pred[pred["model_id"].eq(MODEL_ID)].copy()

    frame = pred[["timestamp_utc", "predicted_score", "fold_id"]].merge(
        data[["timestamp_utc", "forward_return_1h", "btc_forward_return_1h"]],
        on="timestamp_utc",
        how="inner",
        validate="many_to_one",
    ).sort_values("timestamp_utc").reset_index(drop=True)

    if frame.empty:
        raise RuntimeError("No leakage-corrected XRP V3 Ridge OOS predictions available")
    return frame


def _is_realization_bar(ts: pd.Timestamp) -> bool:
    return ts.minute == 0 and ts.second == 0


def _state_return(row, state: str) -> float:
    if state == "XRP":
        return float(row.forward_return_1h)
    return float(row.btc_forward_return_1h)


def _proposed_state(score: float, state: str, policy: Policy) -> str:
    entry = policy.entry_edge_bps / 10000.0
    exit_edge = policy.exit_edge_bps / 10000.0
    if state == "BTC":
        return "XRP" if score >= entry else "BTC"
    return "BTC" if score <= exit_edge else "XRP"


def _edge_for_switch(score: float, state: str, proposed: str) -> float:
    # Ridge score is expected XRP minus BTC return over the next hour.
    if state == "BTC" and proposed == "XRP":
        return float(score)
    if state == "XRP" and proposed == "BTC":
        return float(-score)
    return 0.0


def simulate(frame: pd.DataFrame, policy: Policy, cost_bps: float) -> tuple[dict, pd.DataFrame]:
    state = "BTC"
    age = policy.min_hold_bars
    pending = None
    pending_count = 0
    switches = 0
    blocked_hold = 0
    blocked_confirmation = 0
    blocked_cost = 0
    equity = 1.0
    pending_switch_cost = 0.0
    rows = []

    hurdle = (cost_bps + policy.safety_buffer_bps) / 10000.0

    for row in frame.itertuples(index=False):
        score = float(row.predicted_score)
        proposed = _proposed_state(score, state, policy)
        executed = state
        switched = False
        reason = "HOLD_CURRENT_STATE"

        if proposed == state:
            pending = None
            pending_count = 0
        elif age < policy.min_hold_bars:
            blocked_hold += 1
            pending = None
            pending_count = 0
            reason = "BLOCKED_MIN_HOLD"
        else:
            if pending == proposed:
                pending_count += 1
            else:
                pending = proposed
                pending_count = 1

            if pending_count < policy.confirmation:
                blocked_confirmation += 1
                reason = "AWAIT_CONFIRMATION"
            else:
                edge = _edge_for_switch(score, state, proposed)
                if edge <= hurdle:
                    blocked_cost += 1
                    reason = "BLOCKED_NET_EDGE_HURDLE"
                else:
                    state = proposed
                    executed = state
                    switched = True
                    switches += 1
                    age = 0
                    pending = None
                    pending_count = 0
                    pending_switch_cost += cost_bps / 10000.0
                    reason = "SWITCH_ALLOWED"

        realized = _is_realization_bar(row.timestamp_utc)
        gross = _state_return(row, executed) if realized else 0.0
        switch_cost = pending_switch_cost if realized else 0.0
        net = gross - switch_cost if realized else 0.0

        if realized:
            equity *= 1.0 + net
            pending_switch_cost = 0.0

        rows.append({
            "timestamp_utc": row.timestamp_utc,
            "fold_id": row.fold_id,
            "policy_id": policy.policy_id,
            "cost_bps": float(cost_bps),
            "predicted_score": score,
            "proposed_state": proposed,
            "executed_state": executed,
            "switch": switched,
            "reason": reason,
            "realization_bar": realized,
            "gross_return_1h": gross,
            "switch_cost_realized": switch_cost,
            "net_return_1h": net,
            "equity": equity,
        })
        age += 1

    detail = pd.DataFrame(rows)
    econ = detail[detail["realization_bar"].astype(bool)].copy()
    if econ.empty:
        raise RuntimeError("No hourly realization rows produced")

    peak = econ["equity"].cummax()
    dd = econ["equity"] / peak - 1.0
    raw_xrp_proposals = int((detail["proposed_state"] == "XRP").sum())

    summary = {
        "policy_id": policy.policy_id,
        "cost_bps": float(cost_bps),
        "decision_count": int(len(detail)),
        "realized_hour_count": int(len(econ)),
        "executed_switches": int(switches),
        "raw_xrp_proposal_count": raw_xrp_proposals,
        "blocked_min_hold": int(blocked_hold),
        "blocked_confirmation": int(blocked_confirmation),
        "blocked_cost_hurdle": int(blocked_cost),
        "ending_equity": float(equity),
        "max_drawdown": float(dd.min()),
        "mean_net_return_1h": float(econ["net_return_1h"].mean()),
        "xrp_fraction": float((detail["executed_state"] == "XRP").mean()),
        "btc_fraction": float((detail["executed_state"] == "BTC").mean()),
    }
    return summary, detail


def _aligned_btc_benchmark(frame: pd.DataFrame) -> dict:
    h = frame[frame["timestamp_utc"].map(_is_realization_bar)].copy()
    r = pd.to_numeric(h["btc_forward_return_1h"], errors="coerce").fillna(0.0).to_numpy(float)
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return {
        "realized_hour_count": int(len(h)),
        "ending_equity": float(eq[-1]),
        "max_drawdown": float(dd.min()),
        "mean_return_1h": float(np.mean(r)),
    }


def main():
    frame = _load()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    summaries = []
    details = []
    for policy in POLICIES:
        for cost in COST_BPS:
            summary, detail = simulate(frame, policy, cost)
            summaries.append(summary)
            details.append(detail)
            print(
                f"[SUCCESS] {policy.policy_id} cost={cost}bps "
                f"equity={summary['ending_equity']:.4f} "
                f"switches={summary['executed_switches']}"
            )

    summary_df = pd.DataFrame(summaries)
    detail_df = pd.concat(details, ignore_index=True)
    btc_benchmark = _aligned_btc_benchmark(frame)

    summary_df.to_csv(SUMMARY_PATH, index=False)
    detail_df.to_csv(DETAIL_PATH, index=False)

    MANIFEST_PATH.write_text(json.dumps({
        "research_version": "crypto_xrp_v3",
        "phase": 3,
        "stage": "btc_default_turnover_aware_overlay_simulation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "input_modeling_run": "XRP V3 Phase 2 leakage-corrected OOS predictions",
        "default_state": "BTC",
        "state_space": ["BTC", "XRP"],
        "decision_cadence_minutes": 15,
        "economic_realization_grid": "non-overlapping hourly rows at minute 00",
        "policies": [p.__dict__ for p in POLICIES],
        "cost_scenarios_bps": list(COST_BPS),
        "aligned_always_btc_benchmark": btc_benchmark,
        "v2_threshold_reuse": False,
        "raw_prediction_change_can_switch": False,
        "brokerage_orders": False,
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "future_holdout_inspected": False,
        "research_status": "EXPLORATORY_NO_FREEZE",
        "next_step": "Evaluate aggregate, fold, drawdown, and cost robustness against the pre-registered promotion gates. Do not tune this grid on the same OOS results.",
    }, indent=2) + "\n")

    print("CRYPTO XRP V3 PHASE 3")
    print("=" * 100)
    print(summary_df.to_string(index=False))
    print("\nALIGNED ALWAYS-BTC BENCHMARK")
    print(pd.DataFrame([btc_benchmark]).to_string(index=False))
    print("No fitting, threshold tuning, freeze, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
