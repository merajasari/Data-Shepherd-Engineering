"""StockEagle250 Phase 1: universe integrity and historical-data readiness.

This phase does not train, score, backtest, freeze, or paper trade a model. It
verifies the independent 250-candidate contract and audits point-in-time feature
history without modifying any existing stock-model artifacts or journals.
"""

from __future__ import annotations

import argparse
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
    get_stock_250_data_symbols,
)
from v5_symbols import V5_BENCHMARK_SYMBOL, V5_SYMBOLS  # noqa: E402


PHASE = 1
MINIMUM_ELIGIBLE_SESSIONS = 252
FEATURE_ROOT = Path("data/features/stocks")
PHASE_ROOT = Path("data/model/stock_eagle_250/phase1")
MANIFEST_PATH = PHASE_ROOT / "manifest.json"
CONTRACT_PATH = Path(__file__).with_name("contract.json")
PROTECTED_MODEL_LANES = ("v5", "v8", "v10", "v14", "v15")


def feature_path(symbol: str, feature_root: Path = FEATURE_ROOT) -> Path:
    return Path(feature_root) / symbol / f"{symbol}_features.parquet"


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if contract.get(key) != value
    }
    if mismatches:
        raise ValueError(f"StockEagle250 contract identity mismatch: {mismatches}")
    return contract


def validate_universe() -> dict:
    candidates = tuple(STOCK_250_SYMBOLS)
    data_symbols = tuple(get_stock_250_data_symbols())

    if len(candidates) != 250:
        raise ValueError(f"StockEagle250 requires 250 candidates, found {len(candidates)}")
    if len(set(candidates)) != 250:
        raise ValueError("StockEagle250 candidates must be unique")
    if V5_BENCHMARK_SYMBOL in candidates:
        raise ValueError("SPY must remain benchmark-only")
    if data_symbols != (*candidates, V5_BENCHMARK_SYMBOL):
        raise ValueError("StockEagle250 data symbols must be 250 candidates followed by SPY")
    if not set(V5_SYMBOLS).issubset(candidates):
        raise ValueError("The frozen 100-stock universe must remain a subset of StockEagle250")

    return {
        "candidate_count": len(candidates),
        "data_symbol_count": len(data_symbols),
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "benchmark_is_investable": False,
        "unique_candidates": True,
        "frozen_v5_candidates_preserved": True,
    }


def inspect_history(
    symbol: str,
    feature_root: Path = FEATURE_ROOT,
    reader=pd.read_parquet,
) -> dict:
    path = feature_path(symbol, feature_root)
    base = {
        "symbol": symbol,
        "path": str(path),
        "is_benchmark": symbol == V5_BENCHMARK_SYMBOL,
    }
    if not path.exists():
        return {
            **base,
            "status": "MISSING",
            "rows": 0,
            "observed_sessions": 0,
            "eligible_after_minimum_history": False,
            "start_utc": None,
            "end_utc": None,
        }

    try:
        frame = reader(path, columns=["timestamp_utc"])
        timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    except Exception as exc:
        return {
            **base,
            "status": "UNREADABLE",
            "error_type": type(exc).__name__,
            "rows": 0,
            "observed_sessions": 0,
            "eligible_after_minimum_history": False,
            "start_utc": None,
            "end_utc": None,
        }

    valid = timestamps.dropna()
    observed_sessions = int(valid.nunique())
    duplicate_timestamps = int(valid.duplicated().sum())
    eligible = observed_sessions >= MINIMUM_ELIGIBLE_SESSIONS
    status = "ELIGIBLE" if eligible else "SHORT_HISTORY"

    return {
        **base,
        "status": status,
        "rows": int(len(frame)),
        "observed_sessions": observed_sessions,
        "duplicate_timestamps": duplicate_timestamps,
        "eligible_after_minimum_history": eligible,
        "start_utc": valid.min().isoformat() if not valid.empty else None,
        "end_utc": valid.max().isoformat() if not valid.empty else None,
    }


def audit_histories(
    feature_root: Path = FEATURE_ROOT,
    reader=pd.read_parquet,
) -> list[dict]:
    return [
        inspect_history(symbol, feature_root=feature_root, reader=reader)
        for symbol in get_stock_250_data_symbols()
    ]


