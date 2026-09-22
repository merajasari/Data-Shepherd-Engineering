"""Shared Crypto V5 Selective Rank Phase 1: preregistered causal datasets.

V5 is a new hypothesis after V4 was immutably rejected.  It keeps the stable
one-hour cross-sectional ranking idea but replaces V4's weak return-regression
allocator with two isolated tasks:

* an hourly market-risk dataset for BTC-versus-CASH exposure; and
* a per-asset dataset targeting ALT excess return versus BTC.

No model is fit, no policy is simulated, and no row at or after the untouched
2026-09-01 holdout is inspected.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v5_selective_rank"
V4_PHASE1_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v5_selective_rank/phase1")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def build_datasets(
    regime: pd.DataFrame,
    ranking: pd.DataFrame,
    v4_contract: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    regime = regime.copy()
    ranking = ranking.copy()
    regime["timestamp_utc"] = pd.to_datetime(regime["timestamp_utc"], utc=True)
    ranking["timestamp_utc"] = pd.to_datetime(ranking["timestamp_utc"], utc=True)
    validate_pre_holdout(regime, "V4 regime dataset")
    validate_pre_holdout(ranking, "V4 ranking dataset")

    risk_features = list(v4_contract["regime_feature_columns"])
    rank_features = list(v4_contract["ranking_feature_columns"])
    risk_columns = [
        "timestamp_utc", *risk_features,
        "btc_forward_return_1h", "alt_forward_return_1h",
    ]
    risk = regime[risk_columns].copy()
    risk["btc_positive_1h"] = (risk["btc_forward_return_1h"] > 0.0).astype("int8")
    risk["broad_market_positive_1h"] = (
        risk["alt_forward_return_1h"] > 0.0
    ).astype("int8")

    context = risk[["timestamp_utc", *risk_features, "btc_forward_return_1h"]].copy()
    selection = ranking.merge(context, on="timestamp_utc", how="inner", validate="many_to_one")
    selection["alt_excess_vs_btc_1h"] = (
        selection["forward_return_1h"] - selection["btc_forward_return_1h"]
    )
    selection["alt_outperforms_btc_1h"] = (
        selection["alt_excess_vs_btc_1h"] > 0.0
    ).astype("int8")
    selection["alt_loss_1pct_1h"] = (
        selection["forward_return_1h"] <= -0.01
    ).astype("int8")

    combined_features = list(dict.fromkeys(rank_features + risk_features))
    risk_required = risk_features + [
        "btc_forward_return_1h", "alt_forward_return_1h",
        "btc_positive_1h", "broad_market_positive_1h",
    ]
    selection_required = combined_features + [
        "forward_return_1h", "btc_forward_return_1h",
        "alt_excess_vs_btc_1h", "alt_outperforms_btc_1h",
        "alt_loss_1pct_1h",
    ]
    risk = risk.replace([np.inf, -np.inf], np.nan).dropna(subset=risk_required)
    selection = selection.replace([np.inf, -np.inf], np.nan).dropna(subset=selection_required)
    risk = risk.sort_values("timestamp_utc").reset_index(drop=True)
    selection = selection.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)
    if risk.empty or selection.empty:
        raise RuntimeError("Shared Crypto V5 Phase 1 produced an empty dataset")

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "preregistered_selective_rank_dataset",
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "decision_cadence": "1 hour",
        "economic_horizon": "1 hour",
        "hypothesis": (
            "Trade only when a causally predicted lower-confidence-bound ALT "
            "excess return clears modeled cost; otherwise hold capped BTC when "
            "the independent market-risk gate is confident, or CASH."
        ),
        "models": {
            "market_risk_primary": "hist_gradient_boosting_classifier",
            "alt_excess_primary": "hist_gradient_boosting_regressor",
            "alt_downside_primary": "hist_gradient_boosting_classifier",
            "linear_diagnostics_only": ["logistic_regression", "ridge"],
        },
        "targets": {
            "market_risk": "btc_positive_1h",
            "alt_excess": "alt_excess_vs_btc_1h",
            "alt_downside": "alt_loss_1pct_1h",
        },
        "risk_feature_columns": risk_features,
        "selection_feature_columns": combined_features,
        "frozen_policy_for_later_simulation": {
            "top_n": 5,
            "risk_on_probability_minimum": 0.55,
            "downside_probability_maximum": 0.35,
            "confidence_method": "expanding-fold conformal lower bound",
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "uncertainty_buffer_bps": 5.0,
            "minimum_cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "maximum_btc_weight": 0.60,
            "maximum_alt_weight": 0.15,
            "maximum_turnover_per_hour": 0.25,
            "incumbent_retention_hurdle_bps": 10.0,
            "volatility_scaling": True,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": {
            "median_fold_net_return_gt": 0.0,
            "positive_fold_fraction_gte": 0.80,
            "median_excess_vs_always_btc_gt": 0.0,
            "median_excess_vs_shared_crypto_v3_gt": 0.0,
            "positive_excess_vs_shared_crypto_v3_fraction_gte": 0.80,
            "worst_maximum_drawdown_gte": -0.20,
            "single_fold_profit_concentration_lte": 0.40,
            "survives_stress_cost_bps": 50.0,
        },
        "research_constraints": {
            "single_fixed_top_n": True,
            "no_post_result_threshold_search": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
    }
    return risk, selection, contract


def run(source_root: Path = V4_PHASE1_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    source_root = Path(source_root)
    output_root = Path(output_root)
    v4_contract = json.loads(
        (source_root / "preregistered_contract.json").read_text(encoding="utf-8")
    )
    regime = pd.read_parquet(source_root / "regime_dataset.parquet")
    ranking = pd.read_parquet(source_root / "ranking_dataset.parquet")
    risk, selection, contract = build_datasets(regime, ranking, v4_contract)

    output_root.mkdir(parents=True, exist_ok=True)
    risk_path = output_root / "market_risk_dataset.parquet"
    selection_path = output_root / "alt_selection_dataset.parquet"
    contract_path = output_root / "preregistered_contract.json"
    risk.to_parquet(risk_path, index=False)
    selection.to_parquet(selection_path, index=False)
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "preregistered_selective_rank_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "market_risk_rows": int(len(risk)),
        "alt_selection_rows": int(len(selection)),
        "date_range": {
            "start": min(risk["timestamp_utc"].min(), selection["timestamp_utc"].min()).isoformat(),
            "end": max(risk["timestamp_utc"].max(), selection["timestamp_utc"].max()).isoformat(),
        },
        "outputs": {
            "market_risk_dataset": str(risk_path),
            "alt_selection_dataset": str(selection_path),
            "contract": str(contract_path),
            "manifest": str(output_root / "manifest.json"),
        },
        "hashes": {
            "market_risk_dataset": _sha256(risk_path),
            "alt_selection_dataset": _sha256(selection_path),
            "contract": _sha256(contract_path),
        },
        "safety": {
            "shared_crypto_v3_modified": False,
            "rejected_v4_modified": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": "Run purged walk-forward risk, excess-return, and downside models without scoring the future holdout.",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=V4_PHASE1_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.source_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
