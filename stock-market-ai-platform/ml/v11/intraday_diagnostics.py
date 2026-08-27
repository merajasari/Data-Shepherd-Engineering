"""Post-hoc diagnostics for the rejected V11 intraday baseline.

This module explains an already-observed development result. It cannot select,
freeze, authorize, or trade a replacement strategy.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from ml.v11.intraday_walk_forward import (
    CONTRACT_PATH,
    MANIFEST_PATH,
    OUTPUT_PATH as WALK_FORWARD_PATH,
    Configuration,
    _atomic_write,
    _group_sessions,
    _session_observation,
    _sha,
    load_contract,
    load_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTIC_PATH = ROOT / "data/research/v11/intraday/walk_forward/rejection_diagnostics.json"


def _verify_result(path: Path) -> dict[str, object]:
    result = json.loads(path.read_text(encoding="utf-8"))
    copy = dict(result)
    expected = copy.pop("result_sha256", None)
    if expected != _sha(copy):
        raise ValueError("WALK_FORWARD_RESULT_SHA_MISMATCH")
    if result.get("status") != "WALK_FORWARD_DEVELOPMENT_EVIDENCE":
        raise ValueError("WALK_FORWARD_RESULT_STATUS_INVALID")
    if result.get("model_frozen") is not False:
        raise ValueError("REJECTED_BASELINE_MUST_NOT_BE_FROZEN")
    return result


def _total_return(rows: Sequence[Mapping[str, object]], field: str) -> float:
    return math.prod(1.0 + float(row[field]) for row in rows) - 1.0


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def build_diagnostics(
    *,
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
    result: Mapping[str, object],
) -> dict[str, object]:
    grouped = {symbol: _group_sessions(rows) for symbol, rows in dataset.items()}
    common = sorted(set.intersection(*(set(grouped[symbol]) for symbol in grouped)))
    previous = {common[index]: common[index - 1] for index in range(1, len(common))}
    test_sessions = [str(row["session"]) for row in result["test_results"]]
    unique_test_sessions = list(dict.fromkeys(test_sessions))

    configurations = [
        Configuration(
            config_id=str(item["config_id"]),
            holding_bars=int(item["holding_bars"]),
            weights={name: float(value) for name, value in item["weights"].items()},
        )
        for item in contract["candidate_configurations"]
    ]
    decision_index = int(contract["decision_bar_index"])
    top_n = int(contract["top_n"])
    total_cost = float(contract["modeled_total_cost_bps_round_trip"])
    fee_bps = float(contract["modeled_fees_bps_round_trip"])
    slippage_bps = float(contract["modeled_slippage_bps_round_trip"])

    config_diagnostics = []
    for config in configurations:
        rows = []
        for session in unique_test_sessions:
            row = _session_observation(
                session,
                grouped,
                previous[session],
                config,
                decision_bar_index=decision_index,
                top_n=top_n,
                total_cost_bps=total_cost,
            )
            if row is not None:
                rows.append(row)
        gross_total = _total_return(rows, "strategy_gross_return")
        fees_only_total = math.prod(
            1.0 + float(row["strategy_gross_return"]) - fee_bps / 10000.0
            for row in rows
        ) - 1.0
        net_total = _total_return(rows, "strategy_net_return")
        spy_total = _total_return(rows, "spy_return")
        config_diagnostics.append(
            {
                "config_id": config.config_id,
                "holding_bars": config.holding_bars,
                "observations": len(rows),
                "gross_total_return": gross_total,
                "fees_only_total_return": fees_only_total,
                "net_total_return": net_total,
                "spy_total_return": spy_total,
                "net_relative_total_return": (1.0 + net_total) / (1.0 + spy_total) - 1.0,
                "gross_to_net_cost_drag": gross_total - net_total,
                "excess_hit_rate": _mean(
                    [1.0 if float(row["net_excess_return"]) > 0 else 0.0 for row in rows]
                ),
                "post_hoc_comparison_only": True,
            }
        )

    selected_rows = list(result["test_results"])
    gross_total = _total_return(selected_rows, "strategy_gross_return")
    fees_only_total = math.prod(
        1.0 + float(row["strategy_gross_return"]) - fee_bps / 10000.0
        for row in selected_rows
    ) - 1.0
    net_total = _total_return(selected_rows, "strategy_net_return")

    stock_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"selections": 0.0, "gross_sum": 0.0, "net_contribution_sum": 0.0}
    )
    selection_frequency: Counter[str] = Counter()
    for row in selected_rows:
        session = str(row["session"])
        config_id = str(row["config_id"])
        config = next(item for item in configurations if item.config_id == config_id)
        for symbol in row["selected"]:
            bars = grouped[str(symbol)][session]
            entry = float(bars[decision_index + 1]["open"])
            exit_price = float(bars[decision_index + config.holding_bars]["close"])
            gross = exit_price / entry - 1.0
            selection_frequency[str(symbol)] += 1
            stock_stats[str(symbol)]["selections"] += 1
            stock_stats[str(symbol)]["gross_sum"] += gross
            stock_stats[str(symbol)]["net_contribution_sum"] += (
                gross - total_cost / 10000.0
            ) / top_n

    contributors = []
    for symbol, values in stock_stats.items():
        count = int(values["selections"])
        contributors.append(
            {
                "symbol": symbol,
                "selections": count,
                "mean_gross_return_when_selected": values["gross_sum"] / count,
                "arithmetic_net_contribution": values["net_contribution_sum"],
            }
        )
    contributors.sort(key=lambda row: (row["arithmetic_net_contribution"], row["symbol"]))

    regime_values: dict[str, list[float]] = defaultdict(list)
    for row in selected_rows:
        spy_return = float(row["spy_return"])
        regime = "SPY_POSITIVE" if spy_return > 0.001 else "SPY_NEGATIVE" if spy_return < -0.001 else "SPY_FLAT"
        regime_values[regime].append(float(row["net_excess_return"]))
    regimes = {
        regime: {
            "observations": len(values),
            "mean_net_excess_return": statistics.fmean(values),
            "excess_hit_rate": statistics.fmean(1.0 if value > 0 else 0.0 for value in values),
        }
        for regime, values in sorted(regime_values.items())
    }

    payload: dict[str, object] = {
        "diagnostic_id": "V11_INTRADAY_REJECTED_BASELINE_DIAGNOSTICS_V1",
        "status": "DEVELOPMENT_BASELINE_REJECTED",
        "source_result_sha256": result["result_sha256"],
        "post_hoc": True,
        "eligible_for_model_selection": False,
        "model_frozen": False,
        "test_observations": len(selected_rows),
        "selected_path_cost_attribution": {
            "gross_total_return": gross_total,
            "fees_only_total_return": fees_only_total,
            "net_total_return": net_total,
            "modeled_fees_bps_round_trip": fee_bps,
            "modeled_slippage_bps_round_trip": slippage_bps,
            "modeled_total_cost_bps_round_trip": total_cost,
            "gross_to_net_cost_drag": gross_total - net_total,
        },
        "configuration_comparison": config_diagnostics,
        "market_regimes": regimes,
        "worst_contributors": contributors[:15],
        "best_contributors": list(reversed(contributors[-15:])),
        "most_frequently_selected": [
            {"symbol": symbol, "selections": count}
            for symbol, count in selection_frequency.most_common(15)
        ],
        "interpretation_boundary": (
            "Post-hoc diagnostics explain the rejected baseline only. They may generate "
            "new hypotheses but cannot select, freeze, or authorize a strategy."
        ),
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    payload["diagnostic_sha256"] = _sha(payload)
    return payload


def run(
    *,
    manifest_path: Path = MANIFEST_PATH,
    contract_path: Path = CONTRACT_PATH,
    result_path: Path = WALK_FORWARD_PATH,
    output_path: Path = DIAGNOSTIC_PATH,
) -> dict[str, object]:
    contract = load_contract(contract_path)
    _, dataset = load_dataset(manifest_path)
    result = _verify_result(result_path)
    payload = build_diagnostics(dataset=dataset, contract=contract, result=result)
    _atomic_write(output_path, payload)
    return payload


def main() -> None:
    print("V11 REJECTED-BASELINE DIAGNOSTICS")
    print("=" * 80)
    payload = run()
    costs = payload["selected_path_cost_attribution"]
    print(f"Status: {payload['status']}")
    print(f"Out-of-sample observations: {payload['test_observations']}")
    print(f"Gross return: {costs['gross_total_return']:+.2%}")
    print(f"Fees-only return: {costs['fees_only_total_return']:+.2%}")
    print(f"Net return: {costs['net_total_return']:+.2%}")
    print(f"Gross-to-net cost drag: {costs['gross_to_net_cost_drag']:+.2%}")
    print("Configuration comparison:")
    for row in payload["configuration_comparison"]:
        print(
            f" - {row['config_id']}: gross={row['gross_total_return']:+.2%} "
            f"net={row['net_total_return']:+.2%} "
            f"relative={row['net_relative_total_return']:+.2%} "
            f"hit={row['excess_hit_rate']:.1%}"
        )
    print("Market regimes:")
    for regime, row in payload["market_regimes"].items():
        print(
            f" - {regime}: n={row['observations']} "
            f"mean excess={row['mean_net_excess_return']:+.4%} "
            f"hit={row['excess_hit_rate']:.1%}"
        )
    print(f"Diagnostic SHA-256: {payload['diagnostic_sha256']}")
    print("Post-hoc model selection authorized: NO")
    print("Model frozen: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
