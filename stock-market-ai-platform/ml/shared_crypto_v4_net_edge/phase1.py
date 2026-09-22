"""Shared Crypto V4 Phase 1: causal net-edge research datasets.

Builds two hourly, pre-holdout datasets from the frozen Crypto 15m V1 panels:

* a BTC / equal-weight ALT / CASH regime dataset; and
* a per-asset ALT ranking dataset.

The primary target is aligned with the one-hour execution interval.  A four-hour
target is retained only as a preregistered secondary horizon.  This phase does
not fit models, inspect the future holdout, tune a policy, simulate a portfolio,
modify Shared Crypto V3, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v4_net_edge"
SOURCE_ROOT = Path("data/model/crypto_15m_v1/phase1/core_panel")
OUTPUT_ROOT = Path("data/model/shared_crypto_v4_net_edge/phase1")
REGIME_DATASET_PATH = OUTPUT_ROOT / "regime_dataset.parquet"
RANKING_DATASET_PATH = OUTPUT_ROOT / "ranking_dataset.parquet"
CONTRACT_PATH = OUTPUT_ROOT / "preregistered_contract.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BTC = "BTC-USD"
XRP = "XRP-USD"
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
DECISION_FREQUENCY_MINUTES = 60
PRIMARY_HORIZON = "1h"
SECONDARY_HORIZON = "4h"
MIN_ALT_ASSETS = 10

ASSET_FEATURES = [
    "candle_return", "range_pct", "upper_wick_pct", "lower_wick_pct",
    "return_1bar", "return_2bar", "return_4bar", "return_8bar",
    "return_16bar", "return_32bar", "return_96bar",
    "realized_volatility_4bar", "realized_volatility_16bar",
    "realized_volatility_96bar", "close_to_sma_4bar",
    "close_to_sma_16bar", "close_to_sma_96bar",
    "volume_to_average_4bar", "volume_to_average_16bar",
    "volume_to_average_96bar", "dollar_volume_to_average_4bar",
    "dollar_volume_to_average_16bar", "dollar_volume_to_average_96bar",
    "drawdown_from_high_96bar", "btc_relative_return_1bar",
    "btc_relative_return_4bar", "btc_relative_return_16bar",
    "btc_relative_return_96bar", "utc_time_sin", "utc_time_cos",
    "utc_dow_sin", "utc_dow_cos",
]

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
    ["timestamp_utc", "product_id", "close", "volume",
     "forward_return_1h", "forward_return_4h"]
    + ASSET_FEATURES + BTC_STATE_FEATURES + ALT_STATE_FEATURES
))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_panel(root: Path = SOURCE_ROOT) -> pd.DataFrame:
    paths = sorted(Path(root).glob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"No Crypto 15m V1 core panels found under {root}")
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        missing = set(SOURCE_COLUMNS) - set(frame.columns)
        if missing:
            raise RuntimeError(f"{path.name} missing required V4 columns: {sorted(missing)}")
        frames.append(frame[SOURCE_COLUMNS].copy())
    panel = pd.concat(frames, ignore_index=True)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START].copy()
    panel = panel[(panel["timestamp_utc"].dt.minute == 0) &
                  (panel["timestamp_utc"].dt.second == 0)].copy()
    panel = panel.drop_duplicates(["timestamp_utc", "product_id"], keep="last")
    if XRP in set(panel["product_id"]):
        raise RuntimeError("XRP leaked into the Shared Crypto V4 core universe")
    if BTC not in set(panel["product_id"]):
        raise RuntimeError("BTC-USD is missing from the Shared Crypto V4 source")
    return panel.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def _regime_dataset(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    btc = panel[panel["product_id"] == BTC].copy()
    alts = panel[panel["product_id"] != BTC].copy()

    btc_columns = ["timestamp_utc", "forward_return_1h", "forward_return_4h"] + BTC_STATE_FEATURES
    btc_state = btc[btc_columns].drop_duplicates("timestamp_utc").rename(columns={
        "forward_return_1h": "btc_forward_return_1h",
        "forward_return_4h": "btc_forward_return_4h",
        **{column: f"btc_{column}" for column in BTC_STATE_FEATURES},
    })

    aggregation: dict[str, tuple[str, object]] = {
        "alt_forward_return_1h": ("forward_return_1h", "mean"),
        "alt_forward_return_4h": ("forward_return_4h", "mean"),
        "alt_asset_count": ("product_id", "nunique"),
    }
    for column in ALT_STATE_FEATURES:
        aggregation[f"alt_mean_{column}"] = (column, "mean")
        aggregation[f"alt_median_{column}"] = (column, "median")

    alt_state = alts.groupby("timestamp_utc", sort=True).agg(**aggregation).reset_index()
    breadth = alts.groupby("timestamp_utc", sort=True).agg(
        alt_positive_1bar_fraction=("return_1bar", lambda values: float((values > 0).mean())),
        alt_positive_4bar_fraction=("return_4bar", lambda values: float((values > 0).mean())),
        alt_positive_16bar_fraction=("return_16bar", lambda values: float((values > 0).mean())),
        alt_outperforming_btc_1bar_fraction=("btc_relative_return_1bar", lambda values: float((values > 0).mean())),
        alt_outperforming_btc_4bar_fraction=("btc_relative_return_4bar", lambda values: float((values > 0).mean())),
        alt_return_1bar_dispersion=("return_1bar", lambda values: float(values.std(ddof=0))),
        alt_return_4bar_dispersion=("return_4bar", lambda values: float(values.std(ddof=0))),
        alt_volatility_dispersion=("realized_volatility_16bar", lambda values: float(values.std(ddof=0))),
    ).reset_index()

    data = btc_state.merge(alt_state, on="timestamp_utc", validate="one_to_one")
    data = data.merge(breadth, on="timestamp_utc", validate="one_to_one")
    data = data[data["alt_asset_count"] >= MIN_ALT_ASSETS].copy()
    data["cash_forward_return_1h"] = 0.0
    data["cash_forward_return_4h"] = 0.0

    for horizon in (PRIMARY_HORIZON, SECONDARY_HORIZON):
        columns = [f"btc_forward_return_{horizon}", f"alt_forward_return_{horizon}",
                   f"cash_forward_return_{horizon}"]
        values = data[columns].to_numpy(float)
        labels = np.array(["BTC", "ALT", "CASH"], dtype=object)
        data[f"best_sleeve_{horizon}"] = labels[np.argmax(values, axis=1)]
        data[f"best_return_{horizon}"] = np.max(values, axis=1)
        data[f"btc_minus_alt_forward_return_{horizon}"] = values[:, 0] - values[:, 1]

    target_columns = {
        column for column in data.columns
        if "forward_return" in column or column.startswith("best_sleeve_")
        or column.startswith("best_return_")
    }
    feature_columns = [column for column in data.columns
                       if column != "timestamp_utc" and column not in target_columns]
    required = feature_columns + sorted(target_columns)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    return data.sort_values("timestamp_utc").reset_index(drop=True), feature_columns


def _ranking_dataset(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    alts = panel[panel["product_id"] != BTC].copy()
    alts["dollar_volume"] = pd.to_numeric(alts["close"], errors="coerce") * pd.to_numeric(
        alts["volume"], errors="coerce")

    ranked_features = [
        "return_1bar", "return_4bar", "return_16bar",
        "btc_relative_return_1bar", "btc_relative_return_4bar",
        "btc_relative_return_16bar", "realized_volatility_16bar",
        "volume_to_average_16bar", "dollar_volume",
    ]
    for column in ranked_features:
        alts[f"cross_sectional_rank_{column}"] = alts.groupby("timestamp_utc")[column].rank(
            method="average", pct=True)

    alts["forward_risk_adjusted_return_1h"] = alts["forward_return_1h"] / alts[
        "realized_volatility_16bar"].clip(lower=1e-8)
    alts["forward_risk_adjusted_return_4h"] = alts["forward_return_4h"] / alts[
        "realized_volatility_16bar"].clip(lower=1e-8)
    alts["eligible_asset_count"] = alts.groupby("timestamp_utc")["product_id"].transform("nunique")
    alts = alts[alts["eligible_asset_count"] >= MIN_ALT_ASSETS].copy()

    rank_columns = [f"cross_sectional_rank_{column}" for column in ranked_features]
    feature_columns = ASSET_FEATURES + ["dollar_volume", "eligible_asset_count"] + rank_columns
    target_columns = [
        "forward_return_1h", "forward_return_4h",
        "forward_risk_adjusted_return_1h", "forward_risk_adjusted_return_4h",
    ]
    keep = ["timestamp_utc", "product_id"] + feature_columns + target_columns
    alts = alts.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_columns + target_columns)
    return alts[keep].sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True), feature_columns


def build_datasets(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = panel.copy()
    source["timestamp_utc"] = pd.to_datetime(source["timestamp_utc"], utc=True)
    source = source[source["timestamp_utc"] < FUTURE_HOLDOUT_START].copy()
    source = source[(source["timestamp_utc"].dt.minute == 0) &
                    (source["timestamp_utc"].dt.second == 0)].copy()
    regime, regime_features = _regime_dataset(source)
    ranking, ranking_features = _ranking_dataset(source)
    if regime.empty or ranking.empty:
        raise RuntimeError("Shared Crypto V4 Phase 1 produced an empty dataset")

    contract = {
        "research_version": RESEARCH_VERSION,
        "stage": "horizon_aligned_dual_layer_dataset",
        "primary_decision_frequency_minutes": DECISION_FREQUENCY_MINUTES,
        "primary_prediction_horizon": PRIMARY_HORIZON,
        "secondary_prediction_horizon": SECONDARY_HORIZON,
        "architecture": {
            "layer_1": "predict BTC, selective ALT, and CASH expected returns",
            "layer_2": "rank eligible ALT assets only when the regime layer permits ALT exposure",
            "execution_objective": "switch only when predicted net edge exceeds all-in cost and uncertainty buffer",
        },
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "model_candidates": {
            "regime": ["ridge", "hist_gradient_boosting_regressor"],
            "ranking": ["ridge", "hist_gradient_boosting_regressor"],
        },
        "portfolio_candidates": {
            "top_n": [3, 5],
            "round_trip_cost_bps": [5, 10, 25, 50],
            "maximum_turnover_per_decision": 0.50,
            "minimum_cash_weight": 0.10,
            "maximum_single_asset_weight": 0.25,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": {
            "median_fold_net_excess_vs_shared_v3_gt": 0.0,
            "positive_fold_fraction_gte": 0.75,
            "net_excess_vs_btc_gt": 0.0,
            "survives_cost_bps": 25,
            "single_fold_profit_concentration_lte": 0.50,
            "maximum_drawdown_not_worse_than_shared_v3_by_more_than_pct_points": 5.0,
        },
        "regime_feature_columns": regime_features,
        "ranking_feature_columns": ranking_features,
        "safety": {
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "human_review_required": True,
        },
    }
    return regime, ranking, contract


def run(source_root: Path = SOURCE_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    source_root = Path(source_root)
    output_root = Path(output_root)
    panel = load_source_panel(source_root)
    regime, ranking, contract = build_datasets(panel)
    output_root.mkdir(parents=True, exist_ok=True)
    regime_path = output_root / "regime_dataset.parquet"
    ranking_path = output_root / "ranking_dataset.parquet"
    contract_path = output_root / "preregistered_contract.json"
    manifest_path = output_root / "manifest.json"
    regime.to_parquet(regime_path, index=False)
    ranking.to_parquet(ranking_path, index=False)
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "horizon_aligned_dual_layer_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "source_panel_rows": int(len(panel)),
        "regime_rows": int(len(regime)),
        "ranking_rows": int(len(ranking)),
        "date_range": {
            "start": regime["timestamp_utc"].min().isoformat(),
            "end": regime["timestamp_utc"].max().isoformat(),
        },
        "outputs": {
            "regime_dataset": str(regime_path),
            "ranking_dataset": str(ranking_path),
            "contract": str(contract_path),
            "manifest": str(manifest_path),
        },
        "hashes": {
            "regime_dataset": _sha256(regime_path),
            "ranking_dataset": _sha256(ranking_path),
            "contract": _sha256(contract_path),
        },
        "safety": contract["safety"],
        "next_step": "Run purged walk-forward return regression without scoring the future holdout.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.source_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
