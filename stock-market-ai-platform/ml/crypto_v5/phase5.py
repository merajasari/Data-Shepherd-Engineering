"""Crypto V5 Phase 5: guarded forward paper-decision journal.

Consumes completed Coinbase daily Bronze candles, recreates the frozen trailing
feature contract, verifies Phase 4 hashes, and appends hypothetical portfolio
decisions. This paper module contains no brokerage client; a future live gateway
may be added only under a separate explicitly approved execution contract.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ml.crypto_v1.config import BRONZE_ROOT, CRYPTO_UNIVERSE, PROVIDER_NAME
from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES, add_features_and_eligibility
from ml.crypto_v5.config import (
    ALLOCATION_TEMPLATES, BTC_PRODUCT, FUTURE_HOLDOUT_START_UTC,
    MAX_TURNOVER_PER_REBALANCE, MIN_NON_BTC_ASSETS, MINIMUM_HOLD_DAYS,
    SWITCH_CONFIDENCE_MARGIN,
)
from ml.crypto_v5.phase1 import _breadth
from ml.crypto_v5.phase2 import FEATURES
from ml.crypto_v5.phase3 import capped_target, desired_weights
from ml.crypto_v5.phase4 import (
    OUTPUT_ROOT as PHASE4_ROOT, SELECTED_COST_BPS, SELECTED_HORIZON_DAYS,
    SELECTED_MODEL_ID, SELECTED_TOP_N, SELECTION_STATUS,
)


OUTPUT_ROOT = PHASE4_ROOT.parent / "phase5"
CONTRACT_PATH = PHASE4_ROOT / "selected_contract.json"
STATE_PATH = OUTPUT_ROOT / "paper_state.json"
STATUS_PATH = OUTPUT_ROOT / "paper_status.json"
JOURNAL_PATH = OUTPUT_ROOT / "paper_decisions.jsonl"
STARTING_PAPER_EQUITY = 100_000.0
MAX_CANDLE_AGE_DAYS = 1
FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL = True
ARTIFACT_PATHS = {
    "allocation_btc": PHASE4_ROOT / "artifacts" / "allocation_btc_3d.joblib",
    "allocation_alt": PHASE4_ROOT / "artifacts" / "allocation_alt_3d.joblib",
    "allocation_cash": PHASE4_ROOT / "artifacts" / "allocation_cash_3d.joblib",
    "ranking": PHASE4_ROOT / "artifacts" / "ranking_3d.joblib",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _utc(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")


def verify_contract(contract_path=CONTRACT_PATH, artifact_paths=ARTIFACT_PATHS) -> dict:
    contract_path = Path(contract_path)
    if not contract_path.exists():
        raise FileNotFoundError(contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected_selection = {
        "model_id": SELECTED_MODEL_ID, "horizon_days": SELECTED_HORIZON_DAYS,
        "top_n": SELECTED_TOP_N, "cost_bps_round_trip": SELECTED_COST_BPS,
    }
    if contract.get("selection_status") != SELECTION_STATUS:
        raise RuntimeError("V5 Phase 4 contract is not selected for forward paper evaluation")
    if contract.get("selected") != expected_selection:
        raise RuntimeError("V5 Phase 4 selected policy mismatch")
    if _utc(contract.get("future_holdout_start_utc")) != FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("V5 Phase 4 holdout boundary mismatch")
    expected_hashes = contract.get("artifact_hashes", {})
    for name, path in artifact_paths.items():
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        actual = _sha256(path)
        if expected_hashes.get(name) != actual:
            raise RuntimeError(f"V5 artifact hash mismatch: {name}")
    return contract


def load_completed_bronze(bronze_root=BRONZE_ROOT, as_of_utc=None) -> tuple[pd.DataFrame, pd.Timestamp]:
    as_of = _utc(as_of_utc or datetime.now(timezone.utc))
    completed_before = as_of.floor("D")
    base = Path(bronze_root) / PROVIDER_NAME / "daily"
    paths = [base / product / "candles.csv" for product in CRYPTO_UNIVERSE]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing V5 daily Bronze candles: " + ", ".join(missing))
    frames = [pd.read_csv(path) for path in paths]
    panel = pd.concat(frames, ignore_index=True)
    required = {"product_id", "timestamp_utc", "open", "high", "low", "close", "volume"}
    absent = sorted(required - set(panel.columns))
    if absent:
        raise ValueError("V5 Bronze candles missing columns: " + ", ".join(absent))
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < completed_before].copy()
    panel = panel[panel["product_id"].isin(CRYPTO_UNIVERSE)].copy()
    if panel.duplicated(["product_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate V5 Bronze product/timestamp rows")
    for column in ("open", "high", "low", "close", "volume"):
        panel[column] = pd.to_numeric(panel[column], errors="raise").astype(float)
    if panel.empty or (panel[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("V5 Bronze market history is empty or contains non-positive prices")
    panel["source_provider"] = PROVIDER_NAME
    panel["source_granularity"] = "daily"
    panel["dollar_volume"] = panel["close"] * panel["volume"]
    panel["first_available_timestamp"] = panel.groupby("product_id")["timestamp_utc"].transform("min")
    return panel.sort_values(["product_id", "timestamp_utc"]).reset_index(drop=True), completed_before


def build_snapshot(history: pd.DataFrame, completed_before: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    featured = add_features_and_eligibility(history)
    decision_timestamp = featured["timestamp_utc"].max()
    expected = completed_before - pd.Timedelta(days=1)
    age = (expected - decision_timestamp).days
    if decision_timestamp != decision_timestamp.floor("D") or age < 0 or age > MAX_CANDLE_AGE_DAYS:
        raise RuntimeError(
            f"V5 completed daily snapshot is stale: latest={decision_timestamp.isoformat()}, "
            f"expected={expected.isoformat()}"
        )
    latest = featured[featured["timestamp_utc"] == decision_timestamp].copy()
    eligible = latest[latest["is_eligible"].fillna(False).astype(bool)].copy()
    feature_values = eligible[list(REQUIRED_FEATURES)].replace([np.inf, -np.inf], np.nan)
    eligible = eligible.loc[feature_values.notna().all(axis=1)].copy()
    btc = eligible[eligible["product_id"] == BTC_PRODUCT].copy()
    alts = eligible[eligible["product_id"] != BTC_PRODUCT].copy()
    if len(btc) != 1 or alts["product_id"].nunique() < MIN_NON_BTC_ASSETS:
        raise RuntimeError(
            f"V5 snapshot eligibility failed: btc_rows={len(btc)}, "
            f"eligible_alts={alts['product_id'].nunique()}"
        )
    breadth = _breadth(eligible)
    if len(breadth) != 1:
        raise RuntimeError("V5 snapshot did not produce exactly one breadth row")
    allocation = btc[["timestamp_utc", *REQUIRED_FEATURES]].merge(
        breadth, on="timestamp_utc", validate="one_to_one")
    ranking = alts.merge(breadth, on="timestamp_utc", validate="many_to_one")
    for frame in (allocation, ranking):
        missing = sorted(set(FEATURES) - set(frame.columns))
        if missing:
            raise ValueError("V5 snapshot missing frozen features: " + ", ".join(missing))
        if not np.isfinite(frame[list(FEATURES)].to_numpy(dtype=float)).all():
            raise ValueError("V5 snapshot contains non-finite frozen features")
    return allocation, ranking, decision_timestamp


def _load_state(path=STATE_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {
            "paper_equity": STARTING_PAPER_EQUITY,
            "weights": {"CASH": 1.0}, "selected_regime": "CASH",
            "last_decision_utc": None, "last_regime_switch_utc": None,
            "last_event_hash": None, "decision_count": 0,
        }
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise RuntimeError("V5 paper state must be a JSON object")
    return state


def _regime(scores: dict[str, float]) -> tuple[str, float]:
    ordered = sorted(scores, key=scores.get, reverse=True)
    best, second = ordered[:2]
    confidence = (scores[best] - scores[second]) / max(abs(scores[best]), 0.01)
    return {"alt": "RISK_ON", "btc": "DEFENSIVE", "cash": "CASH"}[best], float(confidence)


def score_snapshot(allocation, ranking, models, state, decision_timestamp) -> dict:
    scores = {
        sleeve: float(models[f"allocation_{sleeve}"].predict(allocation[list(FEATURES)])[0])
        for sleeve in ("btc", "alt", "cash")
    }
    proposed, confidence = _regime(scores)
    current_regime = str(state.get("selected_regime", "CASH"))
    last_switch = state.get("last_regime_switch_utc")
    held_days = (decision_timestamp - _utc(last_switch)).days if last_switch else 10**9
    can_switch = proposed == current_regime or (
        held_days >= MINIMUM_HOLD_DAYS and confidence >= SWITCH_CONFIDENCE_MARGIN)
    selected = proposed if can_switch else current_regime
    ranking = ranking.copy()
    ranking["predicted_score"] = models["ranking"].predict(ranking[list(FEATURES)])
    target = desired_weights(selected, ranking, SELECTED_TOP_N)
    adjusted, trade_turnover = capped_target(dict(state.get("weights", {"CASH": 1.0})), target)
    ranked = ranking.sort_values("predicted_score", ascending=False)
    top = ranked.head(SELECTED_TOP_N)[["product_id", "predicted_score"]]
    return {
        "proposed_regime": proposed, "selected_regime": selected,
        "confidence": confidence, "allocation_scores": scores,
        "top_ranked_assets": top.to_dict("records"),
        "target_weights": {key: float(value) for key, value in sorted(adjusted.items())},
        "turnover": float(trade_turnover),
        "estimated_transaction_cost": float(
            state.get("paper_equity", STARTING_PAPER_EQUITY)
            * trade_turnover * SELECTED_COST_BPS / 10000.0),
        "regime_switched": selected != current_regime,
    }


def append_event(path: Path, event: dict) -> str:
    payload = dict(event)
    payload["event_hash"] = _canonical_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
    return payload["event_hash"]


def run_phase5(
    bronze_root=BRONZE_ROOT, contract_path=CONTRACT_PATH, output_root=OUTPUT_ROOT,
    as_of_utc=None,
) -> dict:
    output_root = Path(output_root)
    state_path, status_path = output_root / STATE_PATH.name, output_root / STATUS_PATH.name
    journal_path = output_root / JOURNAL_PATH.name
    now = _utc(as_of_utc or datetime.now(timezone.utc))
    contract = verify_contract(contract_path)
    contract_hash = _sha256(Path(contract_path))
    if now < FUTURE_HOLDOUT_START_UTC:
        status = {
            "generated_at_utc": now.isoformat(), "status": "WAITING_PRE_HOLDOUT",
            "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
            "paper_only": True, "brokerage_orders": False,
            "future_live_gateway_allowed_after_separate_approval":
                FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
            "journal_written": False,
            "selected_contract_sha256": contract_hash,
        }
        _atomic_json(status_path, status)
        return status
    history, completed_before = load_completed_bronze(bronze_root, now)
    allocation, ranking, decision_timestamp = build_snapshot(history, completed_before)
    state = _load_state(state_path)
    last_decision = state.get("last_decision_utc")
    if last_decision and decision_timestamp <= _utc(last_decision):
        status = {
            "generated_at_utc": now.isoformat(), "status": "NO_NEW_COMPLETED_DAILY_SNAPSHOT",
            "latest_decision_utc": _utc(last_decision).isoformat(),
            "paper_only": True, "brokerage_orders": False,
            "future_live_gateway_allowed_after_separate_approval":
                FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
            "journal_written": False,
            "selected_contract_sha256": contract_hash,
        }
        _atomic_json(status_path, status)
        return status
    if last_decision and decision_timestamp < _utc(last_decision) + pd.Timedelta(SELECTED_HORIZON_DAYS, unit="D"):
        status = {
            "generated_at_utc": now.isoformat(), "status": "MINIMUM_DECISION_CADENCE_ACTIVE",
            "latest_snapshot_utc": decision_timestamp.isoformat(),
            "next_decision_not_before_utc": (
                _utc(last_decision) + pd.Timedelta(SELECTED_HORIZON_DAYS, unit="D")).isoformat(),
            "paper_only": True, "brokerage_orders": False,
            "future_live_gateway_allowed_after_separate_approval":
                FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
            "journal_written": False,
            "selected_contract_sha256": contract_hash,
        }
        _atomic_json(status_path, status)
        return status
    models = {name: joblib.load(path) for name, path in ARTIFACT_PATHS.items()}
    decision = score_snapshot(allocation, ranking, models, state, decision_timestamp)
    decision_id = f"crypto_v5:{decision_timestamp.isoformat()}"
    event = {
        "decision_id": decision_id, "decision_timestamp_utc": decision_timestamp.isoformat(),
        "recorded_at_utc": now.isoformat(), "model_id": SELECTED_MODEL_ID,
        "horizon_days": SELECTED_HORIZON_DAYS, "top_n": SELECTED_TOP_N,
        "cost_bps_round_trip": SELECTED_COST_BPS,
        "paper_equity_before": float(state.get("paper_equity", STARTING_PAPER_EQUITY)),
        "previous_event_hash": state.get("last_event_hash"),
        "selected_contract_sha256": contract_hash,
        **decision,
        "paper_only": True, "brokerage_orders": False,
        "future_live_gateway_allowed_after_separate_approval":
            FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
    }
    event_hash = append_event(journal_path, event)
    new_state = {
        "paper_equity": float(state.get("paper_equity", STARTING_PAPER_EQUITY)),
        "weights": decision["target_weights"], "selected_regime": decision["selected_regime"],
        "last_decision_utc": decision_timestamp.isoformat(),
        "last_regime_switch_utc": (
            decision_timestamp.isoformat() if decision["regime_switched"]
            else state.get("last_regime_switch_utc")),
        "last_event_hash": event_hash, "decision_count": int(state.get("decision_count", 0)) + 1,
        "paper_only": True, "brokerage_orders": False,
        "future_live_gateway_allowed_after_separate_approval":
            FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
    }
    _atomic_json(state_path, new_state)
    status = {
        "generated_at_utc": now.isoformat(), "status": "PAPER_DECISION_RECORDED",
        "decision_id": decision_id, "decision_timestamp_utc": decision_timestamp.isoformat(),
        "selected_regime": decision["selected_regime"],
        "top_ranked_assets": decision["top_ranked_assets"],
        "turnover": decision["turnover"], "event_hash": event_hash,
        "journal_written": True, "paper_only": True, "brokerage_orders": False,
        "future_live_gateway_allowed_after_separate_approval":
            FUTURE_LIVE_GATEWAY_ALLOWED_AFTER_SEPARATE_APPROVAL,
        "selected_contract_sha256": contract_hash,
    }
    _atomic_json(status_path, status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bronze-root", type=Path, default=BRONZE_ROOT)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--as-of-utc", default=None)
    args = parser.parse_args(argv)
    result = run_phase5(args.bronze_root, args.contract, args.output_root, args.as_of_utc)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
