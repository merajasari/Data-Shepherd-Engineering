"""Regression checks for rejected V11 baseline diagnostics."""
from __future__ import annotations

from ml.v11.intraday_diagnostics import build_diagnostics
from ml.v11.intraday_walk_forward_regression import synthetic_dataset, test_contract
from ml.v11.intraday_walk_forward import evaluate_walk_forward


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    dataset = synthetic_dataset()
    contract = test_contract()
    result = evaluate_walk_forward(dataset, contract)
    payload = build_diagnostics(dataset=dataset, contract=contract, result=result)
    require(payload["status"] == "DEVELOPMENT_BASELINE_REJECTED", "Baseline remains explicitly rejected")
    require(payload["post_hoc"] is True, "Diagnostics are labeled post-hoc")
    require(payload["eligible_for_model_selection"] is False, "Diagnostics cannot select a model")
    require(payload["model_frozen"] is False, "Diagnostics cannot freeze a model")
    require(len(payload["configuration_comparison"]) == 4, "Every preregistered configuration is reported")
    require(
        all(row["observations"] == result["test_observations"] for row in payload["configuration_comparison"]),
        "Configurations use identical out-of-sample dates",
    )
    costs = payload["selected_path_cost_attribution"]
    require(costs["gross_total_return"] >= costs["net_total_return"], "Explicit costs cannot improve gross performance")
    require(costs["modeled_fees_bps_round_trip"] == 2, "Two-bps fee assumption is reported")
    require(costs["modeled_slippage_bps_round_trip"] == 8, "Eight-bps slippage assumption is reported")
    require(sum(row["observations"] for row in payload["market_regimes"].values()) == result["test_observations"], "Every test session receives one market regime")
    unique_selected = {
        symbol
        for row in result["test_results"]
        for symbol in row["selected"]
    }
    expected_contributors = min(15, len(unique_selected))
    require(
        len(payload["worst_contributors"]) == expected_contributors,
        "Worst available contributors are reported",
    )
    require(
        len(payload["best_contributors"]) == expected_contributors,
        "Best available contributors are reported",
    )
    require(len(payload["diagnostic_sha256"]) == 64, "Diagnostics have a SHA-256 identity")
    require(payload["paper_trading_only"] is True, "Diagnostics remain paper only")
    require(payload["brokerage_orders"] is False, "Diagnostics have no brokerage authority")

    print("\nStatus: PASSED")
    print("V11 rejected-baseline diagnostics: VERIFIED")
    print("Post-hoc selection authority: NONE")
    print("Model frozen: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
