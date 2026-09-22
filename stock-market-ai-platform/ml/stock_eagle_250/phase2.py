"""StockEagle250 Phase 2: preregistered panel and purged folds.

This phase builds a development-only, point-in-time cross-sectional panel for
250 candidate stocks. It creates executable next-open-to-fifth-close targets,
SPY-relative labels, decision-time cross-sectional feature ranks, and expanding
walk-forward folds with exact target-endpoint purging.

It does not fit a model, inspect future holdout results, paper trade, place
orders, or modify any established stock-model artifacts.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from ml.stock_eagle_250 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = PROJECT_ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from stock_universe_250 import (  # noqa: E402
    STOCK_250_SYMBOLS,
    get_stock_250_sector,
)
from v5_symbols import V5_BENCHMARK_SYMBOL  # noqa: E402


PHASE = 2
TARGET_HORIZON_SESSIONS = 5
MINIMUM_HISTORY_SESSIONS = 252
DEVELOPMENT_VALIDATION_START_UTC = pd.Timestamp("2020-01-01", tz="UTC")
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-23", tz="UTC")
VALIDATION_MONTHS = 6

FEATURE_ROOT = Path("data/features/stocks")
PHASE_ROOT = Path("data/model/stock_eagle_250/phase2")
PANEL_PATH = PHASE_ROOT / "research_panel.parquet"
FOLDS_PATH = PHASE_ROOT / "folds.json"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"
CONTRACT_PATH = Path(__file__).with_name("phase2_contract.json")

RAW_FEATURE_COLUMNS = (
    "daily_return",
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_centered",
)
RANK_FEATURE_COLUMNS = tuple(f"{column}_xrank" for column in RAW_FEATURE_COLUMNS)
TARGET_COLUMN = "forward_relative_return_5d"
ENTRY_COLUMN = "entry_timestamp_utc_5d"
ENDPOINT_COLUMN = "target_endpoint_utc_5d"


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected_identity = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    mismatches = {
        key: {"expected": expected, "actual": contract.get(key)}
        for key, expected in expected_identity.items()
        if contract.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"StockEagle250 Phase 2 identity mismatch: {mismatches}")

    registered_features = tuple(
        contract["features"]["raw_point_in_time_columns"]
    )
    if registered_features != RAW_FEATURE_COLUMNS:
        raise ValueError("Phase 2 code feature order differs from the contract")

    boundary = _utc(contract["untouched_future_holdout"]["start_utc"])
    if boundary != FUTURE_HOLDOUT_START_UTC:
        raise ValueError("Phase 2 code holdout boundary differs from the contract")

    if contract["target"]["horizon_completed_sessions"] != TARGET_HORIZON_SESSIONS:
        raise ValueError("Phase 2 code target horizon differs from the contract")
    return contract


def feature_path(symbol: str, feature_root: Path = FEATURE_ROOT) -> Path:
    return Path(feature_root) / symbol / f"{symbol}_features.parquet"


def load_feature_frame(symbol: str, feature_root: Path = FEATURE_ROOT) -> pd.DataFrame:
    path = feature_path(symbol, feature_root)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Feature history is missing for {symbol}: {path}")

    columns = ["timestamp_utc", "open", "close", *RAW_FEATURE_COLUMNS]
    frame = pd.read_parquet(path, columns=columns).copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
        errors="raise",
    )
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)

    if frame.empty:
        raise ValueError(f"Feature history is empty for {symbol}")
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError(f"Duplicate feature timestamps for {symbol}")
    return frame


def add_executable_forward_return(
    frame: pd.DataFrame,
    prefix: str,
    horizon: int = TARGET_HORIZON_SESSIONS,
) -> pd.DataFrame:
    """Add next-session-open to horizon-session-close return and timestamps."""
    if horizon < 1:
        raise ValueError("horizon must be positive")

    result = frame.copy()
    result[f"{prefix}_entry_timestamp_utc"] = result["timestamp_utc"].shift(-1)
    result[f"{prefix}_target_endpoint_utc"] = result["timestamp_utc"].shift(-horizon)
    result[f"forward_{prefix}_return"] = (
        result["close"].shift(-horizon)
        / result["open"].shift(-1)
        - 1.0
    )
    return result


def build_benchmark_frame(
    feature_root: Path = FEATURE_ROOT,
) -> pd.DataFrame:
    benchmark = load_feature_frame(V5_BENCHMARK_SYMBOL, feature_root)[
        ["timestamp_utc", "open", "close"]
    ]
    benchmark = add_executable_forward_return(benchmark, "spy")
    return benchmark[
        [
            "timestamp_utc",
            "spy_entry_timestamp_utc",
            "spy_target_endpoint_utc",
            "forward_spy_return",
        ]
    ]


def build_candidate_frame(
    symbol: str,
    benchmark: pd.DataFrame,
    feature_root: Path = FEATURE_ROOT,
) -> pd.DataFrame:
    frame = load_feature_frame(symbol, feature_root)
    frame.insert(0, "symbol", symbol)
    frame.insert(1, "sector", get_stock_250_sector(symbol))
    frame["observed_sessions"] = range(1, len(frame) + 1)
    frame["history_eligible"] = (
        frame["observed_sessions"] >= MINIMUM_HISTORY_SESSIONS
    )
    frame["feature_complete"] = (
        frame[list(RAW_FEATURE_COLUMNS)].notna().all(axis=1)
    )

    frame = add_executable_forward_return(frame, "stock")
    frame = frame.merge(
        benchmark,
        on="timestamp_utc",
        how="inner",
        validate="one_to_one",
    )

    entry_matches = frame["stock_entry_timestamp_utc"].eq(
        frame["spy_entry_timestamp_utc"]
    )
    endpoint_matches = frame["stock_target_endpoint_utc"].eq(
        frame["spy_target_endpoint_utc"]
    )
    labeled = (
        entry_matches
        & endpoint_matches
        & frame["forward_stock_return"].notna()
        & frame["forward_spy_return"].notna()
    )

    frame["entry_matches_spy_5d"] = entry_matches
    frame["endpoint_matches_spy_5d"] = endpoint_matches
    frame["is_labeled_5d"] = labeled
    frame[TARGET_COLUMN] = (
        frame["forward_stock_return"] - frame["forward_spy_return"]
    ).where(labeled)
    frame[ENTRY_COLUMN] = frame["stock_entry_timestamp_utc"]
    frame[ENDPOINT_COLUMN] = frame["stock_target_endpoint_utc"]
    return frame


def add_cross_sectional_ranks(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    grouped = result.groupby("timestamp_utc", sort=False)
    for raw_column, rank_column in zip(
        RAW_FEATURE_COLUMNS,
        RANK_FEATURE_COLUMNS,
    ):
        result[rank_column] = grouped[raw_column].rank(
            method="average",
            pct=True,
            ascending=True,
        )
    return result


def validate_panel(
    panel: pd.DataFrame,
    expected_symbols=STOCK_250_SYMBOLS,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
) -> None:
    expected_symbols = set(expected_symbols)
    actual_symbols = set(panel["symbol"])
    problems = []

    if V5_BENCHMARK_SYMBOL in actual_symbols:
        problems.append("SPY appears in the investable candidate panel")
    if actual_symbols != expected_symbols:
        problems.append(
            "Candidate mismatch: "
            f"missing={sorted(expected_symbols - actual_symbols)}, "
            f"unexpected={sorted(actual_symbols - expected_symbols)}"
        )
    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        problems.append("Duplicate timestamp_utc/symbol rows")
    if not panel["timestamp_utc"].is_monotonic_increasing:
        problems.append("Panel is not globally sorted by timestamp_utc")

    holdout_start = _utc(holdout_start)
    if (panel["timestamp_utc"] >= holdout_start).any():
        problems.append("Development panel includes a holdout decision timestamp")
    if (panel[ENDPOINT_COLUMN] >= holdout_start).any():
        problems.append("Development panel includes a target ending in the holdout")

    labeled_missing = panel["is_labeled_5d"] & panel[TARGET_COLUMN].isna()
    if labeled_missing.any():
        problems.append("Labeled rows contain missing relative targets")

    for column in RANK_FEATURE_COLUMNS:
        observed = panel[column].dropna()
        if ((observed <= 0.0) | (observed > 1.0)).any():
            problems.append(f"Cross-sectional rank is outside (0, 1]: {column}")

    if problems:
        raise ValueError("StockEagle250 Phase 2 panel validation failed:\n- " + "\n- ".join(problems))


def build_panel(
    symbols=STOCK_250_SYMBOLS,
    feature_root: Path = FEATURE_ROOT,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
) -> pd.DataFrame:
    symbols = tuple(symbols)
    if len(symbols) != 250 or len(set(symbols)) != 250:
        raise ValueError("Phase 2 requires exactly 250 unique candidate symbols")

    missing = [
        symbol
        for symbol in (*symbols, V5_BENCHMARK_SYMBOL)
        if not feature_path(symbol, feature_root).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Phase 2 feature histories are missing: " + ", ".join(missing)
        )

    benchmark = build_benchmark_frame(feature_root)
    frames = [
        build_candidate_frame(symbol, benchmark, feature_root)
        for symbol in symbols
    ]
    panel = pd.concat(frames, ignore_index=True)

    holdout_start = _utc(holdout_start)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel[ENTRY_COLUMN] = pd.to_datetime(panel[ENTRY_COLUMN], utc=True)
    panel[ENDPOINT_COLUMN] = pd.to_datetime(panel[ENDPOINT_COLUMN], utc=True)

    development_mask = (
        (panel["timestamp_utc"] < holdout_start)
        & (panel[ENTRY_COLUMN] < holdout_start)
        & (panel[ENDPOINT_COLUMN] < holdout_start)
    )
    panel = panel.loc[development_mask].copy()
    panel = panel.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)

    panel = add_cross_sectional_ranks(panel)

    rank_complete = panel[list(RANK_FEATURE_COLUMNS)].notna().all(axis=1)
    panel["model_eligible"] = (
        panel["history_eligible"]
        & panel["feature_complete"]
        & panel["is_labeled_5d"]
        & panel[TARGET_COLUMN].notna()
        & rank_complete
    )

    validate_panel(panel, expected_symbols=symbols, holdout_start=holdout_start)
    return panel


def generate_folds(
    panel: pd.DataFrame,
    validation_start=DEVELOPMENT_VALIDATION_START_UTC,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
    validation_months=VALIDATION_MONTHS,
) -> list[dict]:
    if validation_months < 1:
        raise ValueError("validation_months must be positive")

    x = panel.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x[ENDPOINT_COLUMN] = pd.to_datetime(x[ENDPOINT_COLUMN], utc=True)
    validation_start = _utc(validation_start)
    holdout_start = _utc(holdout_start)
    if validation_start >= holdout_start:
        raise ValueError("validation_start must precede holdout_start")

    usable = (
        x["model_eligible"].fillna(False).astype(bool)
        & x[TARGET_COLUMN].notna()
    )
    last_decision = x.loc[usable, "timestamp_utc"].max()
    if pd.isna(last_decision) or last_decision < validation_start:
        raise ValueError("No eligible validation decisions are available")

    folds = []
    fold_number = 1
    current_start = validation_start

    while current_start < holdout_start and current_start <= last_decision:
        current_end = min(
            current_start + pd.DateOffset(months=validation_months),
            holdout_start,
        )
        train_mask = (
            usable
            & (x["timestamp_utc"] < current_start)
            & (x[ENDPOINT_COLUMN] < current_start)
        )
        validation_mask = (
            usable
            & (x["timestamp_utc"] >= current_start)
            & (x["timestamp_utc"] < current_end)
            & (x[ENDPOINT_COLUMN] < current_end)
        )

        train = x.loc[train_mask]
        validation = x.loc[validation_mask]
        if validation.empty:
            current_start = current_end
            fold_number += 1
            continue
        if train.empty:
            raise ValueError(
                f"Fold starting {current_start.isoformat()} has no purged training rows"
            )

        max_train_endpoint = train[ENDPOINT_COLUMN].max()
        max_validation_endpoint = validation[ENDPOINT_COLUMN].max()
        if max_train_endpoint >= current_start:
            raise AssertionError("Training target endpoint overlaps validation")
        if max_validation_endpoint >= current_end:
            raise AssertionError("Validation target endpoint crosses fold end")

        folds.append({
            "fold_id": f"dev_{fold_number:02d}",
            "split": "development",
            "train_start_utc": train["timestamp_utc"].min().isoformat(),
            "train_end_utc": train["timestamp_utc"].max().isoformat(),
            "max_train_target_endpoint_utc": max_train_endpoint.isoformat(),
            "validation_start_utc": current_start.isoformat(),
            "validation_end_exclusive_utc": current_end.isoformat(),
            "actual_validation_start_utc":
                validation["timestamp_utc"].min().isoformat(),
            "actual_validation_end_utc":
                validation["timestamp_utc"].max().isoformat(),
            "max_validation_target_endpoint_utc":
                max_validation_endpoint.isoformat(),
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "train_sessions": int(train["timestamp_utc"].nunique()),
            "validation_sessions": int(validation["timestamp_utc"].nunique()),
            "train_symbols": int(train["symbol"].nunique()),
            "validation_symbols": int(validation["symbol"].nunique()),
        })

        current_start = current_end
        fold_number += 1

    if not folds:
        raise ValueError("No StockEagle250 development folds were generated")
    return folds


def build_manifest(
    panel: pd.DataFrame,
    folds: list[dict],
    contract: dict,
) -> dict:
    eligible = panel.loc[panel["model_eligible"]]
    daily_counts = eligible.groupby("timestamp_utc")["symbol"].nunique()
    per_symbol = (
        panel.groupby("symbol")
        .agg(
            rows=("timestamp_utc", "size"),
            start_utc=("timestamp_utc", "min"),
            end_utc=("timestamp_utc", "max"),
            eligible_rows=("model_eligible", "sum"),
        )
        .reset_index()
        .sort_values("symbol")
    )
    contract_hash = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()

    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_point_in_time_panel_and_purged_folds",
        "classification": contract["classification"],
        "contract_path": str(CONTRACT_PATH),
        "contract_sha256": contract_hash,
        "candidate_count": int(panel["symbol"].nunique()),
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "benchmark_is_investable": False,
        "target": TARGET_COLUMN,
        "target_horizon_completed_sessions": TARGET_HORIZON_SESSIONS,
        "target_entry": "next_completed_session_open",
        "target_exit": "fifth_completed_session_close",
        "raw_feature_count": len(RAW_FEATURE_COLUMNS),
        "rank_feature_count": len(RANK_FEATURE_COLUMNS),
        "source_rows": int(len(panel)),
        "model_eligible_rows": int(len(eligible)),
        "development_start_utc": panel["timestamp_utc"].min().isoformat(),
        "development_end_utc": panel["timestamp_utc"].max().isoformat(),
        "maximum_development_target_endpoint_utc":
            panel[ENDPOINT_COLUMN].max().isoformat(),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_rows_read": 0,
        "daily_eligible_candidate_count": {
            "minimum": int(daily_counts.min()),
            "median": float(daily_counts.median()),
            "maximum": int(daily_counts.max()),
        },
        "fold_count": len(folds),
        "fold_ids": [fold["fold_id"] for fold in folds],
        "model_candidates": contract["development"]["model_candidates"],
        "transaction_cost_bps_per_side":
            contract["portfolio_assessment"]["transaction_cost_bps_per_side"],
        "paper_trading_enabled": False,
        "brokerage_orders": False,
        "existing_model_artifacts_modified": False,
        "symbols": [
            {
                "symbol": row.symbol,
                "rows": int(row.rows),
                "start_utc": row.start_utc.isoformat(),
                "end_utc": row.end_utc.isoformat(),
                "eligible_rows": int(row.eligible_rows),
            }
            for row in per_symbol.itertuples(index=False)
        ],
        "next_step": (
            "Run only the two fixed learned candidates across these frozen folds, "
            "apply the preregistered portfolio and cost mechanics, and keep the "
            "September 23 future holdout completely unread."
        ),
    }


def main():
    contract = load_contract()
    panel = build_panel()
    folds = generate_folds(panel)
    manifest = build_manifest(panel, folds, contract)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    FOLDS_PATH.write_text(
        json.dumps(folds, indent=2) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        key: manifest[key]
        for key in (
            "display_name",
            "phase",
            "stage",
            "candidate_count",
            "source_rows",
            "model_eligible_rows",
            "development_start_utc",
            "development_end_utc",
            "maximum_development_target_endpoint_utc",
            "future_holdout_start_utc",
            "future_holdout_rows_read",
            "fold_count",
            "paper_trading_enabled",
            "brokerage_orders",
            "next_step",
        )
    }
    summary["outputs"] = {
        "panel": str(PANEL_PATH),
        "folds": str(FOLDS_PATH),
        "manifest": str(MANIFEST_PATH),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
