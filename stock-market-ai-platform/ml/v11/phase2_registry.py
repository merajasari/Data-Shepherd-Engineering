"""V11 Phase 2 preregistration: overnight-gap and liquidity-impact signals.

Phase 1 produced a valid negative result (zero of six signals survived its
predeclared discovery threshold). This contract defines a genuinely different
OHLCV signal family before any Phase-2 values are computed or inspected.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from ml.v11.discovery_registry import (
    CONTROLS as PHASE0_CONTROLS,
    FUTURE_HOLDOUT_START_UTC,
    SIGNALS as PHASE1_SIGNALS,
)

RESEARCH_VERSION = "stock_v11"
PHASE = 2
FAMILY_ID = "overnight_gap_and_liquidity_impact_v1"
TARGET = "five_session_forward_stock_return_minus_spy_return"
OUTPUT_ROOT = Path("data/model/v11/phase2")
REGISTRY_PATH = OUTPUT_ROOT / "signal_registry.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

PHASE0_CONTRACT_SHA256 = (
    "d9e8892da859ff3c78f252f56e3b8a61f0828f3f317e75f2ac620ab87325e093"
)
PHASE1_STATUS = "NO_SIGNAL_PASSED_DISCOVERY_THRESHOLD_CLOSED"

PRIOR_SIGNAL_IDS = tuple(signal["signal_id"] for signal in PHASE1_SIGNALS)
ORTHOGONALIZATION_CONTROLS = tuple(PHASE0_CONTROLS) + PRIOR_SIGNAL_IDS

SIGNALS = (
    {
        "signal_id": "overnight_gap_reversal_1",
        "formula": "-1 * (open_t / close_t_minus_1 - 1)",
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "Large stock-specific overnight gaps partially reverse after the "
            "market opens and contain information distinct from close-to-close momentum."
        ),
        "minimum_history_sessions": 2,
    },
    {
        "signal_id": "overnight_gap_continuation_5",
        "formula": "mean(open_t / close_t_minus_1 - 1, 5 sessions)",
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "Persistent overnight repricing reflects information arriving outside "
            "regular hours and can continue over the next five sessions."
        ),
        "minimum_history_sessions": 6,
    },
    {
        "signal_id": "intraday_pressure_5",
        "formula": "mean(close_t / open_t - 1, 5 sessions)",
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "Repeated open-to-close buying pressure provides a distinct demand "
            "measure after controlling for close-to-close returns and range location."
        ),
        "minimum_history_sessions": 5,
    },
    {
        "signal_id": "abnormal_dollar_volume_5_60",
        "formula": "log(mean(close*volume, 5) / mean(close*volume, 60))",
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "A sustained abnormal dollar-volume shock identifies attention and "
            "information arrival not explained by the existing volume-trend control."
        ),
        "minimum_history_sessions": 60,
    },
    {
        "signal_id": "amihud_liquidity_improvement_5_20",
        "formula": (
            "-1 * (mean(abs(return_1d)/(close*volume), 5) / "
            "mean(abs(return_1d)/(close*volume), 20) - 1)"
        ),
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "A recent reduction in price impact relative to its own baseline "
            "identifies improving tradability and institutional participation."
        ),
        "minimum_history_sessions": 21,
    },
    {
        "signal_id": "signed_dollar_volume_pressure_20",
        "formula": (
            "sum(sign(close/open-1)*(close*volume), 20) / "
            "sum(close*volume, 20)"
        ),
        "direction_hypothesis": "higher_is_better",
        "hypothesis": (
            "Directionally signed dollar volume approximates persistent order-flow "
            "pressure that is not equivalent to volume-return correlation."
        ),
        "minimum_history_sessions": 20,
    },
)

DISCOVERY_RULES = {
    "decision_information": "completed_session_only",
    "target": TARGET,
    "cross_sectional_residualization_controls": list(
        ORTHOGONALIZATION_CONTROLS
    ),
    "primary_metric": "daily_spearman_ic_to_5d_spy_relative_target",
    "hac_lag_sessions": 5,
    "minimum_cross_sectional_assets": 80,
    "minimum_mean_orthogonal_ic": 0.01,
    "minimum_positive_year_rate": 0.70,
    "year_stability_required": True,
    "regime_stability_required": True,
    "minimum_regime_mean_ic": 0.0,
    "multiple_testing_adjustment": "benjamini_hochberg_fdr_5pct",
    "family_selected_before_computation": True,
    "signal_selection_performed_in_phase2_registry": False,
    "portfolio_simulation_performed_in_phase2_registry": False,
}


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_registry() -> dict:
    signal_ids = [signal["signal_id"] for signal in SIGNALS]
    if len(signal_ids) != len(set(signal_ids)):
        raise RuntimeError("Duplicate V11 Phase-2 signal identifiers")
    overlap = sorted(set(signal_ids) & set(PRIOR_SIGNAL_IDS))
    if overlap:
        raise RuntimeError(f"Phase-2 signals overlap Phase-1 signals: {overlap}")
    if FUTURE_HOLDOUT_START_UTC != pd.Timestamp("2026-11-02T00:00:00Z"):
        raise RuntimeError("V11 future holdout boundary changed")

    contract = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "family_id": FAMILY_ID,
        "target": TARGET,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "signals": list(SIGNALS),
        "discovery_rules": DISCOVERY_RULES,
        "prerequisites": {
            "phase0_contract_sha256": PHASE0_CONTRACT_SHA256,
            "phase1_status": PHASE1_STATUS,
            "phase1_signal_count": len(PRIOR_SIGNAL_IDS),
            "phase1_signals_reused_as_candidates": False,
            "v8_production_champion_frozen": True,
            "v9_cycle1": "NOT_CONFIRMED_CLOSED",
            "v9_cycle2": "NO_ELIGIBLE_CANDIDATE_CLOSED",
        },
    }
    contract["contract_sha256"] = hashlib.sha256(
        _canonical(contract).encode("utf-8")
    ).hexdigest()
    return contract


def write_registry(
    registry: dict,
    registry_path: Path = REGISTRY_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> dict:
    expected = json.dumps(registry, indent=2, sort_keys=True) + "\n"
    if registry_path.exists() and registry_path.read_text() != expected:
        raise RuntimeError(
            "Existing V11 Phase-2 registry differs from frozen contract"
        )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_suffix(registry_path.suffix + ".tmp")
    temporary.write_text(expected)
    temporary.replace(registry_path)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "overnight_gap_liquidity_signal_preregistration",
        "family_id": FAMILY_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "signal_count": len(SIGNALS),
        "control_count": len(ORTHOGONALIZATION_CONTROLS),
        "contract_sha256": registry["contract_sha256"],
        "phase1_status": PHASE1_STATUS,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "signal_computed": False,
        "signal_selected": False,
        "model_fitted": False,
        "portfolio_simulated": False,
        "candidate_frozen": False,
        "candidate_promoted": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "v9_results_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_temp.replace(manifest_path)
    return manifest


def main():
    registry = build_registry()
    manifest = write_registry(registry)
    print("STOCK V11 PHASE 2: GAP AND LIQUIDITY SIGNAL PREREGISTRATION")
    print("=" * 104)
    print(f"Signals registered: {manifest['signal_count']}")
    print(f"Orthogonalization controls: {manifest['control_count']}")
    print(f"Contract SHA: {manifest['contract_sha256']}")
    print(f"Untouched V11 holdout begins: {manifest['future_holdout_start_utc']}")
    for signal in registry["signals"]:
        print(f"- {signal['signal_id']}")
    print(
        "No signal computation, selection, fitting, portfolio simulation, "
        "holdout scoring, production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
