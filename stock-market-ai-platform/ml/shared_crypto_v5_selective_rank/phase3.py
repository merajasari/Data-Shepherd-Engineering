"""Shared Crypto V5 Selective Rank Phase 3: fixed-policy evaluation.

Uses only Phase 2 out-of-sample predictions and the single portfolio policy
preregistered in Phase 1.  The primary HGB models are evaluated at 25 bps
round-trip cost and the identical policy is stress-tested at 50 bps.  Results
are compared with Always-BTC and the frozen Shared Crypto V3 confirm-2 policy
on the exact same hourly clock.

This is development evidence only.  It does not inspect the future holdout,
search thresholds, select or freeze a paper candidate, modify an existing
model, write paper state, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v5_selective_rank"
PHASE1_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase1")
PHASE1_CONTRACT = PHASE1_ROOT / "preregistered_contract.json"
PHASE1_SELECTION = PHASE1_ROOT / "alt_selection_dataset.parquet"
PHASE2_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase2")
RISK_PREDICTIONS = PHASE2_ROOT / "market_risk_predictions.parquet"
SELECTION_PREDICTIONS = PHASE2_ROOT / "alt_selection_predictions.parquet"
SHARED_V3_PREDICTIONS = Path("data/model/crypto_15m_v2/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase3")

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
BTC = "BTC-USD"
CASH = "CASH"
SHARED_V3_MODEL_ID = "hist_gradient_boosting"
SHARED_V3_CONFIRMATION = 2
PRIMARY_RISK_COLUMN = "probability_hist_gradient_boosting_classifier"
PRIMARY_EXCESS_COLUMN = "predicted_excess_hist_gradient_boosting_regressor"
PRIMARY_LOWER_BOUND_COLUMN = "lower_bound_hist_gradient_boosting_regressor"
PRIMARY_DOWNSIDE_COLUMN = "downside_probability_hist_gradient_boosting_classifier"
VOLATILITY_COLUMN = "realized_volatility_16bar"


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def _read(path: Path, source: str) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, source)
    return frame


def turnover(old: dict[str, float], new: dict[str, float]) -> float:
    keys = set(old) | set(new)
    return 0.5 * sum(abs(new.get(key, 0.0) - old.get(key, 0.0)) for key in keys)


def cap_turnover(
    old: dict[str, float], target: dict[str, float], maximum_turnover: float
) -> tuple[dict[str, float], float]:
    desired = turnover(old, target)
    if desired <= maximum_turnover or desired == 0.0:
        return target.copy(), desired
    fraction = maximum_turnover / desired
    keys = set(old) | set(target)
    adjusted = {
        key: old.get(key, 0.0) + fraction * (target.get(key, 0.0) - old.get(key, 0.0))
        for key in keys
    }
    adjusted = {key: value for key, value in adjusted.items() if value > 1e-12}
    return adjusted, turnover(old, adjusted)


def _capped_inverse_volatility_weights(
    assets: list[str],
    volatility: dict[str, float],
    gross_exposure: float,
    maximum_asset_weight: float,
) -> dict[str, float]:
    """Allocate inverse-volatility weights with a deterministic hard cap."""
    if not assets or gross_exposure <= 0.0:
        return {}
    inverse = {
        asset: 1.0 / max(float(volatility[asset]), 1e-8)
        for asset in assets
    }
    remaining = list(assets)
    weights = {asset: 0.0 for asset in assets}
    budget = min(gross_exposure, maximum_asset_weight * len(assets))
    while remaining and budget > 1e-12:
        denominator = sum(inverse[asset] for asset in remaining)
        proposed = {
            asset: budget * inverse[asset] / denominator for asset in remaining
        }
        capped = [asset for asset, weight in proposed.items()
                  if weight >= maximum_asset_weight - 1e-12]
        if not capped:
            for asset, weight in proposed.items():
                weights[asset] += weight
            budget = 0.0
            break
        for asset in capped:
            allocation = min(maximum_asset_weight - weights[asset], budget)
            weights[asset] += allocation
            budget -= allocation
            remaining.remove(asset)
    return {asset: weight for asset, weight in weights.items() if weight > 1e-12}


def build_target_weights(
    sleeve: str,
    assets: list[str],
    volatility: dict[str, float],
    maximum_gross_exposure: float,
    maximum_btc_weight: float,
    maximum_alt_weight: float,
) -> dict[str, float]:
    if sleeve == CASH:
        return {CASH: 1.0}
    if sleeve == "BTC":
        invested = min(maximum_gross_exposure, maximum_btc_weight)
        return {BTC: invested, CASH: 1.0 - invested}
    weights = _capped_inverse_volatility_weights(
        assets, volatility, maximum_gross_exposure, maximum_alt_weight
    )
    weights[CASH] = 1.0 - sum(weights.values())
    return weights


def select_alt_assets(
    ranked: pd.DataFrame,
    incumbents: set[str],
    top_n: int,
    lower_bound_hurdle: float,
    downside_maximum: float,
    retention_hurdle: float,
) -> list[str]:
    eligible = ranked[
        (ranked[PRIMARY_LOWER_BOUND_COLUMN] > lower_bound_hurdle)
        & (ranked[PRIMARY_DOWNSIDE_COLUMN] <= downside_maximum)
    ].sort_values(
        [PRIMARY_LOWER_BOUND_COLUMN, "product_id"],
        ascending=[False, True],
    )
    if len(eligible) < top_n:
        return []
    chosen = eligible.head(top_n)["product_id"].tolist()
    cutoff = float(eligible.iloc[top_n - 1][PRIMARY_LOWER_BOUND_COLUMN])
    retained = eligible[
        eligible["product_id"].isin(incumbents)
        & (eligible[PRIMARY_LOWER_BOUND_COLUMN] >= cutoff - retention_hurdle)
    ]["product_id"].tolist()
    result = list(dict.fromkeys(retained + chosen))[:top_n]
    if len(result) < top_n:
        for asset in eligible["product_id"]:
            if asset not in result:
                result.append(asset)
            if len(result) == top_n:
                break
    return result


def _drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) if len(equity) else 0.0


def _prepare(
    risk_path: Path,
    selection_path: Path,
    feature_path: Path,
    shared_v3_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    risk = _read(risk_path, "V5 market-risk predictions")
    selection = _read(selection_path, "V5 ALT-selection predictions")
    features = _read(feature_path, "V5 ALT-selection features")
    shared = _read(shared_v3_path, "Shared Crypto V3 predictions")
    required_risk = {"timestamp_utc", "fold_id", "btc_forward_return_1h",
                     "alt_forward_return_1h", PRIMARY_RISK_COLUMN}
    required_selection = {
        "timestamp_utc", "product_id", "fold_id", "forward_return_1h",
        PRIMARY_EXCESS_COLUMN, PRIMARY_LOWER_BOUND_COLUMN, PRIMARY_DOWNSIDE_COLUMN,
    }
    for name, frame, required in (
        ("risk", risk, required_risk), ("selection", selection, required_selection)
    ):
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"V5 {name} predictions missing columns: {sorted(missing)}")
    if VOLATILITY_COLUMN not in features.columns:
        raise RuntimeError(
            f"V5 preregistered volatility scaling requires {VOLATILITY_COLUMN}"
        )
    feature_columns = ["timestamp_utc", "product_id", VOLATILITY_COLUMN]
    selection = selection.merge(
        features[feature_columns].drop_duplicates(["timestamp_utc", "product_id"]),
        on=["timestamp_utc", "product_id"],
        how="left",
        validate="one_to_one",
    )
    if selection[VOLATILITY_COLUMN].isna().any():
        raise RuntimeError("V5 selection predictions lack point-in-time volatility")
    shared = shared[shared["model_id"] == SHARED_V3_MODEL_ID].copy()
    shared = shared.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    common = (
        set(risk["timestamp_utc"])
        & set(selection["timestamp_utc"])
        & set(shared["timestamp_utc"])
    )
    if not common:
        raise RuntimeError("No common V5/Shared-V3 out-of-sample clock")
    risk = risk[risk["timestamp_utc"].isin(common)].copy()
    selection = selection[selection["timestamp_utc"].isin(common)].copy()
    shared = shared[shared["timestamp_utc"].isin(common)].copy()
    fold_check = selection[["timestamp_utc", "fold_id"]].drop_duplicates()
    fold_check = fold_check.merge(
        risk[["timestamp_utc", "fold_id"]].drop_duplicates(),
        on="timestamp_utc",
        suffixes=("_selection", "_risk"),
        validate="one_to_one",
    )
    if not (fold_check["fold_id_selection"] == fold_check["fold_id_risk"]).all():
        raise RuntimeError("V5 Phase 2 risk and selection folds are misaligned")
    return risk, selection, shared


def simulate_candidate(
    risk: pd.DataFrame,
    selection: pd.DataFrame,
    policy: dict,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    top_n = int(policy["top_n"])
    risk_minimum = float(policy["risk_on_probability_minimum"])
    downside_maximum = float(policy["downside_probability_maximum"])
    buffer_bps = float(policy["uncertainty_buffer_bps"])
    lower_bound_hurdle = (float(cost_bps) + buffer_bps) / 10000.0
    retention_hurdle = float(policy["incumbent_retention_hurdle_bps"]) / 10000.0
    maximum_turnover = float(policy["maximum_turnover_per_hour"])
    maximum_gross = float(policy["maximum_gross_crypto_exposure"])
    maximum_btc = float(policy["maximum_btc_weight"])
    maximum_alt = float(policy["maximum_alt_weight"])
    groups = {timestamp: group for timestamp, group in
              selection.groupby("timestamp_utc", sort=True)}
    period_rows = []
    for fold_id, fold in risk.groupby("fold_id", sort=True):
        weights = {CASH: 1.0}
        for row in fold.sort_values("timestamp_utc").itertuples(index=False):
            ranked = groups.get(row.timestamp_utc)
            if ranked is None or ranked.empty:
                continue
            actual = dict(zip(ranked["product_id"], ranked["forward_return_1h"]))
            actual[BTC] = float(row.btc_forward_return_1h)
            actual[CASH] = 0.0
            available = set(actual)
            forced_target = {
                asset: weight for asset, weight in weights.items() if asset in available
            }
            unavailable_weight = 1.0 - sum(forced_target.values())
            if unavailable_weight > 1e-12:
                forced_target[CASH] = forced_target.get(CASH, 0.0) + unavailable_weight
            forced_turnover = turnover(weights, forced_target)
            weights = forced_target

            incumbents = {asset for asset in weights if asset not in {BTC, CASH}}
            risk_on = float(getattr(row, PRIMARY_RISK_COLUMN)) >= risk_minimum
            assets = select_alt_assets(
                ranked, incumbents, top_n, lower_bound_hurdle,
                downside_maximum, retention_hurdle,
            ) if risk_on else []
            sleeve = "ALT" if assets else "BTC" if risk_on else CASH
            volatility = dict(zip(ranked["product_id"], ranked[VOLATILITY_COLUMN]))
            target = build_target_weights(
                sleeve, assets, volatility, maximum_gross, maximum_btc, maximum_alt
            )
            remaining_turnover = max(0.0, maximum_turnover - forced_turnover)
            new_weights, discretionary_turnover = cap_turnover(
                weights, target, remaining_turnover
            )
            realized_turnover = forced_turnover + discretionary_turnover
            gross_return = float(sum(
                weight * float(actual.get(asset, 0.0))
                for asset, weight in new_weights.items()
            ))
            transaction_cost = realized_turnover * cost_bps / 10000.0
            net_return = gross_return - transaction_cost
            period_rows.append({
                "timestamp_utc": row.timestamp_utc,
                "fold_id": fold_id,
                "cost_bps": float(cost_bps),
                "sleeve": sleeve,
                "selected_alts": "|".join(assets),
                "risk_on_probability": float(getattr(row, PRIMARY_RISK_COLUMN)),
                "turnover": realized_turnover,
                "gross_return": gross_return,
                "transaction_cost": transaction_cost,
                "net_return": net_return,
                "cash_weight": new_weights.get(CASH, 0.0),
                "btc_weight": new_weights.get(BTC, 0.0),
                "alt_weight": sum(weight for asset, weight in new_weights.items()
                                  if asset not in {BTC, CASH}),
            })
            weights = new_weights
    periods = pd.DataFrame(period_rows)
    fold_rows = []
    for (cost, fold_id), group in periods.groupby(["cost_bps", "fold_id"], sort=True):
        fold_rows.append({
            "cost_bps": float(cost),
            "fold_id": fold_id,
            "observations": int(len(group)),
            "net_return": float((1.0 + group["net_return"]).prod() - 1.0),
            "gross_return": float((1.0 + group["gross_return"]).prod() - 1.0),
            "maximum_drawdown": _drawdown(group["net_return"]),
            "total_turnover": float(group["turnover"].sum()),
            "total_transaction_cost": float(group["transaction_cost"].sum()),
            "mean_cash_weight": float(group["cash_weight"].mean()),
            "mean_btc_weight": float(group["btc_weight"].mean()),
            "mean_alt_weight": float(group["alt_weight"].mean()),
        })
    return periods, pd.DataFrame(fold_rows)


def simulate_controls(
    risk: pd.DataFrame,
    shared: pd.DataFrame,
    cost_bps: float,
) -> pd.DataFrame:
    raw = shared[["timestamp_utc", "predicted_label"]].drop_duplicates("timestamp_utc")
    frame = risk.merge(raw, on="timestamp_utc", validate="one_to_one")
    rows = []
    for fold_id, fold in frame.groupby("fold_id", sort=True):
        state = "BTC"
        pending = None
        pending_count = 0
        v3_returns = []
        btc_returns = []
        for row in fold.sort_values("timestamp_utc").itertuples(index=False):
            label = row.predicted_label
            switched = False
            if label == state:
                pending = None
                pending_count = 0
            else:
                if pending == label:
                    pending_count += 1
                else:
                    pending = label
                    pending_count = 1
                if pending_count >= SHARED_V3_CONFIRMATION:
                    state = label
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
            "cost_bps": float(cost_bps),
            "fold_id": fold_id,
            "shared_v3_net_return": float((1.0 + v3).prod() - 1.0),
            "shared_v3_maximum_drawdown": _drawdown(v3),
            "btc_return": float((1.0 + btc).prod() - 1.0),
            "btc_maximum_drawdown": _drawdown(btc),
        })
    return pd.DataFrame(rows)


def summarize_and_gate(
    folds: pd.DataFrame,
    controls: pd.DataFrame,
    primary_cost_bps: float,
    stress_cost_bps: float,
) -> tuple[pd.DataFrame, dict]:
    joined = folds.merge(controls, on=["cost_bps", "fold_id"], validate="one_to_one")
    joined["excess_vs_shared_v3"] = (
        joined["net_return"] - joined["shared_v3_net_return"]
    )
    joined["excess_vs_btc"] = joined["net_return"] - joined["btc_return"]
    summaries = []
    for cost, group in joined.groupby("cost_bps", sort=True):
        profits = group["net_return"].clip(lower=0.0)
        concentration = float(profits.max() / profits.sum()) if profits.sum() > 0 else 1.0
        summaries.append({
            "cost_bps": float(cost),
            "fold_count": int(len(group)),
            "median_fold_net_return": float(group["net_return"].median()),
            "mean_fold_net_return": float(group["net_return"].mean()),
            "positive_fold_fraction": float((group["net_return"] > 0.0).mean()),
            "median_excess_vs_btc": float(group["excess_vs_btc"].median()),
            "median_excess_vs_shared_v3": float(group["excess_vs_shared_v3"].median()),
            "positive_excess_vs_shared_v3_fraction": float(
                (group["excess_vs_shared_v3"] > 0.0).mean()
            ),
            "worst_maximum_drawdown": float(group["maximum_drawdown"].min()),
            "single_fold_profit_concentration": concentration,
            "mean_total_turnover": float(group["total_turnover"].mean()),
            "mean_cash_weight": float(group["mean_cash_weight"].mean()),
        })
    summary = pd.DataFrame(summaries)
    primary = summary[summary["cost_bps"] == float(primary_cost_bps)]
    stress = summary[summary["cost_bps"] == float(stress_cost_bps)]
    if len(primary) != 1 or len(stress) != 1:
        raise RuntimeError("Primary or stress cost summary is missing")
    p = primary.iloc[0]
    s = stress.iloc[0]
    gates = {
        "gate_median_fold_net_return_gt_zero": bool(p["median_fold_net_return"] > 0.0),
        "gate_positive_fold_fraction_gte_80pct": bool(p["positive_fold_fraction"] >= 0.80),
        "gate_median_excess_vs_always_btc_gt_zero": bool(p["median_excess_vs_btc"] > 0.0),
        "gate_median_excess_vs_shared_v3_gt_zero": bool(p["median_excess_vs_shared_v3"] > 0.0),
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": bool(
            p["positive_excess_vs_shared_v3_fraction"] >= 0.80
        ),
        "gate_worst_maximum_drawdown_gte_minus_20pct": bool(
            p["worst_maximum_drawdown"] >= -0.20
        ),
        "gate_single_fold_profit_concentration_lte_40pct": bool(
            p["single_fold_profit_concentration"] <= 0.40
        ),
        "gate_survives_50bps_stress": bool(s["median_fold_net_return"] > 0.0),
    }
    passed = sum(gates.values())
    result = {
        **gates,
        "passed_gate_count": int(passed),
        "total_gate_count": int(len(gates)),
        "status": "QUALIFIES_FOR_HUMAN_REVIEW" if passed == len(gates) else "DO_NOT_ADVANCE",
    }
    return summary, result


def run(
    phase1_contract: Path = PHASE1_CONTRACT,
    risk_path: Path = RISK_PREDICTIONS,
    selection_path: Path = SELECTION_PREDICTIONS,
    feature_path: Path = PHASE1_SELECTION,
    shared_v3_path: Path = SHARED_V3_PREDICTIONS,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = json.loads(Path(phase1_contract).read_text(encoding="utf-8"))
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V5 Phase 1 holdout boundary differs from Phase 3")
    policy = dict(contract["frozen_policy_for_later_simulation"])
    if not policy.get("volatility_scaling"):
        raise RuntimeError("V5 Phase 3 requires preregistered volatility scaling")
    primary_cost = float(policy["primary_round_trip_cost_bps"])
    stress_cost = float(policy["stress_round_trip_cost_bps"])
    risk, selection, shared = _prepare(
        risk_path, selection_path, feature_path, shared_v3_path
    )
    period_frames = []
    fold_frames = []
    control_frames = []
    for cost in (primary_cost, stress_cost):
        periods, folds = simulate_candidate(risk, selection, policy, cost)
        period_frames.append(periods)
        fold_frames.append(folds)
        control_frames.append(simulate_controls(risk, shared, cost))
        print(f"[SUCCESS] fixed V5 policy cost={cost:g}bps folds={len(folds)}")
    periods = pd.concat(period_frames, ignore_index=True)
    folds = pd.concat(fold_frames, ignore_index=True)
    controls = pd.concat(control_frames, ignore_index=True)
    summary, gate_result = summarize_and_gate(
        folds, controls, primary_cost, stress_cost
    )
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    periods.to_parquet(output_root / "portfolio_periods.parquet", index=False)
    folds.to_csv(output_root / "fold_metrics.csv", index=False)
    controls.to_csv(output_root / "matched_controls.csv", index=False)
    summary.to_csv(output_root / "policy_summary.csv", index=False)
    pd.DataFrame([gate_result]).to_csv(output_root / "gate_results.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "single_preregistered_selective_rank_policy",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "common_clock_rows": int(risk["timestamp_utc"].nunique()),
        "candidate_count": 1,
        "primary_cost_bps": primary_cost,
        "stress_cost_bps": stress_cost,
        "matched_benchmarks": ["frozen_shared_crypto_v3_confirm2", "always_btc"],
        "gate_status": gate_result["status"],
        "passed_gate_count": gate_result["passed_gate_count"],
        "total_gate_count": gate_result["total_gate_count"],
        "outputs": {
            "portfolio_periods": str(output_root / "portfolio_periods.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "matched_controls": str(output_root / "matched_controls.csv"),
            "policy_summary": str(output_root / "policy_summary.csv"),
            "gate_results": str(output_root / "gate_results.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "threshold_search_performed": False,
            "shared_crypto_v3_modified": False,
            "rejected_v4_modified": False,
            "future_holdout_scored": False,
            "paper_candidate_selected_automatically": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "human_review_required": True,
        },
        "next_step": (
            "Human review only. Do not freeze, score the future holdout, or launch "
            "paper collection unless every preregistered gate passes."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-contract", type=Path, default=PHASE1_CONTRACT)
    parser.add_argument("--risk-predictions", type=Path, default=RISK_PREDICTIONS)
    parser.add_argument("--selection-predictions", type=Path, default=SELECTION_PREDICTIONS)
    parser.add_argument("--selection-features", type=Path, default=PHASE1_SELECTION)
    parser.add_argument("--shared-v3-predictions", type=Path, default=SHARED_V3_PREDICTIONS)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        args.phase1_contract,
        args.risk_predictions,
        args.selection_predictions,
        args.selection_features,
        args.shared_v3_predictions,
        args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()

