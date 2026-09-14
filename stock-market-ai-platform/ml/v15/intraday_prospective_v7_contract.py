"""Frozen identity and authority checks for V15 V7 prospective paper shadow."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping

from ml.v15.intraday_logistic import canonical_sha256


CONTRACT_PATH = Path(__file__).with_name("intraday_prospective_v7_contract.json")
EXPECTED_CONTRACT_SHA256 = (
    "98e1c92137bebb0be31df2937fdd9a9e213957713e15c06cb479564a0856c222"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_V7_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_PROSPECTIVE_PAPER_SHADOW_NOT_PRODUCTION"
    ):
        failures.append("V15_V7_CLASSIFICATION_INVALID")

    heritage = contract.get("heritage", {})
    boundary = contract.get("evidence_boundary", {})
    mechanics = contract.get("frozen_mechanics", {})
    lifecycle = contract.get("lifecycle", {})
    review = contract.get("review", {})
    authority = contract.get("authority", {})
    training = contract.get("training_policy", {})

    if heritage.get("historical_results_are_design_context_not_v7_evidence") is not True:
        failures.append("V15_V7_HISTORICAL_EVIDENCE_BOUNDARY_MISSING")
    if heritage.get("v6_logic_used") is not False:
        failures.append("V15_V7_V6_REUSE_INVALID")
    if boundary.get("first_eligible_session") != "2026-09-21":
        failures.append("V15_V7_FIRST_SESSION_INVALID")
    if boundary.get("activation_requires_verified_runner") is not True:
        failures.append("V15_V7_VERIFIED_RUNNER_REQUIREMENT_MISSING")
    if boundary.get("historical_rows_count_as_v7_evidence") is not False:
        failures.append("V15_V7_HISTORICAL_ROWS_PROHIBITION_MISSING")
    if boundary.get("missed_decisions_may_be_backfilled") is not False:
        failures.append("V15_V7_BACKFILL_PROHIBITION_MISSING")
    if boundary.get("evidence_is_prospective_paper_only") is not True:
        failures.append("V15_V7_PROSPECTIVE_BOUNDARY_INVALID")

    if mechanics.get("signal_source") != (
        "UNCHANGED_V15_V5_RIDGE_SIGNAL_AND_NESTED_SELECTION"
    ):
        failures.append("V15_V7_SIGNAL_IDENTITY_INVALID")
    if int(mechanics.get("decision_bar_index", -1)) != 5:
        failures.append("V15_V7_DECISION_BAR_INVALID")
    if int(mechanics.get("entry_bar_index", -1)) != 6:
        failures.append("V15_V7_ENTRY_BAR_INVALID")
    if int(mechanics.get("scheduled_exit_bar_index", -1)) != 29:
        failures.append("V15_V7_EXIT_BAR_INVALID")
    if int(mechanics.get("holding_minutes", 0)) != 120:
        failures.append("V15_V7_HORIZON_INVALID")
    if float(mechanics.get("protective_stop_loss_fraction", math.nan)) != 0.02:
        failures.append("V15_V7_STOP_INVALID")
    if int(mechanics.get("modeled_total_cost_bps_round_trip", -1)) != 10:
        failures.append("V15_V7_COST_INVALID")
    if float(mechanics.get("maximum_invested_fraction", math.nan)) != 0.6:
        failures.append("V15_V7_EXPOSURE_INVALID")
    if float(mechanics.get("required_cash_fraction", math.nan)) != 0.4:
        failures.append("V15_V7_CASH_RESERVE_INVALID")
    if mechanics.get("short_sales") is not False or mechanics.get("leverage") is not False:
        failures.append("V15_V7_DIRECTION_OR_LEVERAGE_INVALID")
    if mechanics.get("matched_controls_share_exposure") is not True:
        failures.append("V15_V7_CONTROL_EXPOSURE_PARITY_INVALID")
    if mechanics.get("matched_stock_controls_share_stop") is not True:
        failures.append("V15_V7_CONTROL_STOP_PARITY_INVALID")
    if mechanics.get("matched_spy_stop_applied") is not False:
        failures.append("V15_V7_SPY_STOP_POLICY_INVALID")

    if lifecycle.get("timezone") != "America/New_York":
        failures.append("V15_V7_TIMEZONE_INVALID")
    if int(lifecycle.get("scheduler_interval_seconds", 0)) != 300:
        failures.append("V15_V7_INTERVAL_INVALID")
    if lifecycle.get("decision_must_precede_entry_event") is not True:
        failures.append("V15_V7_DECISION_ORDERING_MISSING")
    if lifecycle.get("entry_must_precede_exit_event") is not True:
        failures.append("V15_V7_ENTRY_ORDERING_MISSING")
    if lifecycle.get("source_bars_after_decision_bar_prohibited_for_signal") is not True:
        failures.append("V15_V7_SIGNAL_LEAKAGE_PROHIBITION_MISSING")
    if tuple(lifecycle.get("decision_checkpoint", ())) != ("09:58", "10:08"):
        failures.append("V15_V7_DECISION_WINDOW_INVALID")
    if tuple(lifecycle.get("entry_checkpoint", ())) != ("10:03", "10:13"):
        failures.append("V15_V7_ENTRY_WINDOW_INVALID")
    if tuple(lifecycle.get("exit_checkpoint", ())) != ("11:58", "12:08"):
        failures.append("V15_V7_EXIT_WINDOW_INVALID")
    if lifecycle.get("decision_features_fixed_to_first_six_completed_bars") is not True:
        failures.append("V15_V7_DECISION_BAR_FREEZE_MISSING")
    if any(lifecycle.get(name) is not True for name in (
        "late_decision_after_checkpoint_prohibited",
        "late_entry_after_checkpoint_prohibited",
        "late_exit_after_checkpoint_prohibited",
    )):
        failures.append("V15_V7_LATE_LIFECYCLE_PROHIBITION_MISSING")
    closures = tuple(lifecycle.get("market_closures", ()))
    if "2026-11-26" not in closures or "2026-12-25" not in closures:
        failures.append("V15_V7_MARKET_CALENDAR_INVALID")

    if training.get("fixed_history_manifest_sha256") != (
        "1d49fbd7a76a7e90c403d5043907f51ba10e26e1915f2edfc50cac68dc730733"
    ):
        failures.append("V15_V7_TRAINING_MANIFEST_INVALID")
    if training.get("fixed_history_last_session") != "2026-09-10":
        failures.append("V15_V7_TRAINING_CUTOFF_INVALID")
    if training.get("model_and_threshold_prepared_once_before_activation") is not True:
        failures.append("V15_V7_MODEL_PREPARATION_BOUNDARY_MISSING")
    if training.get("prepared_artifact_replacement_prohibited") is not True:
        failures.append("V15_V7_MODEL_REPLACEMENT_PROHIBITION_MISSING")
    if training.get("historical_training_expansion_during_v7") is not False:
        failures.append("V15_V7_TRAINING_EXPANSION_PROHIBITION_MISSING")
    if training.get("daily_context_must_precede_decision_session") is not True:
        failures.append("V15_V7_DAILY_CONTEXT_BOUNDARY_MISSING")

    gates = review.get("gates", {}) if isinstance(review, Mapping) else {}
    if int(review.get("minimum_completed_trades", 0)) < 30:
        failures.append("V15_V7_TRADE_MINIMUM_TOO_SMALL")
    if int(review.get("minimum_active_blocks", 0)) < 6:
        failures.append("V15_V7_ACTIVE_BLOCK_MINIMUM_TOO_SMALL")
    if float(gates.get("maximum_drawdown_at_most", math.nan)) != 0.1:
        failures.append("V15_V7_DRAWDOWN_GATE_INVALID")
    if float(gates.get("positive_active_block_share_at_least", math.nan)) != 0.6:
        failures.append("V15_V7_ACTIVE_STABILITY_GATE_INVALID")
    if float(gates.get("non_losing_all_block_share_at_least", math.nan)) != 0.8:
        failures.append("V15_V7_ALL_BLOCK_STABILITY_GATE_INVALID")
    if review.get("automatic_promotion") is not False:
        failures.append("V15_V7_AUTOMATIC_PROMOTION_INVALID")
    if review.get("human_review_required") is not True:
        failures.append("V15_V7_HUMAN_REVIEW_MISSING")

    if authority.get("candidate_mechanics_frozen_for_v7_evidence") is not True:
        failures.append("V15_V7_FREEZE_MISSING")
    if authority.get("paper_shadow_collection_allowed") is not True:
        failures.append("V15_V7_PAPER_COLLECTION_AUTHORITY_MISSING")
    required_false = (
        "model_frozen_for_production",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "dashboard_may_invoke_runner",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        failures.append("V15_V7_AUTHORITY_INVALID")
    if authority.get("scheduler_installation_requires_separate_review") is not True:
        failures.append("V15_V7_SCHEDULER_REVIEW_BOUNDARY_MISSING")

    if failures:
        raise ValueError(";".join(failures))
    return contract
