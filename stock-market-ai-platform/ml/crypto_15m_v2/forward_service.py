"""Frozen Crypto 15m V2 clean forward paper-evaluation service.

Uses authoritative reconciled Coinbase 15-minute REST candles, reconstructs the
frozen 44-feature hourly BTC/ALT/CASH row, verifies the Phase 5 model hash,
produces HGB probabilities, applies frozen confirm_2 execution state, and writes
paper-evaluation records only to the separately preregistered clean lane at/after
2026-09-18 00:00 UTC.

The interrupted September 1 lane remains byte-for-byte preserved. Before the
clean boundary this service publishes waiting telemetry only. It never backfills missed decisions, starts the lane late, or places brokerage
orders. After an operational outage, missed hours remain an explicit permanent
evidence gap and prospective collection may resume only from the current observed
hour; confirm_2 transient candidate state is restarted across that gap.

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
import os
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
LEGACY_STATE_PATH = PHASE5_ROOT / "forward_state.json"
LEGACY_JOURNAL_PATH = PHASE5_ROOT / "forward_journal.csv"
LEGACY_STATUS_PATH = PHASE5_ROOT / "forward_service_status.json"
CLEAN_ROOT = PHASE5_ROOT / "clean_forward_v2"
STATE_PATH = CLEAN_ROOT / "forward_state.json"
JOURNAL_PATH = CLEAN_ROOT / "forward_journal.csv"
SHADOW_PATH = CLEAN_ROOT / "waiting_latest.json"
SERVICE_STATUS_PATH = CLEAN_ROOT / "forward_service_status.json"
LOCK_PATH = CLEAN_ROOT / "forward_service.lock"
CLEAN_LANE_MANIFEST_PATH = CLEAN_ROOT / "clean_lane_manifest.json"

BTC = "BTC-USD"
XRP = "XRP-USD"
CORE_PRODUCTS = tuple(p for p in PRODUCTS if p != XRP)
ALT_PRODUCTS = tuple(p for p in CORE_PRODUCTS if p != BTC)
LABELS = ("BTC", "ALT", "CASH")
ORIGINAL_HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
CLEAN_START = pd.Timestamp("2026-09-18T00:00:00Z")
# Compatibility for code that reports the original Phase 5 freeze boundary.
HOLDOUT = ORIGINAL_HOLDOUT
CLEAN_LANE_ID = "shared_crypto_v2_clean_forward_v2"
CLEAN_LANE_NAME = "Shared Crypto V2 Clean Forward V2"
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


def _clean_lane_manifest() -> dict:
    if not CLEAN_LANE_MANIFEST_PATH.exists():
        return {}
    payload = json.loads(CLEAN_LANE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Clean-lane manifest is not a JSON object")
    return payload


def _ensure_clean_lane(manifest: dict, model_sha256: str) -> dict:
    """Create or verify the isolated lane without mutating interrupted evidence."""
    for path in (LEGACY_STATE_PATH, LEGACY_JOURNAL_PATH):
        if not path.exists():
            raise FileNotFoundError(path)

    legacy_state_hash = _sha256(LEGACY_STATE_PATH)
    legacy_journal_hash = _sha256(LEGACY_JOURNAL_PATH)
    lane = _clean_lane_manifest()
    if lane:
        checks = {
            "lane id": lane.get("lane_id") == CLEAN_LANE_ID,
            "clean boundary": pd.Timestamp(lane.get("preregistered_start_utc")) == CLEAN_START,
            "source model": lane.get("source_model_sha256") == model_sha256,
            "interrupted state preservation": lane.get("interrupted_lane", {}).get("state_sha256") == legacy_state_hash,
            "interrupted journal preservation": lane.get("interrupted_lane", {}).get("journal_sha256") == legacy_journal_hash,
            "brokerage prohibition": lane.get("brokerage_orders") is False,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError("Clean-lane contract verification failed: " + ", ".join(failed))
        for path in (STATE_PATH, JOURNAL_PATH):
            if not path.exists():
                raise FileNotFoundError(path)
        return lane

    if STATE_PATH.exists() or JOURNAL_PATH.exists():
        raise RuntimeError("Unregistered clean-lane state or journal exists; refusing ambiguous recovery")

    policy = manifest.get("execution_policy", {})
    initial_label = manifest.get("state", {}).get("initial_current_executed_label")
    if initial_label not in LABELS:
        raise RuntimeError("Frozen manifest does not provide a valid initial sleeve")
    columns = list(manifest.get("forward_journal_contract", {}).get("columns") or [])
    if not columns:
        raise RuntimeError("Frozen manifest does not provide the forward journal schema")

    legacy = pd.read_csv(LEGACY_JOURNAL_PATH)
    legacy_last = None
    if len(legacy) and "decision_timestamp_utc" in legacy:
        parsed = pd.to_datetime(legacy["decision_timestamp_utc"], utc=True, errors="coerce", format="mixed").dropna()
        legacy_last = parsed.max().isoformat() if len(parsed) else None

    CLEAN_ROOT.mkdir(parents=True, exist_ok=True)
    state = {
        "lane_id": CLEAN_LANE_ID,
        "initialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_model_sha256": model_sha256,
        "current_executed_label": initial_label,
        "pending_candidate_label": None,
        "pending_candidate_count": 0,
        "confirmation_hours_required": CONFIRM_REQUIRED,
        "minimum_hold_hours": int(policy.get("minimum_hold_hours", 0)),
        "forward_evaluation_start_utc": CLEAN_START.isoformat(),
        "starting_equity": 1.0,
        "current_equity": 1.0,
        "last_forward_decision_timestamp_utc": None,
        "last_realized_timestamp_utc": None,
        "brokerage_orders": False,
        "research_note": "Fresh confirm_2 operational state for the separately preregistered clean lane; no interrupted-lane state was inherited.",
    }
    _atomic_json(STATE_PATH, state)
    journal_tmp = JOURNAL_PATH.with_suffix(JOURNAL_PATH.suffix + ".tmp")
    pd.DataFrame(columns=columns).to_csv(journal_tmp, index=False)
    journal_tmp.replace(JOURNAL_PATH)

    lane = {
        "schema_version": 1,
        "lane_id": CLEAN_LANE_ID,
        "display_name": CLEAN_LANE_NAME,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistered_start_utc": CLEAN_START.isoformat(),
        "decision_frequency": policy.get("decision_frequency"),
        "source_model_id": manifest.get("model", {}).get("model_id"),
        "source_model_sha256": model_sha256,
        "source_freeze_manifest_sha256": _sha256(MANIFEST_PATH),
        "execution_policy_id": policy.get("policy_id"),
        "confirmation_hours": int(policy.get("confirmation_hours", -1)),
        "initial_current_executed_label": initial_label,
        "interrupted_lane": {
            "classification": "PRESERVED_INTERRUPTED_NO_BACKFILL",
            "state_path": str(LEGACY_STATE_PATH),
            "state_sha256": legacy_state_hash,
            "journal_path": str(LEGACY_JOURNAL_PATH),
            "journal_sha256": legacy_journal_hash,
            "journal_rows": int(len(legacy)),
            "last_decision_timestamp_utc": legacy_last,
        },
        "late_start_policy": "FAIL_CLOSED_NO_START",
        "missed_hour_policy": "FAIL_CLOSED_NO_BACKFILL",
        "automatic_promotion": False,
        "human_review_required": True,
        "brokerage_orders": False,
    }
    _atomic_json(CLEAN_LANE_MANIFEST_PATH, lane)
    return lane


def _load_contract():
    for path in (MODEL_PATH, MANIFEST_PATH, LEGACY_STATE_PATH, LEGACY_JOURNAL_PATH):
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
    _ensure_clean_lane(manifest, actual)
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
    start = end - pd.Timedelta(LOOKBACK_DAYS, unit="D")
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
        df["decision_timestamp_utc"] = pd.to_datetime(
            df["decision_timestamp_utc"],
            utc=True,
            format="mixed",
        )
    return df


def _hourly_realized_detail(decision_ts: pd.Timestamp) -> dict | None:
    """Return the exact products used by the frozen hourly ALT realization rule.

    This is a read-only derivation from authoritative endpoint candles. It does
    not change the frozen model, confirm-2 execution state, or forward journal
    contract. Every included ALT has equal weight in the aggregate ALT sleeve.
    """
    end_ts = decision_ts + pd.Timedelta(1, unit="h")
    latest = _latest_available_timestamp(BTC)
    if latest is None or latest < end_ts:
        return None
    btc = _read_recent(BTC, end_ts)
    btc0 = btc.loc[btc["timestamp_utc"] == decision_ts, "close"]
    btc1 = btc.loc[btc["timestamp_utc"] == end_ts, "close"]
    if btc0.empty or btc1.empty:
        return None
    btc_r = float(btc1.iloc[-1] / btc0.iloc[-1] - 1.0)
    constituents = []
    for product_id in ALT_PRODUCTS:
        try:
            df = _read_recent(product_id, end_ts)
        except RuntimeError:
            continue
        p0 = df.loc[df["timestamp_utc"] == decision_ts, "close"]
        p1 = df.loc[df["timestamp_utc"] == end_ts, "close"]
        if not p0.empty and not p1.empty:
            constituents.append({
                "product_id": product_id,
                "return_1h": float(p1.iloc[-1] / p0.iloc[-1] - 1.0),
            })
    if len(constituents) < MIN_ALT_ASSETS:
        return None
    weight = 1.0 / len(constituents)
    for item in constituents:
        item["weight"] = weight
    return {
        "btc_return_1h": btc_r,
        "alt_return_1h": float(np.mean([item["return_1h"] for item in constituents])),
        "alt_constituents": constituents,
        "realized_through_utc": end_ts.isoformat(),
    }


def _hourly_realized(decision_ts: pd.Timestamp) -> tuple[float, float] | None:
    detail = _hourly_realized_detail(decision_ts)
    if detail is None:
        return None
    return float(detail["btc_return_1h"]), float(detail["alt_return_1h"])


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
        journal.loc[idx, "realized_through_utc"] = (ts + pd.Timedelta(1, unit="h")).isoformat()
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
    mode = "CLEAN_FORWARD" if decision_ts >= CLEAN_START else "WAITING_CLEAN_BOUNDARY"
    lane = _clean_lane_manifest()
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "mode": mode,
        "decision_timestamp_utc": decision_ts.isoformat(),
        "raw_predicted_label": raw_label,
        "probabilities": probs,
        "current_executed_label": state["current_executed_label"],
        "alt_asset_count": diagnostics["alt_asset_count"],
        "missing_decision_candle_alts": diagnostics["missing_decision_candle_alts"],
        "feature_ineligible_alts": diagnostics["feature_ineligible_alts"],
        "pending_rows_finalized": finalized,
        "model_sha256_verified": True,
        "service_pid": os.getpid(),
        "brokerage_orders": False,
        "lane_id": CLEAN_LANE_ID,
        "lane_name": CLEAN_LANE_NAME,
        "clean_start_utc": CLEAN_START.isoformat(),
        "interrupted_lane_classification": lane.get("interrupted_lane", {}).get("classification"),
        "interrupted_lane_journal_sha256": lane.get("interrupted_lane", {}).get("journal_sha256"),
        "automatic_promotion": False,
        "human_review_required": True,
    }
    if mode == "WAITING_CLEAN_BOUNDARY":
        result["action"] = "waiting_clean_boundary"
        result["note"] = "Clean evidence collection is locked until the preregistered boundary; no evidence row or execution transition was written."
        _atomic_json(SHADOW_PATH, result)
    else:
        journal = _read_journal()
        last = journal["decision_timestamp_utc"].max() if len(journal) else None
        if last is not None and decision_ts <= last:
            result["action"] = "already_processed"
        else:
            if last is None and decision_ts > CLEAN_START:
                result["action"] = "clean_boundary_missed_no_start"
                result["note"] = "The first preregistered clean boundary was missed. This lane fails closed and may not start late or backfill."
            elif last is not None and decision_ts > last + pd.Timedelta(1, unit="h"):
                # Preserve the outage as an explicit evidence gap, but resume from
                # the current genuinely observed boundary.  Never synthesize the
                # missing hourly decisions.  A pre-gap confirm_2 candidate cannot
                # count toward a post-gap confirmation, so restart only that
                # transient confirmation state while preserving the executed sleeve.
                gap_start = last + pd.Timedelta(1, unit="h")
                gap_end = decision_ts - pd.Timedelta(1, unit="h")
                missed_hours = int((decision_ts - last) / pd.Timedelta(1, unit="h")) - 1
                gap = {
                    "detected_at_utc": now.isoformat(),
                    "last_recorded_decision_utc": last.isoformat(),
                    "first_missed_decision_utc": gap_start.isoformat(),
                    "last_missed_decision_utc": gap_end.isoformat(),
                    "resume_decision_utc": decision_ts.isoformat(),
                    "missed_decision_hours": missed_hours,
                    "classification": "PRESERVED_GAP_NO_BACKFILL",
                }
                gaps = state.setdefault("evidence_gaps", [])
                already_recorded = any(
                    item.get("resume_decision_utc") == gap["resume_decision_utc"]
                    and item.get("last_recorded_decision_utc") == gap["last_recorded_decision_utc"]
                    for item in gaps
                    if isinstance(item, dict)
                )
                if not already_recorded:
                    gaps.append(gap)
                state["pending_candidate_label"] = None
                state["pending_candidate_count"] = 0
                state = _append_forward_decision(decision_ts, raw_label, probs, state)
                result["action"] = "forward_resumed_after_gap"
                result["evidence_gap"] = gap
                result["note"] = (
                    "Missed forward hours were preserved as an explicit evidence gap and were not "
                    "backfilled. Prospective collection resumed at the current observed boundary; "
                    "confirm_2 transient candidate state restarted across the gap."
                )
                result["current_executed_label"] = state["current_executed_label"]
                result["pending_candidate_label"] = state.get("pending_candidate_label")
                result["pending_candidate_count"] = state.get("pending_candidate_count", 0)
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


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_lock_exclusively() -> None:
    with LOCK_PATH.open("x", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def _acquire_lock() -> bool:
    """Acquire the service lock and safely recover a dead owner's stale lock."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_lock_exclusively()
        return False
    except FileExistsError:
        try:
            existing_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = None
        if existing_pid is not None and _process_is_alive(existing_pid):
            raise SystemExit(
                f"[SKIP] Crypto V2 forward service already running as PID {existing_pid}"
            )

    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    try:
        _write_lock_exclusively()
    except FileExistsError:
        raise SystemExit("[SKIP] Crypto V2 forward service lock was claimed during recovery")
    return True


