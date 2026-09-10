"""Read-only end-to-end EOD convergence monitor for the stock pipeline.

Tracks the current Tiingo target session through Bronze -> Silver -> Gold ->
Features and verifies the V8 fail-closed gate never opens before the complete
101-symbol data universe has converged. Publishes dashboard/status artifacts and
an append-only operational transition journal. It never modifies market data,
research, model, holdout, portfolio, or brokerage state.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
sys.path.insert(0, str(DATA_INGESTION))

from v5_symbols import get_v5_data_symbols  # noqa: E402
from ml.feature_source import get_feature_backend, get_feature_dataset_path  # noqa: E402

REFRESH_STATE = PROJECT_ROOT / "data/live/v5_eod_refresh_state.json"
V8_GUARD = PROJECT_ROOT / "data/model/v8/eod_guard/status.json"
STATUS_PATH = PROJECT_ROOT / "data/model/operations/data_convergence.json"
EVENTS_PATH = PROJECT_ROOT / "data/model/operations/data_convergence_events.jsonl"
WEB_STATUS_PATH = PROJECT_ROOT / "webapp/static/generated/stock_data_convergence.json"

LAYERS = {
    "bronze": (PROJECT_ROOT / "data/bronze/stocks", "_prices.csv"),
    "silver": (PROJECT_ROOT / "data/silver/stocks", "_prices.parquet"),
    "gold": (PROJECT_ROOT / "data/gold/stocks", "_prices.parquet"),
    "features": (PROJECT_ROOT / "data/features/stocks", "_features.parquet"),
}


def _now():
    return datetime.now(timezone.utc)


def _json(path: Path):
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _target_timestamp(refresh_state):
    raw = refresh_state.get("target_timestamp_ms")
    if raw is not None:
        return pd.to_datetime(int(raw), unit="ms", utc=True)
    raw_date = refresh_state.get("target_date_utc")
    return pd.to_datetime(raw_date, utc=True) if raw_date else None


def _latest(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        if path.suffix == ".csv":
            frame = pd.read_csv(path, usecols=["timestamp"])
            values = pd.to_numeric(frame["timestamp"], errors="coerce").dropna()
            return pd.to_datetime(int(values.max()), unit="ms", utc=True) if not values.empty else None

        # Silver/Gold/feature Parquet files all retain timestamp. Prefer the UTC
        # projection where present because it is human-readable and unambiguous.
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc"])
            values = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
            if not values.empty:
                return values.max()
        except Exception:
            pass

        frame = pd.read_parquet(path, columns=["timestamp"])
        numeric = pd.to_numeric(frame["timestamp"], errors="coerce").dropna()
        if not numeric.empty:
            return pd.to_datetime(int(numeric.max()), unit="ms", utc=True)
        values = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dropna()
        return values.max() if not values.empty else None
    except Exception:
        return None


def _layer_status(name, root, suffix, symbols, target, feature_backend=None):
    latest_by_symbol = {}
    at_target = []
    missing = []
    behind = []
    for symbol in symbols:
        path = (
            get_feature_dataset_path(
                symbol, project_root=PROJECT_ROOT, backend=feature_backend
            )
            if name == "features"
            else root / symbol / f"{symbol}{suffix}"
        )
        ts = _latest(path)
        latest_by_symbol[symbol] = ts
        if ts is None:
            missing.append(symbol)
        elif target is not None and ts >= target:
            at_target.append(symbol)
        else:
            behind.append(symbol)

    readable = [ts for ts in latest_by_symbol.values() if ts is not None]
    common_latest = min(readable).isoformat() if len(readable) == len(symbols) and readable else None
    max_latest = max(readable).isoformat() if readable else None
    return {
        "layer": name,
        "symbols_expected": len(symbols),
        "symbols_at_target": len(at_target),
        "symbols_missing": len(missing),
        "symbols_behind_target": len(behind),
        "common_latest_utc": common_latest,
        "max_latest_utc": max_latest,
        "pending_symbols": sorted(set(missing + behind)),
        "complete_for_target": target is not None and len(at_target) == len(symbols),
        "backend": feature_backend if name == "features" else None,
    }


def _overall_status(layers, target):
    if target is None:
        return "WAITING_FOR_TARGET"
    for name in ("bronze", "silver", "gold", "features"):
        if not layers[name]["complete_for_target"]:
            return f"CATCHING_UP_{name.upper()}"
    return "DATA_CONVERGED"


def _append_transition(payload):
    previous = _json(STATUS_PATH)
    signature_fields = (
        "target_session_utc",
        "status",
        "v8_gate_status",
        "v8_decision_gate_open",
        "verification",
    )
    if previous and all(previous.get(k) == payload.get(k) for k in signature_fields):
        return False
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": "DATA_CONVERGENCE_TRANSITION",
        "created_at_utc": payload["generated_at_utc"],
        "previous_status": previous.get("status") if previous else None,
        **{k: payload.get(k) for k in signature_fields},
    }
    with EVENTS_PATH.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return True


def build_status():
    refresh = _json(REFRESH_STATE)
    guard = _json(V8_GUARD)
    symbols = list(get_v5_data_symbols())
    target = _target_timestamp(refresh)

    feature_backend = get_feature_backend()
    layers = {
        name: _layer_status(
            name, root, suffix, symbols, target,
            feature_backend=feature_backend if name == "features" else None,
        )
        for name, (root, suffix) in LAYERS.items()
    }
    status = _overall_status(layers, target)
    converged = status == "DATA_CONVERGED"
    gate_open = bool(guard.get("decision_gate_open"))
    ranking_ts = guard.get("ranking_timestamp_utc")
    ranking_target_match = bool(
        target is not None
        and ranking_ts
        and pd.to_datetime(ranking_ts, utc=True) == target
    )

    if gate_open and not converged:
        verification = "SAFETY_VIOLATION_GATE_OPEN_BEFORE_CONVERGENCE"
    elif converged and gate_open and ranking_target_match:
        verification = "END_TO_END_READY_VERIFIED"
    elif converged and not gate_open:
        verification = "DATA_CONVERGED_AWAITING_V8_GATE"
    elif converged and gate_open and not ranking_target_match:
        verification = "GATE_OPEN_RANKING_DATE_MISMATCH"
    else:
        verification = "FAIL_CLOSED_WHILE_CATCHING_UP"

    return {
        "generated_at_utc": _now().isoformat(),
        "target_session_utc": target.isoformat() if target is not None else None,
        "target_date_utc": refresh.get("target_date_utc"),
        "expected_symbols": len(symbols),
        "feature_backend": feature_backend,
        "status": status,
        "data_converged": converged,
        "layers": layers,
        "refresh_state_complete": refresh.get("complete"),
        "refresh_remaining_symbols": refresh.get("remaining_symbols") or [],
        "v8_gate_status": guard.get("status", "UNKNOWN"),
        "v8_decision_gate_open": gate_open,
        "v8_ranking_timestamp_utc": ranking_ts,
        "v8_ranking_matches_target": ranking_target_match,
        "verification": verification,
        "safety_violation": verification.startswith("SAFETY_VIOLATION") or verification == "GATE_OPEN_RANKING_DATE_MISMATCH",
        "brokerage_orders": False,
        "read_only_monitor": True,
    }


def publish():
    payload = build_status()
    transitioned = _append_transition(payload)
    payload["transition_recorded"] = transitioned
    for path in (STATUS_PATH, WEB_STATUS_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    return payload


def main():
    d = publish()
    print("STOCK EOD DATA CONVERGENCE")
    print("=" * 88)
    print(f"Target: {d['target_session_utc']}")
    print(f"Status: {d['status']}")
    print(f"Feature backend: {d['feature_backend']}")
    for name in ("bronze", "silver", "gold", "features"):
        layer = d["layers"][name]
        print(f"{name.title():8}: {layer['symbols_at_target']}/{layer['symbols_expected']} at target | common={layer['common_latest_utc']}")
    print(f"V8 gate: {d['v8_gate_status']} | open={d['v8_decision_gate_open']} | ranking={d['v8_ranking_timestamp_utc']}")
    print(f"Verification: {d['verification']}")
    print("Read-only monitor. No brokerage orders or research/holdout mutation.")
    raise SystemExit(3 if d["safety_violation"] else 0)


if __name__ == "__main__":
    main()
