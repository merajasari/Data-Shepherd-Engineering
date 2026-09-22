"""Shared Crypto V4 Net-Edge Phase 3: cost-aware portfolio evaluation.

Uses only Phase 2 out-of-sample one-hour predictions.  It evaluates every
preregistered regime/ranking model, Top-3/Top-5 construction, and transaction
cost combination on a common hourly clock.  It also reconstructs the frozen
Shared Crypto V3 policy (the frozen V2 HGB + confirm-2 policy) and Always-BTC
on that exact clock.

This is development evidence only.  It does not score the future holdout,
select a paper candidate automatically, modify Shared Crypto V3, or place an
order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v4_net_edge"
PHASE1_CONTRACT = Path("data/model/shared_crypto_v4_net_edge/phase1/preregistered_contract.json")
PHASE2_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase2")
REGIME_PREDICTIONS = PHASE2_ROOT / "regime_predictions.parquet"
RANKING_PREDICTIONS = PHASE2_ROOT / "ranking_predictions.parquet"
SHARED_V3_PREDICTIONS = Path("data/model/crypto_15m_v2/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase3")

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
PRIMARY_HORIZON = "1h"
BTC = "BTC-USD"
CASH = "CASH"
SHARED_V3_MODEL_ID = "hist_gradient_boosting"
SHARED_V3_CONFIRMATION = 2
UNCERTAINTY_BUFFER_BPS = 5.0


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def _read(path: Path, source: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, source)
    return frame


def build_target_weights(
    sleeve: str,
    ranked_assets: list[str],
    top_n: int,
    minimum_cash_weight: float,
    maximum_single_asset_weight: float,
) -> dict[str, float]:
    """Create a fully invested, concentration-capped target including cash."""
    weights: dict[str, float] = {CASH: 1.0}
    if sleeve == CASH:
        return weights
    assets = [BTC] if sleeve == "BTC" else list(ranked_assets[:top_n])
    if not assets:
        return weights
    risk_budget = 1.0 - minimum_cash_weight
    per_asset = min(maximum_single_asset_weight, risk_budget / len(assets))
    invested = per_asset * len(assets)
    weights = {asset: per_asset for asset in assets}
    weights[CASH] = 1.0 - invested
    return weights


def turnover(old: dict[str, float], new: dict[str, float]) -> float:
    keys = set(old) | set(new)
    return 0.5 * sum(abs(new.get(key, 0.0) - old.get(key, 0.0)) for key in keys)


def cap_turnover(
    old: dict[str, float], target: dict[str, float], maximum_turnover: float
) -> tuple[dict[str, float], float]:
    desired = turnover(old, target)
    if desired <= maximum_turnover or desired == 0:
        return target.copy(), desired
    fraction = maximum_turnover / desired
    keys = set(old) | set(target)
    adjusted = {
        key: old.get(key, 0.0) + fraction * (target.get(key, 0.0) - old.get(key, 0.0))
        for key in keys
    }
    adjusted = {key: value for key, value in adjusted.items() if value > 1e-12}
    return adjusted, turnover(old, adjusted)


def _expected_return(weights: dict[str, float], expected: dict[str, float]) -> float:
    return float(sum(weight * expected.get(asset, 0.0) for asset, weight in weights.items()))


def _actual_return(weights: dict[str, float], actual: dict[str, float]) -> float:
    return float(sum(weight * actual.get(asset, 0.0) for asset, weight in weights.items()))


def _drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) if len(equity) else 0.0


def _prepare(
    regime_path: Path,
    ranking_path: Path,
    shared_v3_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    regime = _read(regime_path, "V4 regime predictions")
    ranking = _read(ranking_path, "V4 ranking predictions")
    shared = _read(shared_v3_path, "Shared Crypto V3 predictions")
    regime = regime[(regime["horizon"] == PRIMARY_HORIZON)].copy()
    ranking = ranking[(ranking["horizon"] == PRIMARY_HORIZON)].copy()
    shared = shared[shared["model_id"] == SHARED_V3_MODEL_ID].copy()
    shared = shared.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    common = set(regime["timestamp_utc"]) & set(ranking["timestamp_utc"]) & set(shared["timestamp_utc"])
    regime = regime[regime["timestamp_utc"].isin(common)].copy()
    ranking = ranking[ranking["timestamp_utc"].isin(common)].copy()
    shared = shared[shared["timestamp_utc"].isin(common)].copy()
    if not common:
        raise RuntimeError("No common V4/Shared-V3 out-of-sample clock")
    return regime, ranking, shared


def simulate_candidate(
    regime: pd.DataFrame,
    ranking: pd.DataFrame,
    regime_model: str,
    ranking_model: str,
    top_n: int,
    cost_bps: float,
    minimum_cash_weight: float,
    maximum_single_asset_weight: float,
    maximum_turnover: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    regime_rows = regime[regime["model_id"] == regime_model].copy()
    ranking_rows = ranking[ranking["model_id"] == ranking_model].copy()
    rank_groups = {ts: group for ts, group in ranking_rows.groupby("timestamp_utc", sort=True)}
    period_rows = []

    for fold_id, fold in regime_rows.groupby("fold_id", sort=True):
        weights = {CASH: 1.0}
        equity = 1.0
        for row in fold.sort_values("timestamp_utc").itertuples(index=False):
            ranked = rank_groups.get(row.timestamp_utc)
            if ranked is None or ranked.empty:
                continue
            ranked = ranked.sort_values("predicted_score", ascending=False)
            score = dict(zip(ranked["product_id"], ranked["predicted_score"]))
            actual = dict(zip(ranked["product_id"], ranked["actual_return"]))
            actual[BTC] = float(row.btc_forward_return_1h)
            actual[CASH] = 0.0
            expected = {**score, BTC: float(row.predicted_btc_return), CASH: 0.0}

            # An asset that is no longer point-in-time eligible cannot remain
            # silently marked at a zero return.  Move it to cash before the
            # discretionary rebalance and charge its forced turnover.
            eligible_weights = weights.copy()
            unavailable_weight = sum(
                weight for asset, weight in weights.items()
                if asset not in {CASH, BTC} and asset not in actual
            )
            if unavailable_weight:
                eligible_weights = {
                    asset: weight for asset, weight in weights.items()
                    if asset in {CASH, BTC} or asset in actual
                }
                eligible_weights[CASH] = eligible_weights.get(CASH, 0.0) + unavailable_weight
            forced_turnover = turnover(weights, eligible_weights)
            weights = eligible_weights

            target = build_target_weights(
                row.proposed_sleeve,
                ranked["product_id"].tolist(),
                top_n,
                minimum_cash_weight,
                maximum_single_asset_weight,
            )
            desired_turnover = turnover(weights, target)
            expected_edge = _expected_return(target, expected) - _expected_return(weights, expected)
            hurdle = desired_turnover * cost_bps / 10000.0 + UNCERTAINTY_BUFFER_BPS / 10000.0
            rebalance_allowed = desired_turnover == 0 or expected_edge > hurdle
            if not rebalance_allowed:
                target = weights

            remaining_turnover = max(0.0, maximum_turnover - forced_turnover)
            new_weights, discretionary_turnover = cap_turnover(weights, target, remaining_turnover)
            realized_turnover = forced_turnover + discretionary_turnover
            gross = _actual_return(new_weights, actual)
            transaction_cost = realized_turnover * cost_bps / 10000.0
            net = gross - transaction_cost
            equity *= 1.0 + net
            period_rows.append({
                "timestamp_utc": row.timestamp_utc,
                "fold_id": fold_id,
                "regime_model_id": regime_model,
                "ranking_model_id": ranking_model,
                "top_n": top_n,
                "cost_bps": cost_bps,
                "proposed_sleeve": row.proposed_sleeve,
                "rebalance_allowed": rebalance_allowed,
                "expected_edge": expected_edge,
                "hurdle": hurdle,
                "turnover": realized_turnover,
                "gross_return": gross,
                "transaction_cost": transaction_cost,
                "net_return": net,
                "equity_within_fold": equity,
                "cash_weight": new_weights.get(CASH, 0.0),
            })
            weights = new_weights

    periods = pd.DataFrame(period_rows)
    folds = []
    keys = ["regime_model_id", "ranking_model_id", "top_n", "cost_bps", "fold_id"]
    for values, group in periods.groupby(keys, sort=True):
        folds.append({
            **dict(zip(keys, values)),
            "observations": int(len(group)),
            "net_return": float((1.0 + group["net_return"]).prod() - 1.0),
            "gross_return": float((1.0 + group["gross_return"]).prod() - 1.0),
            "maximum_drawdown": _drawdown(group["net_return"]),
            "total_turnover": float(group["turnover"].sum()),
            "total_transaction_cost": float(group["transaction_cost"].sum()),
            "mean_cash_weight": float(group["cash_weight"].mean()),
        })
    return periods, pd.DataFrame(folds)


def simulate_controls(
    regime: pd.DataFrame,
    ranking: pd.DataFrame,
    shared: pd.DataFrame,
    cost_bps: float,
) -> pd.DataFrame:
    base = regime[regime["model_id"] == "ridge"][
        ["timestamp_utc", "fold_id", "btc_forward_return_1h", "alt_forward_return_1h"]
    ].drop_duplicates("timestamp_utc")
    raw = shared[["timestamp_utc", "predicted_label"]].drop_duplicates("timestamp_utc")
    frame = base.merge(raw, on="timestamp_utc", validate="one_to_one").sort_values("timestamp_utc")
    rows = []
    for fold_id, fold in frame.groupby("fold_id", sort=True):
        state = "BTC"
        pending = None
        pending_count = 0
        v3_returns = []
        btc_returns = []
        for row in fold.itertuples(index=False):
            raw_label = row.predicted_label
            switched = False
            if raw_label == state:
                pending = None
                pending_count = 0
            else:
                if pending == raw_label:
                    pending_count += 1
                else:
                    pending = raw_label
                    pending_count = 1
                if pending_count >= SHARED_V3_CONFIRMATION:
                    state = raw_label
                    pending = None
                    pending_count = 0
                    switched = True
            selected = (
                float(row.btc_forward_return_1h) if state == "BTC"
                else float(row.alt_forward_return_1h) if state == "ALT"
                else 0.0
            )
            v3_returns.append(selected - (cost_bps / 10000.0 if switched else 0.0))
            btc_returns.append(float(row.btc_forward_return_1h))
        v3 = pd.Series(v3_returns, dtype=float)
        btc = pd.Series(btc_returns, dtype=float)
        rows.append({
            "fold_id": fold_id,
            "cost_bps": cost_bps,
            "shared_v3_net_return": float((1.0 + v3).prod() - 1.0),
            "shared_v3_maximum_drawdown": _drawdown(v3),
            "btc_return": float((1.0 + btc).prod() - 1.0),
            "btc_maximum_drawdown": _drawdown(btc),
        })
    return pd.DataFrame(rows)


def summarize_and_gate(folds: pd.DataFrame, controls: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    joined = folds.merge(controls, on=["fold_id", "cost_bps"], validate="many_to_one")
    joined["excess_vs_shared_v3"] = joined["net_return"] - joined["shared_v3_net_return"]
    joined["excess_vs_btc"] = joined["net_return"] - joined["btc_return"]
    group_keys = ["regime_model_id", "ranking_model_id", "top_n", "cost_bps"]
    summaries = []
    for values, group in joined.groupby(group_keys, sort=True):
        profits = group["net_return"].clip(lower=0.0)
        concentration = float(profits.max() / profits.sum()) if profits.sum() > 0 else 1.0
        summaries.append({
            **dict(zip(group_keys, values)),
            "fold_count": int(len(group)),
            "median_fold_net_return": float(group["net_return"].median()),
            "mean_fold_net_return": float(group["net_return"].mean()),
            "positive_fold_fraction": float((group["net_return"] > 0).mean()),
            "median_excess_vs_shared_v3": float(group["excess_vs_shared_v3"].median()),
            "positive_excess_vs_shared_v3_fraction": float((group["excess_vs_shared_v3"] > 0).mean()),
            "mean_excess_vs_btc": float(group["excess_vs_btc"].mean()),
            "worst_maximum_drawdown": float(group["maximum_drawdown"].min()),
            "shared_v3_worst_maximum_drawdown": float(group["shared_v3_maximum_drawdown"].min()),
            "single_fold_profit_concentration": concentration,
            "mean_total_turnover": float(group["total_turnover"].mean()),
            "mean_cash_weight": float(group["mean_cash_weight"].mean()),
        })
    summary = pd.DataFrame(summaries)
    gates = summary[summary["cost_bps"] == 25.0].copy()
    gates["gate_median_excess_vs_shared_v3"] = gates["median_excess_vs_shared_v3"] > 0.0
    gates["gate_positive_fold_fraction"] = gates["positive_fold_fraction"] >= 0.75
    gates["gate_net_excess_vs_btc"] = gates["mean_excess_vs_btc"] > 0.0
    gates["gate_survives_25bps"] = gates["median_fold_net_return"] > 0.0
    gates["gate_profit_concentration"] = gates["single_fold_profit_concentration"] <= 0.50
    gates["gate_drawdown_vs_shared_v3"] = (
        gates["worst_maximum_drawdown"]
        >= gates["shared_v3_worst_maximum_drawdown"] - 0.05
    )
    gate_columns = [column for column in gates.columns if column.startswith("gate_")]
    gates["passed_gate_count"] = gates[gate_columns].sum(axis=1).astype(int)
    gates["total_gate_count"] = len(gate_columns)
    gates["status"] = np.where(
        gates["passed_gate_count"] == gates["total_gate_count"],
        "QUALIFIES_FOR_HUMAN_REVIEW",
        "DO_NOT_ADVANCE",
    )
    return summary, gates


def run(
    phase1_contract: Path = PHASE1_CONTRACT,
    regime_path: Path = REGIME_PREDICTIONS,
    ranking_path: Path = RANKING_PREDICTIONS,
    shared_v3_path: Path = SHARED_V3_PREDICTIONS,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = json.loads(Path(phase1_contract).read_text(encoding="utf-8"))
    candidates = contract["portfolio_candidates"]
    regime, ranking, shared = _prepare(regime_path, ranking_path, shared_v3_path)
    regime_models = sorted(regime["model_id"].unique())
    ranking_models = sorted(ranking["model_id"].unique())
    top_ns = [int(value) for value in candidates["top_n"]]
    costs = [float(value) for value in candidates["round_trip_cost_bps"]]

    all_periods = []
    all_folds = []
    controls = pd.concat(
        [simulate_controls(regime, ranking, shared, cost) for cost in costs],
        ignore_index=True,
    )
    for regime_model in regime_models:
        for ranking_model in ranking_models:
            for top_n in top_ns:
                for cost in costs:
                    periods, folds = simulate_candidate(
                        regime,
                        ranking,
                        regime_model,
                        ranking_model,
                        top_n,
                        cost,
                        float(candidates["minimum_cash_weight"]),
                        float(candidates["maximum_single_asset_weight"]),
                        float(candidates["maximum_turnover_per_decision"]),
                    )
                    all_periods.append(periods)
                    all_folds.append(folds)
                    print(
                        f"[SUCCESS] regime={regime_model} ranking={ranking_model} "
                        f"top_n={top_n} cost={cost:g}bps folds={len(folds)}"
                    )

    periods = pd.concat(all_periods, ignore_index=True)
    folds = pd.concat(all_folds, ignore_index=True)
    summary, gates = summarize_and_gate(folds, controls)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    periods.to_parquet(output_root / "portfolio_periods.parquet", index=False)
    folds.to_csv(output_root / "fold_metrics.csv", index=False)
    controls.to_csv(output_root / "matched_controls.csv", index=False)
    summary.to_csv(output_root / "candidate_summary.csv", index=False)
    gates.to_csv(output_root / "gate_results.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "cost_aware_portfolio_candidates",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "primary_horizon": PRIMARY_HORIZON,
        "common_clock_rows": int(regime["timestamp_utc"].nunique()),
        "candidate_count": int(len(summary)),
        "gate_evaluation_cost_bps": 25.0,
        "uncertainty_buffer_bps": UNCERTAINTY_BUFFER_BPS,
        "matched_benchmarks": ["frozen_shared_crypto_v3_confirm2", "always_btc"],
        "qualifying_candidate_count": int((gates["status"] == "QUALIFIES_FOR_HUMAN_REVIEW").sum()),
        "outputs": {
            "portfolio_periods": str(output_root / "portfolio_periods.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "matched_controls": str(output_root / "matched_controls.csv"),
            "candidate_summary": str(output_root / "candidate_summary.csv"),
            "gate_results": str(output_root / "gate_results.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "paper_candidate_selected_automatically": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "human_review_required": True,
        },
        "next_step": "Human review of preregistered gates; do not freeze or launch unless every gate passes.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-contract", type=Path, default=PHASE1_CONTRACT)
    parser.add_argument("--regime-predictions", type=Path, default=REGIME_PREDICTIONS)
    parser.add_argument("--ranking-predictions", type=Path, default=RANKING_PREDICTIONS)
    parser.add_argument("--shared-v3-predictions", type=Path, default=SHARED_V3_PREDICTIONS)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        args.phase1_contract,
        args.regime_predictions,
        args.ranking_predictions,
        args.shared_v3_predictions,
        args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
