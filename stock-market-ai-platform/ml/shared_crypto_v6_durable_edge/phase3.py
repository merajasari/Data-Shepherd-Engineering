"""Shared Crypto V6 Durable Edge Phase 3: fixed daily policy evaluation.

Uses only Phase 2 out-of-sample predictions and the single policy registered
in Phase 1.  The primary HGB classifier is evaluated at 25 bps and the exact
same decisions are stress-tested at 50 bps.  The future holdout remains
untouched, and this module cannot freeze a model, write paper state, or place
an order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v6_durable_edge"
PHASE1_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase1")
PHASE1_CONTRACT = PHASE1_ROOT / "preregistered_contract.json"
PHASE1_ASSETS = PHASE1_ROOT / "daily_asset_dataset.parquet"
PHASE2_PREDICTIONS = Path(
    "data/model/shared_crypto_v6_durable_edge/phase2/daily_predictions.parquet"
)
SHARED_V3_PREDICTIONS = Path("data/model/crypto_15m_v2/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/shared_crypto_v6_durable_edge/phase3")

HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
BTC = "BTC-USD"
CASH = "CASH"
PRIMARY_MODEL = "hist_gradient_boosting_classifier"
PREDICTED_LABEL = f"predicted_label_{PRIMARY_MODEL}"
CONFIDENCE = f"confidence_{PRIMARY_MODEL}"
MARGIN = f"margin_{PRIMARY_MODEL}"
SHARED_V3_MODEL_ID = "hist_gradient_boosting"
SHARED_V3_CONFIRMATION = 2


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
        key: old.get(key, 0.0)
        + fraction * (target.get(key, 0.0) - old.get(key, 0.0))
        for key in keys
    }
    adjusted = {key: value for key, value in adjusted.items() if value > 1e-12}
    return adjusted, turnover(old, adjusted)


def build_target_weights(
    sleeve: str, basket_assets: list[str], policy: dict
) -> dict[str, float]:
    maximum_gross = float(policy["maximum_gross_crypto_exposure"])
    if sleeve == CASH:
        return {CASH: 1.0}
    if sleeve == "BTC":
        invested = min(maximum_gross, float(policy["maximum_btc_weight"]))
        return {BTC: invested, CASH: 1.0 - invested}
    if sleeve != "ALT":
        raise RuntimeError(f"Unexpected V6 sleeve: {sleeve}")
    if not basket_assets:
        raise RuntimeError("V6 ALT target requires the deterministic liquid basket")
    maximum_alt = float(policy["maximum_alt_weight"])
    equal_weight = min(maximum_alt, maximum_gross / len(basket_assets))
    weights = {asset: equal_weight for asset in basket_assets}
    weights[CASH] = 1.0 - sum(weights.values())
    return weights


def _drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) if len(equity) else 0.0


def _basket(value: object) -> list[str]:
    return [asset for asset in str(value).split("|") if asset and asset != "nan"]


def _prepare(
    prediction_path: Path,
    asset_path: Path,
    shared_v3_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions = _read(prediction_path, "V6 daily predictions")
    assets = _read(asset_path, "V6 daily asset dataset")
    shared = _read(shared_v3_path, "Shared Crypto V3 predictions")
    required_predictions = {
        "timestamp_utc", "fold_id", "btc_forward_return_24h",
        "alt_forward_return_24h", "alt_basket_assets", PREDICTED_LABEL,
        CONFIDENCE, MARGIN,
    }
    required_assets = {
        "timestamp_utc", "product_id", "forward_return_24h",
        "selected_liquid_top5",
    }
    missing = required_predictions - set(predictions.columns)
    if missing:
        raise RuntimeError(f"V6 predictions missing columns: {sorted(missing)}")
    missing = required_assets - set(assets.columns)
    if missing:
        raise RuntimeError(f"V6 assets missing columns: {sorted(missing)}")
    if "model_id" not in shared or "predicted_label" not in shared:
        raise RuntimeError("Shared Crypto V3 predictions lack model_id or predicted_label")
    shared = shared[shared["model_id"] == SHARED_V3_MODEL_ID].copy()
    shared = shared.sort_values("timestamp_utc").drop_duplicates(
        "timestamp_utc", keep="last"
    )
    common = set(predictions["timestamp_utc"]) & set(shared["timestamp_utc"])
    if not common:
        raise RuntimeError("No common V6/Shared-V3 out-of-sample daily clock")
    predictions = predictions[predictions["timestamp_utc"].isin(common)].copy()
    shared = shared[shared["timestamp_utc"].isin(common)].copy()
    assets = assets[assets["timestamp_utc"].isin(common)].copy()
    selected = assets[assets["selected_liquid_top5"]].groupby(
        "timestamp_utc"
    )["product_id"].agg(lambda values: tuple(sorted(values.astype(str))))
    expected = predictions.set_index("timestamp_utc")["alt_basket_assets"].map(
        lambda value: tuple(sorted(_basket(value)))
    )
    if not selected.reindex(expected.index).eq(expected).all():
        raise RuntimeError("V6 deterministic ALT basket is incomplete or misaligned")
    return (
        predictions.sort_values(["fold_id", "timestamp_utc"]).reset_index(drop=True),
        assets.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True),
        shared.sort_values("timestamp_utc").reset_index(drop=True),
    )


def simulate_candidate(
    predictions: pd.DataFrame,
    assets: pd.DataFrame,
    policy: dict,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    minimum_confidence = float(policy["minimum_predicted_probability"])
    minimum_margin = float(policy["minimum_probability_margin"])
    confirmations = int(policy["confirmation_count"])
    minimum_hold = timedelta(hours=int(policy["minimum_hold_hours"]))
    maximum_turnover = float(policy["maximum_turnover_per_daily_decision"])
    groups = {
        timestamp: group for timestamp, group in assets.groupby("timestamp_utc", sort=True)
    }
    period_rows = []
    for fold_id, fold in predictions.groupby("fold_id", sort=True):
        weights = {CASH: 1.0}
        state = CASH
        pending = None
        pending_count = 0
        last_state_change = None
        for row in fold.sort_values("timestamp_utc").itertuples(index=False):
            timestamp = row.timestamp_utc
            daily_assets = groups.get(timestamp)
            if daily_assets is None or daily_assets.empty:
                raise RuntimeError(f"Missing V6 assets for {timestamp}")
            actual = dict(zip(
                daily_assets["product_id"], daily_assets["forward_return_24h"]
            ))
            actual[BTC] = float(row.btc_forward_return_24h)
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

            raw_label = str(getattr(row, PREDICTED_LABEL))
            qualified = (
                float(getattr(row, CONFIDENCE)) >= minimum_confidence
                and float(getattr(row, MARGIN)) >= minimum_margin
            )
            signal = raw_label if qualified else None
            can_change = (
                last_state_change is None
                or timestamp - last_state_change >= minimum_hold
            )
            if signal is None or signal == state:
                pending = None
                pending_count = 0
            else:
                if pending == signal:
                    pending_count += 1
                else:
                    pending = signal
                    pending_count = 1
                if pending_count >= confirmations and can_change:
                    state = signal
                    last_state_change = timestamp
                    pending = None
                    pending_count = 0

            basket_assets = _basket(row.alt_basket_assets)
            target = build_target_weights(state, basket_assets, policy)
            remaining = max(0.0, maximum_turnover - forced_turnover)
            new_weights, discretionary_turnover = cap_turnover(weights, target, remaining)
            realized_turnover = forced_turnover + discretionary_turnover
            gross_return = float(sum(
                weight * float(actual.get(asset, 0.0))
                for asset, weight in new_weights.items()
            ))
            transaction_cost = realized_turnover * float(cost_bps) / 10000.0
            net_return = gross_return - transaction_cost
            period_rows.append({
                "timestamp_utc": timestamp,
                "fold_id": fold_id,
                "cost_bps": float(cost_bps),
                "raw_predicted_label": raw_label,
                "qualified_signal": signal or "",
                "policy_state": state,
                "confidence": float(getattr(row, CONFIDENCE)),
                "probability_margin": float(getattr(row, MARGIN)),
                "turnover": realized_turnover,
                "gross_return": gross_return,
                "transaction_cost": transaction_cost,
                "net_return": net_return,
                "cash_weight": new_weights.get(CASH, 0.0),
                "btc_weight": new_weights.get(BTC, 0.0),
                "alt_weight": sum(
                    weight for asset, weight in new_weights.items()
                    if asset not in {BTC, CASH}
                ),
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
    predictions: pd.DataFrame,
    shared: pd.DataFrame,
    cost_bps: float,
) -> pd.DataFrame:
    raw = shared[["timestamp_utc", "predicted_label"]].drop_duplicates(
        "timestamp_utc"
    )
    frame = predictions.merge(raw, on="timestamp_utc", validate="one_to_one")
    rows = []
    for fold_id, fold in frame.groupby("fold_id", sort=True):
        state = "BTC"
        pending = None
        pending_count = 0
        v3_returns = []
        btc_returns = []
        for row in fold.sort_values("timestamp_utc").itertuples(index=False):
            label = str(row.predicted_label)
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
                float(row.btc_forward_return_24h) if state == "BTC"
                else float(row.alt_forward_return_24h) if state == "ALT"
                else 0.0
            )
            v3_returns.append(selected - (float(cost_bps) / 10000.0 if switched else 0.0))
            btc_returns.append(float(row.btc_forward_return_24h))
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
    joined["excess_vs_shared_v3"] = joined["net_return"] - joined["shared_v3_net_return"]
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
        raise RuntimeError("Primary or stress V6 cost summary is missing")
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
    return summary, {
        **gates,
        "passed_gate_count": int(passed),
        "total_gate_count": int(len(gates)),
        "status": "QUALIFIES_FOR_HUMAN_REVIEW" if passed == len(gates) else "DO_NOT_ADVANCE",
    }


def run(
    phase1_contract: Path = PHASE1_CONTRACT,
    prediction_path: Path = PHASE2_PREDICTIONS,
    asset_path: Path = PHASE1_ASSETS,
    shared_v3_path: Path = SHARED_V3_PREDICTIONS,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = json.loads(Path(phase1_contract).read_text(encoding="utf-8"))
    if contract.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError("Unexpected V6 Phase 1 research version")
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V6 Phase 1 holdout boundary differs from Phase 3")
    policy = dict(contract["frozen_policy_for_later_simulation"])
    primary_cost = float(policy["primary_round_trip_cost_bps"])
    stress_cost = float(policy["stress_round_trip_cost_bps"])
    predictions, assets, shared = _prepare(prediction_path, asset_path, shared_v3_path)
    period_frames = []
    fold_frames = []
    control_frames = []
    for cost in (primary_cost, stress_cost):
        periods, folds = simulate_candidate(predictions, assets, policy, cost)
        period_frames.append(periods)
        fold_frames.append(folds)
        control_frames.append(simulate_controls(predictions, shared, cost))
        print(f"[SUCCESS] fixed V6 policy cost={cost:g}bps folds={len(folds)}")
    periods = pd.concat(period_frames, ignore_index=True)
    folds = pd.concat(fold_frames, ignore_index=True)
    controls = pd.concat(control_frames, ignore_index=True)
    summary, gate_result = summarize_and_gate(folds, controls, primary_cost, stress_cost)
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
        "stage": "single_preregistered_persistent_daily_policy",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "common_clock_rows": int(predictions["timestamp_utc"].nunique()),
        "candidate_count": 1,
        "primary_model": PRIMARY_MODEL,
        "primary_cost_bps": primary_cost,
        "stress_cost_bps": stress_cost,
        "matched_benchmarks": [
            "shared_crypto_v3_labels_sampled_on_daily_clock_with_confirm2",
            "always_btc",
        ],
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
            "v5_modified": False,
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
    parser.add_argument("--predictions", type=Path, default=PHASE2_PREDICTIONS)
    parser.add_argument("--assets", type=Path, default=PHASE1_ASSETS)
    parser.add_argument("--shared-v3-predictions", type=Path, default=SHARED_V3_PREDICTIONS)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        args.phase1_contract,
        args.predictions,
        args.assets,
        args.shared_v3_predictions,
        args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
