"""Time-ordered walk-forward evaluation for V11 intraday research.

Configuration selection occurs exclusively on earlier training sessions. Each
selected configuration is then evaluated on the immediately following test
sessions. Results are development evidence only and grant no trading authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v11.intraday_contract import derive_features

ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))
from v5_symbols import get_v5_data_symbols, get_v5_symbols  # noqa: E402

NEW_YORK = ZoneInfo("America/New_York")
MANIFEST_PATH = ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
CONTRACT_PATH = Path(__file__).with_name("intraday_walk_forward_contract.json")
OUTPUT_PATH = ROOT / "data/research/v11/intraday/walk_forward/latest_results.json"
FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "vwap_distance",
    "volume_acceleration",
    "realized_volatility_30m",
    "opening_gap",
)


@dataclass(frozen=True)
class Configuration:
    config_id: str
    holding_bars: int
    weights: Mapping[str, float]


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("status") != "PREREGISTERED_DEVELOPMENT_EVALUATION":
        raise ValueError("WALK_FORWARD_CONTRACT_INVALID")
    if contract.get("selection_on_test_data") is not False:
        raise ValueError("TEST_SELECTION_PROHIBITION_MISSING")
    return contract


def load_dataset(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_copy = dict(manifest)
    expected_manifest_sha = manifest_copy.pop("manifest_sha256", None)
    if expected_manifest_sha != _sha(manifest_copy):
        raise ValueError("MANIFEST_SHA_MISMATCH")
    if manifest.get("status") != "COMPLETE_HISTORICAL_RESEARCH_DATASET":
        raise ValueError("HISTORICAL_DATASET_NOT_COMPLETE")
    if manifest.get("symbol_count") != 101:
        raise ValueError("HISTORICAL_UNIVERSE_INCOMPLETE")

    dataset: dict[str, list[dict[str, object]]] = {}
    for symbol in get_v5_data_symbols():
        metadata = manifest["symbol_metadata"].get(symbol)
        if not isinstance(metadata, dict):
            raise ValueError(f"SYMBOL_METADATA_MISSING:{symbol}")
        path = manifest_path.parent / str(metadata["file"])
        rows = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("sha256") != _sha(rows):
            raise ValueError(f"SYMBOL_SHA_MISMATCH:{symbol}")
        dataset[symbol] = rows
    return manifest, dataset


def _group_sessions(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        stamp = datetime.fromisoformat(str(row["timestamp_utc"])).astimezone(NEW_YORK)
        grouped.setdefault(stamp.date().isoformat(), []).append(dict(row))
    for values in grouped.values():
        values.sort(key=lambda row: str(row["timestamp_utc"]))
    return grouped


def _zscore(values: Mapping[str, float]) -> dict[str, float]:
    center = statistics.fmean(values.values())
    spread = statistics.pstdev(values.values())
    if spread <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (value - center) / spread for symbol, value in values.items()}


def _session_observation(
    session: str,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    previous_session: str,
    config: Configuration,
    *,
    decision_bar_index: int,
    top_n: int,
    total_cost_bps: float,
) -> dict[str, object] | None:
    candidates = get_v5_symbols()
    symbols = get_v5_data_symbols()
    exit_index = decision_bar_index + config.holding_bars
    for symbol in symbols:
        current = grouped[symbol].get(session)
        previous = grouped[symbol].get(previous_session)
        if current is None or previous is None or len(current) <= exit_index:
            return None

    raw_features: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        current = grouped[symbol][session]
        previous = grouped[symbol][previous_session]
        values = derive_features(
            current[: decision_bar_index + 1],
            previous_close=float(previous[-1]["close"]),
        )
        raw_features[symbol] = {
            name: float(getattr(values, name)) for name in FEATURE_NAMES
        }

    spy = raw_features["SPY"]
    relative: dict[str, dict[str, float]] = {}
    for symbol in candidates:
        relative[symbol] = {
            name: (
                raw_features[symbol][name]
                if name == "realized_volatility_30m"
                else raw_features[symbol][name] - spy[name]
            )
            for name in FEATURE_NAMES
        }
    standardized = {
        name: _zscore({symbol: relative[symbol][name] for symbol in candidates})
        for name in FEATURE_NAMES
    }
    scores = {
        symbol: statistics.fmean(
            standardized[name][symbol] * float(config.weights[name])
            for name in FEATURE_NAMES
        )
        for symbol in candidates
    }
    selected = sorted(candidates, key=lambda symbol: (-scores[symbol], symbol))[:top_n]

    gross_returns = []
    for symbol in selected:
        bars = grouped[symbol][session]
        entry = float(bars[decision_bar_index + 1]["open"])
        exit_price = float(bars[exit_index]["close"])
        gross_returns.append(exit_price / entry - 1.0)
    strategy_gross = statistics.fmean(gross_returns)
    strategy_net = strategy_gross - total_cost_bps / 10000.0

    spy_bars = grouped["SPY"][session]
    spy_entry = float(spy_bars[decision_bar_index + 1]["open"])
    spy_exit = float(spy_bars[exit_index]["close"])
    spy_return = spy_exit / spy_entry - 1.0
    return {
        "session": session,
        "config_id": config.config_id,
        "holding_bars": config.holding_bars,
        "selected": selected,
        "strategy_gross_return": strategy_gross,
        "strategy_net_return": strategy_net,
        "spy_return": spy_return,
        "net_excess_return": strategy_net - spy_return,
    }


def _mean_excess(observations: Sequence[Mapping[str, object]]) -> float:
    return statistics.fmean(float(row["net_excess_return"]) for row in observations)


def evaluate_walk_forward(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> dict[str, object]:
    grouped = {symbol: _group_sessions(rows) for symbol, rows in dataset.items()}
    common = sorted(set.intersection(*(set(grouped[symbol]) for symbol in get_v5_data_symbols())))
    if len(common) < 2:
        raise ValueError("INSUFFICIENT_COMMON_SESSIONS")

    configurations = [
        Configuration(
            config_id=str(item["config_id"]),
            holding_bars=int(item["holding_bars"]),
            weights={name: float(item["weights"][name]) for name in FEATURE_NAMES},
        )
        for item in contract["candidate_configurations"]
    ]
    decision_index = int(contract["decision_bar_index"])
    top_n = int(contract["top_n"])
    total_cost = float(contract["modeled_total_cost_bps_round_trip"])
    observations: dict[str, list[dict[str, object]]] = {config.config_id: [] for config in configurations}
    eligible_sessions: list[str] = []
    for index in range(1, len(common)):
        session = common[index]
        prior = common[index - 1]
        complete = True
        session_rows: dict[str, dict[str, object]] = {}
        for config in configurations:
            row = _session_observation(
                session,
                grouped,
                prior,
                config,
                decision_bar_index=decision_index,
                top_n=top_n,
                total_cost_bps=total_cost,
            )
            if row is None:
                complete = False
                break
            session_rows[config.config_id] = row
        if complete:
            eligible_sessions.append(session)
            for config_id, row in session_rows.items():
                observations[config_id].append(row)

    minimum_train = int(contract["minimum_train_sessions"])
    test_size = int(contract["test_sessions_per_fold"])
    minimum_final = int(contract["minimum_final_test_sessions"])
    if len(eligible_sessions) < minimum_train + minimum_final:
        raise ValueError(
            f"INSUFFICIENT_WALK_FORWARD_SESSIONS:{len(eligible_sessions)}"
        )

    by_config_session = {
        config_id: {str(row["session"]): row for row in rows}
        for config_id, rows in observations.items()
    }
    folds = []
    test_observations = []
    cursor = minimum_train
    fold_number = 1
    while cursor < len(eligible_sessions):
        remaining = len(eligible_sessions) - cursor
        if remaining < minimum_final:
            break
        fold_test_size = min(test_size, remaining)
        train_sessions = eligible_sessions[:cursor]
        test_sessions = eligible_sessions[cursor : cursor + fold_test_size]
        train_scores = {
            config.config_id: _mean_excess(
                [by_config_session[config.config_id][session] for session in train_sessions]
            )
            for config in configurations
        }
        selected_config = sorted(
            train_scores,
            key=lambda config_id: (-train_scores[config_id], config_id),
        )[0]
        selected_test = [
            by_config_session[selected_config][session] for session in test_sessions
        ]
        folds.append(
            {
                "fold": fold_number,
                "train_start": train_sessions[0],
                "train_end": train_sessions[-1],
                "train_sessions": len(train_sessions),
                "test_start": test_sessions[0],
                "test_end": test_sessions[-1],
                "test_sessions": len(test_sessions),
                "selected_config": selected_config,
                "train_mean_net_excess": train_scores[selected_config],
                "all_train_scores": train_scores,
                "test_mean_net_excess": _mean_excess(selected_test),
            }
        )
        test_observations.extend(selected_test)
        cursor += fold_test_size
        fold_number += 1

    if not test_observations:
        raise ValueError("NO_WALK_FORWARD_TEST_OBSERVATIONS")
    strategy_growth = math.prod(1.0 + float(row["strategy_net_return"]) for row in test_observations)
    spy_growth = math.prod(1.0 + float(row["spy_return"]) for row in test_observations)
    hit_rate = statistics.fmean(
        1.0 if float(row["net_excess_return"]) > 0 else 0.0
        for row in test_observations
    )
    result: dict[str, object] = {
        "contract_id": contract["contract_id"],
        "status": "WALK_FORWARD_DEVELOPMENT_EVIDENCE",
        "model_frozen": False,
        "selection_on_test_data": False,
        "eligible_sessions": len(eligible_sessions),
        "fold_count": len(folds),
        "test_observations": len(test_observations),
        "folds": folds,
        "test_results": test_observations,
        "strategy_net_total_return": strategy_growth - 1.0,
        "spy_total_return": spy_growth - 1.0,
        "net_relative_total_return": strategy_growth / spy_growth - 1.0,
        "net_excess_hit_rate": hit_rate,
        "modeled_total_cost_bps_round_trip": total_cost,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    result["result_sha256"] = _sha(result)
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
    result["evaluation_contract_sha256"] = _sha(contract)
    result_without_sha = dict(result)
    result_without_sha.pop("result_sha256", None)
    result["result_sha256"] = _sha(result_without_sha)
    _atomic_write(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print("V11 INTRADAY WALK-FORWARD DEVELOPMENT EVALUATION")
    print("=" * 80)
    result = run()
    print(f"Status: {result['status']}")
    print(f"Eligible sessions: {result['eligible_sessions']}")
    print(f"Walk-forward folds: {result['fold_count']}")
    print(f"Out-of-sample observations: {result['test_observations']}")
    print(f"V11 net return: {result['strategy_net_total_return']:+.2%}")
    print(f"SPY return: {result['spy_total_return']:+.2%}")
    print(f"Net relative return: {result['net_relative_total_return']:+.2%}")
    print(f"Excess hit rate: {result['net_excess_hit_rate']:.1%}")
    for fold in result["folds"]:
        print(
            f"Fold {fold['fold']}: {fold['selected_config']} | "
            f"train={fold['train_sessions']} test={fold['test_sessions']} | "
            f"test excess={fold['test_mean_net_excess']:+.4%}"
        )
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Model frozen: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
