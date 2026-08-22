"""Predeclared contract for Stock V11 independent-signal discovery.

V11 begins only after both V9 automatic-tuning cycles failed their safety
gates. It explores new OHLCV information rather than retuning rejected V9
candidates. This phase defines hypotheses only and performs no scoring.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

RESEARCH_VERSION = "stock_v11"
PHASE = 0
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-11-02T00:00:00Z")
TARGET = "five_session_forward_stock_return_minus_spy_return"
OUTPUT_ROOT = Path("data/model/v11/phase0")
REGISTRY_PATH = OUTPUT_ROOT / "signal_registry.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

CONTROLS = (
    "distance_from_low_20d",
    "volatility_20d",
    "beta_60",
    "downside_vol_ratio_20",
    "volume_trend_5_20",
)

SIGNALS = (
    {
        "signal_id": "idiosyncratic_momentum_20",
        "formula": (
            "stock_return_20d - beta_60 * spy_return_20d"
        ),
        "hypothesis": (
            "Twenty-session performance unexplained by contemporaneous market "
            "beta contains stock-specific continuation information."
        ),
        "minimum_history_sessions": 60,
    },
    {
        "signal_id": "idiosyncratic_reversal_5",
        "formula": (
            "-1 * (stock_return_5d - beta_60 * spy_return_5d)"
        ),
        "hypothesis": (
            "Extreme five-session market-adjusted moves partially mean-revert "
            "after controlling for the established V8/V9 exposures."
        ),
        "minimum_history_sessions": 60,
    },
    {
        "signal_id": "range_compression_5_20",
        "formula": (
            "mean_true_range_5d / mean_true_range_20d - 1"
        ),
        "hypothesis": (
            "Recent range compression can identify stocks approaching a "
            "tradable volatility expansion."
        ),
        "minimum_history_sessions": 21,
    },
    {
        "signal_id": "close_location_value_20",
        "formula": (
            "mean((2*close-low-high)/(high-low), 20 sessions)"
        ),
        "hypothesis": (
            "Persistent closes near the upper or lower daily range contain "
            "accumulation/distribution information not captured by momentum."
        ),
        "minimum_history_sessions": 20,
    },
    {
        "signal_id": "volume_return_correlation_20",
        "formula": (
            "rolling_correlation(return_1d, log_volume_change_1d, 20 sessions)"
        ),
        "hypothesis": (
            "Price moves confirmed or contradicted by volume changes contain "
            "incremental cross-sectional ranking information."
        ),
        "minimum_history_sessions": 21,
    },
    {
        "signal_id": "downside_beta_asymmetry_60",
        "formula": (
            "beta_to_spy_on_spy_down_sessions_60d - "
            "beta_to_spy_on_spy_up_sessions_60d"
        ),
        "hypothesis": (
            "Asymmetric downside market sensitivity identifies stocks with "
            "distinct defensive or crash-sensitive behavior."
        ),
        "minimum_history_sessions": 60,
    },
)

DISCOVERY_RULES = {
    "decision_information": "completed_session_only",
    "cross_sectional_residualization_controls": list(CONTROLS),
    "primary_metric": "daily_spearman_ic_to_5d_spy_relative_target",
    "hac_lag_sessions": 5,
    "minimum_cross_sectional_assets": 80,
    "year_stability_required": True,
    "regime_stability_required": True,
    "multiple_testing_adjustment": "benjamini_hochberg_fdr_10pct",
    "selection_performed_in_phase0": False,
    "portfolio_simulation_performed_in_phase0": False,
}


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_registry() -> dict:
    signal_ids = [signal["signal_id"] for signal in SIGNALS]
    if len(signal_ids) != len(set(signal_ids)):
        raise RuntimeError("Duplicate V11 signal identifiers")
    contract = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "target": TARGET,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "signals": list(SIGNALS),
        "discovery_rules": DISCOVERY_RULES,
        "prior_research_status": {
            "v8_production_champion": True,
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
        raise RuntimeError("Existing V11 discovery registry differs from contract")

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_suffix(registry_path.suffix + ".tmp")
    temporary.write_text(expected)
    temporary.replace(registry_path)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "independent_signal_hypothesis_preregistration",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "signal_count": len(SIGNALS),
        "contract_sha256": registry["contract_sha256"],
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
    print("STOCK V11 PHASE 0: INDEPENDENT SIGNAL PREREGISTRATION")
    print("=" * 104)
    print(f"Signals registered: {manifest['signal_count']}")
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
