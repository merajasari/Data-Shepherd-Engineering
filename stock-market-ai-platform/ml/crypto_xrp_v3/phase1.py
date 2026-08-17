"""XRP V3 Phase 1: pre-register BTC-default selective XRP overlay hypothesis.

Research only. This phase does not fit a model, tune thresholds, simulate a
portfolio, inspect the frozen future holdout, or place orders.

The hypothesis is intentionally narrower than XRP V2:
- Decision cadence: 15 minutes.
- Forecast horizon: 1 hour BTC-relative XRP return.
- Default holding: BTC.
- Candidate action: remain in BTC or selectively overlay into XRP.
- No CASH state in the primary hypothesis.
- A switch to XRP must clear an explicit expected edge after cost and safety
  buffer, plus confirmation and minimum-hold requirements.
- A raw prediction change never directly triggers a switch.

XRP V2 diagnostics are treated as development evidence only. Their descriptive
regime/score buckets are not reused as thresholds here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

OUTPUT_ROOT = Path("data/model/crypto_xrp_v3/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    manifest = {
        "research_version": "crypto_xrp_v3",
        "phase": 1,
        "stage": "pre_registered_hypothesis",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "BTC-default selective XRP overlay using a fresh 15m/1h BTC-relative research track",
        "decision_cadence_minutes": 15,
        "economic_horizon": "1h BTC-relative",
        "state_space": ["BTC", "XRP"],
        "default_state": "BTC",
        "default_action": "HOLD_CURRENT_STATE",
        "switch_rule_contract": {
            "raw_prediction_change_can_switch": False,
            "must_clear_expected_net_edge": True,
            "must_include_transaction_cost": True,
            "must_include_slippage_allowance": True,
            "must_include_safety_buffer": True,
            "confirmation_required": True,
            "minimum_hold_required": True,
            "hysteresis_required": True,
        },
        "pre_registered_cost_scenarios_bps": [0, 5, 10, 25],
        "primary_research_goal": "Test whether selective XRP exposure can beat always-BTC after costs while improving drawdown and fold stability relative to XRP V2.",
        "promotion_gates_for_later_review": {
            "aggregate_equity_must_exceed_always_btc_at_5bps": True,
            "positive_fold_fraction_minimum": 0.75,
            "max_drawdown_must_be_better_than_xrp_v2_5bps": True,
            "cost_path_must_be_explainable": True,
        },
        "xrp_v2_development_evidence": {
            "reference_policy": "xrp_hold_c2_1h at 5bps",
            "ending_equity": 1.3912392604167068,
            "aligned_always_btc_equity": 1.04787142672405,
            "max_drawdown": -0.6429794398545121,
            "fold_fraction_strategy_beats_btc": 0.375,
            "interpretation": "Development evidence only; no V2 threshold or descriptive bucket is promoted into V3.",
        },
        "data_policy": {
            "no_synthetic_missing_candles": True,
            "no_future_leakage": True,
            "chronological_walk_forward": True,
            "horizon_aware_purge": "1h",
            "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
            "future_holdout_must_remain_uninspected": True,
        },
        "frozen_xrp_v1_modified": False,
        "xrp_v2_modified": False,
        "brokerage_orders": False,
        "next_step": "Build a fresh V3 modeling/evaluation phase using the existing leakage-safe XRP feature panel but independent policy design. Do not copy V2 thresholds or score buckets.",
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("CRYPTO XRP V3 PHASE 1")
    print("=" * 90)
    print("STATUS: PRE_REGISTERED_BTC_DEFAULT_XRP_OVERLAY")
    print("No fitting, threshold tuning, simulation, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
