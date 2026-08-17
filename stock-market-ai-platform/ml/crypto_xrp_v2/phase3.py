"""Crypto XRP V2 Phase 3: turnover-aware XRP/BTC/CASH policy simulation.

Research only. Uses XRP V2 Phase 2 OOS Ridge scores. A new 15-minute score alone
never changes state. Candidate policies require hysteresis, confirmation,
minimum hold, and positive expected net edge after switching-cost assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1_DATASET = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
PHASE2_PREDICTIONS = Path("data/model/crypto_xrp_v2/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v2/phase3")
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
DETAIL_PATH = OUTPUT_ROOT / "decision_metrics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
MODEL_ID = "ridge"
COST_BPS = (0, 5, 10, 25)


@dataclass(frozen=True)
class Policy:
    policy_id: str
    entry_threshold: float
    exit_threshold: float
    confirmation: int
    min_hold_bars: int
    safety_buffer_bps: float


POLICIES = (
    Policy("xrp_hold_c2_1h", 0.00075, 0.00035, 2, 4, 2.5),
    Policy("xrp_hold_c3_2h", 0.00100, 0.00050, 3, 8, 5.0),
    Policy("xrp_hold_c4_4h", 0.00125, 0.00060, 4, 16, 7.5),
)


def _load() -> pd.DataFrame:
    data = pd.read_parquet(PHASE1_DATASET)
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    pred = pd.read_parquet(PHASE2_PREDICTIONS)
    pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True)
    pred = pred[pred["model_id"] == MODEL_ID].copy()
    frame = pred[["timestamp_utc", "predicted_score", "fold_id"]].merge(
        data[["timestamp_utc", "forward_return_1h", "btc_forward_return_1h"]],
        on="timestamp_utc", how="inner", validate="many_to_one"
    ).sort_values("timestamp_utc").reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("No XRP V2 Ridge OOS predictions available")
    return frame


def proposed_state(score: float, current: str, policy: Policy) -> str:
    if current == "XRP":
        if score <= -policy.entry_threshold:
            return "CASH"
        if score <= policy.exit_threshold:
            return "BTC"
        return "XRP"
    if current == "CASH":
        if score >= policy.entry_threshold:
            return "XRP"
        if score >= -policy.exit_threshold:
            return "BTC"
        return "CASH"
    if score >= policy.entry_threshold:
        return "XRP"
    if score <= -policy.entry_threshold:
        return "CASH"
    return "BTC"


def realized_return(row, state: str) -> float:
    if state == "XRP":
        return float(row.forward_return_1h)
    if state == "BTC":
        return float(row.btc_forward_return_1h)
    return 0.0


def expected_relative_edge(score: float, current: str, proposed: str) -> float:
    # Ridge predicts XRP minus BTC over the next hour. CASH uses a conservative
    # zero-return reference; only magnitude beyond the current-state reference
    # is treated as a switching-edge proxy.
    expected = {"XRP": score, "BTC": 0.0, "CASH": -max(score, 0.0)}
    return float(expected[proposed] - expected[current])


def simulate(frame: pd.DataFrame, policy: Policy, cost_bps: float) -> tuple[dict, pd.DataFrame]:
    state = "BTC"
    age = policy.min_hold_bars
    pending = None
    pending_count = 0
    switches = 0
    blocked_hold = 0
    blocked_confirm = 0
    blocked_cost = 0
    equity = 1.0
    rows = []
    hurdle = (cost_bps + policy.safety_buffer_bps) / 10000.0

    for row in frame.itertuples(index=False):
        score = float(row.predicted_score)
        proposed = proposed_state(score, state, policy)
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
                blocked_confirm += 1
                reason = "AWAIT_CONFIRMATION"
            else:
                edge = expected_relative_edge(score, state, proposed)
                if edge <= hurdle:
                    blocked_cost += 1
                    reason = "BLOCKED_COST_HURDLE"
                else:
                    state = proposed
                    executed = state
                    switched = True
                    switches += 1
                    age = 0
                    pending = None
                    pending_count = 0
                    reason = "SWITCH_ALLOWED"

        gross = realized_return(row, executed)
        cost = cost_bps / 10000.0 if switched else 0.0
        net = gross - cost
        equity *= 1.0 + net
        rows.append({
            "timestamp_utc": row.timestamp_utc,
            "fold_id": row.fold_id,
            "policy_id": policy.policy_id,
            "cost_bps": cost_bps,
            "score": score,
            "proposed_state": proposed,
            "executed_state": executed,
            "switch": switched,
            "reason": reason,
            "gross_return_1h": gross,
            "net_return_1h": net,
            "equity": equity,
        })
        age += 1

    detail = pd.DataFrame(rows)
    dd = detail["equity"] / detail["equity"].cummax() - 1.0
    summary = {
        "policy_id": policy.policy_id,
        "cost_bps": cost_bps,
        "observation_count": len(detail),
        "executed_switches": switches,
        "blocked_min_hold": blocked_hold,
        "blocked_confirmation": blocked_confirm,
        "blocked_cost_hurdle": blocked_cost,
        "ending_equity": float(equity),
        "max_drawdown": float(dd.min()),
        "mean_net_return_1h": float(detail["net_return_1h"].mean()),
        "xrp_fraction": float((detail["executed_state"] == "XRP").mean()),
        "btc_fraction": float((detail["executed_state"] == "BTC").mean()),
        "cash_fraction": float((detail["executed_state"] == "CASH").mean()),
    }
    return summary, detail


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
            print(f"[SUCCESS] {policy.policy_id} cost={cost}bps equity={summary['ending_equity']:.4f} switches={summary['executed_switches']}")
    summary_df = pd.DataFrame(summaries)
    detail_df = pd.concat(details, ignore_index=True)
    summary_df.to_csv(SUMMARY_PATH, index=False)
    detail_df.to_csv(DETAIL_PATH, index=False)
    MANIFEST_PATH.write_text(json.dumps({
        "research_version": "crypto_xrp_v2",
        "phase": 3,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "decision_cadence_minutes": 15,
        "economic_horizon": "1h BTC-relative",
        "research_status": "EXPLORATORY TURNOVER-AWARE POLICY DEVELOPMENT",
        "default_action": "HOLD_CURRENT_STATE",
        "policies": [p.__dict__ for p in POLICIES],
        "cost_scenarios_bps": list(COST_BPS),
        "important_limitation": "Expected net edge is a conservative score-based proxy; no brokerage execution or live slippage model is used.",
        "frozen_benchmark": "XRP V1 Phase 6 remains unchanged.",
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
    }, indent=2) + "\n")
    print("CRYPTO XRP V2 PHASE 3")
    print("=" * 100)
    print(summary_df.to_string(index=False))
    print("No real orders. Frozen XRP V1 unchanged. Future holdout untouched.")


if __name__ == "__main__":
    main()
