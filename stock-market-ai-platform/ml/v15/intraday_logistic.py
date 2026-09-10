"""Leakage-safe V15 intraday logistic walk-forward development evaluation.

V15 combines V11's completed five-minute feature/timing contract with V14's
pooled logistic-regression methodology.  It reads the immutable V11 historical
dataset, publishes development evidence under a V15-only root, and has no
brokerage or existing-model write path.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from ml.v11.intraday_contract import derive_features


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_logistic_contract.json")
MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v15/intraday_logistic/latest_results.json"

FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "vwap_distance",
    "volume_acceleration",
    "realized_volatility_30m",
    "opening_gap",
)
NEW_YORK = ZoneInfo("America/New_York")
EXPECTED_CONTRACT_SHA256 = (
    "054953ddda9af67e536da0632d52439a8230e8819e1cbf3f1deb5f33361115af"
)
V11_BALANCED_WEIGHTS = {
    "return_5m": 1.0,
    "return_15m": 1.0,
    "vwap_distance": 1.0,
    "volume_acceleration": 1.0,
    "realized_volatility_30m": -0.25,
    "opening_gap": 1.0,
}


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        failures.append("V15_CONTRACT_SHA_MISMATCH")
    if contract.get("classification") != (
        "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    ):
        failures.append("V15_CLASSIFICATION_INVALID")
    data = contract.get("data", {})
    model = contract.get("model", {})
    portfolio = contract.get("portfolio", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if data.get("bar_interval_minutes") != 5:
        failures.append("V15_BAR_INTERVAL_INVALID")
    if data.get("decision_time_eastern") != "10:00":
        failures.append("V15_DECISION_TIME_INVALID")
    if tuple(model.get("features", ())) != FEATURE_NAMES:
        failures.append("V15_FEATURE_SET_INVALID")
    if model.get("target") != "positive_cost_adjusted_relative_return_30m":
        failures.append("V15_TARGET_INVALID")
    if int(model.get("purge_gap_sessions", 0)) < 1:
        failures.append("V15_PURGE_GAP_MISSING")
    if portfolio.get("entry") != "NEXT_5MIN_BAR_OPEN":
        failures.append("V15_ENTRY_INVALID")
    if int(portfolio.get("holding_bars", 0)) != 6:
        failures.append("V15_HOLDING_WINDOW_INVALID")
    if evaluation.get("future_data_in_training") is not False:
        failures.append("V15_FUTURE_TRAINING_PROHIBITION_MISSING")
    if evaluation.get("selection_on_test_data") is not False:
        failures.append("V15_TEST_SELECTION_PROHIBITION_MISSING")
    required_false = (
        "live_trading_enabled",
        "brokerage_orders",
        "scheduler_installation_allowed",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        failures.append("V15_AUTHORITY_INVALID")
    if authority.get("development_only") is not True:
        failures.append("V15_DEVELOPMENT_BOUNDARY_MISSING")
    if failures:
        raise ValueError(";".join(failures))
    return contract


def _group_sessions(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        stamp = datetime.fromisoformat(
            str(row["timestamp_utc"]).replace("Z", "+00:00")
        ).astimezone(NEW_YORK)
        grouped.setdefault(stamp.date().isoformat(), []).append(dict(row))
    for values in grouped.values():
        values.sort(key=lambda row: str(row["timestamp_utc"]))
    return grouped


def load_dataset(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unsigned = dict(manifest)
    expected_sha = unsigned.pop("manifest_sha256", None)
    if expected_sha != canonical_sha256(unsigned):
        raise ValueError("V15_SOURCE_MANIFEST_SHA_MISMATCH")
    if manifest.get("status") != "COMPLETE_HISTORICAL_RESEARCH_DATASET":
        raise ValueError("V15_SOURCE_DATASET_INCOMPLETE")
    symbols = list(manifest.get("symbols") or [])
    if len(symbols) != 101 or len(set(symbols)) != 101 or "SPY" not in symbols:
        raise ValueError("V15_SOURCE_UNIVERSE_INVALID")
    metadata = manifest.get("symbol_metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("V15_SOURCE_METADATA_INVALID")
    dataset: dict[str, list[dict[str, object]]] = {}
    for symbol in symbols:
        item = metadata.get(symbol)
        if not isinstance(item, Mapping):
            raise ValueError(f"V15_SOURCE_SYMBOL_METADATA_MISSING:{symbol}")
        path = manifest_path.parent / str(item["file"])
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or item.get("sha256") != canonical_sha256(rows):
            raise ValueError(f"V15_SOURCE_SYMBOL_SHA_MISMATCH:{symbol}")
        dataset[symbol] = rows
    return manifest, dataset


@dataclass
class LogisticRegression:
    learning_rate: float
    epochs: int
    l2: float
    weights: np.ndarray | None = None
    bias: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegression":
        matrix = np.asarray(X, dtype=float)
        labels = np.asarray(y, dtype=float)
        if (
            matrix.ndim != 2
            or labels.ndim != 1
            or len(matrix) != len(labels)
            or len(matrix) == 0
            or not np.isfinite(matrix).all()
            or not np.isfinite(labels).all()
            or set(np.unique(labels)) - {0.0, 1.0}
            or len(np.unique(labels)) < 2
        ):
            raise ValueError("V15_TRAINING_MATRIX_INVALID")
        self.weights = np.zeros(matrix.shape[1], dtype=float)
        self.bias = 0.0
        for _ in range(int(self.epochs)):
            logits = np.clip(matrix @ self.weights + self.bias, -35.0, 35.0)
            probabilities = 1.0 / (1.0 + np.exp(-logits))
            error = probabilities - labels
            gradient = matrix.T @ error / len(matrix) + self.l2 * self.weights
            self.weights -= self.learning_rate * gradient
            self.bias -= self.learning_rate * float(error.mean())
        return self

    def predict_probability(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise ValueError("V15_MODEL_NOT_FITTED")
        logits = np.clip(np.asarray(X, dtype=float) @ self.weights + self.bias, -35.0, 35.0)
        return 1.0 / (1.0 + np.exp(-logits))


def _zscore(values: Mapping[str, float]) -> dict[str, float]:
    center = statistics.fmean(values.values())
    spread = statistics.pstdev(values.values())
    if spread <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (float(value) - center) / spread for symbol, value in values.items()}


def _session_rows(
    session: str,
    previous_session: str,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    contract: Mapping[str, object],
) -> list[dict[str, object]] | None:
    candidates = sorted(symbol for symbol in grouped if symbol != "SPY")
    symbols = candidates + ["SPY"]
    if len(candidates) != int(contract["data"]["candidate_symbols"]):
        raise ValueError("V15_CANDIDATE_UNIVERSE_INVALID")
    decision_index = int(contract["data"]["decision_bar_index"])
    holding = int(contract["portfolio"]["holding_bars"])
    entry_index = decision_index + 1
    exit_index = decision_index + holding
    for symbol in symbols:
        current = grouped[symbol].get(session)
        previous = grouped[symbol].get(previous_session)
        if current is None or previous is None or len(current) <= exit_index:
            return None

    raw: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        try:
            features = derive_features(
                grouped[symbol][session][: decision_index + 1],
                previous_close=float(grouped[symbol][previous_session][-1]["close"]),
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
        raw[symbol] = {
            name: float(getattr(features, name)) for name in FEATURE_NAMES
        }

    relative = {
        symbol: {
            name: (
                raw[symbol][name]
                if name == "realized_volatility_30m"
                else raw[symbol][name] - raw["SPY"][name]
            )
            for name in FEATURE_NAMES
        }
        for symbol in candidates
    }
    standardized = {
        name: _zscore({symbol: relative[symbol][name] for symbol in candidates})
        for name in FEATURE_NAMES
    }
    spy_bars = grouped["SPY"][session]
    spy_return = (
        float(spy_bars[exit_index]["close"])
        / float(spy_bars[entry_index]["open"])
        - 1.0
    )
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    rows: list[dict[str, object]] = []
    for symbol in candidates:
        bars = grouped[symbol][session]
        gross = float(bars[exit_index]["close"]) / float(bars[entry_index]["open"]) - 1.0
        features = [standardized[name][symbol] for name in FEATURE_NAMES]
        rows.append(
            {
                "session": session,
                "symbol": symbol,
                "features": features,
                "gross_return": gross,
                "spy_return": spy_return,
                "net_relative_return": gross - cost - spy_return,
                "label": int(gross - cost - spy_return > 0.0),
                "v11_score": statistics.fmean(
                    standardized[name][symbol] * V11_BALANCED_WEIGHTS[name]
                    for name in FEATURE_NAMES
                ),
            }
        )
    return rows


def build_examples(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> tuple[list[str], dict[str, list[dict[str, object]]]]:
    if (
        "SPY" not in dataset
        or len(dataset) != int(contract["data"]["required_universe_symbols"])
    ):
        raise ValueError("V15_UNIVERSE_INCOMPLETE")
    grouped = {symbol: _group_sessions(rows) for symbol, rows in dataset.items()}
    common = sorted(set.intersection(*(set(values) for values in grouped.values())))
    examples: dict[str, list[dict[str, object]]] = {}
    for index in range(1, len(common)):
        rows = _session_rows(common[index], common[index - 1], grouped, contract)
        if rows is not None:
            examples[common[index]] = rows
    return sorted(examples), examples


def _growth(returns: Sequence[float]) -> float:
    return math.prod(1.0 + float(value) for value in returns) - 1.0


def evaluate_walk_forward(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> dict[str, object]:
    sessions, by_session = build_examples(dataset, contract)
    model_spec = contract["model"]
    evaluation = contract["evaluation"]
    minimum_train = int(model_spec["minimum_training_sessions"])
    minimum_final = int(evaluation["minimum_final_test_sessions"])
    fold_size = int(evaluation["test_sessions_per_fold"])
    if len(sessions) < minimum_train + minimum_final:
        raise ValueError(f"V15_INSUFFICIENT_SESSIONS:{len(sessions)}")

    observations: list[dict[str, object]] = []
    folds: list[dict[str, object]] = []
    purge_gap = int(model_spec["purge_gap_sessions"])
    cursor = minimum_train + purge_gap - 1
    fold_number = 1
    top_n = int(contract["portfolio"]["top_n"])
    cost = float(contract["portfolio"]["modeled_total_cost_bps_round_trip"]) / 10000.0
    while cursor < len(sessions):
        remaining = len(sessions) - cursor
        if remaining < minimum_final:
            break
        test_sessions = sessions[cursor : cursor + min(fold_size, remaining)]
        training_stop = cursor - purge_gap + 1
        training_sessions = sessions[:training_stop]
        training_rows = [row for session in training_sessions for row in by_session[session]]
        if len(training_rows) < int(model_spec["minimum_training_rows"]):
            raise ValueError(
                f"V15_TRAINING_ROWS_BELOW_MINIMUM:{len(training_rows)}"
            )
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
        snapshot = {
            "feature_names": list(FEATURE_NAMES),
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
        fold_observations: list[dict[str, object]] = []
        for session in test_sessions:
            current = by_session[session]
            current_X = np.asarray([row["features"] for row in current], dtype=float)
            probabilities = model.predict_probability((current_X - mean) / std)
            ranked = sorted(
                zip(current, probabilities),
                key=lambda item: (-float(item[1]), str(item[0]["symbol"])),
            )
            selected = ranked[:top_n]
            v11_selected = sorted(
                current,
                key=lambda row: (-float(row["v11_score"]), str(row["symbol"])),
            )[:top_n]
            gross = statistics.fmean(float(row["gross_return"]) for row, _ in selected)
            spy_return = float(current[0]["spy_return"])
            v15_net = gross - cost
            v11_net = (
                statistics.fmean(float(row["gross_return"]) for row in v11_selected)
                - cost
            )
            observation = {
                "session": session,
                "training_cutoff_session": training_sessions[-1],
                "model_sha256": model_sha,
                "selected_symbols": [str(row["symbol"]) for row, _ in selected],
                "selected_probabilities": {
                    str(row["symbol"]): float(probability)
                    for row, probability in selected
                },
                "v15_net_return": v15_net,
                "v11_control_net_return": v11_net,
                "spy_return": spy_return,
                "v15_minus_v11": v15_net - v11_net,
                "v15_minus_spy": v15_net - spy_return,
            }
            observations.append(observation)
            fold_observations.append(observation)
        folds.append(
            {
                "fold": fold_number,
                "training_start_session": training_sessions[0],
                "training_cutoff_session": training_sessions[-1],
                "training_sessions": len(training_sessions),
                "training_rows": len(training_rows),
                "test_start_session": test_sessions[0],
                "test_end_session": test_sessions[-1],
                "test_sessions": len(test_sessions),
                "model_sha256": model_sha,
                "mean_v15_minus_v11": statistics.fmean(
                    float(row["v15_minus_v11"]) for row in fold_observations
                ),
                "mean_v15_minus_spy": statistics.fmean(
                    float(row["v15_minus_spy"]) for row in fold_observations
                ),
            }
        )
        cursor += len(test_sessions)
        fold_number += 1

    if not observations:
        raise ValueError("V15_NO_WALK_FORWARD_OBSERVATIONS")
    v15_return = _growth([float(row["v15_net_return"]) for row in observations])
    v11_return = _growth([float(row["v11_control_net_return"]) for row in observations])
    spy_return = _growth([float(row["spy_return"]) for row in observations])
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "candidate_id": contract["candidate_id"],
        "classification": contract["classification"],
        "status": "V15_WALK_FORWARD_DEVELOPMENT_EVIDENCE",
        "model_frozen": False,
        "eligible_sessions": len(sessions),
        "fold_count": len(folds),
        "test_sessions": len(observations),
        "folds": folds,
        "test_observations": observations,
        "v15_net_total_return": v15_return,
        "v11_control_net_total_return": v11_return,
        "spy_total_return": spy_return,
        "v15_relative_to_v11": (1.0 + v15_return) / (1.0 + v11_return) - 1.0,
        "v15_relative_to_spy": (1.0 + v15_return) / (1.0 + spy_return) - 1.0,
        "v15_v11_win_rate": statistics.fmean(
            float(row["v15_minus_v11"] > 0.0) for row in observations
        ),
        "v15_spy_win_rate": statistics.fmean(
            float(row["v15_minus_spy"] > 0.0) for row in observations
        ),
        "selection_on_test_data": False,
        "paper_trading_only": True,
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
    manifest, dataset = load_dataset(manifest_path)
    result = evaluate_walk_forward(dataset, contract)
    result["source_manifest_sha256"] = manifest["manifest_sha256"]
    result["contract_sha256"] = canonical_sha256(contract)
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    result["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    print("V15 INTRADAY LOGISTIC WALK-FORWARD DEVELOPMENT")
    print("=" * 80)
    try:
        result = run()
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Model frozen: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Eligible sessions: {result['eligible_sessions']}")
    print(f"Walk-forward folds: {result['fold_count']}")
    print(f"Out-of-sample sessions: {result['test_sessions']}")
    print(f"V15 net return: {result['v15_net_total_return']:+.2%}")
    print(f"V11 control return: {result['v11_control_net_total_return']:+.2%}")
    print(f"SPY return: {result['spy_total_return']:+.2%}")
    print(f"V15 relative to V11: {result['v15_relative_to_v11']:+.2%}")
    print(f"V15 relative to SPY: {result['v15_relative_to_spy']:+.2%}")
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO | development evidence only")
    print("Existing models modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
