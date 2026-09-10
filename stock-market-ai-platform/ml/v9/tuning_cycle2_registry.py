"""V9 automatic-tuning Cycle 2: predeclared risk-controlled search space.

Cycle 1 is closed with NOT_CONFIRMED. Cycle 2 does not modify its results or
relax its gates. This registry explores broader diversification and simple
decision-time SPY trend overlays using development data only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path

from ml.v9.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

CYCLE_ID = "V9_RISK_CONTROLLED_CYCLE_2"
OUTPUT_ROOT = Path("data/model/v9/tuning_cycle2")
REGISTRY_PATH = OUTPUT_ROOT / "candidate_registry.jsonl"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SCORE_IDS = (
    "downside_vol_ratio_20",
    "volume_trend_5_20",
    "equal_weight_rank_blend",
)
TOP_N_VALUES = (10, 15, 20)
HOLD_SESSION_VALUES = (10, 20)
RISK_OVERLAYS = (
    "NONE",
    "SPY_SMA200_HALF_EXPOSURE",
    "SPY_SMA200_CASH",
)
PRIMARY_COST_BPS = 10
COST_STRESS_BPS = 30
OBJECTIVE_ID = "risk_controlled_relative_return_v2"

MANDATORY_CONFIRMATION_GATES = {
    "all_walk_forward_folds_relative_positive": True,
    "minimum_worst_fold_sharpe": 0.0,
    "minimum_primary_max_drawdown": -0.25,
    "minimum_spy_down_regime_max_drawdown": -0.35,
    "minimum_30bps_mean_relative_return": 0.0,
    "minimum_positive_year_rate": 0.70,
    "minimum_worst_year_relative_return": -0.05,
}


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _candidate_id(config: dict) -> str:
    digest = hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()
    return f"V9C2_{digest[:16].upper()}"


def build_candidate_registry() -> list[dict]:
    rows = []
    for score_id, top_n, hold, overlay in product(
        SCORE_IDS,
        TOP_N_VALUES,
        HOLD_SESSION_VALUES,
        RISK_OVERLAYS,
    ):
        config = {
            "cycle_id": CYCLE_ID,
            "research_version": RESEARCH_VERSION,
            "score_id": score_id,
            "top_n": top_n,
            "holding_sessions": hold,
            "weighting": "equal_weight",
            "entry": "next_trading_session_open",
            "risk_overlay": overlay,
            "risk_overlay_signal": (
                None if overlay == "NONE" else "SPY close below trailing SMA200"
            ),
            "below_sma200_target_exposure": {
                "NONE": 1.0,
                "SPY_SMA200_HALF_EXPOSURE": 0.5,
                "SPY_SMA200_CASH": 0.0,
            }[overlay],
            "above_sma200_target_exposure": 1.0,
            "leverage_allowed": False,
            "shorting_allowed": False,
            "cash_return_assumption": 0.0,
            "cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
            "objective_id": OBJECTIVE_ID,
            "development_data_end_exclusive_utc": (
                FUTURE_HOLDOUT_START_UTC.isoformat()
            ),
        }
        rows.append(
            {
                "candidate_id": _candidate_id(config),
                "config": config,
                "status": "REGISTERED_UNEVALUATED",
            }
        )

    rows.sort(key=lambda row: row["candidate_id"])
    ids = [row["candidate_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Cycle-2 candidate hash collision detected")
    return rows


def _registry_text(rows: list[dict]) -> str:
    return "".join(_canonical_json(row) + "\n" for row in rows)


def write_registry(
    rows: list[dict],
    registry_path: Path = REGISTRY_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> dict:
    expected = _registry_text(rows)
    if registry_path.exists() and registry_path.read_text() != expected:
        raise RuntimeError(
            "Existing Cycle-2 registry differs from the predeclared search space"
        )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_temp = registry_path.with_suffix(registry_path.suffix + ".tmp")
    registry_temp.write_text(expected)
    registry_temp.replace(registry_path)

    registry_sha = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    manifest = {
        "cycle_id": CYCLE_ID,
        "research_version": RESEARCH_VERSION,
        "stage": "development_only_risk_controlled_candidate_registry",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "registry_sha256": registry_sha,
        "objective_id": OBJECTIVE_ID,
        "search_space": {
            "score_ids": list(SCORE_IDS),
            "top_n_values": list(TOP_N_VALUES),
            "holding_session_values": list(HOLD_SESSION_VALUES),
            "risk_overlays": list(RISK_OVERLAYS),
            "primary_cost_bps": PRIMARY_COST_BPS,
            "cost_stress_bps": COST_STRESS_BPS,
            "cost_tuned": False,
        },
        "mandatory_confirmation_gates": MANDATORY_CONFIRMATION_GATES,
        "cycle1_status": "NOT_CONFIRMED_CLOSED",
        "cycle1_runner_up_considered": False,
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "candidate_evaluated": False,
        "candidate_confirmed": False,
        "candidate_promoted": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_temp.replace(manifest_path)
    return manifest


def main():
    rows = build_candidate_registry()
    manifest = write_registry(rows)
    print("STOCK V9 AUTOMATIC TUNING CYCLE 2")
    print("=" * 96)
    print(f"Candidates registered: {manifest['candidate_count']}")
    print(f"Registry SHA: {manifest['registry_sha256']}")
    print(
        "Search: "
        f"{len(SCORE_IDS)} signals x {len(TOP_N_VALUES)} Top-N values x "
        f"{len(HOLD_SESSION_VALUES)} holding periods x "
        f"{len(RISK_OVERLAYS)} risk overlays"
    )
    print("Cycle 1 remains closed as NOT_CONFIRMED.")
    print(
        "Development registry only. No evaluation, holdout access, confirmation, "
        "promotion, production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
