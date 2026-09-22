"""Read-only crypto dashboard service.

Presents frozen Crypto V1 research simulation plus frozen Crypto 15m V2 and
XRP V1 shadow/forward service state. Presentation only: never fits models or
places orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from ml.crypto_v1.config import CRYPTO_UNIVERSE, MODEL_ROOT

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
V2_PHASE4_ROOT = Path("data/model/crypto_15m_v2/phase4")
V2_PHASE5_ROOT = Path("data/model/crypto_15m_v2/phase5")
V2_ARCHIVED_ROOT = V2_PHASE5_ROOT / "clean_forward_v2"
V2_ARCHIVED_JOURNAL_PATH = V2_ARCHIVED_ROOT / "forward_journal.csv"
V2_CLEAN_ROOT = V2_PHASE5_ROOT / "clean_forward_v3"
V2_STATUS_PATH = V2_CLEAN_ROOT / "forward_service_status.json"
V2_JOURNAL_PATH = V2_CLEAN_ROOT / "forward_journal.csv"
V2_CLEAN_MANIFEST_PATH = V2_CLEAN_ROOT / "clean_lane_manifest.json"
V2_INTERRUPTED_JOURNAL_PATH = V2_PHASE5_ROOT / "forward_journal.csv"
V2_POLICY_SUMMARY_PATH = V2_PHASE4_ROOT / "policy_summary.csv"
V2_PHASE4_MANIFEST_PATH = V2_PHASE4_ROOT / "manifest.json"
V5_PHASE5_ROOT = Path("data/research/crypto_ten_year/reconstruction/crypto_v5/phase5")
V5_ARCHIVED_ROOT = V5_PHASE5_ROOT / "clean_forward_v1"
V5_CLEAN_ROOT = V5_PHASE5_ROOT / "clean_forward_v2"
V5_STATUS_PATH = V5_CLEAN_ROOT / "forward_service_status.json"
V5_STATE_PATH = V5_CLEAN_ROOT / "paper_state.json"
V5_JOURNAL_PATH = V5_CLEAN_ROOT / "paper_events.jsonl"
V5_MANIFEST_PATH = V5_CLEAN_ROOT / "clean_lane_manifest.json"
RECONCILE_STATUS_PATH = Path("data/live/crypto_rt/reconcile_status.json")
XRP_PHASE6_ROOT = Path("data/model/crypto_xrp_v1/phase6")
XRP_STATUS_PATH = XRP_PHASE6_ROOT / "forward_service_status.json"
XRP_SHADOW_PATH = XRP_PHASE6_ROOT / "shadow_latest.json"
XRP_PHASE7_ROOT = Path("data/model/crypto_xrp_v1/phase7")
XRP_PHASE7_STATUS_PATH = XRP_PHASE7_ROOT / "evaluation_status.json"
XRP_PHASE7_SUMMARY_PATH = XRP_PHASE7_ROOT / "forward_summary.json"
READINESS_STATUS_PATH = Path("data/live/crypto_readiness/readiness_status.json")
SHARED_V3_MANIFEST_PATH = Path("data/model/crypto_15m_v3/phase4/manifest.json")
XRP_V2_MANIFEST_PATH = Path("data/model/crypto_xrp_v2/phase5/manifest.json")
XRP_V3_MANIFEST_PATH = Path("data/model/crypto_xrp_v3/phase4/manifest.json")

PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "momentum"
PRIMARY_VARIANT = "top_5_equal_weight"
PRIMARY_TOP_N = 5
PRIMARY_COST_BPS = 25.0
DISPLAY_STARTING_EQUITY = 100000.0
SHARED_V2_STARTING_PAPER_EQUITY = 100000.0
V5_STARTING_PAPER_EQUITY = 100000.0


def _read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _parse_utc(value):
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        return None


def _heartbeat_time(path, payload):
    for key in ("generated_at_utc", "last_updated_utc", "updated_at_utc"):
        ts = _parse_utc(payload.get(key))
        if ts is not None:
            return ts
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) if path.exists() else None
    except OSError:
        return None


def _service_health(name, path, payload, stale_after_minutes, extra_error=None, detail_override=None):
    if not path.exists() or not payload:
        return {
            "name": name,
            "status": "UNAVAILABLE",
            "heartbeat_at_utc": None,
            "age_minutes": None,
            "stale_after_minutes": stale_after_minutes,
            "detail": "Runtime status file is missing or unreadable.",
        }

    raw_status = str(payload.get("status", "ok")).strip().lower()
    if raw_status not in {"ok", "success", "running", "healthy"}:
        return {
            "name": name,
            "status": "ERROR",
            "heartbeat_at_utc": payload.get("generated_at_utc") or payload.get("last_updated_utc"),
            "age_minutes": None,
            "stale_after_minutes": stale_after_minutes,
            "detail": f"Runtime status reported {raw_status!r}.",
        }

    if extra_error:
        return {
            "name": name,
            "status": "ERROR",
            "heartbeat_at_utc": payload.get("generated_at_utc") or payload.get("last_updated_utc"),
            "age_minutes": None,
            "stale_after_minutes": stale_after_minutes,
            "detail": extra_error,
        }

    heartbeat = _heartbeat_time(path, payload)
    if heartbeat is None:
        return {
            "name": name,
            "status": "UNAVAILABLE",
            "heartbeat_at_utc": None,
            "age_minutes": None,
            "stale_after_minutes": stale_after_minutes,
            "detail": "No usable heartbeat timestamp is available.",
        }

    age_minutes = max(0.0, (datetime.now(timezone.utc) - heartbeat).total_seconds() / 60.0)
    status = "STALE" if age_minutes > stale_after_minutes else "HEALTHY"
    detail = detail_override or (
        f"Heartbeat is {age_minutes:.1f} minutes old; stale threshold is {stale_after_minutes} minutes."
    )
    return {
        "name": name,
        "status": status,
        "heartbeat_at_utc": heartbeat.isoformat(),
        "age_minutes": round(age_minutes, 1),
        "stale_after_minutes": stale_after_minutes,
        "detail": detail,
    }


def _operational_health():
    reconcile = _read_json(RECONCILE_STATUS_PATH)
    v2 = _read_json(V2_STATUS_PATH)
    v5 = _read_json(V5_STATUS_PATH)

    v2_error = None
    if v2 and v2.get("model_sha256_verified") is False:
        v2_error = "Frozen Shared V2 model hash verification failed."
    elif v2 and v2.get("action") in {"clean_boundary_missed_no_start", "gap_detected_no_backfill"}:
        v2_error = "Shared V2 clean evidence lane is fail-closed after a missed required hour."

    v5_error = None
    if v5 and v5.get("contract_verified") is False:
        v5_error = "Crypto V5 frozen contract or artifact verification failed."
    elif v5 and str(v5.get("mode", "")).startswith("FAIL_CLOSED"):
        v5_error = "Crypto V5 clean paper lane is fail-closed and requires review."
    elif v5 and v5.get("brokerage_orders") is not False:
        v5_error = "Crypto V5 unexpectedly reports brokerage orders enabled."

    services = [
        _service_health("15m Reconciler", RECONCILE_STATUS_PATH, reconcile, 45),
        _service_health("Shared Crypto V3", V2_STATUS_PATH, v2, 90, v2_error),
        _service_health("Crypto V5 V2", V5_STATUS_PATH, v5, 30, v5_error),
        {
            "name": "Web Dashboard",
            "status": "HEALTHY",
            "heartbeat_at_utc": datetime.now(timezone.utc).isoformat(),
            "age_minutes": 0.0,
            "stale_after_minutes": 5,
            "detail": "This dashboard request rendered successfully.",
        },
    ]
    rank = {"HEALTHY": 0, "STALE": 1, "UNAVAILABLE": 2, "ERROR": 3}
    overall = max(services, key=lambda item: rank[item["status"]])["status"]
    return {
        "overall_status": overall,
        "services": services,
        "note": "Active crypto lanes only. Archived XRP services are excluded from operational status.",
    }


def _forward_evaluation_readiness():
    payload = _read_json(READINESS_STATUS_PATH)
    if not payload:
        return {
            "available": False,
            "status": "UNAVAILABLE",
            "ready": False,
            "message": "Forward-evaluation readiness snapshot is not available yet.",
        }

    heartbeat = _heartbeat_time(READINESS_STATUS_PATH, payload)
    age_minutes = None
    stale = False
    if heartbeat is not None:
        age_minutes = max(0.0, (datetime.now(timezone.utc) - heartbeat).total_seconds() / 60.0)
        stale = age_minutes > 30

    source_status = str(payload.get("status", "NOT_READY_FOR_FORWARD_EVALUATION"))
    display_status = "STALE" if stale else source_status
    failures = payload.get("failures") or []
    return {
        "available": True,
        "status": display_status,
        "source_status": source_status,
        "ready": bool(payload.get("ready", False)) and not stale,
        "generated_at_utc": payload.get("generated_at_utc"),
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "stale_after_minutes": 30,
        "holdout_start_utc": payload.get("holdout_start_utc"),
        "clean_forward_start_utc": payload.get("clean_forward_start_utc"),
        "pre_holdout": payload.get("pre_holdout"),
        "passed_checks": int(payload.get("passed_checks", 0) or 0),
        "total_checks": int(payload.get("total_checks", 0) or 0),
        "failed_checks": int(payload.get("failed_checks", 0) or 0),
        "failures": failures[:5],
        "brokerage_orders": bool(payload.get("brokerage_orders", False)),
        "message": (
            "Latest canonical readiness audit passed every check."
            if payload.get("ready") and not stale
            else "Readiness requires attention; review failed checks or refresh the audit snapshot."
        ),
    }


def _read_predictions():
    path = PHASE3_ROOT / "predictions.parquet"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    return frame


def _primary_daily():
    data = _read_csv(PHASE4_ROOT / "portfolio_daily.csv")
    if data.empty:
        return data
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    mask = (
        data["split"].eq("holdout")
        & data["model_id"].eq(PRIMARY_MODEL_ID)
        & data["variant"].eq(PRIMARY_VARIANT)
        & pd.to_numeric(data["top_n"], errors="coerce").eq(PRIMARY_TOP_N)
        & pd.to_numeric(data["cost_bps_round_trip"], errors="coerce").eq(PRIMARY_COST_BPS)
    )
    return data.loc[mask].sort_values("timestamp_utc").reset_index(drop=True)


def _btc_daily():
    data = _read_csv(PHASE4_ROOT / "portfolio_daily.csv")
    if data.empty:
        return data
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    mask = (
        data["split"].eq("holdout")
        & data["model_id"].eq(PRIMARY_MODEL_ID)
        & data["variant"].eq("btc_benchmark")
        & pd.to_numeric(data["cost_bps_round_trip"], errors="coerce").eq(PRIMARY_COST_BPS)
    )
    return data.loc[mask].sort_values("timestamp_utc").reset_index(drop=True)


def _latest_rankings():
    predictions = _read_predictions()
    if predictions.empty:
        return None, []
    frame = predictions[
        (predictions["split"] == "holdout")
        & (predictions["model_id"] == PRIMARY_MODEL_ID)
        & (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
    ].copy()
    if frame.empty:
        return None, []
    latest = frame["timestamp_utc"].max()
    day = frame[frame["timestamp_utc"] == latest].sort_values(
        ["predicted_score", "product_id"], ascending=[False, True]
    )
    rows = []
    count = len(day)
    for rank, row in enumerate(day.itertuples(index=False), 1):
        score = float(row.predicted_score)
        rows.append(
            {
                "rank": rank,
                "product_id": row.product_id,
                "score": score,
                "score_pct": score * 100,
                "rank_percentile": (1 - (rank - 1) / max(1, count - 1)) * 100,
                "top5": rank <= PRIMARY_TOP_N,
            }
        )
    return latest.isoformat(), rows


def _equity_history(primary, btc):
    if primary.empty:
        return []
    benchmark = (
        dict(zip(btc["timestamp_utc"], pd.to_numeric(btc["equity"], errors="coerce")))
        if not btc.empty
        else {}
    )
    return [
        {
            "timestamp": row.timestamp_utc.isoformat(),
            "equity": DISPLAY_STARTING_EQUITY * float(row.equity),
            "btc_equity": (
                DISPLAY_STARTING_EQUITY * float(benchmark[row.timestamp_utc])
                if row.timestamp_utc in benchmark and pd.notna(benchmark[row.timestamp_utc])
                else None
            ),
            "is_rebalance": bool(row.is_rebalance),
        }
        for row in primary.itertuples(index=False)
    ]


def _v2_live():
    status = _read_json(V2_STATUS_PATH)
    lane = _read_json(V2_CLEAN_MANIFEST_PATH)
    reconcile = _read_json(RECONCILE_STATUS_PATH)
    if not status:
        return {"available": False, "message": "Frozen Crypto 15m V2 forward service status is not available yet."}
    probs = status.get("probabilities") or {}

    def probability(label):
        try:
            value = float(probs.get(label))
        except (TypeError, ValueError):
            return None
        return value if 0.0 <= value <= 1.0 else None

    probability_values = {
        "BTC": probability("BTC"),
        "ALT": probability("ALT"),
        "CASH": probability("CASH"),
    }
    probability_sum = sum(value for value in probability_values.values() if value is not None)
    decision_available = (
        all(value is not None for value in probability_values.values())
        and abs(probability_sum - 1.0) <= 0.01
        and bool(status.get("decision_timestamp_utc"))
        and bool(status.get("raw_predicted_label"))
        and bool(status.get("current_executed_label"))
    )
    journal = _read_csv(V2_JOURNAL_PATH)
    realized = (
        journal[journal.get("status", pd.Series(dtype=str)).eq("REALIZED")]
        if not journal.empty and "status" in journal
        else pd.DataFrame()
    )
    equity = (
        float(pd.to_numeric(realized.get("equity", pd.Series(dtype=float)), errors="coerce").dropna().iloc[-1])
        if not realized.empty
        and pd.to_numeric(realized.get("equity", pd.Series(dtype=float)), errors="coerce").notna().any()
        else 1.0
    )
    return {
        "available": True,
        "decision_available": decision_available,
        "message": (
            "Latest frozen Shared V2 decision is available."
            if decision_available
            else "The runtime status exists, but no complete decision payload is available. Probabilities are intentionally withheld rather than shown as zero."
        ),
        "mode": status.get("mode", "UNKNOWN"),
        "action": status.get("action"),
        "decision_timestamp_utc": status.get("decision_timestamp_utc"),
        "generated_at_utc": status.get("generated_at_utc"),
        "raw_predicted_label": status.get("raw_predicted_label"),
        "current_executed_label": status.get("current_executed_label"),
        "prob_btc": probability_values["BTC"],
        "prob_alt": probability_values["ALT"],
        "prob_cash": probability_values["CASH"],
        "alt_asset_count": int(status.get("alt_asset_count", 0)),
        "missing_alts": status.get("missing_decision_candle_alts", []),
        "ineligible_alts": status.get("feature_ineligible_alts", []),
        "brokerage_orders": bool(status.get("brokerage_orders", False)),
        "lane_id": status.get("lane_id") or lane.get("lane_id"),
        "lane_name": status.get("lane_name") or lane.get("display_name"),
        "clean_start_utc": status.get("clean_start_utc") or lane.get("preregistered_start_utc"),
        "interrupted_lane_classification": status.get("interrupted_lane_classification") or lane.get("interrupted_lane", {}).get("classification"),
        "interrupted_journal_rows": int(lane.get("interrupted_lane", {}).get("journal_rows", 0) or 0),
        "interrupted_last_decision_utc": lane.get("interrupted_lane", {}).get("last_decision_timestamp_utc"),
        "automatic_promotion": bool(status.get("automatic_promotion", False)),
        "human_review_required": bool(status.get("human_review_required", True)),
        "reconcile_boundary": reconcile.get("latest_expected_bar_start_utc"),
        "reconcile_product_count": reconcile.get("product_count"),
        "journal_rows": max(0, len(journal)),
        "realized_rows": len(realized),
        "paper_equity_multiple": equity,
    }


def _xrp_live():
    status = _read_json(XRP_STATUS_PATH)
    shadow = _read_json(XRP_SHADOW_PATH)
    if not status:
        return {"available": False, "message": "XRP V1 Phase 6 shadow forward service status is not available yet."}
    return {
        "available": True,
        "mode": status.get("mode", "UNKNOWN"),
        "action": status.get("action"),
        "decision_timestamp_utc": status.get("decision_timestamp_utc"),
        "current_shadow_state": status.get("current_shadow_state"),
        "score": status.get("predicted_btc_relative_return_4h"),
        "model_sha256_verified": bool(status.get("model_sha256_verified", False)),
        "policy_verified": bool(status.get("policy_verified", False)),
        "brokerage_orders": bool(status.get("brokerage_orders", False)),
        "shadow_only": bool(status.get("shadow_only", True)),
        "xrp_latest_bar_utc": shadow.get("xrp_latest_bar_utc"),
        "btc_latest_bar_utc": shadow.get("btc_latest_bar_utc"),
        "common_latest_bar_utc": shadow.get("common_latest_bar_utc"),
        "state_before": shadow.get("state_before"),
        "state_after": shadow.get("state_after"),
        "proposed_state": shadow.get("proposed_state"),
        "state_switch": bool(shadow.get("state_switch", False)),
        "state_reset": bool(shadow.get("state_reset", False)),
        "minimum_hold_blocked": bool(shadow.get("minimum_hold_blocked", False)),
        "hours_since_state_change": shadow.get("hours_since_state_change"),
        "minimum_hold_hours": shadow.get("minimum_hold_hours", 24),
        "policy_id": shadow.get("policy_id", "hyst_10_05_hold24"),
        "model_id": shadow.get("model_id", "ridge"),
        "model_sha256": shadow.get("model_sha256"),
        "feature_count": shadow.get("feature_count", 44),
        "future_holdout_start_utc": shadow.get("future_holdout_start_utc", "2026-09-01T00:00:00+00:00"),
        "forward_evaluation_journal": bool(shadow.get("forward_evaluation_journal", False)),
    }


def _v2_research_evidence():
    summary = _read_csv(V2_POLICY_SUMMARY_PATH)
    manifest = _read_json(V2_PHASE4_MANIFEST_PATH)
    if summary.empty or "policy" not in summary:
        return {"available": False}
    row = summary[summary["policy"] == "confirm_2"]
    if row.empty:
        return {"available": False}
    record = row.iloc[0]
    return {
        "available": True,
        "policy": "confirm_2",
        "confirmation_hours": 2,
        "ending_equity_0bps": float(record["ending_equity_0bps"]),
        "ending_equity_5bps": float(record["ending_equity_5bps"]),
        "executed_switches": int(record["executed_switches"]),
        "switch_reduction_fraction": float(record["switch_reduction_fraction"]),
        "max_drawdown_0bps": float(record["max_drawdown_0bps"]),
        "max_drawdown_5bps": float(record["max_drawdown_5bps"]),
        "raw_switches": 6084,
        "research_status": manifest.get(
            "research_status",
            "EXPLORATORY ONLY. Phase 3 OOS results were already inspected before policy selection.",
        ),
        "future_validation_rule": manifest.get("future_validation_rule"),
        "cost_limitation": manifest.get("cost_limitation"),
        "holdout_start": "2026-09-01T00:00:00+00:00",
    }



def _equity_drawdown(values):
    clean = [float(x) for x in values if pd.notna(x)]
    if not clean:
        return None
    series = pd.Series([1.0] + clean, dtype=float)
    return float((series / series.cummax() - 1.0).min())


def _archived_shared_v2_performance():
    journal = _read_csv(V2_ARCHIVED_JOURNAL_PATH)
    if journal.empty or "status" not in journal:
        return {
            "name": "Shared Crypto V2 Clean Forward V2",
            "classification": "PRESERVED_INTERRUPTED_NO_BACKFILL",
            "decision_count": 0, "realized_count": 0,
            "ending_equity": 1.0, "ending_equity_dollars": SHARED_V2_STARTING_PAPER_EQUITY,
            "paper_return": 0.0, "latest_realized_utc": None,
        }
    realized = journal[journal["status"].eq("REALIZED")].copy()
    values = pd.to_numeric(realized.get("equity", pd.Series(dtype=float)), errors="coerce").dropna()
    equity = float(values.iloc[-1]) if len(values) else 1.0
    latest = (
        realized["realized_through_utc"].dropna().iloc[-1]
        if not realized.empty and "realized_through_utc" in realized
        and realized["realized_through_utc"].notna().any()
        else None
    )
    return {
        "name": "Shared Crypto V2 Clean Forward V2",
        "classification": "PRESERVED_INTERRUPTED_NO_BACKFILL",
        "decision_count": len(journal), "realized_count": len(realized),
        "ending_equity": equity,
        "ending_equity_dollars": equity * SHARED_V2_STARTING_PAPER_EQUITY,
        "paper_return": equity - 1.0, "latest_realized_utc": str(latest) if latest else None,
    }


def _shared_v2_forward_performance(now_utc=None):
    holdout = pd.Timestamp("2026-09-22T07:00:00Z")
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
    journal = _read_csv(V2_JOURNAL_PATH)
    base = {
        "name": "Shared Crypto V2 Clean Forward V3",
        "holdout_start_utc": holdout.isoformat(),
        "archived_v2": _archived_shared_v2_performance(),
        "cost_bps": 5.0,
        "brokerage_orders": False,
        "starting_equity_dollars": SHARED_V2_STARTING_PAPER_EQUITY,
    }
    empty = {
        "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": 0,
        "realized_count": 0, "pending_count": 0, "switch_count": 0,
        "candidate_equity": 1.0, "candidate_equity_dollars": SHARED_V2_STARTING_PAPER_EQUITY,
        "candidate_return": 0.0, "candidate_max_drawdown": None,
        "benchmark_label": "Always BTC", "benchmark_equity": 1.0,
        "benchmark_equity_dollars": SHARED_V2_STARTING_PAPER_EQUITY,
        "benchmark_return": 0.0, "benchmark_max_drawdown": None,
        "latest_realized_utc": None, "chart_points": [], "return_points": [],
        "probability_points": [],
    }
    if now < holdout:
        return {**base, **empty}
    if journal.empty or "decision_timestamp_utc" not in journal:
        return {**base, **empty}
    frame = journal.copy()
    frame["decision_timestamp_utc"] = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="coerce")
    frame = frame[frame["decision_timestamp_utc"] >= holdout].sort_values("decision_timestamp_utc")
    realized = frame[frame.get("status", pd.Series(index=frame.index, dtype=str)).eq("REALIZED")].copy()
    decision_count = len(frame)
    realized_count = len(realized)
    pending_count = max(0, decision_count - realized_count)
    switch_count = int(pd.to_numeric(frame.get("sleeve_switch", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0).sum())
    if realized.empty:
        probabilities = []
        for row in frame.itertuples(index=False):
            probabilities.append({
                "timestamp": pd.Timestamp(row.decision_timestamp_utc).isoformat(),
                "btc": float(row.prob_btc), "alt": float(row.prob_alt),
                "cash": float(row.prob_cash),
                "executed": str(row.executed_label_after),
            })
        return {**base, **empty, "decision_count": decision_count,
                "pending_count": pending_count, "switch_count": switch_count,
                "probability_points": probabilities}
    candidate_path = pd.to_numeric(realized["equity"], errors="coerce").dropna()
    candidate_equity = float(candidate_path.iloc[-1]) if len(candidate_path) else 1.0
    btc_returns = pd.to_numeric(realized["btc_realized_return_1h"], errors="coerce").dropna()
    btc_path = (1.0 + btc_returns).cumprod()
    benchmark_equity = float(btc_path.iloc[-1]) if len(btc_path) else 1.0
    latest_realized = realized["realized_through_utc"].dropna().iloc[-1] if "realized_through_utc" in realized and realized["realized_through_utc"].notna().any() else realized["decision_timestamp_utc"].iloc[-1].isoformat()
    candidate_peak = 1.0
    btc_peak = 1.0
    btc_running = 1.0
    chart_points = [{
        "timestamp": holdout.isoformat(), "candidate": SHARED_V2_STARTING_PAPER_EQUITY,
        "benchmark": SHARED_V2_STARTING_PAPER_EQUITY, "candidate_drawdown": 0.0,
        "benchmark_drawdown": 0.0,
    }]
    return_points = []
    for row in realized.itertuples(index=False):
        candidate = float(row.equity)
        btc_return = float(row.btc_realized_return_1h)
        btc_running *= 1.0 + btc_return
        candidate_peak = max(candidate_peak, candidate)
        btc_peak = max(btc_peak, btc_running)
        timestamp = str(row.realized_through_utc or pd.Timestamp(row.decision_timestamp_utc).isoformat())
        chart_points.append({
            "timestamp": timestamp,
            "candidate": candidate * SHARED_V2_STARTING_PAPER_EQUITY,
            "benchmark": btc_running * SHARED_V2_STARTING_PAPER_EQUITY,
            "candidate_drawdown": candidate / candidate_peak - 1.0,
            "benchmark_drawdown": btc_running / btc_peak - 1.0,
        })
        return_points.append({
            "timestamp": timestamp,
            "net_return": float(row.net_selected_return_1h),
            "btc_return": btc_return,
            "executed": str(row.executed_label_after),
        })
    probability_points = []
    for row in frame.itertuples(index=False):
        probability_points.append({
            "timestamp": pd.Timestamp(row.decision_timestamp_utc).isoformat(),
            "btc": float(row.prob_btc), "alt": float(row.prob_alt),
            "cash": float(row.prob_cash), "executed": str(row.executed_label_after),
        })
    return {
        **base, "status": "FORWARD_EVALUATION_ACTIVE",
        "decision_count": decision_count, "realized_count": realized_count,
        "pending_count": pending_count, "switch_count": switch_count,
        "candidate_equity": candidate_equity,
        "candidate_equity_dollars": candidate_equity * SHARED_V2_STARTING_PAPER_EQUITY,
        "candidate_return": candidate_equity - 1.0,
        "candidate_max_drawdown": _equity_drawdown(candidate_path.tolist()),
        "benchmark_label": "Always BTC", "benchmark_equity": benchmark_equity,
        "benchmark_equity_dollars": benchmark_equity * SHARED_V2_STARTING_PAPER_EQUITY,
        "benchmark_return": benchmark_equity - 1.0,
        "benchmark_max_drawdown": _equity_drawdown(btc_path.tolist()),
        "latest_realized_utc": str(latest_realized), "chart_points": chart_points,
        "return_points": return_points, "probability_points": probability_points,
    }


def _v5_forward_performance():
    manifest = _read_json(V5_MANIFEST_PATH)
    status = _read_json(V5_STATUS_PATH)
    state = _read_json(V5_STATE_PATH)
    events = _read_jsonl(V5_JOURNAL_PATH)
    clean_start = manifest.get(
        "preregistered_observation_start_utc",
        manifest.get("preregistered_start_utc", "2026-09-23T07:00:00+00:00"),
    )
    decisions = [row for row in events if row.get("event_type") == "DECISION"]
    realizations = [row for row in events if row.get("event_type") == "REALIZATION"]
    current_equity = float(state.get("paper_equity", V5_STARTING_PAPER_EQUITY) or V5_STARTING_PAPER_EQUITY)
    chart_points = [{
        "timestamp": clean_start, "candidate": V5_STARTING_PAPER_EQUITY,
        "candidate_drawdown": 0.0,
    }]
    return_points = []
    peak = V5_STARTING_PAPER_EQUITY
    for row in sorted(realizations, key=lambda item: item.get("realized_through_utc", "")):
        equity = float(row.get("paper_equity_after", V5_STARTING_PAPER_EQUITY))
        peak = max(peak, equity)
        timestamp = row.get("realized_through_utc") or row.get("decision_timestamp_utc")
        chart_points.append({
            "timestamp": timestamp, "candidate": equity,
            "candidate_drawdown": equity / peak - 1.0,
        })
        return_points.append({
            "timestamp": timestamp, "net_return": float(row.get("net_return", 0.0)),
            "gross_return": float(row.get("gross_return", 0.0)),
            "regime": row.get("selected_regime"),
        })
    latest = decisions[-1] if decisions else {}
    mode = status.get("mode", "NOT_INSTALLED" if not status else "UNKNOWN")
    return {
        "name": "Crypto V5 Clean Paper V2", "available": bool(status or state or events),
        "archived_lane_name": "Crypto V5 Clean Paper V1",
        "archived_lane_mutated": False,
        "status": status.get("status", "not_started"), "mode": mode,
        "action": status.get("action"), "generated_at_utc": status.get("generated_at_utc"),
        "clean_start_utc": clean_start,
        "first_eligible_decision_utc": manifest.get("first_eligible_decision_utc", clean_start),
        "starting_equity_dollars": V5_STARTING_PAPER_EQUITY,
        "current_equity_dollars": current_equity,
        "candidate_return": current_equity / V5_STARTING_PAPER_EQUITY - 1.0,
        "candidate_max_drawdown": min(
            [point["candidate_drawdown"] for point in chart_points], default=0.0),
        "decision_count": len(decisions), "realized_count": len(realizations),
        "pending_count": max(0, len(decisions) - len(realizations)),
        "selected_regime": latest.get("selected_regime") or state.get("selected_regime", "CASH"),
        "top_ranked_assets": latest.get("top_ranked_assets", []),
        "allocation_scores": latest.get("allocation_scores", {}),
        "target_weights": latest.get("target_weights", state.get("weights", {"CASH": 1.0})),
        "turnover": latest.get("turnover"), "cost_bps": 25.0,
        "model_id": latest.get("model_id", "ridge"), "horizon_days": 3,
        "top_n": 3, "chart_points": chart_points, "return_points": return_points,
        "contract_verified": bool(status.get("contract_verified", False)) if status else False,
        "paper_only": True, "brokerage_orders": False,
        "automatic_promotion": False, "human_review_required": True,
    }


def _xrp_phase7_forward_performance():
    holdout = pd.Timestamp("2026-09-01T00:00:00Z")
    now = pd.Timestamp.now(tz="UTC")
    summary = _read_json(XRP_PHASE7_SUMMARY_PATH)
    base = {
        "name": "XRP V1 Phase 7",
        "holdout_start_utc": holdout.isoformat(),
        "cost_bps": 5.0,
        "brokerage_orders": False,
    }
    if now < holdout or not summary or int(summary.get("valid_realization_count", 0) or 0) == 0:
        return {**base, "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": int(summary.get("decision_count", 0) or 0) if summary else 0, "realized_count": int(summary.get("valid_realization_count", 0) or 0) if summary else 0, "invalid_count": int(summary.get("invalid_realization_count", 0) or 0) if summary else 0, "pending_count": int(summary.get("pending_realization_count", 0) or 0) if summary else 0, "switch_count": int(summary.get("state_switch_count", 0) or 0) if summary else 0, "candidate_equity": 1.0, "candidate_return": 0.0, "candidate_max_drawdown": None, "benchmark_label": "Always BTC", "benchmark_equity": 1.0, "benchmark_return": 0.0, "benchmark_max_drawdown": None, "latest_realized_utc": None}
    candidate_equity = float(summary.get("equity_5bps", 1.0))
    benchmark_equity = float(summary.get("always_btc_equity", 1.0))
    return {**base, "status": "FORWARD_EVALUATION_ACTIVE", "decision_count": int(summary.get("decision_count", 0) or 0), "realized_count": int(summary.get("valid_realization_count", 0) or 0), "invalid_count": int(summary.get("invalid_realization_count", 0) or 0), "pending_count": int(summary.get("pending_realization_count", 0) or 0), "switch_count": int(summary.get("state_switch_count", 0) or 0), "candidate_equity": candidate_equity, "candidate_return": candidate_equity - 1.0, "candidate_max_drawdown": summary.get("max_drawdown_5bps"), "benchmark_label": "Always BTC", "benchmark_equity": benchmark_equity, "benchmark_return": benchmark_equity - 1.0, "benchmark_max_drawdown": summary.get("always_btc_max_drawdown"), "latest_realized_utc": summary.get("last_realized_decision_utc")}


def _future_forward_performance():
    return {
        "holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "shared_v2_clean_start_utc": "2026-09-22T07:00:00+00:00",
        "shared_v2": _shared_v2_forward_performance(),
        "crypto_v5": _v5_forward_performance(),
        "xrp_phase7": _xrp_phase7_forward_performance(),
        "note": "XRP retains its Sep 1 evidence boundary. Shared V2 Clean Forward V2 is preserved as interrupted evidence. V3 begins at the separately preregistered Sep 22 07:00 UTC boundary with fresh state and a $100,000 paper basis. No backfill, tuning, automatic promotion, or real brokerage orders.",
    }


FORWARD_VALIDATION_MIN_REALIZATIONS = 30


def _forward_validation_track(track):
    realized = int(track.get("realized_count", 0) or 0)
    remaining = max(0, FORWARD_VALIDATION_MIN_REALIZATIONS - realized)
    base = {
        "name": track.get("name"),
        "minimum_realizations": FORWARD_VALIDATION_MIN_REALIZATIONS,
        "realized_count": realized,
        "observations_remaining": remaining,
        "brokerage_orders": False,
    }
    if realized < FORWARD_VALIDATION_MIN_REALIZATIONS:
        return {
            **base,
            "status": "AWAITING_MINIMUM_FUTURE_SAMPLE",
            "assessment_ready": False,
            "assessment": None,
            "candidate_return": track.get("candidate_return", 0.0),
            "benchmark_return": track.get("benchmark_return", 0.0),
            "excess_return": None,
            "candidate_max_drawdown": track.get("candidate_max_drawdown"),
            "benchmark_max_drawdown": track.get("benchmark_max_drawdown"),
            "drawdown_comparison": "NOT_AVAILABLE",
        }

    candidate_return = float(track.get("candidate_return", 0.0) or 0.0)
    benchmark_return = float(track.get("benchmark_return", 0.0) or 0.0)
    excess = candidate_return - benchmark_return
    tolerance = 1e-12
    if excess > tolerance:
        assessment = "OUTPERFORMING_BENCHMARK"
    elif excess < -tolerance:
        assessment = "UNDERPERFORMING_BENCHMARK"
    else:
        assessment = "MATCHING_BENCHMARK"

    candidate_dd = track.get("candidate_max_drawdown")
    benchmark_dd = track.get("benchmark_max_drawdown")
    if candidate_dd is None or benchmark_dd is None:
        dd_comparison = "NOT_AVAILABLE"
    elif float(candidate_dd) > float(benchmark_dd) + tolerance:
        dd_comparison = "BETTER_THAN_BENCHMARK"
    elif float(candidate_dd) < float(benchmark_dd) - tolerance:
        dd_comparison = "WORSE_THAN_BENCHMARK"
    else:
        dd_comparison = "MATCHING_BENCHMARK"

    return {
        **base,
        "status": "FORWARD_SAMPLE_ASSESSMENT_AVAILABLE",
        "assessment_ready": True,
        "assessment": assessment,
        "candidate_return": candidate_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess,
        "candidate_max_drawdown": candidate_dd,
        "benchmark_max_drawdown": benchmark_dd,
        "drawdown_comparison": dd_comparison,
    }


def _forward_validation_summary(forward_performance):
    return {
        "minimum_realizations": FORWARD_VALIDATION_MIN_REALIZATIONS,
        "shared_v2": _forward_validation_track(forward_performance["shared_v2"]),
        "xrp_phase7": _forward_validation_track(forward_performance["xrp_phase7"]),
        "note": "Fixed 30-realization gate applied independently to XRP's Sep 1 lane and Shared V2's Sep 18 clean lane. This is descriptive assessment, not model selection, threshold tuning, or promotion authority.",
    }


def _development_research_tracks():
    shared = _read_json(SHARED_V3_MANIFEST_PATH)
    xrp_v2 = _read_json(XRP_V2_MANIFEST_PATH)
    xrp_v3 = _read_json(XRP_V3_MANIFEST_PATH)
    return [
        {
            "name": "Shared Crypto V3",
            "status": shared.get("status", "REJECT_CURRENT_POLICY_FAMILY"),
            "summary": "15m decisions / 1h horizon. Current turnover-control policy family failed realistic transaction-cost robustness and is preserved as rejected development evidence.",
            "detail": "No freeze. Frozen Shared V2 remains unchanged.",
        },
        {
            "name": "XRP V2",
            "status": xrp_v2.get("status", "OVERLAY_DIAGNOSTICS_ONLY_NO_FREEZE"),
            "summary": "15m decisions / 1h BTC-relative research. Aggregate overlay evidence exists, but temporal stability and drawdown gates were insufficient.",
            "detail": "Diagnostics only. No freeze and no further tuning of the same V2 policy family.",
        },
        {
            "name": "XRP V3",
            "status": xrp_v3.get("status", "NO_PROMOTION_CANDIDATE"),
            "summary": "BTC-default selective XRP overlay. Aggregate 5 bps results were promising, but the pre-registered 75% positive-fold gate failed.",
            "detail": "No promotion candidate. Frozen XRP V1 Phase 6 remains unchanged.",
        },
    ]


def get_crypto_dashboard_payload():
    primary = _primary_daily()
    btc = _btc_daily()
    ranking_timestamp, rankings = _latest_rankings()
    live = _v2_live()
    evidence = _v2_research_evidence()
    xrp_live = _xrp_live()
    research_tracks = _development_research_tracks()
    operational_health = _operational_health()
    forward_evaluation_readiness = _forward_evaluation_readiness()
    future_forward_performance = _future_forward_performance()
    forward_validation_summary = _forward_validation_summary(future_forward_performance)

    common = {
        "universe": list(CRYPTO_UNIVERSE),
        "rankings": rankings,
        "ranking_timestamp": ranking_timestamp,
        "live_v2": live,
        "v2_research": evidence,
        "xrp_live": xrp_live,
        "development_research_tracks": research_tracks,
        "operational_health": operational_health,
        "forward_evaluation_readiness": forward_evaluation_readiness,
        "future_forward_performance": future_forward_performance,
        "v5_forward_performance": future_forward_performance["crypto_v5"],
        "forward_validation_summary": forward_validation_summary,
    }
    if primary.empty:
        return {
            "available": False,
            "message": "Crypto V1 Phase 4 artifacts are not available on this machine.",
            **common,
        }

    current_multiple = float(primary["equity"].iloc[-1])
    current_equity = DISPLAY_STARTING_EQUITY * current_multiple
    cumulative_return = current_multiple - 1
    peak = pd.to_numeric(primary["equity"], errors="coerce").cummax()
    drawdown = pd.to_numeric(primary["equity"], errors="coerce") / peak - 1
    btc_multiple = float(btc["equity"].iloc[-1]) if not btc.empty else None
    btc_return = btc_multiple - 1 if btc_multiple is not None else None
    excess = cumulative_return - btc_return if btc_return is not None else None
    rebalances = primary[primary["is_rebalance"].astype(str).str.lower().isin(["true", "1"])]

    return {
        "available": True,
        "mode": "frozen_research_simulation",
        "starting_equity": DISPLAY_STARTING_EQUITY,
        "current_equity": current_equity,
        "net_change": current_equity - DISPLAY_STARTING_EQUITY,
        "cumulative_return": cumulative_return,
        "btc_return": btc_return,
        "excess_return_vs_btc": excess,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0,
        "observation_count": max(0, len(primary) - 1),
        "rebalance_count": int(primary["is_rebalance"].astype(str).str.lower().isin(["true", "1"]).sum()),
        "latest_rebalance_timestamp": rebalances["timestamp_utc"].max().isoformat() if not rebalances.empty else None,
        "top_five": rankings[:5],
        "equity_history": _equity_history(primary, btc),
        **common,
        "contract": {
            "research_version": "crypto_v1",
            "model_id": PRIMARY_MODEL_ID,
            "horizon_days": PRIMARY_HORIZON_DAYS,
            "variant": PRIMARY_VARIANT,
            "top_n": PRIMARY_TOP_N,
            "round_trip_cost_bps": PRIMARY_COST_BPS,
            "benchmark": "BTC-USD",
            "leverage": False,
            "real_orders": False,
        },
    }
