"""V15 V6 stability-first, risk-managed intraday development evaluation."""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_adaptive_v4 import (
    _atomic_write,
    _fit_model,
    _growth,
    _higher_quantile,
    _max_drawdown,
    _relative,
    _session_prediction,
)
from ml.v15.intraday_risk_managed_v5 import load_contract as load_v5_contract
from ml.v15.intraday_risk_managed_v5_disposition import (
    load_disposition as load_v5_disposition,
    validate_result_artifact as validate_v5_result_artifact,
)
from ml.v15.intraday_hybrid_v2 import HYBRID_FEATURE_NAMES
from ml.v15.intraday_logistic import _group_sessions, canonical_sha256, load_dataset
from ml.v15.intraday_selective_v3 import (
    RidgeReturnRegression,
    build_multihorizon_examples,
    load_contract as load_v3_contract,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_stability_first_v6_contract.json")
MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v15/intraday_stability_first_v6/latest_results.json"
EXPECTED_CONTRACT_SHA256 = (
    "08279154b9f43e354b18ba66dcf89dbcf56913385d2ee298f4d0770ecc39101f"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_V6_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_POST_V5_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    ):
        failures.append("V15_V6_CLASSIFICATION_INVALID")
    heritage = contract.get("heritage", {})
    data = contract.get("data", {})
    model = contract.get("model", {})
    risk = contract.get("risk_management", {})
    nested = contract.get("nested_selection", {})
    portfolio = contract.get("portfolio", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if heritage.get("v5_outcomes_read_before_v6_design") is not True:
        failures.append("V15_V6_V5_DISCLOSURE_MISSING")
    if heritage.get("v5_results_reused_as_fresh_evidence") is not False:
        failures.append("V15_V6_V5_EVIDENCE_BOUNDARY_INVALID")
    if data.get("current_session_daily_close_prohibited") is not True:
        failures.append("V15_V6_DAILY_LEAKAGE_PROHIBITION_MISSING")
    if int(data.get("holding_bars", 0)) != 24:
        failures.append("V15_V6_HORIZON_INVALID")
    if int(data.get("entry_bar_index", -1)) != 6:
        failures.append("V15_V6_ENTRY_INDEX_INVALID")
    if int(data.get("scheduled_exit_bar_index", -1)) != 29:
        failures.append("V15_V6_EXIT_INDEX_INVALID")
    if int(data.get("minimum_eligible_intraday_sessions", 0)) < 300:
        failures.append("V15_V6_HISTORY_MINIMUM_TOO_SMALL")
    if model.get("type") != "NUMPY_RIDGE_ABSOLUTE_RETURN_REGRESSION":
        failures.append("V15_V6_MODEL_TYPE_INVALID")
    if int(model.get("feature_count", 0)) != len(HYBRID_FEATURE_NAMES):
        failures.append("V15_V6_FEATURE_COUNT_INVALID")
    if float(risk.get("protective_stop_loss_fraction", math.nan)) != 0.02:
        failures.append("V15_V6_STOP_INVALID")
    if risk.get("gap_fill") != "BAR_OPEN_WHEN_BAR_OPEN_IS_BELOW_STOP_PRICE":
        failures.append("V15_V6_GAP_FILL_INVALID")
    if risk.get("stop_parameter_grid_search") is not False:
        failures.append("V15_V6_STOP_TUNING_PROHIBITION_MISSING")
    if risk.get("stop_applies_to_v15_and_MATCHED_STOCK_CONTROLS") is not True:
        failures.append("V15_V6_STOP_CONTROL_PARITY_INVALID")
    if tuple(nested.get("candidate_top_n", ())) != (1, 3, 5):
        failures.append("V15_V6_TOPK_GRID_INVALID")
    if tuple(nested.get("candidate_participation_quantiles", ())) != (
        0.5,
        0.65,
        0.8,
    ):
        failures.append("V15_V6_QUANTILE_GRID_INVALID")
    if int(nested.get("validation_subwindow_count", 0)) != 2:
        failures.append("V15_V6_SUBWINDOW_COUNT_INVALID")
    if nested.get("selection_objective") != (
        "HIGHEST_WORST_VALIDATION_SUBWINDOW_RETURN"
    ):
        failures.append("V15_V6_STABILITY_OBJECTIVE_INVALID")
    if tuple(nested.get("tie_break_order", ()))[:2] != (
        "HIGHEST_COMPOUNDED_ABSOLUTE_NET_RETURN",
        "HIGHEST_MATCHED_SPY_EDGE",
    ):
        failures.append("V15_V6_STABILITY_TIE_BREAK_INVALID")
    if nested.get("selection_data") != "OUTER_TRAINING_SESSIONS_ONLY":
        failures.append("V15_V6_NESTED_SELECTION_INVALID")
    if nested.get("outer_test_outcomes_used_for_selection") is not False:
        failures.append("V15_V6_OUTER_TEST_SELECTION_PROHIBITION_MISSING")
    if portfolio.get("cost_applied_only_when_trade_occurs") is not True:
        failures.append("V15_V6_COST_APPLICATION_INVALID")
    if float(portfolio.get("no_trade_return", math.nan)) != 0.0:
        failures.append("V15_V6_CASH_RETURN_INVALID")
    if evaluation.get("development_evidence_only") is not True:
        failures.append("V15_V6_DEVELOPMENT_BOUNDARY_MISSING")
    if evaluation.get("fresh_paper_boundary_required_after_development") is not True:
        failures.append("V15_V6_FRESH_BOUNDARY_MISSING")
    required_false = (
        "model_frozen",
        "paper_forward_allowed",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "scheduler_installation_allowed",
        "dashboard_active_model_label_allowed",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        failures.append("V15_V6_AUTHORITY_INVALID")
    if authority.get("development_only") is not True:
        failures.append("V15_V6_DEVELOPMENT_AUTHORITY_INVALID")
    if authority.get("human_review_required") is not True:
        failures.append("V15_V6_REVIEW_BOUNDARY_INVALID")
    if failures:
        raise ValueError(";".join(failures))
    return contract


def _gap_aware_stop_return(
    bars: Sequence[Mapping[str, object]],
    *,
    entry_bar_index: int,
    exit_bar_index: int,
    stop_fraction: float,
) -> tuple[float, bool, int | None]:
    entry = float(bars[entry_bar_index]["open"])
    if not math.isfinite(entry) or entry <= 0.0:
        raise ValueError("V15_V6_ENTRY_PRICE_INVALID")
    stop_price = entry * (1.0 - float(stop_fraction))
    for bar_index in range(entry_bar_index, exit_bar_index + 1):
        bar = bars[bar_index]
        if float(bar["low"]) <= stop_price:
            fill = min(stop_price, float(bar["open"]))
            if not math.isfinite(fill) or fill <= 0.0:
                raise ValueError("V15_V6_STOP_FILL_INVALID")
            return fill / entry - 1.0, True, bar_index
    return float(bars[exit_bar_index]["close"]) / entry - 1.0, False, None


def build_risk_managed_examples(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, object],
    contract: Mapping[str, object],
) -> tuple[list[str], dict[str, list[dict[str, object]]], dict[str, object]]:
    sessions, base, audit = build_multihorizon_examples(
        intraday_dataset, daily_frames, load_v3_contract()
    )
    grouped = {
        symbol: _group_sessions(rows) for symbol, rows in intraday_dataset.items()
    }
    entry_index = int(contract["data"]["entry_bar_index"])
    exit_index = int(contract["data"]["scheduled_exit_bar_index"])
    stop_fraction = float(contract["risk_management"]["protective_stop_loss_fraction"])
    horizon = str(contract["data"]["holding_bars"])
    result: dict[str, list[dict[str, object]]] = {}
    for session in sessions:
        rows: list[dict[str, object]] = []
        for original in base[session]:
            symbol = str(original["symbol"])
            gross, stopped, stop_bar = _gap_aware_stop_return(
                grouped[symbol][session],
                entry_bar_index=entry_index,
                exit_bar_index=exit_index,
                stop_fraction=stop_fraction,
            )
            outcomes = {
                key: dict(value) for key, value in original["outcomes"].items()
            }
            outcomes[horizon].update(
                {
                    "risk_managed_gross_return": gross,
                    "protective_stop_triggered": stopped,
                    "protective_stop_bar_index": stop_bar,
                }
            )
            rows.append({**original, "outcomes": outcomes})
        result[session] = rows
    return sessions, result, audit


def _portfolio_return(
    selected: Sequence[tuple[Mapping[str, object], float]] | Sequence[Mapping[str, object]],
    *,
    horizon: str,
    cost: float,
) -> tuple[float, int]:
    rows = [item[0] if isinstance(item, tuple) else item for item in selected]
    gross = statistics.fmean(
        float(row["outcomes"][horizon]["risk_managed_gross_return"])
        for row in rows
    )
    stopped = sum(
        bool(row["outcomes"][horizon]["protective_stop_triggered"])
        for row in rows
    )
    return gross - cost, stopped


def _score_configuration(
    sessions: Sequence[str],
    by_session: Mapping[str, Sequence[Mapping[str, object]]],
    model: RidgeReturnRegression,
    mean: np.ndarray,
    std: np.ndarray,
    *,
    top_n: int,
    participation_quantile: float,
    contract: Mapping[str, object],
) -> dict[str, object]:
    horizon = str(contract["data"]["holding_bars"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    floor = float(contract["nested_selection"]["absolute_predicted_net_return_floor"])
    predictions: list[tuple[str, list[tuple[Mapping[str, object], float]], float]] = []
    for session in sessions:
        selected, expected = _session_prediction(
            by_session[session], model, mean, std, top_n
        )
        predictions.append((session, selected, expected))
    raw_threshold = _higher_quantile(
        [expected for _, _, expected in predictions], participation_quantile
    )
    threshold = max(floor, raw_threshold)
    returns: list[float] = []
    spy_returns: list[float] = []
    flags: list[bool] = []
    stops = 0
    for _, selected, expected in predictions:
        trade = expected >= threshold and expected > floor
        flags.append(trade)
        if trade:
            value, triggered = _portfolio_return(
                selected, horizon=horizon, cost=cost
            )
            returns.append(value)
            stops += triggered
            spy_returns.append(float(selected[0][0]["outcomes"][horizon]["spy_return"]))
        else:
            returns.append(0.0)
            spy_returns.append(0.0)
    subwindow_count = int(contract["nested_selection"]["validation_subwindow_count"])
    if len(sessions) % subwindow_count != 0:
        raise ValueError("V15_V6_VALIDATION_SUBWINDOWS_UNEVEN")
    width = len(sessions) // subwindow_count
    subwindow_returns = [
        _growth(returns[index * width : (index + 1) * width])
        for index in range(subwindow_count)
    ]
    subwindow_trades = [
        sum(flags[index * width : (index + 1) * width])
        for index in range(subwindow_count)
    ]
    net_return = _growth(returns)
    matched_spy = _growth(spy_returns)
    return {
        "top_n": top_n,
        "participation_quantile": participation_quantile,
        "raw_quantile_threshold": raw_threshold,
        "applied_threshold": threshold,
        "trades": sum(flags),
        "stop_triggered_positions": stops,
        "net_total_return": net_return,
        "matched_spy_total_return": matched_spy,
        "matched_spy_edge": _relative(net_return, matched_spy),
        "max_drawdown": _max_drawdown(returns),
        "validation_subwindow_returns": subwindow_returns,
        "validation_subwindow_trades": subwindow_trades,
        "worst_validation_subwindow_return": min(subwindow_returns),
    }


def select_configuration(
    outer_training_sessions: Sequence[str],
    by_session: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    RidgeReturnRegression,
    np.ndarray,
    np.ndarray,
    dict[str, object],
]:
    nested = contract["nested_selection"]
    purge = int(contract["model"]["purge_gap_sessions"])
    validation_count = int(nested["inner_validation_sessions"])
    inner_training_stop = len(outer_training_sessions) - validation_count - purge
    if inner_training_stop < int(nested["minimum_inner_training_sessions"]):
        raise ValueError("V15_V6_INNER_TRAINING_HISTORY_INSUFFICIENT")
    inner_training_sessions = list(outer_training_sessions[:inner_training_stop])
    validation_sessions = list(outer_training_sessions[-validation_count:])
    training_rows = [
        row for session in inner_training_sessions for row in by_session[session]
    ]
    if len(training_rows) < int(contract["model"]["minimum_training_rows"]):
        raise ValueError(f"V15_V6_TRAINING_ROWS_BELOW_MINIMUM:{len(training_rows)}")
    model, mean, std, snapshot = _fit_model(training_rows, contract)
    snapshot.update(
        {
            "training_start_session": inner_training_sessions[0],
            "training_cutoff_session": inner_training_sessions[-1],
            "training_sessions": len(inner_training_sessions),
        }
    )
    unsigned_snapshot = dict(snapshot)
    unsigned_snapshot.pop("model_sha256", None)
    snapshot["model_sha256"] = canonical_sha256(unsigned_snapshot)
    diagnostics: list[dict[str, object]] = []
    minimum_subwindow_trades = int(
        nested["minimum_trades_per_validation_subwindow"]
    )
    minimum_subwindow_return = float(
        nested["validation_subwindow_net_return_at_least"]
    )
    for top_n in nested["candidate_top_n"]:
        for quantile in nested["candidate_participation_quantiles"]:
            score = _score_configuration(
                validation_sessions,
                by_session,
                model,
                mean,
                std,
                top_n=int(top_n),
                participation_quantile=float(quantile),
                contract=contract,
            )
            score["eligible"] = (
                int(score["trades"]) >= int(nested["minimum_inner_trades"])
                and float(score["net_total_return"])
                > float(nested["inner_net_total_return_greater_than"])
                and float(score["matched_spy_edge"])
                > float(nested["inner_matched_spy_edge_greater_than"])
                and float(score["max_drawdown"])
                <= float(nested["inner_max_drawdown_at_most"])
                and all(
                    int(value) >= minimum_subwindow_trades
                    for value in score["validation_subwindow_trades"]
                )
                and all(
                    float(value) >= minimum_subwindow_return
                    for value in score["validation_subwindow_returns"]
                )
            )
            diagnostics.append(score)
    eligible = [item for item in diagnostics if item["eligible"]]
    boundary = {
        "inner_training_start_session": inner_training_sessions[0],
        "inner_training_cutoff_session": inner_training_sessions[-1],
        "inner_validation_start_session": validation_sessions[0],
        "inner_validation_end_session": validation_sessions[-1],
    }
    if not eligible:
        configuration = {
            "top_n": None,
            "participation_quantile": None,
            "applied_threshold": None,
            "cash_fallback": True,
            **boundary,
        }
    else:
        selected = max(
            eligible,
            key=lambda item: (
                float(item["worst_validation_subwindow_return"]),
                float(item["net_total_return"]),
                float(item["matched_spy_edge"]),
                -float(item["max_drawdown"]),
                int(item["trades"]),
                int(item["top_n"]),
                float(item["participation_quantile"]),
            ),
        )
        configuration = {
            "top_n": int(selected["top_n"]),
            "participation_quantile": float(selected["participation_quantile"]),
            "applied_threshold": float(selected["applied_threshold"]),
            "cash_fallback": False,
            **boundary,
        }
    return configuration, diagnostics, model, mean, std, snapshot


def evaluate_walk_forward(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, object],
    contract: Mapping[str, object],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if progress:
        progress("Building V11/V14 features with gap-aware protective-stop paths...")
    sessions, by_session, feature_audit = build_risk_managed_examples(
        intraday_dataset, daily_frames, contract
    )
    minimum_history = int(contract["data"]["minimum_eligible_intraday_sessions"])
    if len(sessions) < minimum_history:
        raise ValueError(
            f"V15_V6_INSUFFICIENT_ELIGIBLE_SESSIONS:{len(sessions)}<{minimum_history}"
        )
    model_spec = contract["model"]
    evaluation = contract["evaluation"]
    purge = int(model_spec["purge_gap_sessions"])
    cursor = int(model_spec["minimum_outer_training_sessions"]) + purge - 1
    available = len(sessions) - cursor
    if available < int(evaluation["minimum_final_test_sessions"]):
        raise ValueError("V15_V6_INSUFFICIENT_TEST_SESSIONS")
    fold_size = int(evaluation["test_sessions_per_fold"])
    horizon = str(contract["data"]["holding_bars"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    floor = float(contract["nested_selection"]["absolute_predicted_net_return_floor"])
    observations: list[dict[str, object]] = []
    folds: list[dict[str, object]] = []
    fold_number = 1
    while cursor < len(sessions):
        test_sessions = sessions[cursor : cursor + min(fold_size, len(sessions) - cursor)]
        training_sessions = sessions[: cursor - purge + 1]
        configuration, diagnostics, model, mean, std, snapshot = select_configuration(
            training_sessions, by_session, contract
        )
        cash_fallback = bool(configuration["cash_fallback"])
        top_n = int(configuration["top_n"] or 1)
        fold_rows: list[dict[str, object]] = []
        for session in test_sessions:
            current = by_session[session]
            if cash_fallback:
                selected: list[tuple[Mapping[str, object], float]] = []
                expected = None
                trade = False
            else:
                selected, expected = _session_prediction(
                    current, model, mean, std, top_n
                )
                trade = (
                    float(expected) >= float(configuration["applied_threshold"])
                    and float(expected) > floor
                )
            if trade:
                v15_return, stopped_positions = _portfolio_return(
                    selected, horizon=horizon, cost=cost
                )
                v11_selected = sorted(
                    current,
                    key=lambda row: (-float(row["v11_score"]), str(row["symbol"])),
                )[:top_n]
                v14_selected = sorted(
                    current,
                    key=lambda row: (
                        -float(row["v14_daily_probability"]),
                        str(row["symbol"]),
                    ),
                )[:top_n]
                matched_v11, _ = _portfolio_return(
                    v11_selected, horizon=horizon, cost=cost
                )
                matched_v14, _ = _portfolio_return(
                    v14_selected, horizon=horizon, cost=cost
                )
                matched_spy = float(current[0]["outcomes"][horizon]["spy_return"])
            else:
                v15_return = matched_v11 = matched_v14 = matched_spy = 0.0
                stopped_positions = 0
            always_spy = float(current[0]["outcomes"][horizon]["spy_return"])
            observation = {
                "session": session,
                "daily_context_session": current[0]["daily_context_session"],
                "model_training_cutoff_session": snapshot["training_cutoff_session"],
                "inner_validation_end_session": configuration[
                    "inner_validation_end_session"
                ],
                "holding_bars": int(horizon),
                "top_n": configuration["top_n"],
                "participation_quantile": configuration["participation_quantile"],
                "applied_threshold": configuration["applied_threshold"],
                "cash_fallback": cash_fallback,
                "trade": trade,
                "predicted_topk_net_return": expected,
                "selected_symbols": [str(row["symbol"]) for row, _ in selected],
                "protective_stop_triggered_positions": stopped_positions,
                "v15_net_return": v15_return,
                "matched_v11_net_return": matched_v11,
                "matched_v14_context_net_return": matched_v14,
                "matched_spy_return": matched_spy,
                "always_on_spy_return": always_spy,
            }
            observations.append(observation)
            fold_rows.append(observation)
        fold_return = _growth([float(row["v15_net_return"]) for row in fold_rows])
        folds.append(
            {
                "fold": fold_number,
                "test_start_session": test_sessions[0],
                "test_end_session": test_sessions[-1],
                "test_sessions": len(test_sessions),
                "selected_configuration": configuration,
                "inner_configuration_diagnostics": diagnostics,
                "model_snapshot": snapshot,
                "trades": sum(bool(row["trade"]) for row in fold_rows),
                "stop_triggered_positions": sum(
                    int(row["protective_stop_triggered_positions"])
                    for row in fold_rows
                ),
                "v15_net_total_return": fold_return,
            }
        )
        if progress:
            label = (
                "CASH"
                if cash_fallback
                else (
                    f"top {top_n} / q{float(configuration['participation_quantile']):.0%} "
                    f"/ threshold {float(configuration['applied_threshold']) * 10000:.1f}bp"
                )
            )
            progress(
                f"Fold {fold_number}: {test_sessions[0]} -> {test_sessions[-1]} "
                f"| {label} | trades {folds[-1]['trades']}/{len(test_sessions)} "
                f"| stops {folds[-1]['stop_triggered_positions']} "
                f"| return {fold_return:+.2%}"
            )
        cursor += len(test_sessions)
        fold_number += 1

    def total(name: str) -> float:
        return _growth([float(row[name]) for row in observations])

    v15_total = total("v15_net_return")
    matched_v11_total = total("matched_v11_net_return")
    matched_v14_total = total("matched_v14_context_net_return")
    matched_spy_total = total("matched_spy_return")
    always_spy_total = total("always_on_spy_return")
    traded = [row for row in observations if row["trade"]]
    trade_returns = [float(row["v15_net_return"]) for row in traded]
    trades = len(traded)
    trade_rate = trades / len(observations)
    profitable_trade_rate = (
        statistics.fmean(float(value > 0.0) for value in trade_returns)
        if trade_returns
        else 0.0
    )
    positive_fold_share = statistics.fmean(
        float(float(fold["v15_net_total_return"]) > 0.0) for fold in folds
    )
    maximum_drawdown = _max_drawdown(
        [float(row["v15_net_return"]) for row in observations]
    )
    worst_trade_return = min(trade_returns) if trade_returns else 0.0
    totals = {
        "v15_net_total_return": v15_total,
        "matched_v11_net_total_return": matched_v11_total,
        "matched_v14_context_net_total_return": matched_v14_total,
        "matched_spy_total_return": matched_spy_total,
        "always_on_spy_total_return": always_spy_total,
        "v15_relative_to_matched_v11": _relative(v15_total, matched_v11_total),
        "v15_relative_to_matched_v14_context": _relative(v15_total, matched_v14_total),
        "v15_relative_to_matched_spy": _relative(v15_total, matched_spy_total),
        "v15_relative_to_always_on_spy": _relative(v15_total, always_spy_total),
    }
    gates = evaluation["gates"]
    gate_results = {
        "positive_net_return": v15_total
        > float(gates["v15_net_total_return_greater_than"]),
        "positive_relative_to_matched_v11": totals["v15_relative_to_matched_v11"]
        > float(gates["v15_relative_to_matched_v11_greater_than"]),
        "positive_relative_to_matched_v14_context": totals[
            "v15_relative_to_matched_v14_context"
        ]
        > float(gates["v15_relative_to_matched_v14_context_greater_than"]),
        "positive_relative_to_matched_spy": totals["v15_relative_to_matched_spy"]
        > float(gates["v15_relative_to_matched_spy_greater_than"]),
        "positive_relative_to_always_on_spy": totals["v15_relative_to_always_on_spy"]
        > float(gates["v15_relative_to_always_on_spy_greater_than"]),
        "minimum_trades": trades >= int(gates["completed_trades_at_least"]),
        "minimum_trade_rate": trade_rate >= float(gates["trade_rate_at_least"]),
        "maximum_trade_rate": trade_rate <= float(gates["trade_rate_at_most"]),
        "profitable_trade_rate": profitable_trade_rate
        >= float(gates["profitable_trade_rate_at_least"]),
        "fold_stability": positive_fold_share
        >= float(gates["positive_fold_share_at_least"]),
        "drawdown_control": maximum_drawdown
        <= float(gates["v15_max_drawdown_at_most"]),
        "worst_trade_control": worst_trade_return
        >= float(gates["worst_trade_return_at_least"]),
    }
    passed = all(gate_results.values())
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "candidate_id": contract["candidate_id"],
        "classification": contract["classification"],
        "status": (
            "V15_V6_DEVELOPMENT_GATES_PASSED_NOT_FROZEN"
            if passed
            else "V15_V6_REJECTED_DEVELOPMENT_CANDIDATE"
        ),
        "development_gates_passed": passed,
        "model_frozen": False,
        "paper_forward_allowed": False,
        "eligible_sessions": len(sessions),
        "fold_count": len(folds),
        "test_sessions": len(observations),
        "completed_trades": trades,
        "cash_sessions": len(observations) - trades,
        "trade_rate": trade_rate,
        "profitable_trade_rate": profitable_trade_rate,
        "positive_fold_share": positive_fold_share,
        "v15_max_drawdown": maximum_drawdown,
        "worst_trade_return": worst_trade_return,
        "protective_stop_triggered_positions": sum(
            int(row["protective_stop_triggered_positions"]) for row in observations
        ),
        "gate_results": gate_results,
        "folds": folds,
        "test_observations": observations,
        **totals,
        **feature_audit,
        "selection_on_outer_test_data": False,
        "fresh_paper_boundary_required": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v13_modified": False,
        "v14_modified": False,
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def run(
    *,
    manifest_path: Path = MANIFEST_PATH,
    contract_path: Path = CONTRACT_PATH,
    output_path: Path = OUTPUT_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    contract = load_contract(contract_path)
    disposition = load_v5_disposition()
    validate_v5_result_artifact()
    if contract["heritage"]["v5_disposition_sha256"] != disposition[
        "disposition_sha256"
    ]:
        raise ValueError("V15_V6_V5_DISPOSITION_BINDING_MISMATCH")
    v5_contract = load_v5_contract()
    if canonical_sha256(v5_contract) != contract["heritage"]["v5_contract_sha256"]:
        raise ValueError("V15_V6_V5_CONTRACT_BINDING_MISMATCH")
    if progress:
        progress("Loading immutable V11 intraday manifest...")
    manifest, intraday = load_dataset(manifest_path)
    if progress:
        progress("Loading synchronized prior-close V14 daily context...")
    symbols, daily_frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V6_V14_UNIVERSE_MISMATCH")
    result = evaluate_walk_forward(
        intraday, daily_frames, contract, progress=progress
    )
    result["source_manifest_sha256"] = manifest["manifest_sha256"]
    result["contract_sha256"] = canonical_sha256(contract)
    result["v5_disposition_sha256"] = disposition["disposition_sha256"]
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    result["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    print("V15 V6 STABILITY-FIRST 120-MINUTE INTRADAY DEVELOPMENT")
    print("=" * 80)
    try:
        result = run(progress=lambda message: print(message, flush=True))
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Model frozen: NO | paper forward: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Eligible sessions: {result['eligible_sessions']}")
    print(f"Walk-forward folds: {result['fold_count']}")
    print(f"Out-of-sample sessions: {result['test_sessions']}")
    print(
        f"Trades / cash sessions: {result['completed_trades']} / "
        f"{result['cash_sessions']}"
    )
    print(f"Trade rate: {result['trade_rate']:.1%}")
    print(
        "Protective-stop triggered positions: "
        f"{result['protective_stop_triggered_positions']}"
    )
    print(f"V15 V6 net return: {result['v15_net_total_return']:+.2%}")
    print(f"Matched V11 control: {result['matched_v11_net_total_return']:+.2%}")
    print(
        "Matched V14 context control: "
        f"{result['matched_v14_context_net_total_return']:+.2%}"
    )
    print(f"Matched SPY control: {result['matched_spy_total_return']:+.2%}")
    print(f"Always-on SPY: {result['always_on_spy_total_return']:+.2%}")
    print(f"Maximum drawdown: {result['v15_max_drawdown']:.2%}")
    print(f"Worst portfolio trade: {result['worst_trade_return']:+.2%}")
    print(
        f"Development gates: {'PASS' if result['development_gates_passed'] else 'FAIL'}"
    )
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO | fresh paper boundary still required")
    print("Existing models modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
