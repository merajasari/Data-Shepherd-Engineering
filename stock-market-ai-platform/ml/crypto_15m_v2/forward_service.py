"""Frozen Crypto 15m V2 forward inference + paper-evaluation journal service.

Uses authoritative reconciled Coinbase 15-minute REST candles, reconstructs the
frozen 44-feature hourly BTC/ALT/CASH row, verifies the Phase 5 model hash,
produces HGB probabilities, applies frozen confirm_2 execution state, and writes
paper-evaluation records only for genuinely new hourly decisions at/after the
2026-09-01 UTC holdout boundary.

Before the holdout boundary the service runs in shadow mode and writes only a
separate shadow snapshot. It never backfills missed holdout decisions and never
places brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import time

import joblib
import numpy as np
import pandas as pd

from ml.crypto_rt import PRODUCTS
from ml.crypto_15m_v1.phase1 import _build_base_features, _btc_context
from ml.crypto_15m_v2.phase1 import BTC_FEATURES, ALT_STATE_COLUMNS, MIN_ALT_ASSETS

RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
PHASE5_ROOT = Path("data/model/crypto_15m_v2/phase5")
MODEL_PATH = PHASE5_ROOT / "frozen_hgb.joblib"
MANIFEST_PATH = PHASE5_ROOT / "freeze_manifest.json"
STATE_PATH = PHASE5_ROOT / "forward_state.json"
JOURNAL_PATH = PHASE5_ROOT / "forward_journal.csv"
SHADOW_PATH = PHASE5_ROOT / "shadow_latest.json"
SERVICE_STATUS_PATH = PHASE5_ROOT / "forward_service_status.json"
LOCK_PATH = PHASE5_ROOT / "forward_service.lock"

BTC = "BTC-USD"
XRP = "XRP-USD"
CORE_PRODUCTS = tuple(p for p in PRODUCTS if p != XRP)
LABELS = ("BTC", "ALT", "CASH")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
COST_BPS = 5.0
CONFIRM_REQUIRED = 2
DEFAULT_POLL_SECONDS = 60
LOOKBACK_DAYS = 7


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_contract():
    for path in (MODEL_PATH, MANIFEST_PATH, STATE_PATH, JOURNAL_PATH):
        if not path.exists():
            raise FileNotFoundError(path)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = manifest["model"]["artifact_sha256"]
    actual = _sha256(MODEL_PATH)
    if actual != expected:
        raise RuntimeError(f"Frozen model SHA256 mismatch: expected {expected}, got {actual}")
    if manifest["execution_policy"]["policy_id"] != "confirm_2":
        raise RuntimeError("Frozen execution policy is not confirm_2")
    if int(manifest["execution_policy"]["confirmation_hours"]) != CONFIRM_REQUIRED:
        raise RuntimeError("Frozen confirmation count differs from service contract")
    features = list(manifest["model"]["feature_columns"])
    model = joblib.load(MODEL_PATH)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return manifest, features, model, state


def _latest_available_timestamp(product_id: str) -> pd.Timestamp | None:
    paths = sorted((RAW_ROOT / product_id).glob("*.parquet"), reverse=True)
    for path in paths:
        try:
            df = pd.read_parquet(path, columns=["timestamp_utc"])
        except Exception:
            continue
        ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dropna()
        if len(ts):
            return ts.max()
    return None


def _read_recent(product_id: str, end: pd.Timestamp) -> pd.DataFrame:
    start = end - pd.Timedelta(days=LOOKBACK_DAYS)
    months = pd.period_range(start.tz_localize(None).to_period("M"), end.tz_localize(None).to_period("M"), freq="M")
    frames = []
    for period in months:
        path = RAW_ROOT / product_id / f"{period}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df[(df["timestamp_utc"] >= start) & (df["timestamp_utc"] <= end)].copy()
        if len(df):
            frames.append(df)
    if not frames:
        raise RuntimeError(f"No recent authoritative bars for {product_id}")
    out = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc")
    return out.drop_duplicates(["timestamp_utc", "product_id"], keep="last").reset_index(drop=True)


def _latest_hourly_decision_timestamp() -> pd.Timestamp:
    latest = []
    for product_id in CORE_PRODUCTS:
        ts = _latest_available_timestamp(product_id)
        if ts is None:
            raise RuntimeError(f"No authoritative archive for {product_id}")
        latest.append(ts)
    common_ceiling = min(latest)
    # Frozen Phase 1 cadence uses xx:00 candle timestamps. Only use an xx:00
    # candle that is already present in every core product archive.
    candidate = common_ceiling.floor("h")
    return candidate


def _build_hourly_feature_row(decision_ts: pd.Timestamp, frozen_features: list[str]) -> tuple[pd.DataFrame, dict]:
    raw = {p: _read_recent(p, decision_ts) for p in CORE_PRODUCTS}
    if any(decision_ts not in set(df["timestamp_utc"]) for df in raw.values()):
        missing = [p for p, df in raw.items() if decision_ts not in set(df["timestamp_utc"])]
        raise RuntimeError(f"Decision candle {decision_ts} missing for core products: {', '.join(missing)}")

    btc_base = _build_base_features(raw[BTC])
    btc_context = _btc_context(btc_base)

    product_rows = []
    for product_id in CORE_PRODUCTS:
        base = btc_base.copy() if product_id == BTC else _build_base_features(raw[product_id])
        row = base[base["timestamp_utc"] == decision_ts].copy()
        if row.empty:
            raise RuntimeError(f"No feature row at {decision_ts} for {product_id}")
        row = row.merge(btc_context, on="timestamp_utc", how="left", validate="one_to_one")
        for bars in (1, 4, 16, 96):
            row[f"btc_relative_return_{bars}bar"] = row[f"return_{bars}bar"] - row[f"btc_return_{bars}bar"]
        product_rows.append(row)

    panel = pd.concat(product_rows, ignore_index=True)
    btc = panel[panel["product_id"] == BTC].copy()
    alts = panel[panel["product_id"] != BTC].copy()
    if len(btc) != 1:
        raise RuntimeError("Expected exactly one BTC feature row")
    if alts["product_id"].nunique() < MIN_ALT_ASSETS:
        raise RuntimeError("Insufficient ALT assets for frozen feature contract")

    record = {"timestamp_utc": decision_ts}
    for c in BTC_FEATURES:
        record[f"btc_{c}"] = float(btc.iloc[0][c])
    record["alt_asset_count"] = int(alts["product_id"].nunique())
    for c in ALT_STATE_COLUMNS:
        values = pd.to_numeric(alts[c], errors="coerce")
        record[f"alt_mean_{c}"] = float(values.mean())
        record[f"alt_median_{c}"] = float(values.median())
    record["alt_positive_1bar_fraction"] = float((alts["return_1bar"] > 0).mean())
    record["alt_positive_4bar_fraction"] = float((alts["return_4bar"] > 0).mean())
    record["alt_positive_16bar_fraction"] = float((alts["return_16bar"] > 0).mean())
    record["alt_return_4bar_dispersion"] = float(alts["return_4bar"].std(ddof=0))
    record["alt_return_16bar_dispersion"] = float(alts["return_16bar"].std(ddof=0))
    record["alt_btc_relative_4bar_positive_fraction"] = float((alts["btc_relative_return_4bar"] > 0).mean())
    record["alt_btc_relative_16bar_positive_fraction"] = float((alts["btc_relative_return_16bar"] > 0).mean())

    frame = pd.DataFrame([record])
    missing = [c for c in frozen_features if c not in frame.columns]
    if missing:
        raise RuntimeError("Live feature row missing frozen features: " + ", ".join(missing))
    frame = frame.replace([np.inf, -np.inf], np.nan)
    bad = [c for c in frozen_features if pd.isna(frame.iloc[0][c])]
    if bad:
        raise RuntimeError("Live feature row has null frozen features: " + ", ".join(bad))
    return frame[frozen_features], {"alt_asset_count": int(record["alt_asset_count"])}


def _predict(model, features: pd.DataFrame) -> tuple[str, dict]:
    pred = str(model.predict(features)[0])
    proba = model.predict_proba(features)[0]
    classes = list(model.named_steps["model"].classes_)
    probs = {label: float(proba[classes.index(label)]) for label in LABELS}
    return pred, probs


def _apply_confirm2(state: dict, raw_label: str) -> tuple[str, str, dict]:
    before = state["current_executed_label"]
    if raw_label == before:
        state["pending_candidate_label"] = None
        state["pending_candidate_count"] = 0
        return before, before, state

    if state.get("pending_candidate_label") == raw_label:
        state["pending_candidate_count"] = int(state.get("pending_candidate_count", 0)) + 1
    else:
        state["pending_candidate_label"] = raw_label
        state["pending_candidate_count"] = 1

    after = before
    if state["pending_candidate_count"] >= CONFIRM_REQUIRED:
        after = raw_label
        state["current_executed_label"] = raw_label
        state["pending_candidate_label"] = None
        state["pending_candidate_count"] = 0
    return before, after, state


def _read_journal() -> pd.DataFrame:
    df = pd.read_csv(JOURNAL_PATH)
    if len(df):
        df["decision_timestamp_utc"] = pd.to_datetime(df["decision_timestamp_utc"], utc=True)
    return df


def _hourly_realized(decision_ts: pd.Timestamp) -> tuple[float, float] | None:
    end_ts = decision_ts + pd.Timedelta(hours=1)
    latest = _latest_available_timestamp(BTC)
    if latest is None or latest < end_ts:
        return None
    btc = _read_recent(BTC, end_ts)
    btc0 = btc.loc[btc["timestamp_utc"] == decision_ts, "close"]
    btc1 = btc.loc[btc["timestamp_utc"] == end_ts, "close"]
    if btc0.empty or btc1.empty:
        return None
    btc_r = float(btc1.iloc[-1] / btc0.iloc[-1] - 1.0)

    returns = []
    for product_id in CORE_PRODUCTS:
        if product_id == BTC:
            continue
        df = _read_recent(product_id, end_ts)
        p0 = df.loc[df["timestamp_utc"] == decision_ts, "close"]
        p1 = df.loc[df["timestamp_utc"] == end_ts, "close"]
        if not p0.empty and not p1.empty:
            returns.append(float(p1.iloc[-1] / p0.iloc[-1] - 1.0))
    if len(returns) < MIN_ALT_ASSETS:
        return None
    return btc_r, float(np.mean(returns))


def _finalize_pending_rows(state: dict) -> int:
    journal = _read_journal()
    if journal.empty:
        return 0
    changed = 0
    equity = float(state.get("current_equity", 1.0))
    # Reconstruct from already-realized rows if state was restored manually.
    realized_rows = journal[journal["status"] == "REALIZED"]
    if len(realized_rows):
        equity = float(pd.to_numeric(realized_rows["equity"], errors="coerce").dropna().iloc[-1])

    for idx, row in journal[journal["status"] == "PENDING_REALIZATION"].sort_values("decision_timestamp_utc").iterrows():
        ts = pd.Timestamp(row["decision_timestamp_utc"])
        realized = _hourly_realized(ts)
        if realized is None:
            continue
        btc_r, alt_r = realized
        sleeve = str(row["executed_label_after"])
        gross = btc_r if sleeve == "BTC" else alt_r if sleeve == "ALT" else 0.0
        switched = float(row["sleeve_switch"])
        cost = switched * COST_BPS / 10000.0
        net = (1.0 + gross) * (1.0 - cost) - 1.0
        equity *= (1.0 + net)
        journal.loc[idx, "btc_realized_return_1h"] = btc_r
        journal.loc[idx, "alt_realized_return_1h"] = alt_r
        journal.loc[idx, "gross_selected_return_1h"] = gross
        journal.loc[idx, "transaction_cost"] = cost
        journal.loc[idx, "net_selected_return_1h"] = net
        journal.loc[idx, "equity"] = equity
        journal.loc[idx, "realized_through_utc"] = (ts + pd.Timedelta(hours=1)).isoformat()
        journal.loc[idx, "status"] = "REALIZED"
        changed += 1
        state["last_realized_timestamp_utc"] = ts.isoformat()
    if changed:
        journal.to_csv(JOURNAL_PATH, index=False)
        state["current_equity"] = equity
    return changed


def _append_forward_decision(decision_ts: pd.Timestamp, raw_label: str, probs: dict, state: dict) -> dict:
    journal = _read_journal()
    if len(journal) and decision_ts <= journal["decision_timestamp_utc"].max():
        return state

    before, after, state = _apply_confirm2(state, raw_label)
    switched = int(after != before)
    row = {
        "decision_timestamp_utc": decision_ts.isoformat(),
        "raw_predicted_label": raw_label,
        "executed_label_before": before,
        "executed_label_after": after,
        "pending_candidate_label": state.get("pending_candidate_label"),
        "pending_candidate_count": int(state.get("pending_candidate_count", 0)),
        "prob_btc": probs["BTC"],
        "prob_alt": probs["ALT"],
        "prob_cash": probs["CASH"],
        "btc_realized_return_1h": np.nan,
        "alt_realized_return_1h": np.nan,
        "gross_selected_return_1h": np.nan,
        "sleeve_switch": switched,
        "cost_bps_assumption": COST_BPS,
        "transaction_cost": np.nan,
        "net_selected_return_1h": np.nan,
        "equity": np.nan,
        "realized_through_utc": None,
        "status": "PENDING_REALIZATION",
    }
    pd.DataFrame([row]).to_csv(JOURNAL_PATH, mode="a", header=False, index=False)
    state["last_forward_decision_timestamp_utc"] = decision_ts.isoformat()
    state["last_raw_prediction"] = raw_label
    state["last_probabilities"] = probs
    return state


def run_once() -> dict:
    manifest, frozen_features, model, state = _load_contract()
    finalized = _finalize_pending_rows(state)
    decision_ts = _latest_hourly_decision_timestamp()
    X, diagnostics = _build_hourly_feature_row(decision_ts, frozen_features)
    raw_label, probs = _predict(model, X)
    now = pd.Timestamp.now(tz="UTC")

    mode = "SHADOW" if decision_ts < HOLDOUT else "FORWARD"
    action = "shadow_snapshot"
    if mode == "SHADOW":
        _atomic_json(SHADOW_PATH, {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision_timestamp_utc": decision_ts.isoformat(),
            "raw_predicted_label": raw_label,
            "probabilities": probs,
            "current_frozen_sleeve": state["current_executed_label"],
            "alt_asset_count": diagnostics["alt_asset_count"],
            "mode": "SHADOW_PRE_HOLDOUT",
            "note": "No forward journal row or performance result is written before 2026-09-01 UTC.",
        })
    else:
        last = state.get("last_forward_decision_timestamp_utc")
        if last and decision_ts <= pd.Timestamp(last):
            action = "already_processed"
        else:
            # Never replay/backfill missed holdout hours: process only the latest
            # currently available hourly decision.
            if last and decision_ts > pd.Timestamp(last) + pd.Timedelta(hours=1):
                state["last_forward_gap_detected"] = {
                    "previous_decision_utc": last,
                    "next_live_decision_utc": decision_ts.isoformat(),
                    "policy": "missed decisions are not backfilled",
                }
            state = _append_forward_decision(decision_ts, raw_label, probs, state)
            action = "journal_appended"

    _atomic_json(STATE_PATH, state)
    status = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "action": action,
        "decision_timestamp_utc": decision_ts.isoformat(),
        "raw_predicted_label": raw_label,
        "probabilities": probs,
        "executed_label": state["current_executed_label"],
        "pending_candidate_label": state.get("pending_candidate_label"),
        "pending_candidate_count": int(state.get("pending_candidate_count", 0)),
        "journal_rows_finalized_this_cycle": finalized,
        "current_equity": float(state.get("current_equity", 1.0)),
        "frozen_model_sha256": manifest["model"]["artifact_sha256"],
        "holdout_start_utc": HOLDOUT.isoformat(),
        "wall_clock_utc": now.isoformat(),
        "brokerage_orders": False,
    }
    _atomic_json(SERVICE_STATUS_PATH, status)
    return status


def _acquire_lock() -> None:
    PHASE5_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        LOCK_PATH.write_text(str(__import__("os").getpid()), encoding="utf-8", errors="strict") if not LOCK_PATH.exists() else (_ for _ in ()).throw(FileExistsError())
    except FileExistsError:
        raise SystemExit("[SKIP] Crypto V2 forward service already running")


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = ap.parse_args(argv)
    if args.poll_seconds < 30:
        raise SystemExit("poll-seconds must be at least 30")

    stop = False
    def request_stop(*_args):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    _acquire_lock()
    try:
        while True:
            try:
                result = run_once()
                print(
                    f"[FORWARD] {result['generated_at_utc']} mode={result['mode']} "
                    f"decision={result['decision_timestamp_utc']} raw={result['raw_predicted_label']} "
                    f"executed={result['executed_label']} action={result['action']} "
                    f"equity={result['current_equity']:.6f}",
                    flush=True,
                )
            except Exception as exc:
                _atomic_json(SERVICE_STATUS_PATH, {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "brokerage_orders": False,
                })
                print(f"[FORWARD ERROR] {type(exc).__name__}: {exc}", flush=True)
            if args.once or stop:
                break
            for _ in range(args.poll_seconds):
                if stop:
                    break
                time.sleep(1)
            if stop:
                break
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
