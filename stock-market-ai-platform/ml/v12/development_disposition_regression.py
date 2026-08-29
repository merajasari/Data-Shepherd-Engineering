"""Regression checks for the immutable V12 development disposition."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile

from ml.v12.challenger_contract import contract_sha256, load_contract
from ml.v12.development_disposition import (
    EXPECTED_CANDIDATES,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_EVALUATION_SHA256,
    _evaluation_body,
    record_disposition,
    validate_evaluation,
)
from ml.v12.development_evaluator import (
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SPEC_SHA256,
    _canonical_sha,
)


GATE_NAMES = (
    "net_annualized_return_delta",
    "terminal_wealth_greater_than_control",
    "maximum_drawdown_not_worse_than_control",
    "walk_forward_fold_win_rate",
    "positive_spy_regime_noninferior",
    "negative_spy_regime_outperformance",
    "high_volatility_regime_outperformance",
    "turnover_not_more_than_control_multiple",
    "all_costs_included",
    "small_account_feasibility_pass_rate",
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def _fixture() -> dict[str, object]:
    summaries = [
        {
            "candidate_id": "V10_CONTROL_5K",
            "mean_terminal_wealth": 5204.56,
            "mean_net_annualized_return": 0.1499,
            "maximum_drawdown": -0.1214,
        },
        {
            "candidate_id": "V12_INTRADAY_CONFIRM_5K",
            "mean_terminal_wealth": 5190.94,
            "mean_net_annualized_return": 0.1399,
            "maximum_drawdown": -0.0461,
        },
        {
            "candidate_id": "V12_VOL_CONTROL_5K",
            "mean_terminal_wealth": 4727.58,
            "mean_net_annualized_return": -0.1680,
            "maximum_drawdown": -0.1135,
        },
        {
            "candidate_id": "V12_COMBINED_5K",
            "mean_terminal_wealth": 5148.15,
            "mean_net_annualized_return": 0.1064,
            "maximum_drawdown": -0.0360,
        },
    ]
    passed_counts = {
        "V12_INTRADAY_CONFIRM_5K": 6,
        "V12_VOL_CONTROL_5K": 5,
        "V12_COMBINED_5K": 6,
    }
    gate_rows = []
    gate_details: dict[str, object] = {
        "V10_CONTROL_5K": {
            "all_gates_passed": True,
            "classification": "CONTROL_NOT_A_CHALLENGER",
        }
    }
    for candidate_id, passed_count in passed_counts.items():
        for index, gate in enumerate(GATE_NAMES):
            gate_rows.append(
                {
                    "candidate_id": candidate_id,
                    "gate": gate,
                    "passed": index < passed_count,
                }
            )
        gate_details[candidate_id] = {
            "gates_passed": passed_count,
            "gates_total": 10,
            "all_gates_passed": False,
        }
    body: dict[str, object] = {
        "status": "V12_PREREGISTERED_DEVELOPMENT_EVIDENCE",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v10_control_candidate": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SPEC_SHA256,
        "candidate_ids": list(EXPECTED_CANDIDATES),
        "period_count": 76,
        "walk_forward_folds": [{"fold": index} for index in range(1, 6)],
        "candidate_summaries": summaries,
        "gate_results": gate_rows,
        "gate_details": gate_details,
        "selected_candidate": "V10_CONTROL_5K",
        "decision": "RETAIN_FROZEN_V10_CONTROL",
        "candidate_frozen": False,
        "fresh_paper_confirmation_activated": False,
        "v10_holdout_outcomes_read": False,
        "v11_fresh_outcomes_read": False,
        "v11_production_journal_read": False,
        "production_data_read": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "source_inputs": {
            "v10_candidate_id": EXPECTED_V10_CANDIDATE,
            "v10_frozen_spec_sha256": EXPECTED_V10_SPEC_SHA256,
            "production_inputs_read": False,
            "holdout_outcomes_read": False,
        },
    }
    payload = dict(body)
    payload["evaluation_sha256"] = _canonical_sha(body)
    payload["generated_at_utc"] = "2026-08-29T00:00:00+00:00"
    return payload


def _expect_blocked(payload: dict[str, object], label: str) -> None:
    body = _evaluation_body(payload)
    payload["evaluation_sha256"] = _canonical_sha(body)
    try:
        validate_evaluation(
            payload,
            expected_evaluation_sha256=str(payload["evaluation_sha256"]),
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(label)
    require(True, label)


def main() -> None:
    contract = load_contract()
    require(
        contract_sha256(contract) == EXPECTED_CONTRACT_SHA256,
        "Locked V12 contract identity matches disposition",
    )
    require(
        EXPECTED_EVALUATION_SHA256
        == "89fa9135324a041cb105d9acf21752775e838c9f6452d5bb1a192a86d5a6d6b7",
        "Observed V12 evaluation identity is locked",
    )

    fixture = _fixture()
    fixture_sha = str(fixture["evaluation_sha256"])
    failed = validate_evaluation(
        fixture,
        expected_evaluation_sha256=fixture_sha,
    )
    require(
        tuple(failed) == EXPECTED_CANDIDATES[1:],
        "All three challengers have recorded failed gates",
    )
    require(
        all(failed[candidate_id] for candidate_id in EXPECTED_CANDIDATES[1:]),
        "Every challenger has at least one failed gate",
    )

    tampered = copy.deepcopy(fixture)
    tampered["candidate_summaries"][0]["mean_terminal_wealth"] = 999999.0
    try:
        validate_evaluation(tampered, expected_evaluation_sha256=fixture_sha)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Evaluation tampering fails SHA verification")
    require(True, "Evaluation tampering fails SHA verification")

    changed_decision = copy.deepcopy(fixture)
    changed_decision["decision"] = "ELIGIBLE_FOR_SEPARATE_V12_FREEZE_AUDIT"
    changed_decision["selected_candidate"] = "V12_COMBINED_5K"
    _expect_blocked(changed_decision, "Unauthorized V12 promotion fails closed")

    passing_challenger = copy.deepcopy(fixture)
    candidate_id = "V12_COMBINED_5K"
    passing_challenger["gate_details"][candidate_id]["all_gates_passed"] = True
    for row in passing_challenger["gate_results"]:
        if row["candidate_id"] == candidate_id:
            row["passed"] = True
    _expect_blocked(passing_challenger, "Reinterpreted passing challenger fails closed")

    activated = copy.deepcopy(fixture)
    activated["fresh_paper_confirmation_activated"] = True
    _expect_blocked(activated, "Premature fresh-paper activation fails closed")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        disposition_path = root / "status.json"
        lock_path = root / "status.sha256"
        first, created = record_disposition(
            fixture,
            disposition_path=disposition_path,
            lock_path=lock_path,
            expected_evaluation_sha256=fixture_sha,
            recorded_at_utc="2026-08-29T00:00:00+00:00",
        )
        require(created, "First disposition writes atomically")
        require(disposition_path.exists() and lock_path.exists(), "Disposition and SHA lock exist")
        require(
            lock_path.read_text(encoding="utf-8").strip()
            == first["disposition_sha256"],
            "Disposition lock matches the canonical identity",
        )
        require(
            first["decision"] == "RETAIN_FROZEN_V10_CONTROL",
            "Disposition retains frozen V10",
        )
        require(first["candidate_frozen"] is False, "Disposition freezes no V12 candidate")
        require(
            first["fresh_paper_confirmation_activated"] is False,
            "Disposition activates no fresh paper confirmation",
        )
        require(first["brokerage_orders"] is False, "Disposition has no brokerage authority")

        second, created_again = record_disposition(
            fixture,
            disposition_path=disposition_path,
            lock_path=lock_path,
            expected_evaluation_sha256=fixture_sha,
        )
        require(not created_again, "Repeated disposition is idempotent")
        require(
            second["disposition_sha256"] == first["disposition_sha256"],
            "Restart preserves disposition identity",
        )

        lock_path.write_text("0" * 64 + "\n", encoding="utf-8")
        try:
            record_disposition(
                fixture,
                disposition_path=disposition_path,
                lock_path=lock_path,
                expected_evaluation_sha256=fixture_sha,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Tampered disposition lock fails closed")
        require(True, "Tampered disposition lock fails closed")

    source = Path(__file__).with_name("development_disposition.py").read_text(
        encoding="utf-8"
    )
    for prohibited in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(prohibited not in source, f"Brokerage SDK absent: {prohibited}")

    print("\nStatus: PASSED")
    print("V12 final development disposition: VERIFIED")
    print("Decision: RETAIN FROZEN V10 CONTROL")
    print("Post-result V12 tuning: PROHIBITED")
    print("Candidate freeze authority: NONE")
    print("Fresh paper confirmation: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production evidence modified: NO")


if __name__ == "__main__":
    main()