def _publish_starting_status(stale_lock_recovered: bool) -> dict:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "mode": "STARTING",
        "action": "service_starting",
        "service_pid": os.getpid(),
        "stale_lock_recovered": bool(stale_lock_recovered),
        "model_sha256_verified": None,
        "brokerage_orders": False,
        "lane_id": CLEAN_LANE_ID,
        "lane_name": CLEAN_LANE_NAME,
        "clean_start_utc": CLEAN_START.isoformat(),
        "automatic_promotion": False,
        "human_review_required": True,
    }
    _atomic_json(SERVICE_STATUS_PATH, payload)
    return payload


def _release_lock() -> None:
    try:
        owner_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return
    if owner_pid == os.getpid():
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = ap.parse_args(argv)
    stop = False
    def request_stop(*_args):
        nonlocal stop; stop = True
    signal.signal(signal.SIGINT, request_stop); signal.signal(signal.SIGTERM, request_stop)
    stale_lock_recovered = _acquire_lock()
    try:
        _publish_starting_status(stale_lock_recovered)
        if stale_lock_recovered:
            print("[FORWARD] Recovered stale service lock from a dead or invalid PID", flush=True)
        while True:
            try:
                result = run_once()
                print(f"[FORWARD] {result['generated_at_utc']} mode={result['mode']} decision={result['decision_timestamp_utc']} raw={result['raw_predicted_label']} executed={result['current_executed_label']} alts={result['alt_asset_count']} action={result['action']}", flush=True)
            except Exception as exc:
                payload = {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "error",
                    "mode": "ERROR",
                    "action": "run_failed",
                    "service_pid": os.getpid(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "brokerage_orders": False,
                    "lane_id": CLEAN_LANE_ID,
                    "clean_start_utc": CLEAN_START.isoformat(),
                }
                _atomic_json(SERVICE_STATUS_PATH, payload)
                print(f"[FORWARD ERROR] {payload['error']}", flush=True)
            if args.once or stop: break
            for _ in range(max(15,args.poll_seconds)):
                if stop: break
                time.sleep(1)
            if stop: break
    finally:
        _release_lock()

if __name__ == "__main__": main()
