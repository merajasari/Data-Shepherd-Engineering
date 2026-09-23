"""StockEagle250 V2 Phase 1: preregistered V10-inspired risk control.

This phase validates the already-observed V1 disposition and the fixed V2
contract. It may inspect only saved V1 development evidence ending before the
September 23 guard band. It does not calculate V2 performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v2 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
V1_PHASE3_ROOT = Path("data/model/stock_eagle_250/phase3")
V1_PHASE4_ROOT = Path("data/model/stock_eagle_250/phase4")
V1_PREDICTIONS_PATH = V1_PHASE3_ROOT / "walk_forward_predictions.parquet"
V1_PHASE3_MANIFEST_PATH = V1_PHASE3_ROOT / "manifest.json"
V1_ADJUDICATION_PATH = V1_PHASE4_ROOT / "adjudication.json"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v2/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

V1_RESEARCH_VERSION = "stock_eagle_250_v1"
V1_RANKING_CANDIDATE = "ridge_fixed_v1"
V2_CANDIDATE = "ridge_v1_rank_v10_regime_exposure_v2"
GUARD_BAND_START_UTC = pd.Timestamp("2026-09-23", tz="UTC")
FUTURE_START_UTC = pd.Timestamp("2026-10-01", tz="UTC")
MAXIMUM_DEVELOPMENT_ENDPOINT_UTC = pd.Timestamp("2026-09-22", tz="UTC")
SPY_TREND_LOOKBACK = 20
SPY_VOL_LOOKBACK = 20
SPY_VOL_BASELINE_LOOKBACK = 252
SPY_VOL_BASELINE_MINIMUM = 60
EXPOSURE_BY_STATE = {
    "NEGATIVE_HIGH_VOL": 0.0,
    "NEGATIVE_LOW_VOL": 0.5,
    "POSITIVE_HIGH_VOL": 0.75,
    "POSITIVE_LOW_VOL": 1.0,
    "NOT_READY": 0.0,
}
REQUIRED_PREDICTION_COLUMNS = {
    "fold_id",
    "timestamp_utc",
    "entry_timestamp_utc_5d",
    "target_endpoint_utc_5d",
    "symbol",
    "forward_stock_return",
    "forward_spy_return",
    "prediction_ridge_fixed_v1",
}


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        raise RuntimeError(f"StockEagle250 V2 identity mismatch: {mismatches}")
    if not contract.get("created_before_v2_results"):
        raise RuntimeError("V2 contract was not marked preregistered")

    lineage = contract["lineage_references"]
    v10 = lineage["stock_v10"]
    expected_v10 = {
        "spy_trend_lookback_sessions": SPY_TREND_LOOKBACK,
        "spy_volatility_lookback_sessions": SPY_VOL_LOOKBACK,
        "spy_volatility_baseline_sessions": SPY_VOL_BASELINE_LOOKBACK,
        "spy_volatility_baseline_minimum_sessions": SPY_VOL_BASELINE_MINIMUM,
        "volatility_baseline_lag_sessions": 1,
    }
    if any(v10.get(key) != value for key, value in expected_v10.items()):
        raise RuntimeError("V10 reference parameters differ from V2 code")

    if lineage["stock_eagle_250_v1"]["candidate_id"] != V1_RANKING_CANDIDATE:
        raise RuntimeError("V2 does not reference the fixed V1 Ridge candidate")
    if contract["fixed_candidate"]["candidate_id"] != V2_CANDIDATE:
        raise RuntimeError("Unexpected V2 candidate identity")

    states = contract["fixed_candidate"]["market_states"]
    contract_exposures = {
        state: float(specification["gross_exposure"])
        for state, specification in states.items()
    }
    if contract_exposures != EXPOSURE_BY_STATE:
        raise RuntimeError("V2 exposure map differs from the preregistration")

    boundaries = contract["data_boundaries"]
    if _utc(boundaries["sealed_guard_band_start_utc"]) != GUARD_BAND_START_UTC:
        raise RuntimeError("V2 guard-band start differs from code")
    if _utc(boundaries["new_untouched_future_start_utc"]) != FUTURE_START_UTC:
        raise RuntimeError("V2 future boundary differs from code")
    if _utc(boundaries["maximum_development_target_endpoint_utc"]) != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
        raise RuntimeError("V2 development endpoint differs from code")

    authority = contract["authority"]
    prohibited = (
        "model_freezing_enabled",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
    )
    if any(authority.get(key) is not False for key in prohibited):
        raise RuntimeError("V2 Phase 1 has trading or freezing authority")
    return contract


def validate_v1_evidence(
    adjudication: dict,
    phase3_manifest: dict,
) -> None:
    problems = []
    if adjudication.get("research_version") != V1_RESEARCH_VERSION:
        problems.append("unexpected V1 adjudication research version")
    if adjudication.get("status") != "REJECT_CURRENT_STOCK_EAGLE_250_V1_CANDIDATES":
        problems.append("V1 is not recorded as rejected")
    if adjudication.get("qualified_candidate_count") != 0:
        problems.append("V1 unexpectedly reports a qualified candidate")
    failed = adjudication.get("failed_gates_by_candidate", {}).get(
        V1_RANKING_CANDIDATE,
        [],
    )
    if "gate_worst_fold_maximum_drawdown_gte_minus_35pct" not in failed:
        problems.append("V1 Ridge drawdown failure is not preserved")

    safety = adjudication.get("safety", {})
    forbidden_true = (
        "future_holdout_scored",
        "candidate_frozen",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
    )
    if any(safety.get(key) is not False for key in forbidden_true):
        problems.append("V1 adjudication reports forbidden activity")

    if phase3_manifest.get("research_version") != V1_RESEARCH_VERSION:
        problems.append("unexpected V1 Phase 3 research version")
    if phase3_manifest.get("future_holdout_rows_read") != 0:
        problems.append("V1 Phase 3 reports holdout rows")
    endpoint = _utc(phase3_manifest.get("maximum_target_endpoint_utc"))
    if endpoint != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
        problems.append("V1 development endpoint differs from the sealed source")

    if problems:
        raise RuntimeError("StockEagle250 V2 rejected V1 evidence:\n- " + "\n- ".join(problems))


def validate_source_predictions(predictions: pd.DataFrame) -> dict:
    missing = sorted(REQUIRED_PREDICTION_COLUMNS - set(predictions.columns))
    if missing:
        raise RuntimeError(f"V1 prediction source is missing columns: {missing}")
    frame = predictions.copy()
    decisions = pd.to_datetime(frame["timestamp_utc"], utc=True)
    endpoints = pd.to_datetime(frame["target_endpoint_utc_5d"], utc=True)
    entries = pd.to_datetime(frame["entry_timestamp_utc_5d"], utc=True)

    problems = []
    if frame.empty:
        problems.append("prediction source is empty")
    if (decisions >= GUARD_BAND_START_UTC).any():
        problems.append("decision timestamp enters the sealed guard band")
    if (entries >= GUARD_BAND_START_UTC).any():
        problems.append("entry timestamp enters the sealed guard band")
    if (endpoints >= GUARD_BAND_START_UTC).any():
        problems.append("target endpoint enters the sealed guard band")
    if endpoints.max() != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
        problems.append("prediction source lacks the fixed final development endpoint")
    if frame.duplicated(["fold_id", "timestamp_utc", "symbol"]).any():
        problems.append("duplicate fold/timestamp/symbol prediction rows")
    if not np.isfinite(
        pd.to_numeric(frame["prediction_ridge_fixed_v1"], errors="coerce")
    ).all():
        problems.append("non-finite V1 Ridge predictions")
    fold_count = int(frame["fold_id"].nunique())
    if fold_count != 14:
        problems.append(f"expected 14 folds, found {fold_count}")
    if problems:
        raise RuntimeError(
            "StockEagle250 V2 rejected its V1 prediction source:\n- "
            + "\n- ".join(problems)
        )
    return {
        "source_rows": int(len(frame)),
        "fold_count": fold_count,
        "development_decision_start_utc": decisions.min().isoformat(),
        "development_decision_end_utc": decisions.max().isoformat(),
        "maximum_development_target_endpoint_utc": endpoints.max().isoformat(),
    }


def market_state_frame(spy_returns: pd.DataFrame) -> pd.DataFrame:
    """Build the fixed V10-style state from completed-session SPY returns."""
    required = {"timestamp_utc", "spy_return_1d"}
    missing = sorted(required - set(spy_returns.columns))
    if missing:
        raise ValueError(f"SPY state input is missing columns: {missing}")
    frame = spy_returns[list(required)].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (frame["timestamp_utc"] >= GUARD_BAND_START_UTC).any():
        raise RuntimeError("SPY state input enters the sealed V2 guard band")
    frame = frame.sort_values("timestamp_utc").drop_duplicates(
        "timestamp_utc",
        keep="last",
    )
    returns = pd.to_numeric(frame["spy_return_1d"], errors="coerce")
    frame["spy_trailing_compound_return_20"] = (
        (1.0 + returns)
        .rolling(SPY_TREND_LOOKBACK, min_periods=SPY_TREND_LOOKBACK)
        .apply(np.prod, raw=True)
        - 1.0
    )
    frame["spy_realized_volatility_20"] = returns.rolling(
        SPY_VOL_LOOKBACK,
        min_periods=SPY_VOL_LOOKBACK,
    ).std(ddof=0)
    frame["lagged_rolling_median_spy_volatility_252"] = (
        frame["spy_realized_volatility_20"]
        .shift(1)
        .rolling(
            SPY_VOL_BASELINE_LOOKBACK,
            min_periods=SPY_VOL_BASELINE_MINIMUM,
        )
        .median()
    )
    signal_columns = [
        "spy_trailing_compound_return_20",
        "spy_realized_volatility_20",
        "lagged_rolling_median_spy_volatility_252",
    ]
    ready = np.isfinite(frame[signal_columns]).all(axis=1)
    negative = frame["spy_trailing_compound_return_20"] < 0.0
    high_vol = (
        frame["spy_realized_volatility_20"]
        > frame["lagged_rolling_median_spy_volatility_252"]
    )
    frame["market_state"] = np.select(
        [
            ready & negative & high_vol,
            ready & negative & ~high_vol,
            ready & ~negative & high_vol,
            ready & ~negative & ~high_vol,
        ],
        [
            "NEGATIVE_HIGH_VOL",
            "NEGATIVE_LOW_VOL",
            "POSITIVE_HIGH_VOL",
            "POSITIVE_LOW_VOL",
        ],
        default="NOT_READY",
    )
    frame["gross_exposure"] = frame["market_state"].map(EXPOSURE_BY_STATE).astype(float)
    return frame


def build_manifest(
    contract: dict,
    source_summary: dict,
) -> dict:
    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_v10_inspired_risk_control_readiness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V2_CANDIDATE,
        "candidate_count": 1,
        "ranking_source": V1_RANKING_CANDIDATE,
        "v10_market_state_reference": True,
        "contract_sha256": _sha256(CONTRACT_PATH),
        "source": source_summary,
        "sealed_guard_band_start_utc": GUARD_BAND_START_UTC.isoformat(),
        "sealed_guard_band_end_exclusive_utc": FUTURE_START_UTC.isoformat(),
        "new_untouched_future_start_utc": FUTURE_START_UTC.isoformat(),
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v2_performance_calculated": False,
        "qualification_gates_fixed_before_v2_results": bool(
            contract["created_before_v2_results"]
        ),
        "safety": {
            "v1_artifacts_modified": False,
            "v10_artifacts_modified": False,
            "hyperparameter_search_performed": False,
            "exposure_search_performed": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "existing_forward_journals_modified": False,
        },
        "next_step": (
            "Evaluate this one fixed challenger on the saved V1 out-of-sample "
            "fold predictions at both 10-bps primary and 20-bps stress costs. "
            "Do not read September 23 or later."
        ),
    }


def run(
    predictions_path: Path = V1_PREDICTIONS_PATH,
    phase3_manifest_path: Path = V1_PHASE3_MANIFEST_PATH,
    adjudication_path: Path = V1_ADJUDICATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    adjudication = json.loads(Path(adjudication_path).read_text(encoding="utf-8"))
    phase3_manifest = json.loads(Path(phase3_manifest_path).read_text(encoding="utf-8"))
    validate_v1_evidence(adjudication, phase3_manifest)
    predictions = pd.read_parquet(predictions_path)
    source_summary = validate_source_predictions(predictions)
    payload = build_manifest(contract, source_summary)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=V1_PREDICTIONS_PATH)
    parser.add_argument("--phase3-manifest", type=Path, default=V1_PHASE3_MANIFEST_PATH)
    parser.add_argument("--adjudication", type=Path, default=V1_ADJUDICATION_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    payload = run(
        predictions_path=args.predictions,
        phase3_manifest_path=args.phase3_manifest,
        adjudication_path=args.adjudication,
        output_root=args.output_root,
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
