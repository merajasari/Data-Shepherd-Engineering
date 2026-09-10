"""Identity and validation for the accelerated V10 Cycle 3 paper-forward lane.

This amendment does not replace or edit the frozen January 4 confirmation
contract.  It authorizes a separate prospective, paper-only evidence journal.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Mapping

CONTRACT_PATH = Path(__file__).with_name(
    "cycle3_accelerated_forward_contract.json"
)
EXPECTED_CONTRACT_SHA256 = (
    "1859bbfae9980c10540d716d83c52b0af92d4875c4b9c8d8c948e9799edcab5b"
)
EXPECTED_CANDIDATE_ID = "c3_confirm2_blend50"
EXPECTED_FROZEN_SHA256 = (
    "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
)
FIRST_DECISION_SESSION_UTC = "2026-09-08T00:00:00+00:00"
LAST_DECISION_SESSION_UTC = "2026-12-18T00:00:00+00:00"
INDEPENDENT_CONFIRMATION_START_UTC = "2027-01-04T00:00:00+00:00"


def contract_sha256(contract: Mapping[str, object]) -> str:
    encoded = json.dumps(
        contract, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_iso(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def validate_contract(contract: Mapping[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    if contract.get("contract_id") != "V10_CYCLE3_ACCELERATED_PAPER_FORWARD_V1":
        reasons.append("CONTRACT_ID_CHANGED")
    if contract.get("status") != "AUTHORIZED_PROSPECTIVE_PAPER_FORWARD":
        reasons.append("STATUS_CHANGED")

    source = contract.get("source_candidate", {})
    if not isinstance(source, Mapping):
        reasons.append("SOURCE_CANDIDATE_INVALID")
    else:
        if source.get("candidate_id") != EXPECTED_CANDIDATE_ID:
            reasons.append("CANDIDATE_CHANGED")
        if source.get("frozen_sha256") != EXPECTED_FROZEN_SHA256:
            reasons.append("FROZEN_SHA_CHANGED")
        if source.get("development_gates_passed") != 13:
            reasons.append("DEVELOPMENT_GATES_CHANGED")
        if source.get("candidate_modified") is not False:
            reasons.append("CANDIDATE_MUST_REMAIN_UNMODIFIED")

    window = contract.get("evidence_window", {})
    if not isinstance(window, Mapping):
        reasons.append("EVIDENCE_WINDOW_INVALID")
    else:
        expected = {
            "first_decision_session_utc": FIRST_DECISION_SESSION_UTC,
            "last_decision_session_utc": LAST_DECISION_SESSION_UTC,
            "independent_confirmation_start_utc": (
                INDEPENDENT_CONFIRMATION_START_UTC
            ),
        }
        for field, value in expected.items():
            if window.get(field) != value or not _aware_iso(window.get(field)):
                reasons.append(f"{field.upper()}_CHANGED")
        if window.get("missed_decisions_backfilled") is not False:
            reasons.append("BACKFILL_PROHIBITION_MISSING")
        if window.get("cross_confirmation_boundary_outcomes_allowed") is not False:
            reasons.append("CROSS_BOUNDARY_OUTCOMES_MUST_BE_PROHIBITED")
        if window.get("january_confirmation_modified") is not False:
            reasons.append("JANUARY_CONFIRMATION_MUST_REMAIN_UNMODIFIED")

    portfolio = contract.get("fixed_portfolio_contract", {})
    required_portfolio = {
        "top_n": 10,
        "weighting": "equal_weight",
        "entry": "next_session_open",
        "holding_sessions": 5,
        "cohort_offsets": [0, 1, 2, 3, 4],
        "primary_cost_bps_per_dollar_traded": 10,
        "benchmark": "SPY",
        "control": "V8_DISTANCE_FROM_LOW_20D_SAME_DATES",
    }
    if not isinstance(portfolio, Mapping):
        reasons.append("PORTFOLIO_CONTRACT_INVALID")
    else:
        for field, value in required_portfolio.items():
            if portfolio.get(field) != value:
                reasons.append(f"PORTFOLIO_{field.upper()}_CHANGED")

    policy = contract.get("evidence_policy", {})
    if not isinstance(policy, Mapping):
        reasons.append("EVIDENCE_POLICY_INVALID")
    else:
        required_true = (
            "append_only",
            "hash_chained",
            "duplicate_safe",
            "prospective_decisions_only",
            "overlapping_exits_are_diagnostic_not_independent",
            "human_review_required",
        )
        for field in required_true:
            if policy.get(field) is not True:
                reasons.append(f"{field.upper()}_REQUIRED")
        if policy.get("minimum_blocks_for_provisional_paper_champion_review") != 8:
            reasons.append("PROVISIONAL_REVIEW_BLOCKS_CHANGED")
        if policy.get("minimum_blocks_for_stronger_limited_live_review") != 12:
            reasons.append("STRONGER_REVIEW_BLOCKS_CHANGED")
        for field in (
            "automatic_promotion",
            "candidate_retuning_allowed",
            "results_used_for_candidate_selection",
        ):
            if policy.get(field) is not False:
                reasons.append(f"{field.upper()}_MUST_BE_FALSE")

    authority = contract.get("authority", {})
    if not isinstance(authority, Mapping):
        reasons.append("AUTHORITY_INVALID")
    else:
        if authority.get("paper_trading_only") is not True:
            reasons.append("PAPER_ONLY_REQUIRED")
        for field in (
            "live_trading_enabled",
            "brokerage_orders",
            "brokerage_sdks_allowed",
            "modify_v8",
            "invoke_v8_production",
            "read_v8_holdout_outcomes",
            "modify_original_v10_holdout",
            "read_original_v10_holdout_outcomes",
            "modify_january_confirmation",
        ):
            if authority.get(field) is not False:
                reasons.append(f"{field.upper()}_MUST_BE_FALSE")
    return tuple(dict.fromkeys(reasons))


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    reasons = validate_contract(contract)
    if reasons:
        raise ValueError("ACCELERATED_CONTRACT_INVALID:" + ",".join(reasons))
    observed = contract_sha256(contract)
    if observed != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            "ACCELERATED_CONTRACT_SHA_MISMATCH:"
            f"expected={EXPECTED_CONTRACT_SHA256}:observed={observed}"
        )
    return contract


def verify_frozen_source() -> None:
    """Verify the original immutable candidate without reading holdout outcomes."""
    from ml.v10 import cycle3_holdout_runner as frozen

    if frozen.EXPECTED_SHA != EXPECTED_FROZEN_SHA256:
        raise RuntimeError("SOURCE_FROZEN_SHA_MISMATCH")
    if frozen.CANDIDATE_ID != EXPECTED_CANDIDATE_ID:
        raise RuntimeError("SOURCE_CANDIDATE_ID_MISMATCH")
    if frozen.HOLDOUT_START.isoformat() != INDEPENDENT_CONFIRMATION_START_UTC:
        raise RuntimeError("JANUARY_CONFIRMATION_BOUNDARY_CHANGED")
    frozen._verify_freeze()


def main() -> None:
    contract = load_contract()
    print("V10 CYCLE 3 ACCELERATED PAPER-FORWARD CONTRACT")
    print("=" * 88)
    print(f"Status: {contract['status']}")
    print(f"Candidate: {EXPECTED_CANDIDATE_ID}")
    print(f"Frozen SHA-256: {EXPECTED_FROZEN_SHA256}")
    print(f"Contract SHA-256: {EXPECTED_CONTRACT_SHA256}")
    print(f"First decision session: {FIRST_DECISION_SESSION_UTC}")
    print(f"Last decision session: {LAST_DECISION_SESSION_UTC}")
    print(
        "Independent January confirmation: "
        f"{INDEPENDENT_CONFIRMATION_START_UTC} (UNCHANGED)"
    )
    print("Automatic promotion: NO | human review required: YES")
    print("V8 modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
