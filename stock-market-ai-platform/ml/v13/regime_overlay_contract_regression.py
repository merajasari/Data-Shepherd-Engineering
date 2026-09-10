"""Fail-closed regression for the V13 fresh regime-overlay preregistration."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SHA256,
    EXPECTED_V11_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    EXPECTED_V12_EVALUATION_SHA256,
    contract_sha256,
    load_contract,
    run,
    validate_contract,
    validate_predecessor_disposition,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def predecessor_payload() -> dict[str, object]:
    return {
        "status": "V12_DEVELOPMENT_CLOSED_RETAIN_V10",
        "decision": "RETAIN_FROZEN_V10_CONTROL",
        "selected_candidate": "V10_CONTROL_5K",
        "evaluation_sha256": EXPECTED_V12_EVALUATION_SHA256,
        "disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "post_result_v12_tuning_allowed": False,
        "candidate_frozen": False,
        "fresh_paper_confirmation_activated": False,
        "brokerage_orders": False,
        "production_modified": False,
    }


def main() -> None:
    contract = load_contract()
    require(validate_contract(contract) == [], "V13 preregistered contract validates")
    require(
        contract_sha256(contract) == EXPECTED_CONTRACT_SHA256,
        "V13 contract identity is locked",
    )

    predecessor = contract["predecessor_lock"]
    require(
        predecessor["v12_evaluation_sha256"] == EXPECTED_V12_EVALUATION_SHA256,
        "V12 evaluation identity is locked",
    )
    require(
        predecessor["v12_disposition_sha256"] == EXPECTED_V12_DISPOSITION_SHA256,
        "V12 disposition identity is locked",
    )
    require(
        predecessor["v12_decision"] == "RETAIN_FROZEN_V10_CONTROL",
        "V12 retain-control decision is preserved",
    )
    require(
        contract["control"]["v10_candidate_id"] == EXPECTED_V10_CANDIDATE,
        "Frozen V10 candidate remains the control",
    )
    require(
        contract["control"]["v10_frozen_spec_sha256"] == EXPECTED_V10_SHA256,
        "Frozen V10 identity is locked",
    )
    require(
        contract["control"]["ranking_contract_immutable"] is True,
        "V10 ranking contract remains immutable",
    )

    challenger = contract["challenger"]
    require(challenger["candidate_count"] == 1, "Exactly one V13 challenger is fixed")
    require(
        challenger["ranking_source"] == "UNCHANGED_V10_CYCLE3_RANKS",
        "V13 cannot replace V10 rankings",
    )
    require(
        challenger["blanket_volatility_scaling"] is False,
        "Rejected blanket volatility scaling is prohibited",
    )
    require(challenger["leverage_allowed"] is False, "V13 cannot add leverage")

    v11 = contract["v11_input_boundary"]
    require(v11["contract_sha256"] == EXPECTED_V11_SHA256, "V11 input identity is locked")
    require(
        v11["role"] == "ENTRY_CONFIRMATION_ONLY_IN_LOCKED_REGIME",
        "V11 is limited to regime-bounded entry confirmation",
    )
    require(v11["ranking_weight"] == 0, "V11 has zero ranking authority")
    require(v11["fresh_outcomes_read"] is False, "V11 fresh outcomes are prohibited")

    regime = contract["regime_gate"]
    require(regime["all_conditions_required"] is True, "Both regime conditions are required")
    require(
        regime["condition_1"] == "V10_CONFIRMED_NEGATIVE_REGIME",
        "Frozen V10 negative-regime definition is reused",
    )
    require(
        regime["condition_2_threshold"] == 0.25,
        "Twenty-five-percent high-volatility threshold is locked",
    )
    require(
        regime["missing_or_stale_regime_input_action"] == "HOLD_CASH",
        "Missing regime data fails closed",
    )

    entry = contract["entry_confirmation_rule"]
    require(entry["applies_only_when_regime_gate_true"] is True, "Overlay is regime scoped")
    require(
        entry["outside_regime_action"] == "EXECUTE_UNCHANGED_V10_CONTROL",
        "Outside the locked regime V10 remains unchanged",
    )
    require(len(entry["confirm_symbol_if_all"]) == 3, "Three entry tests are locked")
    require(entry["minimum_confirmed_positions"] == 3, "Minimum diversification is locked")

    execution = contract["small_account_execution"]
    require(execution["starting_capital_usd"] == 5000, "$5,000 capital basis is locked")
    require(execution["integer_shares_only"] is True, "Integer shares are required")
    require(execution["fractional_shares"] is False, "Fractional shares are prohibited")
    require(execution["margin"] is False, "Margin is prohibited")
    require(execution["short_selling"] is False, "Short selling is prohibited")
    require(
        execution["minimum_cash_buffer_pct"] == 0.1,
        "Ten-percent cash buffer is locked",
    )
    require(
        execution["maximum_position_notional_pct"] == 0.2,
        "Position notional is capped at twenty percent",
    )

    evidence = contract["fresh_evidence"]
    require(
        evidence["boundary_utc"] == "2026-09-01T14:00:00+00:00",
        "Fresh evidence boundary is locked",
    )
    require(evidence["minimum_completed_sessions"] == 60, "Sixty fresh sessions are required")
    require(
        evidence["minimum_regime_eligible_sessions"] == 15,
        "Fifteen qualifying regime sessions are required",
    )
    require(
        evidence["development_or_preboundary_observations_allowed"] is False,
        "Development and pre-boundary evidence are prohibited",
    )
    require(evidence["v10_holdout_outcomes_allowed"] is False, "V10 holdout outcomes are prohibited")
    require(evidence["v11_fresh_outcomes_allowed"] is False, "V11 fresh outcomes are prohibited")
    require(
        evidence["activation_status"] == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "Fresh evidence activation remains disabled",
    )

    gates = contract["confirmation_gates"]
    require(gates["all_gates_required"] is True, "Every fresh confirmation gate is required")
    require(
        gates["net_annualized_return_delta_vs_control_at_least"] == 0.03,
        "Three-point annualized improvement gate is locked",
    )
    require(
        gates["maximum_drawdown_not_worse_than_control"] is True,
        "Drawdown cannot be worse than V10",
    )
    require(
        gates["failure_action"] == "RETAIN_FROZEN_V10_CONTROL",
        "Failure retains frozen V10",
    )

    authority = contract["authority"]
    require(authority["research_only"] is True, "V13 authority is research only")
    require(authority["paper_trading_only"] is True, "V13 remains paper only")
    require(authority["live_trading_enabled"] is False, "Live trading remains disabled")
    require(authority["brokerage_orders"] is False, "Brokerage orders remain off")
    require(authority["candidate_freeze_authorized"] is False, "Candidate freeze authority is absent")
    require(
        authority["fresh_evidence_activation_authorized"] is False,
        "Fresh evidence activation authority is absent",
    )

    tampered_regime = copy.deepcopy(contract)
    tampered_regime["regime_gate"]["condition_2_threshold"] = 0.2
    require(
        "VOLATILITY_THRESHOLD_CHANGED" in validate_contract(tampered_regime),
        "Regime-threshold tampering fails closed",
    )
    promoted_v11 = copy.deepcopy(contract)
    promoted_v11["challenger"]["ranking_weight_from_v11"] = 0.2
    require(
        "V11_RANKING_WEIGHT_MUST_BE_ZERO" in validate_contract(promoted_v11),
        "V11 ranking promotion fails closed",
    )
    blanket_scaler = copy.deepcopy(contract)
    blanket_scaler["challenger"]["blanket_volatility_scaling"] = True
    require(
        "BLANKET_VOLATILITY_SCALING_PROHIBITED" in validate_contract(blanket_scaler),
        "Blanket volatility scaling fails closed",
    )
    activated = copy.deepcopy(contract)
    activated["fresh_evidence"]["activation_status"] = "ENABLED"
    require(
        "PREMATURE_FRESH_EVIDENCE_ACTIVATION" in validate_contract(activated),
        "Premature activation fails closed",
    )
    retuned_v12 = copy.deepcopy(contract)
    retuned_v12["hypothesis_origin"]["v12_tuning_or_reinterpretation"] = True
    require(
        "V12_REINTERPRETATION_PROHIBITED" in validate_contract(retuned_v12),
        "V12 reinterpretation fails closed",
    )
    bad_predecessor = predecessor_payload()
    bad_predecessor["decision"] = "PROMOTE_V12"
    require(
        validate_predecessor_disposition(bad_predecessor),
        "Tampered V12 disposition fails closed",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        disposition_path = Path(temp_dir) / "status.json"
        disposition_path.write_text(
            json.dumps(predecessor_payload()),
            encoding="utf-8",
        )
        before = set(Path(temp_dir).iterdir())
        loaded, predecessor_loaded = run(disposition_path=disposition_path)
        after = set(Path(temp_dir).iterdir())
        require(loaded == contract, "Locked contract passes read-only preflight")
        require(
            predecessor_loaded["disposition_sha256"] == EXPECTED_V12_DISPOSITION_SHA256,
            "Predecessor disposition passes identity preflight",
        )
        require(before == after, "Preregistration preflight writes no evidence")

    source = Path(__file__).with_name("regime_overlay_contract.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(
            forbidden_import not in source,
            f"Brokerage SDK absent: {forbidden_import}",
        )

    print("Status: PASSED")
    print("V13 successor hypothesis: PREREGISTERED FRESH EVIDENCE")
    print("Control/challenger: 1/1")
    print("Frozen V10 rankings modified: NO")
    print("V11 authority: REGIME-BOUNDED ENTRY CONFIRMATION ONLY")
    print("V12 observations reused: 0")
    print("Fresh evidence activation: DISABLED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
