"""Validate the preregistered V13 fresh regime-overlay research contract.

V13 is a new successor hypothesis, not a continuation or reinterpretation of
V12. It keeps the frozen V10 rankings unchanged and permits the registered V11
entry confirmation only when the locked negative/high-volatility regime gate
is true. This module is read-only and has no activation or brokerage surface.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("regime_overlay_contract.json")
V12_DISPOSITION_PATH = ROOT / "data/research/v12/development/disposition/status.json"

EXPECTED_CONTRACT_SHA256 = (
    "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702"
)
EXPECTED_V12_EVALUATION_SHA256 = (
    "89fa9135324a041cb105d9acf21752775e838c9f6452d5bb1a192a86d5a6d6b7"
)
EXPECTED_V12_DISPOSITION_SHA256 = (
    "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2"
)
EXPECTED_V10_CANDIDATE = "c3_confirm2_blend50"
EXPECTED_V10_SHA256 = (
    "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
)
EXPECTED_V11_SHA256 = (
    "f539fabe9532752adb2a3b6b98aa244671b5ec8d8ae86b5eaacf8076f812a6c8"
)


def canonical_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def contract_sha256(contract: Mapping[str, object]) -> str:
    return canonical_sha256(contract)


def validate_contract(contract: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("CONTRACT_SHA256_CHANGED")
    if contract.get("research_version") != "stock_v13":
        failures.append("RESEARCH_VERSION_CHANGED")
    if contract.get("status") != "PREREGISTERED_FRESH_EVIDENCE_DISABLED":
        failures.append("STATUS_CHANGED")

    origin = contract.get("hypothesis_origin")
    if not isinstance(origin, Mapping):
        failures.append("HYPOTHESIS_ORIGIN_INVALID")
    else:
        if origin.get("classification") != "POST_V12_SUCCESSOR_HYPOTHESIS":
            failures.append("HYPOTHESIS_ORIGIN_CHANGED")
        if origin.get("v12_tuning_or_reinterpretation") is not False:
            failures.append("V12_REINTERPRETATION_PROHIBITED")
        if origin.get("v12_development_observations_reused") != 0:
            failures.append("V12_OBSERVATION_REUSE_PROHIBITED")
        if origin.get("fresh_evidence_required") is not True:
            failures.append("FRESH_EVIDENCE_REQUIREMENT_REMOVED")

    predecessor = contract.get("predecessor_lock")
    if not isinstance(predecessor, Mapping):
        failures.append("PREDECESSOR_LOCK_INVALID")
    else:
        expected = {
            "v12_status": "V12_DEVELOPMENT_CLOSED_RETAIN_V10",
            "v12_decision": "RETAIN_FROZEN_V10_CONTROL",
            "v12_selected_candidate": "V10_CONTROL_5K",
            "v12_evaluation_sha256": EXPECTED_V12_EVALUATION_SHA256,
            "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
            "post_result_v12_tuning_allowed": False,
        }
        for key, value in expected.items():
            if predecessor.get(key) != value:
                failures.append(f"PREDECESSOR_{key.upper()}_CHANGED")

    control = contract.get("control")
    if not isinstance(control, Mapping):
        failures.append("CONTROL_INVALID")
    else:
        if control.get("candidate_id") != "V10_CONTROL_5K":
            failures.append("CONTROL_ID_CHANGED")
        if control.get("v10_candidate_id") != EXPECTED_V10_CANDIDATE:
            failures.append("V10_CANDIDATE_CHANGED")
        if control.get("v10_frozen_spec_sha256") != EXPECTED_V10_SHA256:
            failures.append("V10_SHA_CHANGED")
        if control.get("ranking_contract_immutable") is not True:
            failures.append("V10_RANKING_MUTATION_ALLOWED")

    challenger = contract.get("challenger")
    if not isinstance(challenger, Mapping):
        failures.append("CHALLENGER_INVALID")
    else:
        if challenger.get("candidate_id") != "V13_NEGATIVE_HIGH_VOL_CONFIRM_5K":
            failures.append("CHALLENGER_ID_CHANGED")
        if challenger.get("candidate_count") != 1:
            failures.append("CHALLENGER_COUNT_CHANGED")
        if challenger.get("ranking_source") != "UNCHANGED_V10_CYCLE3_RANKS":
            failures.append("RANKING_SOURCE_CHANGED")
        if challenger.get("ranking_weight_from_v11") != 0:
            failures.append("V11_RANKING_WEIGHT_MUST_BE_ZERO")
        if challenger.get("blanket_volatility_scaling") is not False:
            failures.append("BLANKET_VOLATILITY_SCALING_PROHIBITED")
        if challenger.get("leverage_allowed") is not False:
            failures.append("LEVERAGE_PROHIBITED")

    v11 = contract.get("v11_input_boundary")
    if not isinstance(v11, Mapping):
        failures.append("V11_BOUNDARY_INVALID")
    else:
        if v11.get("contract_sha256") != EXPECTED_V11_SHA256:
            failures.append("V11_SHA_CHANGED")
        if v11.get("role") != "ENTRY_CONFIRMATION_ONLY_IN_LOCKED_REGIME":
            failures.append("V11_ROLE_CHANGED")
        for key in (
            "fresh_outcomes_read",
            "production_journal_reads",
            "production_journal_writes",
        ):
            if v11.get(key) is not False:
                failures.append(f"V11_{key.upper()}_MUST_BE_FALSE")

    regime = contract.get("regime_gate")
    if not isinstance(regime, Mapping):
        failures.append("REGIME_GATE_INVALID")
    else:
        if regime.get("all_conditions_required") is not True:
            failures.append("REGIME_CONJUNCTION_CHANGED")
        if regime.get("condition_1") != "V10_CONFIRMED_NEGATIVE_REGIME":
            failures.append("NEGATIVE_REGIME_CHANGED")
        if regime.get("condition_2_input") != "SPY_REALIZED_DAILY_VOLATILITY_20_SESSIONS":
            failures.append("VOLATILITY_INPUT_CHANGED")
        if regime.get("condition_2_threshold") != 0.25:
            failures.append("VOLATILITY_THRESHOLD_CHANGED")
        if regime.get("condition_2_operator") != ">=":
            failures.append("VOLATILITY_OPERATOR_CHANGED")
        if regime.get("missing_or_stale_regime_input_action") != "HOLD_CASH":
            failures.append("REGIME_FAIL_CLOSED_REMOVED")

    confirmation = contract.get("entry_confirmation_rule")
    expected_tests = [
        "return_15m_minus_spy_return_15m >= 0",
        "volume_acceleration >= 0",
        "realized_volatility_30m <= cross_section_percentile_80",
    ]
    if not isinstance(confirmation, Mapping):
        failures.append("ENTRY_CONFIRMATION_INVALID")
    else:
        if confirmation.get("applies_only_when_regime_gate_true") is not True:
            failures.append("CONFIRMATION_SCOPE_CHANGED")
        if confirmation.get("outside_regime_action") != "EXECUTE_UNCHANGED_V10_CONTROL":
            failures.append("OUTSIDE_REGIME_ACTION_CHANGED")
        if confirmation.get("confirm_symbol_if_all") != expected_tests:
            failures.append("ENTRY_TESTS_CHANGED")
        if confirmation.get("minimum_confirmed_positions") != 3:
            failures.append("MINIMUM_CONFIRMATIONS_CHANGED")
        for key in (
            "insufficient_confirmations_action",
            "missing_or_stale_intraday_data_action",
        ):
            if confirmation.get(key) != "HOLD_CASH":
                failures.append(f"{key.upper()}_CHANGED")

    execution = contract.get("small_account_execution")
    if not isinstance(execution, Mapping):
        failures.append("EXECUTION_CONTRACT_INVALID")
    else:
        expected = {
            "starting_capital_usd": 5000,
            "integer_shares_only": True,
            "fractional_shares": False,
            "margin": False,
            "short_selling": False,
            "maximum_deployed_capital_pct": 0.9,
            "minimum_cash_buffer_pct": 0.1,
            "maximum_position_notional_pct": 0.2,
            "maximum_spread_bps": 20,
        }
        for key, value in expected.items():
            if execution.get(key) != value:
                failures.append(f"EXECUTION_{key.upper()}_CHANGED")

    evidence = contract.get("fresh_evidence")
    if not isinstance(evidence, Mapping):
        failures.append("FRESH_EVIDENCE_INVALID")
    else:
        if evidence.get("boundary_utc") != "2026-09-01T14:00:00+00:00":
            failures.append("FRESH_BOUNDARY_CHANGED")
        if evidence.get("minimum_completed_sessions") != 60:
            failures.append("MINIMUM_FRESH_SESSIONS_CHANGED")
        if evidence.get("minimum_regime_eligible_sessions") != 15:
            failures.append("MINIMUM_REGIME_SESSIONS_CHANGED")
        for key in (
            "development_or_preboundary_observations_allowed",
            "v10_holdout_outcomes_allowed",
            "v11_fresh_outcomes_allowed",
        ):
            if evidence.get(key) is not False:
                failures.append(f"EVIDENCE_{key.upper()}_MUST_BE_FALSE")
        if evidence.get("activation_status") != "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT":
            failures.append("PREMATURE_FRESH_EVIDENCE_ACTIVATION")

    gates = contract.get("confirmation_gates")
    if not isinstance(gates, Mapping):
        failures.append("CONFIRMATION_GATES_INVALID")
    else:
        if gates.get("all_gates_required") is not True:
            failures.append("ALL_GATES_REQUIREMENT_REMOVED")
        if gates.get("net_annualized_return_delta_vs_control_at_least") != 0.03:
            failures.append("RETURN_DELTA_GATE_CHANGED")
        if gates.get("maximum_drawdown_not_worse_than_control") is not True:
            failures.append("DRAWDOWN_GATE_REMOVED")
        if gates.get("failure_action") != "RETAIN_FROZEN_V10_CONTROL":
            failures.append("FAILURE_ACTION_CHANGED")

    change = contract.get("change_control")
    if not isinstance(change, Mapping) or any(
        change.get(key) is not expected
        for key, expected in {
            "candidate_set_fixed_before_fresh_evidence": True,
            "regime_threshold_locked": True,
            "entry_tests_locked": True,
            "execution_rules_locked": True,
            "confirmation_gates_locked": True,
            "post_result_tuning_allowed": False,
            "successor_requires_new_version": True,
        }.items()
    ):
        failures.append("CHANGE_CONTROL_INVALID")

    authority = contract.get("authority")
    if not isinstance(authority, Mapping):
        failures.append("AUTHORITY_INVALID")
    else:
        if authority.get("research_only") is not True:
            failures.append("RESEARCH_ONLY_BOUNDARY_REMOVED")
        if authority.get("paper_trading_only") is not True:
            failures.append("PAPER_ONLY_BOUNDARY_REMOVED")
        for key in (
            "live_trading_enabled",
            "brokerage_orders",
            "candidate_freeze_authorized",
            "fresh_evidence_activation_authorized",
            "v8_production_reads",
            "v8_production_writes",
            "v10_production_reads",
            "v10_production_writes",
            "v11_production_reads",
            "v11_production_writes",
            "v12_development_evidence_reads",
            "holdout_outcomes_read",
        ):
            if authority.get(key) is not False:
                failures.append(f"AUTHORITY_{key.upper()}_MUST_BE_FALSE")
    return list(dict.fromkeys(failures))


def validate_predecessor_disposition(
    payload: Mapping[str, object],
) -> list[str]:
    expected = {
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
    return [
        f"V12_DISPOSITION_{key.upper()}_CHANGED"
        for key, value in expected.items()
        if payload.get(key) != value
    ]


def run(
    *,
    contract_path: Path = CONTRACT_PATH,
    disposition_path: Path = V12_DISPOSITION_PATH,
) -> tuple[dict[str, object], dict[str, object]]:
    contract = load_contract(contract_path)
    failures = validate_contract(contract)
    if not disposition_path.exists():
        failures.append("V12_DISPOSITION_MISSING")
        disposition: dict[str, object] = {}
    else:
        disposition = json.loads(disposition_path.read_text(encoding="utf-8"))
        failures.extend(validate_predecessor_disposition(disposition))
    if failures:
        raise RuntimeError("V13_PREREGISTRATION_BLOCKED:" + ",".join(failures))
    return contract, disposition


def main() -> None:
    print("DATA SHEPHERD V13 FRESH REGIME-OVERLAY PREREGISTRATION")
    print("=" * 84)
    try:
        contract, _ = run()
    except Exception as exc:
        print("Status: BLOCKED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Fresh evidence activation: DISABLED")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {contract['status']}")
    print(f"Challenger: {contract['challenger']['candidate_id']}")
    print(f"Control: {contract['control']['candidate_id']}")
    print(f"Fresh evidence boundary: {contract['fresh_evidence']['boundary_utc']}")
    print(f"Minimum fresh sessions: {contract['fresh_evidence']['minimum_completed_sessions']}")
    print(f"Minimum qualifying regime sessions: {contract['fresh_evidence']['minimum_regime_eligible_sessions']}")
    print(f"Contract SHA-256: {contract_sha256(contract)}")
    print("Frozen V10 rankings modified: NO")
    print("Blanket volatility scaling: PROHIBITED")
    print("V11 authority: REGIME-BOUNDED ENTRY CONFIRMATION ONLY")
    print("V12 observations reused: 0")
    print("Fresh evidence activation: DISABLED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
