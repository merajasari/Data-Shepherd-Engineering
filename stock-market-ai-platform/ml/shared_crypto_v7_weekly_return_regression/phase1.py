"""Shared Crypto V7 Weekly Return Regression Phase 1 dataset.

V7 is a separately named hypothesis created only after V6 was immutably
rejected.  It replaces the imbalanced BTC/ALT/CASH classification target with
two learned exact seven-day net-return targets: BTC and a deterministic
point-in-time liquid Top-5 ALT basket.

This phase preregisters the dataset, targets, models, policy, and gates before
V7 results exist.  It fits no model, simulates no portfolio, does not inspect
the future holdout, and cannot modify a paper lane or place an order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v7_weekly_return_regression"
SOURCE_ROOT = Path("data/model/crypto_15m_v1/phase1/core_panel")
OUTPUT_ROOT = Path("data/model/shared_crypto_v7_weekly_return_regression/phase1")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
BTC = "BTC-USD"
XRP = "XRP-USD"
MIN_ALT_ASSETS = 10
HORIZON_HOURS = 168
DECISION_HOUR_UTC = 0
LIQUID_ALT_COUNT = 5
LIQUIDITY_LOOKBACK_HOURS = 24
PRIMARY_COST_BPS = 25.0
STRESS_COST_BPS = 50.0

BTC_STATE_FEATURES = [
    "return_1bar", "return_4bar", "return_16bar", "return_96bar",
    "realized_volatility_4bar", "realized_volatility_16bar",
    "realized_volatility_96bar", "close_to_sma_4bar",
    "close_to_sma_16bar", "close_to_sma_96bar",
    "volume_to_average_4bar", "volume_to_average_16bar",
    "volume_to_average_96bar", "drawdown_from_high_96bar",
    "utc_time_sin", "utc_time_cos", "utc_dow_sin", "utc_dow_cos",
]

ALT_STATE_FEATURES = [
    "return_1bar", "return_4bar", "return_16bar", "return_96bar",
    "btc_relative_return_1bar", "btc_relative_return_4bar",
    "btc_relative_return_16bar", "realized_volatility_4bar",
    "realized_volatility_16bar", "realized_volatility_96bar",
    "volume_to_average_4bar", "volume_to_average_16bar",
    "dollar_volume_to_average_16bar", "drawdown_from_high_96bar",
]
SOURCE_COLUMNS = sorted(set(
    ["timestamp_utc", "product_id", "close", "volume"]
    + BTC_STATE_FEATURES + ALT_STATE_FEATURES
))


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


def load_source_panel(root: Path = SOURCE_ROOT) -> pd.DataFrame:
    paths = sorted(Path(root).glob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"No Crypto 15m V1 core panels found under {root}")
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        missing = set(SOURCE_COLUMNS) - set(frame.columns)
        if missing:
            raise RuntimeError(f"{path.name} missing required V7 columns: {sorted(missing)}")
        frames.append(frame[SOURCE_COLUMNS].copy())
    panel = pd.concat(frames, ignore_index=True)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < HOLDOUT].copy()
    panel = panel[
        (panel["timestamp_utc"].dt.minute == 0)
        & (panel["timestamp_utc"].dt.second == 0)
    ].copy()
    panel = panel.drop_duplicates(["timestamp_utc", "product_id"], keep="last")
    if XRP in set(panel["product_id"]):
        raise RuntimeError("XRP leaked into the Shared Crypto V7 core universe")
    if BTC not in set(panel["product_id"]):
        raise RuntimeError("BTC-USD is missing from the Shared Crypto V7 source")
    return panel.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def _attach_exact_horizon_returns(
    panel: pd.DataFrame, horizon_hours: int = HORIZON_HOURS
) -> pd.DataFrame:
    """Attach forward and trailing values only at the exact requested clock."""
    frame = panel.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, "V7 source panel")
    delta = timedelta(hours=int(horizon_hours))

    future = frame[["timestamp_utc", "product_id", "close"]].copy()
    future["timestamp_utc"] = future["timestamp_utc"] - delta
    future = future.rename(columns={"close": "future_close_exact_168h"})
    frame = frame.merge(
        future,
        on=["timestamp_utc", "product_id"],
        how="left",
        validate="one_to_one",
    )

    past = frame[["timestamp_utc", "product_id", "close"]].copy()
    past["timestamp_utc"] = past["timestamp_utc"] + delta
    past = past.rename(columns={"close": "past_close_exact_168h"})
    frame = frame.merge(
        past,
        on=["timestamp_utc", "product_id"],
        how="left",
        validate="one_to_one",
    )
    frame["forward_return_168h"] = (
        frame["future_close_exact_168h"] / frame["close"] - 1.0
    )
    frame["trailing_return_168h"] = (
        frame["close"] / frame["past_close_exact_168h"] - 1.0
    )
    return frame


def _daily_assets(panel: pd.DataFrame) -> pd.DataFrame:
    frame = _attach_exact_horizon_returns(panel)
    frame = frame.sort_values(["product_id", "timestamp_utc"]).reset_index(drop=True)
    frame["dollar_volume"] = (
        pd.to_numeric(frame["close"], errors="coerce")
        * pd.to_numeric(frame["volume"], errors="coerce")
    )
    frame["trailing_dollar_volume_24h"] = frame.groupby(
        "product_id", sort=False
    )["dollar_volume"].transform(
        lambda values: values.rolling(
            LIQUIDITY_LOOKBACK_HOURS,
            min_periods=LIQUIDITY_LOOKBACK_HOURS,
        ).mean()
    )
    frame = frame[
        (frame["timestamp_utc"].dt.hour == DECISION_HOUR_UTC)
        & (frame["timestamp_utc"].dt.minute == 0)
        & (frame["timestamp_utc"].dt.second == 0)
    ].copy()
    return frame.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def build_datasets(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = panel.copy()
    source["timestamp_utc"] = pd.to_datetime(source["timestamp_utc"], utc=True)
    validate_pre_holdout(source, "V7 source panel")
    if XRP in set(source["product_id"]):
        raise RuntimeError("XRP leaked into the Shared Crypto V7 core universe")
    if BTC not in set(source["product_id"]):
        raise RuntimeError("BTC-USD is missing from the Shared Crypto V7 source")
    required = {
        "timestamp_utc", "product_id", "close", "volume",
        *BTC_STATE_FEATURES, *ALT_STATE_FEATURES,
    }
    missing = required - set(source.columns)
    if missing:
        raise RuntimeError(f"V7 source panel missing columns: {sorted(missing)}")

    daily = _daily_assets(source)
    btc = daily[daily["product_id"] == BTC].copy()
    alts = daily[daily["product_id"] != BTC].copy()
    # Point-in-time eligibility and ranking must not depend on whether a future
    # label happens to be available.  Label completeness is checked only after
    # the deterministic basket has been selected.
    alt_required = [
        "trailing_return_168h", "trailing_dollar_volume_24h",
        *ALT_STATE_FEATURES,
    ]
    alts = alts.replace([np.inf, -np.inf], np.nan).dropna(subset=alt_required)
    alts["eligible_asset_count"] = alts.groupby("timestamp_utc")[
        "product_id"
    ].transform("nunique")
    alts = alts[alts["eligible_asset_count"] >= MIN_ALT_ASSETS].copy()
    alts = alts.sort_values(
        ["timestamp_utc", "trailing_dollar_volume_24h", "product_id"],
        ascending=[True, False, True],
    )
    alts["liquidity_rank"] = alts.groupby("timestamp_utc").cumcount() + 1
    alts["selected_liquid_top5"] = alts["liquidity_rank"] <= LIQUID_ALT_COUNT

    basket = alts[alts["selected_liquid_top5"]].groupby(
        "timestamp_utc", sort=True
    ).agg(
        alt_forward_return_168h=("forward_return_168h", "mean"),
        alt_forward_label_count=("forward_return_168h", "count"),
        alt_basket_size=("product_id", "nunique"),
        alt_basket_assets=("product_id", lambda values: "|".join(sorted(values))),
    ).reset_index()
    basket = basket[
        basket["alt_forward_label_count"] == LIQUID_ALT_COUNT
    ].drop(columns="alt_forward_label_count")

    aggregations: dict[str, tuple[str, object]] = {
        "alt_asset_count": ("product_id", "nunique"),
        "alt_positive_1bar_fraction": (
            "return_1bar", lambda values: float((values > 0.0).mean())
        ),
        "alt_positive_4bar_fraction": (
            "return_4bar", lambda values: float((values > 0.0).mean())
        ),
        "alt_outperforming_btc_4bar_fraction": (
            "btc_relative_return_4bar", lambda values: float((values > 0.0).mean())
        ),
        "alt_return_4bar_dispersion": (
            "return_4bar", lambda values: float(values.std(ddof=0))
        ),
        "alt_volatility_dispersion": (
            "realized_volatility_16bar", lambda values: float(values.std(ddof=0))
        ),
        "alt_mean_trailing_return_168h": ("trailing_return_168h", "mean"),
        "alt_median_trailing_return_168h": ("trailing_return_168h", "median"),
        "alt_positive_trailing_return_168h_fraction": (
            "trailing_return_168h", lambda values: float((values > 0.0).mean())
        ),
    }
    for column in ALT_STATE_FEATURES:
        aggregations[f"alt_mean_{column}"] = (column, "mean")
        aggregations[f"alt_median_{column}"] = (column, "median")
    alt_state = alts.groupby("timestamp_utc", sort=True).agg(
        **aggregations
    ).reset_index()

    btc_columns = [
        "timestamp_utc", "forward_return_168h", "trailing_return_168h",
        *BTC_STATE_FEATURES,
    ]
    btc_state = btc[btc_columns].drop_duplicates("timestamp_utc").rename(columns={
        "forward_return_168h": "btc_forward_return_168h",
        "trailing_return_168h": "btc_trailing_return_168h",
        **{column: f"btc_{column}" for column in BTC_STATE_FEATURES},
    })
    regime = btc_state.merge(alt_state, on="timestamp_utc", validate="one_to_one")
    regime = regime.merge(basket, on="timestamp_utc", validate="one_to_one")
    regime = regime[regime["alt_basket_size"] == LIQUID_ALT_COUNT].copy()
    cost = PRIMARY_COST_BPS / 10000.0
    regime["btc_net_entry_return_168h"] = regime["btc_forward_return_168h"] - cost
    regime["alt_net_entry_return_168h"] = regime["alt_forward_return_168h"] - cost
    regime["realized_best_net_sleeve_168h"] = np.where(
        regime["btc_net_entry_return_168h"]
        >= regime["alt_net_entry_return_168h"],
        "BTC",
        "ALT",
    )

    target_columns = {
        "btc_forward_return_168h", "alt_forward_return_168h",
        "btc_net_entry_return_168h", "alt_net_entry_return_168h",
        "realized_best_net_sleeve_168h", "alt_basket_assets", "alt_basket_size",
    }
    feature_columns = [
        column for column in regime.columns
        if column != "timestamp_utc" and column not in target_columns
    ]
    numeric_required = feature_columns + [
        "btc_forward_return_168h", "alt_forward_return_168h",
        "btc_net_entry_return_168h", "alt_net_entry_return_168h",
    ]
    regime = regime.replace([np.inf, -np.inf], np.nan).dropna(
        subset=numeric_required
    )
    complete_alt_clock = alts.groupby("timestamp_utc")[
        "forward_return_168h"
    ].apply(lambda values: bool(values.notna().all()))
    complete_alt_clock = set(complete_alt_clock[complete_alt_clock].index)
    regime = regime[regime["timestamp_utc"].isin(complete_alt_clock)].copy()
    regime = regime.sort_values("timestamp_utc").reset_index(drop=True)
    valid_clock = set(regime["timestamp_utc"])
    alts = alts[alts["timestamp_utc"].isin(valid_clock)].copy()
    asset_columns = [
        "timestamp_utc", "product_id", "close", "forward_return_168h",
        "trailing_return_168h", "trailing_dollar_volume_24h",
        "eligible_asset_count", "liquidity_rank", "selected_liquid_top5",
    ]
    assets = alts[asset_columns].sort_values(
        ["timestamp_utc", "liquidity_rank"]
    ).reset_index(drop=True)
    if regime.empty or assets.empty:
        raise RuntimeError("Shared Crypto V7 Phase 1 produced an empty dataset")

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "preregistered_weekly_return_regression_dataset",
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "new_hypothesis_after_rejection": {
            "rejected_parent": "shared_crypto_v6_durable_edge",
            "parent_disposition": "REJECT_CURRENT_V6_POLICY_FAMILY",
            "observed_failure_addressed": (
                "The imbalanced three-class 24-hour target collapsed toward cash, "
                "never allocated to BTC, produced only two positive folds, and "
                "concentrated nearly eighty percent of profit in one fold."
            ),
            "v6_thresholds_retuned": False,
        },
        "decision_cadence": "daily at 00:00 UTC",
        "economic_horizon": "exact 168 hours",
        "hypothesis": (
            "Separate learned seven-day net-return regressions can estimate the "
            "magnitude of durable BTC and liquid-ALT opportunity without the "
            "class-imbalance failure of direct BTC/ALT/CASH classification."
        ),
        "model_candidates": {
            "primary": "two_hist_gradient_boosting_absolute_error_regressors",
            "diagnostic_only": "two_ridge_regressors",
            "targets": [
                "btc_net_entry_return_168h",
                "alt_net_entry_return_168h",
            ],
            "target_search": False,
        },
        "walk_forward_contract": {
            "expanding_training_window": True,
            "purge_hours": HORIZON_HOURS,
            "validation_days": 180,
            "maximum_folds": 6,
            "primary_model_selected_before_results": True,
        },
        "regime_feature_columns": feature_columns,
        "alt_sleeve": {
            "construction": "equal-weight deterministic point-in-time liquidity basket",
            "top_n": LIQUID_ALT_COUNT,
            "liquidity_measure": "trailing mean hourly close times volume over 24 hours",
            "learned_ranker": False,
        },
        "frozen_policy_for_later_simulation": {
            "decision_hour_utc": DECISION_HOUR_UTC,
            "minimum_hold_hours": HORIZON_HOURS,
            "confirmation_count": 2,
            "sleeve_rule": (
                "Choose the larger predicted net return when it is greater than "
                "zero; otherwise choose CASH."
            ),
            "minimum_predicted_net_return": 0.0,
            "primary_round_trip_cost_bps": PRIMARY_COST_BPS,
            "stress_round_trip_cost_bps": STRESS_COST_BPS,
            "minimum_cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "maximum_btc_weight": 0.60,
            "maximum_alt_weight": 0.12,
            "maximum_turnover_per_daily_decision": 0.30,
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
            "survives_stress_cost_bps": STRESS_COST_BPS,
        },
        "research_constraints": {
            "one_primary_model_family": True,
            "one_fixed_policy": True,
            "no_post_result_threshold_search": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            "automatic_promotion": False,
            "human_review_required": True,
        },
    }
    return regime, assets, contract


def run(source_root: Path = SOURCE_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    source_root = Path(source_root)
    output_root = Path(output_root)
    panel = load_source_panel(source_root)
    regime, assets, contract = build_datasets(panel)
    output_root.mkdir(parents=True, exist_ok=True)
    regime_path = output_root / "daily_regression_dataset.parquet"
    assets_path = output_root / "daily_asset_dataset.parquet"
    contract_path = output_root / "preregistered_contract.json"
    regime.to_parquet(regime_path, index=False)
    assets.to_parquet(assets_path, index=False)
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "preregistered_weekly_return_regression_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "source_rows": int(len(panel)),
        "regime_rows": int(len(regime)),
        "asset_rows": int(len(assets)),
        "date_range": {
            "start": regime["timestamp_utc"].min().isoformat(),
            "end": regime["timestamp_utc"].max().isoformat(),
        },
        "outputs": {
            "daily_regression_dataset": str(regime_path),
            "daily_asset_dataset": str(assets_path),
            "contract": str(contract_path),
            "manifest": str(output_root / "manifest.json"),
        },
        "hashes": {
            "daily_regression_dataset": _sha256(regime_path),
            "daily_asset_dataset": _sha256(assets_path),
            "contract": _sha256(contract_path),
        },
        "safety": {
            "v5_modified": False,
            "v6_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "model_fitted": False,
            "portfolio_simulated": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Fit the preregistered 168-hour-purged walk-forward regressors "
            "without scoring the future holdout."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.source_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
