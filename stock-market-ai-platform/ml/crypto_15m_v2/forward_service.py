"""Frozen Crypto 15m V2 forward inference + paper-evaluation journal service.

Uses authoritative reconciled Coinbase 15-minute REST candles, reconstructs the
frozen 44-feature hourly BTC/ALT/CASH row, verifies the Phase 5 model hash,
produces HGB probabilities, applies frozen confirm_2 execution state, and writes
paper-evaluation records only for genuinely new hourly decisions at/after the
2026-09-01 UTC holdout boundary.

Before the holdout boundary the service runs in shadow mode and writes only a
separate shadow snapshot. It never backfills missed holdout decisions and never
places brokerage orders.

The frozen Phase 1/V2 dataset was built with a minimum-alt-universe rule rather
than requiring every ALT to have every timestamp. Forward inference therefore
requires BTC plus at least the same frozen minimum number of ALT assets at the
decision timestamp; an ALT with a genuine missing Coinbase candle is excluded
from that hour rather than synthesized or allowed to stop inference.
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
ALT_PRODUCTS = tuple(p for p in CORE_PRODUCTS if p != BTC)
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
    btc_latest = _latest_available_timestamp(BTC)
    if btc_latest is None:
        raise RuntimeError("No authoritative archive for BTC-USD")
    return btc_latest.floor("h")


def _build_hourly_feature_row(decision_ts: pd.Timestamp, frozen_features: list[str]) -> tuple[pd.DataFrame, dict]:
    btc_raw = _read_recent(BTC, decision_ts)
    if decision_ts not in set(btc_raw["timestamp_utc"]):
        raise RuntimeError(f"Decision candle {decision_ts} missing for BTC-USD")

    alt_raw: dict[str, pd.DataFrame] = {}
    missing_alts: list[str] = []
    for product_id in ALT_PRODUCTS:
        try:
            df = _read_recent(product_id, decision_ts)
        except RuntimeError:
            missing_alts.append(product_id)
            continue
        if decision_ts not in set(df["timestamp_utc"]):
            missing_alts.append(product_id)
            continue
        alt_raw[product_id] = df

    if len(alt_raw) < MIN_ALT_ASSETS:
        raise RuntimeError(
            f"Only {len(alt_raw)} ALT assets have authoritative decision candle {decision_ts}; "
            f"minimum required is {MIN_ALT_ASSETS}. Missing: {', '.join(missing_alts)}"
        )

    btc_base = _build_base_features(btc_raw)
    btc_context = _btc_context(btc_base)

    product_rows = []
    btc_row = btc_base[btc_base["timestamp_utc"] == decision_ts].copy()
    if btc_row.empty:
        raise RuntimeError(f"No feature row at {decision_ts} for BTC-USD")
    btc_row = btc_row.merge(btc_context, on="timestamp_utc", how="left", validate="one_to_one")
    for bars in (1, 4, 16, 96):
        btc_row[f"btc_relative_return_{bars}bar"] = btc_row[f"return_{bars}bar"] - btc_row[f"btc_return_{bars}bar"]
    product_rows.append(btc_row)

    feature_ready_alts: list[str] = []
    feature_failed_alts: list[str] = []
    for product_id, raw_df in alt_raw.items():
        base = _build_base_features(raw_df)
        row = base[base["timestamp_utc"] == decision_ts].copy()
        if row.empty:
            feature_failed_alts.append(product_id)
            continue
        row = row.merge(btc_context, on="timestamp_utc", how="left", validate="one_to_one")
        for bars in (1, 4, 16, 96):
            row[f"btc_relative_return_{bars}bar"] = row[f"return_{bars}bar"] - row[f"btc_return_{bars}bar"]
        required_alt = list(ALT_STATE_COLUMNS) + ["return_1bar", "return_4bar", "return_16bar", "btc_relative_return_4bar", "btc_relative_return_16bar"]
        if row[required_alt].replace([np.inf, -np.inf], np.nan).isna().any(axis=None):
            feature_failed_alts.append(product_id)
            continue
        product_rows.append(row)
        feature_ready_alts.append(product_id)

    if len(feature_ready_alts) < MIN_ALT_ASSETS:
        raise RuntimeError(
            f"Only {len(feature_ready_alts)} ALT assets have complete frozen features at {decision_ts}; "
            f"minimum required is {MIN_ALT_ASSETS}. Feature-ineligible: {', '.join(feature_failed_alts)}"
        )

    panel = pd.concat(product_rows, ignore_index=True)
    btc = panel[panel["product_id"] == BTC].copy()
    alts = panel[panel["product_id"] != BTC].copy()
    if len(btc) != 1:
        raise RuntimeError("Expected exactly one BTC feature row")

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
    diagnostics = {
        "alt_asset_count": int(record["alt_asset_count"]),
        "missing_decision_candle_alts": sorted(missing_alts),
        "feature_ineligible_alts": sorted(feature_failed_alts),
    }
    return frame[frozen_features], diagnostics


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
    # An all-empty CSV column is otherwise inferred as float64 by pandas.
    # Realization writes an ISO-8601 timestamp here, so keep it string-capable.
    if "realized_through_utc" in df.columns:
        df["realized_through_utc"] = df["realized_through_utc"].astype("object")
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
    for product_id in ALT_PRODUCTS:
        try:
            df = _read_recent(product_id, end_ts)
        except RuntimeError:
            continue
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
        "decision_timestamp_utc": decision_ts.isoformat(), "raw_predicted_label": raw_label,
        "executed_label_before": before, "executed_label_after": after,
        "pending_candidate_label": state.get("pending_candidate_label"),
        "pending_candidate_count": int(state.get("pending_candidate_count", 0)),
        "prob_btc": probs["BTC"], "prob_alt": probs["ALT"], "prob_cash": probs["CASH"],
        "btc_realized_return_1h": np.nan, "alt_realized_return_1h": np.nan,
        "gross_selected_return_1h": np.nan, "sleeve_switch": switched,
        "cost_bps_assumption": COST_BPS, "transaction_cost": np.nan,
        "net_selected_return_1h": np.nan, "equity": np.nan,
        "realized_through_utc": None, "status": "PENDING_REALIZATION",
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
    mode = "FORWARD" if decision_ts >= HOLDOUT else "SHADOW"
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "decision_timestamp_utc": decision_ts.isoformat(),
        "raw_predicted_label": raw_label,
        "probabilities": probs,
        "current_executed_label": state["current_executed_label"],
        "alt_asset_count": diagnostics["alt_asset_count"],
        "missing_decision_candle_alts": diagnostics["missing_decision_candle_alts"],
        "feature_ineligible_alts": diagnostics["feature_ineligible_alts"],
        "pending_rows_finalized": finalized,
        "brokerage_orders": False,
    }
    if mode == "SHADOW":
        result["action"] = "shadow_snapshot"
        result["note"] = "Pre-holdout shadow inference only; execution state and forward journal are unchanged."
        _atomic_json(SHADOW_PATH, result)
    else:
        journal = _read_journal()
        last = journal["decision_timestamp_utc"].max() if len(journal) else None
        if last is not None and decision_ts <= last:
            result["action"] = "already_processed"
        else:
            if last is not None and decision_ts > last + pd.Timedelta(hours=1):
                result["action"] = "gap_detected_no_backfill"
                result["note"] = "A forward decision hour was missed. Frozen policy forbids historical backfill into the forward journal."
            else:
                state = _append_forward_decision(decision_ts, raw_label, probs, state)
                result["action"] = "forward_decision_appended"
                result["current_executed_label"] = state["current_executed_label"]
                result["pending_candidate_label"] = state.get("pending_candidate_label")
                result["pending_candidate_count"] = state.get("pending_candidate_count", 0)
    state["service_last_checked_utc"] = now.isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    _atomic_json(SERVICE_STATUS_PATH, result)
    return result


def _acquire_lock() -> None:
    PHASE5_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK_PATH.open("x", encoding="utf-8") as f:
            f.write(str(__import__("os").getpid()))
    except FileExistsError:
        raise SystemExit("[SKIP] Crypto V2 forward service already running")


def _release_lock() -> None:
    try: LOCK_PATH.unlink()
    except FileNotFoundError: pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = ap.parse_args(argv)
    stop = False
    def request_stop(*_args):
        nonlocal stop; stop = True
    signal.signal(signal.SIGINT, request_stop); signal.signal(signal.SIGTERM, request_stop)
    _acquire_lock()
    try:
        while True:
            try:
                result = run_once()
                print(f"[FORWARD] {result['generated_at_utc']} mode={result['mode']} decision={result['decision_timestamp_utc']} raw={result['raw_predicted_label']} executed={result['current_executed_label']} alts={result['alt_asset_count']} action={result['action']}", flush=True)
            except Exception as exc:
                payload={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"status":"error","error":f"{type(exc).__name__}: {exc}","brokerage_orders":False}
                _atomic_json(SERVICE_STATUS_PATH,payload); print(f"[FORWARD ERROR] {payload['error']}",flush=True)
            if args.once or stop: break
            for _ in range(max(15,args.poll_seconds)):
                if stop: break
                time.sleep(1)
            if stop: break
    finally:
        _release_lock()

if __name__ == "__main__": main()
