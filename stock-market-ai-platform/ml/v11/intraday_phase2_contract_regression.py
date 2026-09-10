"""Regression checks for V11 Phase 2 preregistration."""
from __future__ import annotations

import copy

from ml.v11.intraday_phase2_contract import (
    EXPECTED_WEIGHTS,
    contract_sha256,
    load_contract,
    validate_contract,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    contract = load_contract()
    require(not validate_contract(contract), "Preregistered contract validates")
    require(contract["configuration"]["config_id"] == "MOMENTUM_BALANCED_6", "Balanced momentum hypothesis is locked")
    require(contract["configuration"]["holding_bars"] == 6, "Six-bar holding period is locked")
    require(contract["configuration"]["weights"] == EXPECTED_WEIGHTS, "Six feature weights are locked")
    require(contract["hypothesis_origin"]["post_hoc_origin_disclosed"] is True, "Post-hoc hypothesis origin is disclosed")
    require(contract["hypothesis_origin"]["development_observations_reused"] == 0, "Development observations are excluded")
    require(contract["fresh_confirmation_start_utc"] == "2026-09-01T14:00:00+00:00", "Fresh evidence boundary is locked")
    require(contract["activation_status"] == "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY", "Fresh paper confirmation is activated")
    require(contract["evidence_policy"]["minimum_preliminary_sessions"] == 20, "Preliminary evidence requires 20 fresh sessions")
    require(contract["evidence_policy"]["minimum_accumulating_sessions"] == 60, "Accumulating evidence requires 60 fresh sessions")
    require(contract["modeled_total_cost_bps_round_trip"] == 10, "Ten-bps round-trip cost is locked")
    require(contract["paper_trading_only"] is True, "Phase 2 remains paper only")
    require(contract["brokerage_orders"] is False, "Brokerage orders remain off")
    require(contract["v8_production_writes"] is False, "V8 production is isolated")
    require(contract["v10_production_writes"] is False, "V10 production is isolated")
    require(len(contract_sha256(contract)) == 64, "Contract has a SHA-256 identity")

    tampered = copy.deepcopy(contract)
    tampered["configuration"]["weights"]["return_5m"] = 2.0
    require("REGISTERED_WEIGHTS_CHANGED" in validate_contract(tampered), "Weight tampering fails closed")
    reused = copy.deepcopy(contract)
    reused["hypothesis_origin"]["development_observations_reused"] = 40
    require("DEVELOPMENT_EVIDENCE_REUSE_PROHIBITED" in validate_contract(reused), "Development-evidence reuse fails closed")
    activated = copy.deepcopy(contract)
    activated["activation_status"] = "LIVE_TRADING_ENABLED"
    require("ACTIVATION_MUST_BE_PAPER_CONFIRMATION_ONLY" in validate_contract(activated), "Non-paper activation fails closed")

    print("Status: PASSED")
    print("Phase 2 research specification: PREREGISTERED")
    print("Fresh confirmation activation: ENABLED PAPER ONLY")
    print("Model selection authority: NONE")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
