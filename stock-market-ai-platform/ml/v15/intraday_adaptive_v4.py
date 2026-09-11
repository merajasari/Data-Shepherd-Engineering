"""Leakage-safe V15 V4 adaptive intraday development evaluation.

V4 responds to V3's one-trade failure with a separately preregistered design.
It freezes the 120-minute horizon, predicts absolute return after modeled cost,
and selects a top-1/top-3/top-5 portfolio plus a score quantile using only each
outer fold's earlier training history. It remains development-only.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_hybrid_v2 import HYBRID_FEATURE_NAMES
from ml.v15.intraday_logistic import canonical_sha256, load_dataset
from ml.v15.intraday_selective_v3 import (
    RidgeReturnRegression,
    build_multihorizon_examples,
    load_contract as load_v3_contract,
)
from ml.v15.intraday_selective_v3_disposition import (
    load_disposition as load_v3_disposition,
    validate_result_artifact as validate_v3_result_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_adaptive_v4_contract.json")
MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v15/intraday_adaptive_v4/latest_results.json"
EXPECTED_CONTRACT_SHA256 = (
    "2233fed531b9d38aa981fe4149b2fa560902104b64da3c4ae1300416a8620f4d"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_V4_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_POST_V3_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    ):
        failures.append("V15_V4_CLASSIFICATION_INVALID")
    heritage = contract.get("heritage", {})
    data = contract.get("data", {})
    model = contract.get("model", {})
    nested = contract.get("nested_selection", {})
    portfolio = contract.get("portfolio", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if heritage.get("v3_outcomes_read_before_v4_design") is not True:
        failures.append("V15_V4_V3_DISCLOSURE_MISSING")
    if heritage.get("v3_results_reused_as_fresh_evidence") is not False:
        failures.append("V15_V4_V3_EVIDENCE_BOUNDARY_INVALID")
    if data.get("current_session_daily_close_prohibited") is not True:
        failures.append("V15_V4_DAILY_LEAKAGE_PROHIBITION_MISSING")
    if int(data.get("holding_bars", 0)) != 24:
        failures.append("V15_V4_HORIZON_INVALID")
    if int(data.get("minimum_eligible_intraday_sessions", 0)) < 300:
        failures.append("V15_V4_HISTORY_MINIMUM_TOO_SMALL")
    if model.get("type") != "NUMPY_RIDGE_ABSOLUTE_RETURN_REGRESSION":
        failures.append("V15_V4_MODEL_TYPE_INVALID")
    if model.get("target") != (
        "STOCK_GROSS_RETURN_MINUS_TEN_BPS_ROUND_TRIP_COST_AT_120_MINUTES"
    ):
        failures.append("V15_V4_TARGET_INVALID")
    if int(model.get("feature_count", 0)) != len(HYBRID_FEATURE_NAMES):
        failures.append("V15_V4_FEATURE_COUNT_INVALID")
    top_n = tuple(int(value) for value in nested.get("candidate_top_n", ()))
    quantiles = tuple(
        float(value) for value in nested.get("candidate_participation_quantiles", ())
    )
    if top_n != (1, 3, 5) or quantiles != (0.5, 0.65, 0.8):
        failures.append("V15_V4_CONFIGURATION_GRID_INVALID")
    if nested.get("selection_data") != "OUTER_TRAINING_SESSIONS_ONLY":
        failures.append("V15_V4_NESTED_SELECTION_INVALID")
    if nested.get("quantile_threshold_uses_predictions_only") is not True:
        failures.append("V15_V4_QUANTILE_LEAKAGE_GUARD_MISSING")
    if nested.get("no_eligible_configuration") != "HOLD_CASH_FOR_OUTER_FOLD":
        failures.append("V15_V4_CASH_FALLBACK_MISSING")
    if nested.get("outer_test_outcomes_used_for_selection") is not False:
        failures.append("V15_V4_OUTER_TEST_SELECTION_PROHIBITION_MISSING")
    if portfolio.get("cost_applied_only_when_trade_occurs") is not True:
        failures.append("V15_V4_COST_APPLICATION_INVALID")
    if float(portfolio.get("no_trade_return", math.nan)) != 0.0:
        failures.append("V15_V4_CASH_RETURN_INVALID")
    if evaluation.get("development_evidence_only") is not True:
        failures.append("V15_V4_DEVELOPMENT_BOUNDARY_MISSING")
    if evaluation.get("fresh_paper_boundary_required_after_development") is not True:
        failures.append("V15_V4_FRESH_BOUNDARY_MISSING")
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
        failures.append("V15_V4_AUTHORITY_INVALID")
    if authority.get("development_only") is not True:
        failures.append("V15_V4_DEVELOPMENT_AUTHORITY_INVALID")
    if authority.get("human_review_required") is not True:
        failures.append("V15_V4_REVIEW_BOUNDARY_INVALID")
    if failures:
        raise ValueError(";".join(failures))
    return contract


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _growth(returns: Sequence[float]) -> float:
    return math.prod(1.0 + float(value) for value in returns) - 1.0


def _max_drawdown(returns: Sequence[float]) -> float:
    equity = peak = 1.0
    maximum = 0.0
    for value in returns:
        equity *= 1.0 + float(value)
        peak = max(peak, equity)
        maximum = max(maximum, 1.0 - equity / peak)
    return maximum


def _relative(candidate: float, control: float) -> float:
    return (1.0 + float(candidate)) / (1.0 + float(control)) - 1.0


def _fit_model(
    rows: Sequence[Mapping[str, object]],
    contract: Mapping[str, object],
) -> tuple[RidgeReturnRegression, np.ndarray, np.ndarray, dict[str, object]]:
    horizon = int(contract["data"]["holding_bars"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    X = np.asarray([row["features"] for row in rows], dtype=float)
    y = np.asarray(
        [float(row["outcomes"][str(horizon)]["gross_return"]) - cost for row in rows],
        dtype=float,
    )
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0.0] = 1.0
    model = RidgeReturnRegression(
        alpha=float(contract["model"]["ridge_alpha"])
    ).fit((X - mean) / std, y)
    snapshot: dict[str, object] = {
        "feature_names": list(HYBRID_FEATURE_NAMES),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "weights": model.weights.tolist() if model.weights is not None else [],
        "bias": model.bias,
        "target_holding_bars": horizon,
        "training_rows": len(rows),
        "target": contract["model"]["target"],
    }
    snapshot["model_sha256"] = canonical_sha256(snapshot)
    return model, mean, std, snapshot


def _session_prediction(
    rows: Sequence[Mapping[str, object]],
    model: RidgeReturnRegression,
    mean: np.ndarray,
    std: np.ndarray,
    top_n: int,
) -> tuple[list[tuple[Mapping[str, object], float]], float]:
    matrix = np.asarray([row["features"] for row in rows], dtype=float)
    predictions = model.predict((matrix - mean) / std)
    ranked = sorted(
        zip(rows, predictions),
        key=lambda item: (-float(item[1]), str(item[0]["symbol"])),
    )
    selected = ranked[:top_n]
    expected = statistics.fmean(float(value) for _, value in selected)
    return selected, expected


def _higher_quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("V15_V4_EMPTY_CALIBRATION_SIGNALS")
    index = int(math.ceil(float(quantile) * (len(ordered) - 1)))
    return ordered[index]


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
    horizon = int(contract["data"]["holding_bars"])
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
    matched_spy_returns: list[float] = []
    trades = 0
    for _, selected, expected in predictions:
        trade = expected >= threshold and expected > floor
        if trade:
            trades += 1
            returns.append(
                statistics.fmean(
                    float(row["outcomes"][str(horizon)]["gross_return"])
                    for row, _ in selected
                )
                - cost
            )
            matched_spy_returns.append(
                float(selected[0][0]["outcomes"][str(horizon)]["spy_return"])
            )
        else:
            returns.append(0.0)
            matched_spy_returns.append(0.0)
    net_return = _growth(returns)
    matched_spy_return = _growth(matched_spy_returns)
    return {
        "top_n": top_n,
        "participation_quantile": participation_quantile,
        "raw_quantile_threshold": raw_threshold,
        "applied_threshold": threshold,
        "trades": trades,
        "net_total_return": net_return,
        "matched_spy_total_return": matched_spy_return,
        "matched_spy_edge": _relative(net_return, matched_spy_return),
        "max_drawdown": _max_drawdown(returns),
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
        raise ValueError("V15_V4_INNER_TRAINING_HISTORY_INSUFFICIENT")
    inner_training_sessions = list(outer_training_sessions[:inner_training_stop])
    inner_validation_sessions = list(outer_training_sessions[-validation_count:])
    training_rows = [
        row for session in inner_training_sessions for row in by_session[session]
    ]
    if len(training_rows) < int(contract["model"]["minimum_training_rows"]):
        raise ValueError(f"V15_V4_TRAINING_ROWS_BELOW_MINIMUM:{len(training_rows)}")
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
    for top_n in nested["candidate_top_n"]:
        for quantile in nested["candidate_participation_quantiles"]:
            score = _score_configuration(
                inner_validation_sessions,
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
            )
            diagnostics.append(score)
    eligible = [item for item in diagnostics if item["eligible"]]
    boundary = {
        "inner_training_start_session": inner_training_sessions[0],
        "inner_training_cutoff_session": inner_training_sessions[-1],
        "inner_validation_start_session": inner_validation_sessions[0],
        "inner_validation_end_session": inner_validation_sessions[-1],
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
        progress("Building frozen V11/V14 features and 120-minute outcomes...")
    v3_contract = load_v3_contract()
    sessions, by_session, feature_audit = build_multihorizon_examples(
        intraday_dataset, daily_frames, v3_contract
    )
    minimum_history = int(contract["data"]["minimum_eligible_intraday_sessions"])
    if len(sessions) < minimum_history:
        raise ValueError(
            f"V15_V4_INSUFFICIENT_ELIGIBLE_SESSIONS:{len(sessions)}<{minimum_history}"
        )
    model_spec = contract["model"]
    evaluation = contract["evaluation"]
    purge = int(model_spec["purge_gap_sessions"])
    cursor = int(model_spec["minimum_outer_training_sessions"]) + purge - 1
    available = len(sessions) - cursor
    minimum_test = int(evaluation["minimum_final_test_sessions"])
    if available < minimum_test:
        raise ValueError(f"V15_V4_INSUFFICIENT_TEST_SESSIONS:{available}<{minimum_test}")
    fold_size = int(evaluation["test_sessions_per_fold"])
    horizon = int(contract["data"]["holding_bars"])
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
                v15_return = (
                    statistics.fmean(
                        float(row["outcomes"][str(horizon)]["gross_return"])
                        for row, _ in selected
                    )
                    - cost
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
                matched_v11 = (
                    statistics.fmean(
                        float(row["outcomes"][str(horizon)]["gross_return"])
                        for row in v11_selected
                    )
                    - cost
                )
                matched_v14 = (
                    statistics.fmean(
                        float(row["outcomes"][str(horizon)]["gross_return"])
                        for row in v14_selected
                    )
                    - cost
                )
                matched_spy = float(
                    current[0]["outcomes"][str(horizon)]["spy_return"]
                )
            else:
                v15_return = matched_v11 = matched_v14 = matched_spy = 0.0
            always_spy = float(current[0]["outcomes"][str(horizon)]["spy_return"])
            observation = {
                "session": session,
                "daily_context_session": current[0]["daily_context_session"],
                "model_training_cutoff_session": snapshot["training_cutoff_session"],
                "inner_validation_end_session": configuration[
                    "inner_validation_end_session"
                ],
                "holding_bars": horizon,
                "top_n": configuration["top_n"],
                "participation_quantile": configuration["participation_quantile"],
                "applied_threshold": configuration["applied_threshold"],
                "cash_fallback": cash_fallback,
                "trade": trade,
                "predicted_topk_net_return": expected,
                "selected_symbols": [str(row["symbol"]) for row, _ in selected],
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
    trades = len(traded)
    trade_rate = trades / len(observations)
    profitable_trade_rate = (
        statistics.fmean(float(float(row["v15_net_return"]) > 0.0) for row in traded)
        if traded
        else 0.0
    )
    positive_fold_share = statistics.fmean(
        float(float(fold["v15_net_total_return"]) > 0.0) for fold in folds
    )
    maximum_drawdown = _max_drawdown(
        [float(row["v15_net_return"]) for row in observations]
    )
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
    }
    passed = all(gate_results.values())
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "candidate_id": contract["candidate_id"],
        "classification": contract["classification"],
        "status": (
            "V15_V4_DEVELOPMENT_GATES_PASSED_NOT_FROZEN"
            if passed
            else "V15_V4_REJECTED_DEVELOPMENT_CANDIDATE"
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
    disposition = load_v3_disposition()
    validate_v3_result_artifact()
    if contract["heritage"]["v3_disposition_sha256"] != disposition[
        "disposition_sha256"
    ]:
        raise ValueError("V15_V4_V3_DISPOSITION_BINDING_MISMATCH")
    v3_contract = load_v3_contract()
    if canonical_sha256(v3_contract) != contract["heritage"][
        "v3_feature_contract_sha256"
    ]:
        raise ValueError("V15_V4_V3_FEATURE_CONTRACT_MISMATCH")
    if progress:
        progress("Loading immutable V11 intraday manifest...")
    manifest, intraday = load_dataset(manifest_path)
    if progress:
        progress("Loading synchronized prior-close V14 daily context...")
    symbols, daily_frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V4_V14_UNIVERSE_MISMATCH")
    result = evaluate_walk_forward(
        intraday, daily_frames, contract, progress=progress
    )
    result["source_manifest_sha256"] = manifest["manifest_sha256"]
    result["contract_sha256"] = canonical_sha256(contract)
    result["v3_disposition_sha256"] = disposition["disposition_sha256"]
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    result["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    print("V15 V4 ADAPTIVE 120-MINUTE INTRADAY DEVELOPMENT")
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
    print(f"V15 V4 net return: {result['v15_net_total_return']:+.2%}")
    print(f"Matched V11 control: {result['matched_v11_net_total_return']:+.2%}")
    print(
        "Matched V14 context control: "
        f"{result['matched_v14_context_net_total_return']:+.2%}"
    )
    print(f"Matched SPY control: {result['matched_spy_total_return']:+.2%}")
    print(f"Always-on SPY: {result['always_on_spy_total_return']:+.2%}")
    print(f"Maximum drawdown: {result['v15_max_drawdown']:.2%}")
    print(
        f"Development gates: {'PASS' if result['development_gates_passed'] else 'FAIL'}"
    )
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO | fresh paper boundary still required")
    print("Existing models modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
