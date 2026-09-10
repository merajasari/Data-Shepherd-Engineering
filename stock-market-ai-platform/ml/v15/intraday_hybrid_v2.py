"""Leakage-safe V15 V2 hybrid intraday development evaluation.

The hybrid uses a fixed, pre-period V14 daily logistic model as slow context,
then combines its prior-close probability and daily features with V11's
completed 5-minute features.  V1's observed outcomes are explicitly classified
as development history; this module cannot create paper-forward evidence.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_logistic import (
    LogisticRegression,
    build_examples,
    canonical_sha256,
    load_dataset,
)
from ml.v15.intraday_logistic_v1_disposition import load_disposition


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_hybrid_v2_contract.json")
MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v15/intraday_hybrid_v2/latest_results.json"
EXPECTED_CONTRACT_SHA256 = (
    "e5d2799e91e8c8a826efc00d176a4561bca546d69d200fdb3343fffe1a06f4cc"
)

FAST_FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "vwap_distance",
    "volume_acceleration",
    "realized_volatility_30m",
    "opening_gap",
)
DAILY_FEATURE_NAMES = (
    "daily_return",
    "return_5d",
    "return_20d",
    "price_vs_sma_20",
    "volatility_ratio_5_20",
    "volume_ratio",
)
SLOW_FEATURE_NAMES = DAILY_FEATURE_NAMES + ("v14_daily_probability",)
INTERACTION_FEATURE_NAMES = (
    "v14_daily_probability_x_return_5m",
    "v14_daily_probability_x_return_15m",
    "return_20d_x_return_15m",
    "price_vs_sma_20_x_vwap_distance",
    "volatility_ratio_5_20_x_realized_volatility_30m",
    "volume_ratio_x_volume_acceleration",
    "daily_return_x_opening_gap",
)
HYBRID_FEATURE_NAMES = FAST_FEATURE_NAMES + SLOW_FEATURE_NAMES + INTERACTION_FEATURE_NAMES


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_V2_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_POST_V1_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    ):
        failures.append("V15_V2_CLASSIFICATION_INVALID")
    heritage = contract.get("heritage", {})
    data = contract.get("data", {})
    slow = contract.get("slow_context_model", {})
    hybrid = contract.get("hybrid_model", {})
    portfolio = contract.get("portfolio", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if heritage.get("v1_outcomes_read_before_v2_design") is not True:
        failures.append("V15_V2_V1_DISCLOSURE_MISSING")
    if heritage.get("v1_results_reused_as_fresh_evidence") is not False:
        failures.append("V15_V2_V1_EVIDENCE_BOUNDARY_INVALID")
    if data.get("daily_context_as_of") != "PRIOR_COMPLETED_SESSION_ONLY":
        failures.append("V15_V2_DAILY_CONTEXT_TIMING_INVALID")
    if data.get("current_session_daily_close_prohibited") is not True:
        failures.append("V15_V2_CURRENT_DAILY_CLOSE_PROHIBITION_MISSING")
    if int(data.get("minimum_eligible_intraday_sessions", 0)) < 252:
        failures.append("V15_V2_HISTORY_MINIMUM_TOO_SMALL")
    if tuple(slow.get("features", ())) != DAILY_FEATURE_NAMES:
        failures.append("V15_V2_SLOW_FEATURE_SET_INVALID")
    if slow.get("target") != "target_up_5d" or int(slow.get("purge_gap_sessions", 0)) != 5:
        failures.append("V15_V2_SLOW_MODEL_TIMING_INVALID")
    if slow.get("frozen_during_v2_evaluation") is not True:
        failures.append("V15_V2_SLOW_MODEL_NOT_FIXED")
    if tuple(hybrid.get("fast_features", ())) != FAST_FEATURE_NAMES:
        failures.append("V15_V2_FAST_FEATURE_SET_INVALID")
    if tuple(hybrid.get("slow_features", ())) != SLOW_FEATURE_NAMES:
        failures.append("V15_V2_SLOW_INPUT_SET_INVALID")
    if tuple(hybrid.get("interaction_features", ())) != INTERACTION_FEATURE_NAMES:
        failures.append("V15_V2_INTERACTION_SET_INVALID")
    if hybrid.get("target") != "positive_cost_adjusted_relative_return_30m":
        failures.append("V15_V2_TARGET_INVALID")
    if int(hybrid.get("purge_gap_sessions", 0)) < 1:
        failures.append("V15_V2_PURGE_GAP_MISSING")
    if portfolio.get("entry") != "NEXT_5MIN_BAR_OPEN" or int(portfolio.get("holding_bars", 0)) != 6:
        failures.append("V15_V2_INTRADAY_WINDOW_INVALID")
    if evaluation.get("development_evidence_only") is not True:
        failures.append("V15_V2_DEVELOPMENT_BOUNDARY_MISSING")
    if evaluation.get("use_all_remaining_sessions_after_minimum_is_met") is not True:
        failures.append("V15_V2_COMPLETE_OOS_WINDOW_MISSING")
    if evaluation.get("fresh_paper_boundary_required_after_development") is not True:
        failures.append("V15_V2_FRESH_BOUNDARY_MISSING")
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
        failures.append("V15_V2_AUTHORITY_INVALID")
    if authority.get("development_only") is not True or authority.get("human_review_required") is not True:
        failures.append("V15_V2_REVIEW_BOUNDARY_INVALID")
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


def _zscore(values: Mapping[str, float]) -> dict[str, float]:
    center = statistics.fmean(values.values())
    spread = statistics.pstdev(values.values())
    if spread <= 0.0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (float(value) - center) / spread for symbol, value in values.items()}


def _daily_rows(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    data = frame.reset_index().copy()
    timestamp_name = "timestamp_utc" if "timestamp_utc" in data.columns else data.columns[0]
    data[timestamp_name] = pd.to_datetime(data[timestamp_name], utc=True)
    data = data.sort_values(timestamp_name).drop_duplicates(timestamp_name, keep="last")
    result: dict[str, dict[str, float]] = {}
    for row in data.to_dict("records"):
        session = pd.Timestamp(row[timestamp_name]).date().isoformat()
        values: dict[str, float] = {}
        for name in (*DAILY_FEATURE_NAMES, "target_up_5d"):
            try:
                values[name] = float(row[name])
            except (KeyError, TypeError, ValueError):
                values[name] = math.nan
        result[session] = values
    return result


def _pretrain_daily_context(
    daily_frames: Mapping[str, pd.DataFrame],
    candidate_symbols: Sequence[str],
    first_intraday_session: str,
    contract: Mapping[str, object],
) -> tuple[LogisticRegression, np.ndarray, np.ndarray, dict[str, object], dict[str, dict[str, dict[str, float]]]]:
    slow = contract["slow_context_model"]
    mapped = {symbol: _daily_rows(daily_frames[symbol]) for symbol in candidate_symbols}
    common = sorted(set.intersection(*(set(rows) for rows in mapped.values())))
    prior = [session for session in common if session < first_intraday_session]
    if not prior:
        raise ValueError(
            f"V15_V2_PRIOR_DAILY_CONTEXT_UNAVAILABLE:{first_intraday_session}"
        )
    first_context_session = prior[-1]
    context_index = common.index(first_context_session)
    purge = int(slow["purge_gap_sessions"])
    if context_index < purge:
        raise ValueError("V15_V2_DAILY_PRETRAIN_HISTORY_INSUFFICIENT")
    cutoff = common[context_index - purge]
    training_records: list[dict[str, object]] = []
    X_rows: list[list[float]] = []
    labels: list[int] = []
    for symbol in candidate_symbols:
        for session in common:
            if session > cutoff:
                break
            row = mapped[symbol][session]
            vector = [row[name] for name in DAILY_FEATURE_NAMES]
            target = row["target_up_5d"]
            if np.isfinite(vector).all() and np.isfinite(target):
                X_rows.append(vector)
                labels.append(int(target))
                training_records.append(
                    {"session": session, "symbol": symbol, "features": vector, "label": int(target)}
                )
    if len(X_rows) < int(slow["minimum_training_rows"]):
        raise ValueError(
            f"V15_V2_DAILY_TRAINING_ROWS_BELOW_MINIMUM:{len(X_rows)}"
        )
    X = np.asarray(X_rows, dtype=float)
    y = np.asarray(labels, dtype=int)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0.0] = 1.0
    model = LogisticRegression(
        learning_rate=float(slow["learning_rate"]),
        epochs=int(slow["epochs"]),
        l2=float(slow["l2"]),
    ).fit((X - mean) / std, y)
    snapshot: dict[str, object] = {
        "feature_names": list(DAILY_FEATURE_NAMES),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "weights": model.weights.tolist() if model.weights is not None else [],
        "bias": model.bias,
        "training_start_session": min(record["session"] for record in training_records),
        "training_cutoff_session": cutoff,
        "first_intraday_session": first_intraday_session,
        "first_daily_context_session": first_context_session,
        "training_rows": len(training_records),
        "training_data_sha256": canonical_sha256(training_records),
        "frozen_during_v2_evaluation": True,
    }
    snapshot["model_sha256"] = canonical_sha256(snapshot)
    return model, mean, std, snapshot, mapped


def _daily_context_for_session(
    session: str,
    symbols: Sequence[str],
    mapped: Mapping[str, Mapping[str, Mapping[str, float]]],
    model: LogisticRegression,
    mean: np.ndarray,
    std: np.ndarray,
) -> tuple[dict[str, dict[str, float]], list[dict[str, object]]]:
    raw: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        row = mapped[symbol].get(session)
        if row is None:
            raise ValueError(f"V15_V2_DAILY_CONTEXT_MISSING:{session}:{symbol}")
        vector = np.asarray([row[name] for name in DAILY_FEATURE_NAMES], dtype=float)
        if not np.isfinite(vector).all():
            raise ValueError(f"V15_V2_DAILY_CONTEXT_INVALID:{session}:{symbol}")
        raw[symbol] = dict(zip(DAILY_FEATURE_NAMES, vector.tolist()))
    matrix = np.asarray(
        [[raw[symbol][name] for name in DAILY_FEATURE_NAMES] for symbol in symbols],
        dtype=float,
    )
    probabilities = model.predict_probability((matrix - mean) / std)
    standardized = {
        name: _zscore({symbol: raw[symbol][name] for symbol in symbols})
        for name in DAILY_FEATURE_NAMES
    }
    probability_z = _zscore(dict(zip(symbols, probabilities.tolist())))
    context: dict[str, dict[str, float]] = {}
    audit: list[dict[str, object]] = []
    for symbol, probability in zip(symbols, probabilities):
        context[symbol] = {
            **{name: standardized[name][symbol] for name in DAILY_FEATURE_NAMES},
            "v14_daily_probability": probability_z[symbol],
            "v14_daily_probability_raw": float(probability),
        }
        audit.append(
            {
                "session": session,
                "symbol": symbol,
                "features": [raw[symbol][name] for name in DAILY_FEATURE_NAMES],
                "v14_daily_probability": float(probability),
            }
        )
    return context, audit


def _interactions(values: Mapping[str, float]) -> list[float]:
    return [
        values["v14_daily_probability"] * values["return_5m"],
        values["v14_daily_probability"] * values["return_15m"],
        values["return_20d"] * values["return_15m"],
        values["price_vs_sma_20"] * values["vwap_distance"],
        values["volatility_ratio_5_20"] * values["realized_volatility_30m"],
        values["volume_ratio"] * values["volume_acceleration"],
        values["daily_return"] * values["opening_gap"],
    ]


def build_hybrid_examples(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, pd.DataFrame],
    contract: Mapping[str, object],
) -> tuple[list[str], dict[str, list[dict[str, object]]], dict[str, object]]:
    base_sessions, base = build_examples(intraday_dataset, contract)
    if not base_sessions:
        raise ValueError("V15_V2_NO_INTRADAY_EXAMPLES")
    symbols = sorted(symbol for symbol in intraday_dataset if symbol != "SPY")
    if sorted(daily_frames) != sorted(symbols + ["SPY"]):
        raise ValueError("V15_V2_DAILY_UNIVERSE_MISMATCH")
    model, daily_mean, daily_std, slow_snapshot, mapped = _pretrain_daily_context(
        daily_frames, symbols, base_sessions[0], contract
    )
    common_daily = sorted(set.intersection(*(set(rows) for rows in mapped.values())))
    context_session_by_intraday: dict[str, str] = {}
    for session in base_sessions:
        prior = [daily_session for daily_session in common_daily if daily_session < session]
        if not prior:
            raise ValueError(f"V15_V2_PRIOR_DAILY_CONTEXT_UNAVAILABLE:{session}")
        context_session_by_intraday[session] = prior[-1]
    contexts: dict[str, dict[str, dict[str, float]]] = {}
    context_audit: list[dict[str, object]] = []
    for session in base_sessions:
        context_session = context_session_by_intraday[session]
        if context_session not in contexts:
            contexts[context_session], audit = _daily_context_for_session(
                context_session, symbols, mapped, model, daily_mean, daily_std
            )
            context_audit.extend(audit)
    hybrid: dict[str, list[dict[str, object]]] = {}
    for session in base_sessions:
        context_session = context_session_by_intraday[session]
        rows: list[dict[str, object]] = []
        for base_row in base[session]:
            symbol = str(base_row["symbol"])
            fast = dict(zip(FAST_FEATURE_NAMES, base_row["features"]))
            slow = contexts[context_session][symbol]
            combined = {**fast, **{name: slow[name] for name in SLOW_FEATURE_NAMES}}
            rows.append(
                {
                    **base_row,
                    "features": (
                        [combined[name] for name in FAST_FEATURE_NAMES]
                        + [combined[name] for name in SLOW_FEATURE_NAMES]
                        + _interactions(combined)
                    ),
                    "daily_context_session": context_session,
                    "v14_daily_probability": slow["v14_daily_probability_raw"],
                }
            )
        hybrid[session] = rows
    audit = {
        "slow_context_model_snapshot": slow_snapshot,
        "slow_context_model_sha256": slow_snapshot["model_sha256"],
        "daily_context_input_sha256": canonical_sha256(context_audit),
        "first_daily_context_session": min(contexts),
        "last_daily_context_session": max(contexts),
    }
    return base_sessions, hybrid, audit


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


def evaluate_walk_forward(
    intraday_dataset: Mapping[str, Sequence[Mapping[str, object]]],
    daily_frames: Mapping[str, pd.DataFrame],
    contract: Mapping[str, object],
) -> dict[str, object]:
    preliminary_sessions, _ = build_examples(intraday_dataset, contract)
    minimum_history = int(contract["data"]["minimum_eligible_intraday_sessions"])
    if len(preliminary_sessions) < minimum_history:
        raise ValueError(
            f"V15_V2_INSUFFICIENT_ELIGIBLE_SESSIONS:"
            f"{len(preliminary_sessions)}<{minimum_history}"
        )
    sessions, by_session, audit = build_hybrid_examples(
        intraday_dataset, daily_frames, contract
    )
    model_spec = contract["hybrid_model"]
    evaluation = contract["evaluation"]
    minimum_train = int(model_spec["minimum_training_sessions"])
    minimum_final = int(evaluation["minimum_final_test_sessions"])
    fold_size = int(evaluation["test_sessions_per_fold"])
    purge = int(model_spec["purge_gap_sessions"])
    cursor = minimum_train + purge - 1
    available_test_sessions = len(sessions) - cursor
    if available_test_sessions < minimum_final:
        raise ValueError(
            f"V15_V2_INSUFFICIENT_TEST_SESSIONS:"
            f"{available_test_sessions}<{minimum_final}"
        )
    folds: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    top_n = int(contract["portfolio"]["top_n"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    fold_number = 1
    while cursor < len(sessions):
        remaining = len(sessions) - cursor
        test_sessions = sessions[cursor : cursor + min(fold_size, remaining)]
        training_sessions = sessions[: cursor - purge + 1]
        training_rows = [row for session in training_sessions for row in by_session[session]]
        if len(training_rows) < int(model_spec["minimum_training_rows"]):
            raise ValueError(f"V15_V2_TRAINING_ROWS_BELOW_MINIMUM:{len(training_rows)}")
        X = np.asarray([row["features"] for row in training_rows], dtype=float)
        y = np.asarray([row["label"] for row in training_rows], dtype=int)
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0.0] = 1.0
        model = LogisticRegression(
            learning_rate=float(model_spec["learning_rate"]),
            epochs=int(model_spec["epochs"]),
            l2=float(model_spec["l2"]),
        ).fit((X - mean) / std, y)
        snapshot: dict[str, object] = {
            "feature_names": list(HYBRID_FEATURE_NAMES),
            "feature_mean": mean.tolist(),
            "feature_std": std.tolist(),
            "weights": model.weights.tolist() if model.weights is not None else [],
            "bias": model.bias,
            "training_start_session": training_sessions[0],
            "training_cutoff_session": training_sessions[-1],
            "training_sessions": len(training_sessions),
            "training_rows": len(training_rows),
        }
        model_sha = canonical_sha256(snapshot)
        fold_rows: list[dict[str, object]] = []
        for session in test_sessions:
            current = by_session[session]
            matrix = np.asarray([row["features"] for row in current], dtype=float)
            probabilities = model.predict_probability((matrix - mean) / std)
            selected = sorted(
                zip(current, probabilities),
                key=lambda item: (-float(item[1]), str(item[0]["symbol"])),
            )[:top_n]
            v11_selected = sorted(
                current,
                key=lambda row: (-float(row["v11_score"]), str(row["symbol"])),
            )[:top_n]
            v14_selected = sorted(
                current,
                key=lambda row: (-float(row["v14_daily_probability"]), str(row["symbol"])),
            )[:top_n]
            v15_net = statistics.fmean(float(row["gross_return"]) for row, _ in selected) - cost
            v11_net = statistics.fmean(float(row["gross_return"]) for row in v11_selected) - cost
            v14_net = statistics.fmean(float(row["gross_return"]) for row in v14_selected) - cost
            spy = float(current[0]["spy_return"])
            observation = {
                "session": session,
                "daily_context_session": current[0]["daily_context_session"],
                "training_cutoff_session": training_sessions[-1],
                "model_sha256": model_sha,
                "selected_symbols": [str(row["symbol"]) for row, _ in selected],
                "selected_probabilities": {
                    str(row["symbol"]): float(probability) for row, probability in selected
                },
                "v15_net_return": v15_net,
                "v11_control_net_return": v11_net,
                "v14_context_control_net_return": v14_net,
                "spy_return": spy,
                "v15_minus_v11": v15_net - v11_net,
                "v15_minus_v14_context": v15_net - v14_net,
                "v15_minus_spy": v15_net - spy,
            }
            observations.append(observation)
            fold_rows.append(observation)
        folds.append(
            {
                "fold": fold_number,
                "training_start_session": training_sessions[0],
                "training_cutoff_session": training_sessions[-1],
                "test_start_session": test_sessions[0],
                "test_end_session": test_sessions[-1],
                "test_sessions": len(test_sessions),
                "model_sha256": model_sha,
                "model_snapshot": snapshot,
                "mean_v15_minus_v11": statistics.fmean(float(row["v15_minus_v11"]) for row in fold_rows),
                "mean_v15_minus_v14_context": statistics.fmean(float(row["v15_minus_v14_context"]) for row in fold_rows),
                "mean_v15_minus_spy": statistics.fmean(float(row["v15_minus_spy"]) for row in fold_rows),
            }
        )
        cursor += len(test_sessions)
        fold_number += 1
    if not observations:
        raise ValueError("V15_V2_NO_WALK_FORWARD_OBSERVATIONS")
    v15_returns = [float(row["v15_net_return"]) for row in observations]
    v11_returns = [float(row["v11_control_net_return"]) for row in observations]
    v14_returns = [float(row["v14_context_control_net_return"]) for row in observations]
    spy_returns = [float(row["spy_return"]) for row in observations]
    totals = {
        "v15_net_total_return": _growth(v15_returns),
        "v11_control_net_total_return": _growth(v11_returns),
        "v14_context_control_net_total_return": _growth(v14_returns),
        "spy_total_return": _growth(spy_returns),
    }
    totals["v15_relative_to_v11"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["v11_control_net_total_return"]) - 1.0
    totals["v15_relative_to_v14_context"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["v14_context_control_net_total_return"]) - 1.0
    totals["v15_relative_to_spy"] = (1.0 + totals["v15_net_total_return"]) / (1.0 + totals["spy_total_return"]) - 1.0
    totals["v15_v11_win_rate"] = statistics.fmean(float(row["v15_minus_v11"] > 0.0) for row in observations)
    totals["v15_spy_win_rate"] = statistics.fmean(float(row["v15_minus_spy"] > 0.0) for row in observations)
    totals["positive_fold_share"] = statistics.fmean(float(fold["mean_v15_minus_v11"] > 0.0) for fold in folds)
    totals["v15_max_drawdown"] = _max_drawdown(v15_returns)
    totals["v11_max_drawdown"] = _max_drawdown(v11_returns)
    gates = evaluation["gates"]
    gate_results = {
        "positive_net_return": totals["v15_net_total_return"] > float(gates["v15_net_total_return_greater_than"]),
        "positive_relative_to_v11": totals["v15_relative_to_v11"] > float(gates["v15_relative_to_v11_greater_than"]),
        "positive_relative_to_v14_context": totals["v15_relative_to_v14_context"] > float(gates["v15_relative_to_v14_context_greater_than"]),
        "positive_relative_to_spy": totals["v15_relative_to_spy"] > float(gates["v15_relative_to_spy_greater_than"]),
        "v11_win_rate": totals["v15_v11_win_rate"] >= float(gates["v15_v11_win_rate_at_least"]),
        "spy_win_rate": totals["v15_spy_win_rate"] >= float(gates["v15_spy_win_rate_at_least"]),
        "fold_stability": totals["positive_fold_share"] >= float(gates["positive_fold_share_at_least"]),
        "drawdown_control": totals["v15_max_drawdown"] - totals["v11_max_drawdown"] <= float(gates["v15_drawdown_minus_v11_drawdown_at_most"]),
    }
    passed = all(gate_results.values())
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "candidate_id": contract["candidate_id"],
        "classification": contract["classification"],
        "status": "V15_V2_DEVELOPMENT_GATES_PASSED_NOT_FROZEN" if passed else "V15_V2_REJECTED_DEVELOPMENT_CANDIDATE",
        "development_gates_passed": passed,
        "model_frozen": False,
        "paper_forward_allowed": False,
        "eligible_sessions": len(sessions),
        "fold_count": len(folds),
        "test_sessions": len(observations),
        "folds": folds,
        "test_observations": observations,
        "gate_results": gate_results,
        **totals,
        **audit,
        "selection_on_test_data": False,
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
) -> dict[str, object]:
    contract = load_contract(contract_path)
    disposition = load_disposition()
    if contract["heritage"]["v1_disposition_sha256"] != disposition["disposition_sha256"]:
        raise ValueError("V15_V2_V1_DISPOSITION_BINDING_MISMATCH")
    manifest, intraday = load_dataset(manifest_path)
    preliminary_sessions, _ = build_examples(intraday, contract)
    minimum_history = int(contract["data"]["minimum_eligible_intraday_sessions"])
    if len(preliminary_sessions) < minimum_history:
        raise ValueError(
            f"V15_V2_INSUFFICIENT_ELIGIBLE_SESSIONS:"
            f"{len(preliminary_sessions)}<{minimum_history}"
        )
    symbols, frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V2_V14_UNIVERSE_MISMATCH")
    result = evaluate_walk_forward(intraday, frames, contract)
    result["source_manifest_sha256"] = manifest["manifest_sha256"]
    result["contract_sha256"] = canonical_sha256(contract)
    result["v1_disposition_sha256"] = disposition["disposition_sha256"]
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    result["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    print("V15 V2 V11 + V14 INTRADAY HYBRID DEVELOPMENT")
    print("=" * 80)
    try:
        result = run()
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
    print(f"V15 V2 net return: {result['v15_net_total_return']:+.2%}")
    print(f"V11 control return: {result['v11_control_net_total_return']:+.2%}")
    print(f"V14 context control return: {result['v14_context_control_net_total_return']:+.2%}")
    print(f"SPY return: {result['spy_total_return']:+.2%}")
    print(f"Development gates: {'PASS' if result['development_gates_passed'] else 'FAIL'}")
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO | fresh paper boundary still required")
    print("Existing models modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
