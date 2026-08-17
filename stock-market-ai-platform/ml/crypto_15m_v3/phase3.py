"""Crypto 15m V3 Phase 3: turnover-aware policy simulation.

Research only. Uses Phase 2 OOS predictions. A raw prediction change never
switches state by itself. Candidate policies must clear modeled switching cost,
confirmation, hysteresis, and minimum-hold requirements.

Decision state is updated every 15 minutes, but economic returns are realized
only on a non-overlapping one-hour grid. This prevents four-way compounding of
overlapping one-hour forward returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

PHASE1_DATASET = Path("data/model/crypto_15m_v3/phase1/market_allocation_15m_1h.parquet")
PHASE2_PREDICTIONS = Path("data/model/crypto_15m_v3/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/crypto_15m_v3/phase3")
POLICY_SUMMARY = OUTPUT_ROOT / "policy_summary.csv"
DECISION_METRICS = OUTPUT_ROOT / "decision_metrics.csv"
MANIFEST = OUTPUT_ROOT / "manifest.json"
MODEL_ID = "hist_gradient_boosting"
COST_BPS = (0, 5, 10, 25)


@dataclass(frozen=True)
class Policy:
    policy_id: str
    confirmation: int
    min_hold_bars: int
    prob_margin: float
    safety_buffer_bps: float


POLICIES = (
    Policy("hold_confirm2_1h", 2, 4, 0.02, 2.5),
    Policy("hold_confirm3_2h", 3, 8, 0.03, 5.0),
    Policy("hold_confirm4_4h", 4, 16, 0.04, 7.5),
)


def _load() -> pd.DataFrame:
    data = pd.read_parquet(PHASE1_DATASET)
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    pred = pd.read_parquet(PHASE2_PREDICTIONS)
    pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True)
    pred = pred[pred["model_id"] == MODEL_ID].copy()
    needed = ["timestamp_utc", "predicted_label", "prob_btc", "prob_alt", "prob_cash", "fold_id"]
    pred = pred[needed]
    frame = pred.merge(
        data[["timestamp_utc", "btc_forward_return_1h", "alt_forward_return_1h", "cash_forward_return_1h"]],
        on="timestamp_utc",
        how="inner",
        validate="many_to_one",
    ).sort_values("timestamp_utc").reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("No Phase 2 HGB OOS predictions available")
    return frame


def _prob(row, state: str) -> float:
    return float(getattr(row, f"prob_{state.lower()}"))


def _ret(row, state: str) -> float:
    return float(getattr(row, f"{state.lower()}_forward_return_1h"))


def _is_realization_bar(ts: pd.Timestamp) -> bool:
    return ts.minute == 0 and ts.second == 0


def simulate(frame: pd.DataFrame, policy: Policy, cost_bps: float) -> tuple[dict, pd.DataFrame]:
    state = "BTC"
    state_age = policy.min_hold_bars
    pending = None
    pending_count = 0
    equity = 1.0
    rows = []
    switches = 0
    raw_changes = 0
    blocked_hold = 0
    blocked_cost = 0
    blocked_confirm = 0
    last_raw = None
    pending_switch_cost = 0.0
    hurdle = (cost_bps + policy.safety_buffer_bps) / 10000.0

    for row in frame.itertuples(index=False):
        raw = row.predicted_label
        if last_raw is not None and raw != last_raw:
            raw_changes += 1
        last_raw = raw
        executed = state
        switched = False
        reason = "HOLD_CURRENT_STATE"

        if raw == state:
            pending = None
            pending_count = 0
        else:
            advantage = _prob(row, raw) - _prob(row, state)
            if state_age < policy.min_hold_bars:
                blocked_hold += 1
                pending = None
                pending_count = 0
                reason = "BLOCKED_MIN_HOLD"
            elif advantage < policy.prob_margin:
                blocked_cost += 1
                pending = None
                pending_count = 0
                reason = "BLOCKED_HYSTERESIS"
            else:
                if pending == raw:
                    pending_count += 1
                else:
                    pending = raw
                    pending_count = 1
                if pending_count < policy.confirmation:
                    blocked_confirm += 1
                    reason = "AWAIT_CONFIRMATION"
                elif advantage <= hurdle:
                    blocked_cost += 1
                    reason = "BLOCKED_COST_HURDLE"
                else:
                    state = raw
                    executed = state
                    switched = True
                    switches += 1
                    state_age = 0
                    pending = None
                    pending_count = 0
                    pending_switch_cost += cost_bps / 10000.0
                    reason = "SWITCH_ALLOWED"

        realized = _is_realization_bar(row.timestamp_utc)
        gross = _ret(row, executed) if realized else 0.0
        cost = pending_switch_cost if realized else 0.0
        net = gross - cost if realized else 0.0
        if realized:
            equity *= 1.0 + net
            pending_switch_cost = 0.0

        rows.append({
            "timestamp_utc": row.timestamp_utc,
            "fold_id": row.fold_id,
            "policy_id": policy.policy_id,
            "cost_bps": cost_bps,
            "raw_predicted_label": raw,
            "executed_state": executed,
            "switch": switched,
            "reason": reason,
            "realization_bar": realized,
            "gross_return_1h": gross,
            "switch_cost_realized": cost,
            "net_return_1h": net,
            "equity": equity,
        })
        state_age += 1

    detail = pd.DataFrame(rows)
    realized_detail = detail[detail["realization_bar"]].copy()
    peak = realized_detail["equity"].cummax()
    dd = realized_detail["equity"] / peak - 1.0
    summary = {
        "policy_id": policy.policy_id,
        "cost_bps": cost_bps,
        "decision_count": len(detail),
        "realized_hour_count": len(realized_detail),
        "raw_prediction_changes": raw_changes,
        "executed_switches": switches,
        "switch_reduction_fraction": 1.0 - (switches / raw_changes if raw_changes else 0.0),
        "blocked_min_hold": blocked_hold,
        "blocked_hysteresis_or_cost": blocked_cost,
        "blocked_confirmation": blocked_confirm,
        "ending_equity": float(equity),
        "max_drawdown": float(dd.min()) if not dd.empty else 0.0,
        "mean_net_return_1h": float(realized_detail["net_return_1h"].mean()) if not realized_detail.empty else 0.0,
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
    summary_df.to_csv(POLICY_SUMMARY, index=False)
    detail_df.to_csv(DECISION_METRICS, index=False)
    MANIFEST.write_text(json.dumps({
        "research_version": "crypto_15m_v3",
        "phase": 3,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "decision_cadence_minutes": 15,
        "economic_horizon": "1h",
        "economic_realization_grid": "non-overlapping hourly rows at minute 00; decisions continue every 15 minutes",
        "research_status": "EXPLORATORY TURNOVER-AWARE POLICY DEVELOPMENT",
        "default_action": "HOLD_CURRENT_STATE",
        "policies": [p.__dict__ for p in POLICIES],
        "cost_scenarios_bps": list(COST_BPS),
        "important_limitation": "Probability differences are switching-edge proxies; no real brokerage execution or live slippage model is used.",
        "frozen_benchmark": "Crypto 15m V2 remains unchanged.",
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
    }, indent=2) + "\n")
    print("CRYPTO 15M V3 PHASE 3")
    print("=" * 100)
    print(summary_df.to_string(index=False))
    print("No real orders. Frozen V2 unchanged. Future holdout untouched.")


if __name__ == "__main__":
    main()