def build_manifest(records: list[dict], contract: dict | None = None) -> dict:
    contract = contract or load_contract()
    by_symbol = {record["symbol"]: record for record in records}
    expected = set(get_stock_250_data_symbols())
    if set(by_symbol) != expected:
        missing_records = sorted(expected - set(by_symbol))
        unexpected_records = sorted(set(by_symbol) - expected)
        raise ValueError(
            "StockEagle250 audit records do not match the contracted universe: "
            f"missing={missing_records}, unexpected={unexpected_records}"
        )

    candidates = [by_symbol[symbol] for symbol in STOCK_250_SYMBOLS]
    benchmark = by_symbol[V5_BENCHMARK_SYMBOL]
    missing = [row["symbol"] for row in records if row["status"] == "MISSING"]
    unreadable = [row["symbol"] for row in records if row["status"] == "UNREADABLE"]
    short_history = [
        row["symbol"] for row in candidates if row["status"] == "SHORT_HISTORY"
    ]
    eligible = [
        row["symbol"] for row in candidates
        if row["eligible_after_minimum_history"]
    ]
    complete_files = all(
        row["status"] not in {"MISSING", "UNREADABLE"} for row in records
    )
    duplicate_symbols = [
        row["symbol"] for row in records if row.get("duplicate_timestamps", 0) > 0
    ]
    ready = complete_files and not duplicate_symbols

    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "universe_integrity_and_historical_feature_readiness",
        "classification": contract["classification"],
        "universe": validate_universe(),
        "minimum_observed_sessions_for_candidate_eligibility":
            MINIMUM_ELIGIBLE_SESSIONS,
        "feature_root": str(FEATURE_ROOT),
        "candidate_feature_files_present":
            250 - sum(row["status"] in {"MISSING", "UNREADABLE"} for row in candidates),
        "eligible_candidate_count": len(eligible),
        "eligible_candidates": eligible,
        "short_history_candidate_count": len(short_history),
        "short_history_candidates": short_history,
        "missing_symbol_count": len(missing),
        "missing_symbols": missing,
        "unreadable_symbol_count": len(unreadable),
        "unreadable_symbols": unreadable,
        "duplicate_timestamp_symbol_count": len(duplicate_symbols),
        "duplicate_timestamp_symbols": duplicate_symbols,
        "benchmark_status": benchmark["status"],
        "ready_for_phase2_dataset_construction": ready,
        "paper_trading_enabled": False,
        "brokerage_orders": False,
        "protected_model_lanes": list(PROTECTED_MODEL_LANES),
        "existing_model_artifacts_modified": False,
        "records": records,
        "next_step": (
            "Define the leakage-safe point-in-time panel, targets, development folds, "
            "cost assumptions, and untouched holdout boundary before model fitting."
            if ready else
            "Backfill or repair the listed historical feature datasets, rerun Phase 1, "
            "and do not begin model fitting until the readiness audit passes."
        ),
    }


def run(feature_root: Path = FEATURE_ROOT) -> dict:
    contract = load_contract()
    validate_universe()
    records = audit_histories(feature_root=feature_root)
    manifest = build_manifest(records, contract=contract)
    manifest["feature_root"] = str(feature_root)
    return manifest


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-root",
        type=Path,
        default=FEATURE_ROOT,
        help="Historical feature root to audit.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit unsuccessfully when the complete 251-file audit is not ready.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest = run(feature_root=args.feature_root)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    summary = {
        key: manifest[key]
        for key in (
            "display_name",
            "phase",
            "stage",
            "candidate_feature_files_present",
            "eligible_candidate_count",
            "short_history_candidate_count",
            "missing_symbol_count",
            "unreadable_symbol_count",
            "duplicate_timestamp_symbol_count",
            "benchmark_status",
            "ready_for_phase2_dataset_construction",
            "paper_trading_enabled",
            "brokerage_orders",
            "next_step",
        )
    }
    summary["manifest_path"] = str(MANIFEST_PATH)
    print(json.dumps(summary, indent=2))

    if args.strict and not manifest["ready_for_phase2_dataset_construction"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
