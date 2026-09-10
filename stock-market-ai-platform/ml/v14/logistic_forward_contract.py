"""Identity and validation for the isolated V14 logistic candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

CONTRACT_PATH = Path(__file__).with_name("logistic_forward_contract.json")
EXPECTED_CANDIDATE_ID = "v14_logistic_walk_forward_top10"
EXPECTED_CONTRACT_ID = "V14_LOGISTIC_WALK_FORWARD_PAPER_FORWARD_V1"
EXPECTED_CONTRACT_SHA256 = "b1a933792b2d5298281708292dc94e565130397ce79a1533bf89cbe1c805abd3"


def canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def contract_sha256(contract: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(contract)).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V14_CONTRACT_MUST_BE_OBJECT")
    if payload.get("contract_id") != EXPECTED_CONTRACT_ID:
        raise ValueError("V14_CONTRACT_ID_MISMATCH")
    if payload.get("candidate_id") != EXPECTED_CANDIDATE_ID:
        raise ValueError("V14_CANDIDATE_ID_MISMATCH")
    model = payload.get("model")
    portfolio = payload.get("portfolio")
    evaluation = payload.get("evaluation")
    authority = payload.get("authority")
    if not all(isinstance(value, dict) for value in (model, portfolio, evaluation, authority)):
        raise ValueError("V14_CONTRACT_SECTIONS_INVALID")
    required_features = model.get("features")
    if not isinstance(required_features, list) or len(required_features) < 3:
        raise ValueError("V14_FEATURE_SET_INVALID")
    checks = (
        model.get("type") == "numpy_logistic_regression",
        model.get("target") == "target_up_5d",
        model.get("training_scope") == "pooled_cross_sectional_expanding_window",
        int(model.get("purge_gap_sessions", 0)) == 5,
        int(portfolio.get("top_n", 0)) == 10,
        portfolio.get("weighting") == "equal_weight",
        portfolio.get("entry") == "next_session_open",
        int(portfolio.get("holding_sessions", 0)) == 5,
        int(portfolio.get("cost_bps_per_dollar_traded", 0)) == 10,
        evaluation.get("outcomes_for_model_selection") is False,
        evaluation.get("online_retraining") is True,
        evaluation.get("training_cutoff_is_recorded") is True,
        evaluation.get("model_snapshot_is_recorded") is True,
        authority.get("paper_trading_only") is True,
        authority.get("live_trading_enabled") is False,
        authority.get("brokerage_orders") is False,
        authority.get("automatic_promotion") is False,
        authority.get("modify_v8") is False,
        authority.get("modify_v10") is False,
    )
    if not all(checks):
        raise ValueError("V14_CONTRACT_RULE_MISMATCH")
    if contract_sha256(payload) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("V14_CONTRACT_SHA256_MISMATCH")
    return payload
