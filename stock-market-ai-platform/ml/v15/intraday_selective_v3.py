"""Nested, cost-aware V15 V3 selective intraday development evaluation.

V3 predicts continuous cost-adjusted excess return and may hold cash. Holding
window and safety buffer are selected using only each outer fold's training
history. Outer test outcomes never select a configuration. This remains
development evidence and cannot schedule itself or place orders.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_hybrid_v2 import (
    HYBRID_FEATURE_NAMES,
    build_hybrid_examples,
    load_contract as load_v2_contract,
)
from ml.v15.intraday_hybrid_v2_disposition import (
    load_disposition as load_v2_disposition,
    validate_result_artifact as validate_v2_result_artifact,
)
from ml.v15.intraday_logistic import (
    _group_sessions,
    canonical_sha256,
    load_dataset,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_selective_v3_contract.json")
MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v15/intraday_selective_v3/latest_results.json"
EXPECTED_CONTRACT_SHA256 = (
    "0d62d527889a9e0d9f530d4439bc0e61d65da61d83c05a46ec7b8a65c192504a"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_V3_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_POST_V2_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    ):
        failures.append("V15_V3_CLASSIFICATION_INVALID")
    heritage = contract.get("heritage", {})
    data = contract.get("data", {})
    model = contract.get("model", {})
    nested = contract.get("nested_selection", {})
    portfolio = contract.get("portfolio", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if heritage.get("v2_outcomes_read_before_v3_design") is not True:
        failures.append("V15_V3_V2_DISCLOSURE_MISSING")
    if heritage.get("v2_results_reused_as_fresh_evidence") is not False:
        failures.append("V15_V3_V2_EVIDENCE_BOUNDARY_INVALID")
    if data.get("current_session_daily_close_prohibited") is not True:
        failures.append("V15_V3_DAILY_LEAKAGE_PROHIBITION_MISSING")
    if int(data.get("minimum_eligible_intraday_sessions", 0)) < 300:
        failures.append("V15_V3_HISTORY_MINIMUM_TOO_SMALL")
    if model.get("type") != "NUMPY_RIDGE_RETURN_REGRESSION":
        failures.append("V15_V3_MODEL_TYPE_INVALID")
    if model.get("target") != "COST_ADJUSTED_STOCK_MINUS_SPY_RETURN_BY_HORIZON":
        failures.append("V15_V3_TARGET_INVALID")
    if int(model.get("feature_count", 0)) != len(HYBRID_FEATURE_NAMES):
        failures.append("V15_V3_FEATURE_COUNT_INVALID")
    horizons = tuple(int(value) for value in nested.get("candidate_holding_bars", ()))
    buffers = tuple(float(value) for value in nested.get("candidate_safety_buffers", ()))
    if horizons != (6, 12, 24) or buffers != (0.0005, 0.001, 0.0015):
        failures.append("V15_V3_CONFIGURATION_GRID_INVALID")
    if nested.get("selection_data") != "OUTER_TRAINING_SESSIONS_ONLY":
        failures.append("V15_V3_NESTED_SELECTION_INVALID")
    if nested.get("no_eligible_configuration") != "HOLD_CASH_FOR_OUTER_FOLD":
        failures.append("V15_V3_CASH_FALLBACK_MISSING")
    if nested.get("outer_test_outcomes_used_for_selection") is not False:
        failures.append("V15_V3_OUTER_TEST_SELECTION_PROHIBITION_MISSING")
    if portfolio.get("cost_applied_only_when_trade_occurs") is not True:
        failures.append("V15_V3_COST_APPLICATION_INVALID")
    if float(portfolio.get("no_trade_return", math.nan)) != 0.0:
        failures.append("V15_V3_CASH_RETURN_INVALID")
    if evaluation.get("development_evidence_only") is not True:
        failures.append("V15_V3_DEVELOPMENT_BOUNDARY_MISSING")
    if evaluation.get("fresh_paper_boundary_required_after_development") is not True:
        failures.append("V15_V3_FRESH_BOUNDARY_MISSING")
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
        failures.append("V15_V3_AUTHORITY_INVALID")
    if authority.get("development_only") is not True or authority.get("human_review_required") is not True:
        failures.append("V15_V3_REVIEW_BOUNDARY_INVALID")
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


@dataclass
class RidgeReturnRegression:
    alpha: float
    weights: np.ndarray | None = None
    bias: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgeReturnRegression":
        matrix = np.asarray(X, dtype=float)
        targets = np.asarray(y, dtype=float)
        if (
            matrix.ndim != 2
            or targets.ndim != 1
            or len(matrix) != len(targets)
            or len(matrix) == 0
            or not np.isfinite(matrix).all()
            or not np.isfinite(targets).all()
        ):
            raise ValueError("V15_V3_TRAINING_MATRIX_INVALID")
        self.bias = float(targets.mean())
        centered = targets - self.bias
        gram = matrix.T @ matrix
        penalty = np.eye(matrix.shape[1], dtype=float) * float(self.alpha)
        self.weights = np.linalg.solve(gram + penalty, matrix.T @ centered)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise ValueError("V15_V3_MODEL_NOT_FITTED")
        return np.asarray(X, dtype=float) @ self.weights + self.bias


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


def build_multihorizon_examples(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, object],
    contract: Mapping[str, object],
) -> tuple[list[str], dict[str, list[dict[str, object]]], dict[str, object]]:
    v2_contract = load_v2_contract()
    sessions, base, audit = build_hybrid_examples(
        intraday_dataset, daily_frames, v2_contract
    )
    grouped = {
        symbol: _group_sessions(rows) for symbol, rows in intraday_dataset.items()
    }
    symbols = sorted(symbol for symbol in intraday_dataset if symbol != "SPY")
    horizons = [
        int(value) for value in contract["nested_selection"]["candidate_holding_bars"]
    ]
    decision_index = int(contract["data"]["decision_bar_index"])
    entry_index = decision_index + 1
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    result: dict[str, list[dict[str, object]]] = {}
    for session in sessions:
        required = symbols + ["SPY"]
        if any(
            session not in grouped[symbol]
            or len(grouped[symbol][session]) <= decision_index + max(horizons)
            for symbol in required
        ):
            continue
        spy_bars = grouped["SPY"][session]
        spy_by_horizon = {
            str(horizon): (
                float(spy_bars[decision_index + horizon]["close"])
                / float(spy_bars[entry_index]["open"])
                - 1.0
            )
            for horizon in horizons
        }
        rows: list[dict[str, object]] = []
        for row in base[session]:
            symbol = str(row["symbol"])
            bars = grouped[symbol][session]
            outcomes: dict[str, dict[str, float]] = {}
            for horizon in horizons:
                gross = (
                    float(bars[decision_index + horizon]["close"])
                    / float(bars[entry_index]["open"])
                    - 1.0
                )
                spy_return = spy_by_horizon[str(horizon)]
                outcomes[str(horizon)] = {
                    "gross_return": gross,
                    "spy_return": spy_return,
                    "net_relative_return": gross - spy_return - cost,
                }
            rows.append({**row, "outcomes": outcomes})
        result[session] = rows
    return sorted(result), result, audit


def _fit_model(
    rows: Sequence[Mapping[str, object]],
    horizon: int,
    contract: Mapping[str, object],
) -> tuple[RidgeReturnRegression, np.ndarray, np.ndarray, dict[str, object]]:
    X = np.asarray([row["features"] for row in rows], dtype=float)
    y = np.asarray(
        [row["outcomes"][str(horizon)]["net_relative_return"] for row in rows],
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


def _evaluate_configuration(
    sessions: Sequence[str],
    by_session: Mapping[str, Sequence[Mapping[str, object]]],
    model: RidgeReturnRegression,
    mean: np.ndarray,
    std: np.ndarray,
    *,
    horizon: int,
    buffer: float,
    top_n: int,
    cost: float,
) -> dict[str, object]:
    returns: list[float] = []
    trades = 0
    for session in sessions:
        selected, expected = _session_prediction(
            by_session[session], model, mean, std, top_n
        )
        if expected > buffer:
            trades += 1
            returns.append(
                statistics.fmean(
                    float(row["outcomes"][str(horizon)]["gross_return"])
                    for row, _ in selected
                )
                - cost
            )
        else:
            returns.append(0.0)
    return {
        "holding_bars": horizon,
        "safety_buffer": buffer,
        "trades": trades,
        "net_total_return": _growth(returns),
        "max_drawdown": _max_drawdown(returns),
    }


def select_configuration(
    outer_training_sessions: Sequence[str],
    by_session: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    nested = contract["nested_selection"]
    purge = int(contract["model"]["purge_gap_sessions"])
    validation_count = int(nested["inner_validation_sessions"])
    inner_training_stop = len(outer_training_sessions) - validation_count - purge
    if inner_training_stop < int(nested["minimum_inner_training_sessions"]):
        raise ValueError("V15_V3_INNER_TRAINING_HISTORY_INSUFFICIENT")
    inner_training_sessions = list(outer_training_sessions[:inner_training_stop])
    inner_validation_sessions = list(outer_training_sessions[-validation_count:])
    training_rows = [
        row for session in inner_training_sessions for row in by_session[session]
    ]
    top_n = int(contract["portfolio"]["top_n"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    diagnostics: list[dict[str, object]] = []
    for horizon in nested["candidate_holding_bars"]:
        model, mean, std, _ = _fit_model(training_rows, int(horizon), contract)
        for buffer in nested["candidate_safety_buffers"]:
            score = _evaluate_configuration(
                inner_validation_sessions,
                by_session,
                model,
                mean,
                std,
                horizon=int(horizon),
                buffer=float(buffer),
                top_n=top_n,
                cost=cost,
            )
            score["eligible"] = (
                int(score["trades"]) >= int(nested["minimum_inner_trades"])
                and float(score["net_total_return"])
                > float(nested["inner_net_total_return_greater_than"])
                and float(score["max_drawdown"])
                <= float(nested["inner_max_drawdown_at_most"])
            )
            diagnostics.append(score)
    eligible = [item for item in diagnostics if item["eligible"]]
    if not eligible:
        return {
            "holding_bars": 6,
            "safety_buffer": None,
            "cash_fallback": True,
            "inner_training_start_session": inner_training_sessions[0],
            "inner_training_cutoff_session": inner_training_sessions[-1],
            "inner_validation_start_session": inner_validation_sessions[0],
            "inner_validation_end_session": inner_validation_sessions[-1],
        }, diagnostics
    selected = max(
        eligible,
        key=lambda item: (
            float(item["net_total_return"]),
            -float(item["max_drawdown"]),
            float(item["safety_buffer"]),
            -int(item["holding_bars"]),
        ),
    )
    return {
        "holding_bars": int(selected["holding_bars"]),
        "safety_buffer": float(selected["safety_buffer"]),
        "cash_fallback": False,
        "inner_training_start_session": inner_training_sessions[0],
        "inner_training_cutoff_session": inner_training_sessions[-1],
        "inner_validation_start_session": inner_validation_sessions[0],
        "inner_validation_end_session": inner_validation_sessions[-1],
    }, diagnostics


def evaluate_walk_forward(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, object],
    contract: Mapping[str, object],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if progress:
        progress("Building V11/V14 hybrid features and 30/60/120-minute outcomes...")
    sessions, by_session, feature_audit = build_multihorizon_examples(
        intraday_dataset, daily_frames, contract
    )
    minimum_history = int(contract["data"]["minimum_eligible_intraday_sessions"])
    if len(sessions) < minimum_history:
        raise ValueError(
            f"V15_V3_INSUFFICIENT_ELIGIBLE_SESSIONS:{len(sessions)}<{minimum_history}"
        )
    model_spec = contract["model"]
    evaluation = contract["evaluation"]
    purge = int(model_spec["purge_gap_sessions"])
    cursor = int(model_spec["minimum_outer_training_sessions"]) + purge - 1
    available = len(sessions) - cursor
    minimum_test = int(evaluation["minimum_final_test_sessions"])
    if available < minimum_test:
        raise ValueError(f"V15_V3_INSUFFICIENT_TEST_SESSIONS:{available}<{minimum_test}")
    fold_size = int(evaluation["test_sessions_per_fold"])
    top_n = int(contract["portfolio"]["top_n"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    observations: list[dict[str, object]] = []
    folds: list[dict[str, object]] = []
    fold_number = 1
    while cursor < len(sessions):
        remaining = len(sessions) - cursor
        test_sessions = sessions[cursor : cursor + min(fold_size, remaining)]
        training_sessions = sessions[: cursor - purge + 1]
        training_rows = [
            row for session in training_sessions for row in by_session[session]
        ]
        if len(training_rows) < int(model_spec["minimum_training_rows"]):
            raise ValueError(f"V15_V3_TRAINING_ROWS_BELOW_MINIMUM:{len(training_rows)}")
        configuration, diagnostics = select_configuration(
            training_sessions, by_session, contract
        )
        horizon = int(configuration["holding_bars"])
        cash_fallback = bool(configuration["cash_fallback"])
        if cash_fallback:
            model = mean = std = snapshot = None
        else:
            model, mean, std, snapshot = _fit_model(
                training_rows, horizon, contract
            )
            snapshot.update(
                {
                    "training_start_session": training_sessions[0],
                    "training_cutoff_session": training_sessions[-1],
                    "training_sessions": len(training_sessions),
                }
            )
            unsigned_snapshot = dict(snapshot)
            unsigned_snapshot.pop("model_sha256", None)
            snapshot["model_sha256"] = canonical_sha256(unsigned_snapshot)
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
                trade = float(expected) > float(configuration["safety_buffer"])
            if trade:
                v15_return = (
                    statistics.fmean(
                        float(row["outcomes"][str(horizon)]["gross_return"])
                        for row, _ in selected
                    )
                    - cost
                )
            else:
                v15_return = 0.0
            v11_selected = sorted(
                current,
                key=lambda row: (-float(row["v11_score"]), str(row["symbol"])),
            )[:top_n]
            v14_selected = sorted(
                current,
                key=lambda row: (-float(row["v14_daily_probability"]), str(row["symbol"])),
            )[:top_n]
            v11_return = (
                statistics.fmean(
                    float(row["outcomes"][str(horizon)]["gross_return"])
                    for row in v11_selected
                )
                - cost
            )
            v14_return = (
                statistics.fmean(
                    float(row["outcomes"][str(horizon)]["gross_return"])
                    for row in v14_selected
                )
                - cost
            )
            spy_return = float(current[0]["outcomes"][str(horizon)]["spy_return"])
            observation = {
                "session": session,
                "daily_context_session": current[0]["daily_context_session"],
                "outer_training_cutoff_session": training_sessions[-1],
                "holding_bars": horizon,
                "safety_buffer": configuration["safety_buffer"],
                "cash_fallback": cash_fallback,
                "trade": trade,
                "predicted_top10_net_relative_return": expected,
                "selected_symbols": [str(row["symbol"]) for row, _ in selected],
                "v15_net_return": v15_return,
                "v11_control_net_return": v11_return,
                "v14_context_control_net_return": v14_return,
                "spy_return": spy_return,
            }
            observations.append(observation)
            fold_rows.append(observation)
        fold_return = _growth([float(row["v15_net_return"]) for row in fold_rows])
        folds.append(
            {
                "fold": fold_number,
                "training_start_session": training_sessions[0],
                "training_cutoff_session": training_sessions[-1],
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
                else f"{horizon * 5}m / {float(configuration['safety_buffer']) * 10000:.0f}bp"
            )
            progress(
                f"Fold {fold_number}: {test_sessions[0]} -> {test_sessions[-1]} "
                f"| {label} | trades {folds[-1]['trades']}/{len(test_sessions)} "
                f"| return {fold_return:+.2%}"
            )
        cursor += len(test_sessions)
        fold_number += 1
    v15_returns = [float(row["v15_net_return"]) for row in observations]
    v11_returns = [float(row["v11_control_net_return"]) for row in observations]
    v14_returns = [float(row["v14_context_control_net_return"]) for row in observations]
    spy_returns = [float(row["spy_return"]) for row in observations]
    traded = [row for row in observations if row["trade"]]
    totals: dict[str, float] = {
        "v15_net_total_return": _growth(v15_returns),
        "v11_control_net_total_return": _growth(v11_returns),
        "v14_context_control_net_total_return": _growth(v14_returns),
        "spy_total_return": _growth(spy_returns),
    }
    totals["v15_relative_to_v11"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["v11_control_net_total_return"]) - 1.0
    totals["v15_relative_to_v14_context"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["v14_context_control_net_total_return"]) - 1.0
    totals["v15_relative_to_spy"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["spy_total_return"]) - 1.0
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
    maximum_drawdown = _max_drawdown(v15_returns)
    gates = evaluation["gates"]
    gate_results = {
        "positive_net_return": totals["v15_net_total_return"] > float(gates["v15_net_total_return_greater_than"]),
        "positive_relative_to_v11": totals["v15_relative_to_v11"] > float(gates["v15_relative_to_v11_greater_than"]),
        "positive_relative_to_v14_context": totals["v15_relative_to_v14_context"] > float(gates["v15_relative_to_v14_context_greater_than"]),
        "positive_relative_to_spy": totals["v15_relative_to_spy"] > float(gates["v15_relative_to_spy_greater_than"]),
        "minimum_trades": trades >= int(gates["completed_trades_at_least"]),
        "minimum_trade_rate": trade_rate >= float(gates["trade_rate_at_least"]),
        "maximum_trade_rate": trade_rate <= float(gates["trade_rate_at_most"]),
        "profitable_trade_rate": profitable_trade_rate >= float(gates["profitable_trade_rate_at_least"]),
        "fold_stability": positive_fold_share >= float(gates["positive_fold_share_at_least"]),
        "drawdown_control": maximum_drawdown <= float(gates["v15_max_drawdown_at_most"]),
    }
    passed = all(gate_results.values())
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "candidate_id": contract["candidate_id"],
        "classification": contract["classification"],
        "status": "V15_V3_DEVELOPMENT_GATES_PASSED_NOT_FROZEN" if passed else "V15_V3_REJECTED_DEVELOPMENT_CANDIDATE",
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
    disposition = load_v2_disposition()
    validate_v2_result_artifact()
    if contract["heritage"]["v2_disposition_sha256"] != disposition["disposition_sha256"]:
        raise ValueError("V15_V3_V2_DISPOSITION_BINDING_MISMATCH")
    v2_contract = load_v2_contract()
    if canonical_sha256(v2_contract) != contract["heritage"]["v2_feature_contract_sha256"]:
        raise ValueError("V15_V3_V2_FEATURE_CONTRACT_MISMATCH")
    if progress:
        progress("Loading immutable V11 intraday manifest...")
    manifest, intraday = load_dataset(manifest_path)
    if progress:
        progress("Loading synchronized V14 daily feature panels...")
    symbols, daily_frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V3_V14_UNIVERSE_MISMATCH")
    result = evaluate_walk_forward(
        intraday, daily_frames, contract, progress=progress
    )
    result["source_manifest_sha256"] = manifest["manifest_sha256"]
    result["contract_sha256"] = canonical_sha256(contract)
    result["v2_disposition_sha256"] = disposition["disposition_sha256"]
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    result["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    print("V15 V3 SELECTIVE INTRADAY RETURN-REGRESSION DEVELOPMENT")
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
    print(f"Trades / cash sessions: {result['completed_trades']} / {result['cash_sessions']}")
    print(f"Trade rate: {result['trade_rate']:.1%}")
    print(f"V15 V3 net return: {result['v15_net_total_return']:+.2%}")
    print(f"V11 control return: {result['v11_control_net_total_return']:+.2%}")
    print(f"V14 context control return: {result['v14_context_control_net_total_return']:+.2%}")
    print(f"SPY return: {result['spy_total_return']:+.2%}")
    print(f"Maximum drawdown: {result['v15_max_drawdown']:.2%}")
    print(f"Development gates: {'PASS' if result['development_gates_passed'] else 'FAIL'}")
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO | fresh paper boundary still required")
    print("Existing models modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
