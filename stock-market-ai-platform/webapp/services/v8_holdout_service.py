"""Read-only V8 frozen holdout dashboard service."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
ROOT = Path("data/model/v8/holdout")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
V8_RANKED_PATH = Path("data/model/v8/phase4/fixed_complementarity_ranked_panel.parquet")


def _events():
    out = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _event_time(event):
    event_type = event.get("event_type")
    if event_type == "EXIT":
        return event.get("exit_timestamp_utc")
    if event_type == "ENTRY":
        return event.get("entry_timestamp_utc")
    return event.get("decision_timestamp_utc")


def _event_history(events):
    """Return a compact read-only lifecycle view for dashboard visualization."""
    rows = []
    for event in events:
        event_type = event.get("event_type")
        if event_type not in {"DECISION", "ENTRY", "EXIT"}:
            continue
        rows.append({
            "event_type": event_type,
            "timestamp_utc": _event_time(event),
            "decision_timestamp_utc": event.get("decision_timestamp_utc"),
            "cohort_offset": event.get("cohort_offset"),
            "symbol_count": len(event.get("symbols", [])),
            "net_portfolio_return": event.get("net_portfolio_return") if event_type == "EXIT" else None,
            "spy_return": event.get("spy_return") if event_type == "EXIT" else None,
            "net_relative_return": event.get("net_relative_return") if event_type == "EXIT" else None,
        })
    return sorted(rows, key=lambda row: row.get("timestamp_utc") or "")


def _latest_v8_top10():
    """Read the latest eligible pre-holdout DISTANCE_ONLY Top-10 snapshot."""
    if not V8_RANKED_PATH.exists():
        return {"timestamp_utc": None, "rows": []}
    try:
        panel = pd.read_parquet(
            V8_RANKED_PATH,
            columns=["timestamp_utc", "symbol", "score", "score_id", "rank_descending"],
        )
        panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True, errors="coerce")
        panel = panel[
            (panel["score_id"] == "DISTANCE_ONLY")
            & panel["timestamp_utc"].notna()
            & (panel["timestamp_utc"] < HOLDOUT_START)
        ].copy()
        if panel.empty:
            return {"timestamp_utc": None, "rows": []}
        latest_ts = panel["timestamp_utc"].max()
        latest = (
            panel[panel["timestamp_utc"] == latest_ts]
            .sort_values(["rank_descending", "symbol"], ascending=[True, True])
            .head(10)
        )
        rows = []
        for _, row in latest.iterrows():
            rows.append({
                "rank": int(row["rank_descending"]),
                "symbol": str(row["symbol"]),
                "score": float(row["score"]),
                "target_weight": 0.10,
            })
        return {"timestamp_utc": latest_ts.isoformat(), "rows": rows}
    except Exception:
        return {"timestamp_utc": None, "rows": []}


def _curve(exits):
    if not exits:
        return []
    by_cohort = {i: {"strategy": 1.0, "spy": 1.0} for i in range(5)}
    points = []
    exits = sorted(exits, key=lambda e: e.get("exit_timestamp_utc", ""))
    for e in exits:
        c = int(e["cohort_offset"])
        by_cohort[c]["strategy"] *= 1.0 + float(e["net_portfolio_return"])
        by_cohort[c]["spy"] *= 1.0 + float(e["spy_return"])
        active = [v for v in by_cohort.values() if v["strategy"] != 1.0 or v["spy"] != 1.0]
        points.append({
            "timestamp_utc": e["exit_timestamp_utc"],
            "strategy_normalized": 100000.0 * sum(v["strategy"] for v in active) / len(active),
            "spy_normalized": 100000.0 * sum(v["spy"] for v in active) / len(active),
        })
    return points


def get_v8_holdout_dashboard():
    now = pd.Timestamp.now(tz="UTC")
    status = {}
    if STATUS_PATH.exists():
        try:
            status = json.loads(STATUS_PATH.read_text())
        except Exception:
            status = {}
    ev = _events()
    decisions = [e for e in ev if e.get("event_type") == "DECISION"]
    entries = [e for e in ev if e.get("event_type") == "ENTRY"]
    exits = [e for e in ev if e.get("event_type") == "EXIT"]
    rel = [float(e["net_relative_return"]) for e in exits if e.get("net_relative_return") is not None]
    latest_top10 = _latest_v8_top10()
    if now < HOLDOUT_START:
        state = "WAITING_FOR_HOLDOUT"
    elif not exits:
        state = status.get("status", "ACTIVE_WAITING_FOR_COMPLETED_COHORT")
    else:
        state = "ACTIVE"
    return {
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256": EXPECTED_SHA,
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "state": state,
        "days_until_holdout": max(0, int((HOLDOUT_START - now).total_seconds() // 86400) + (1 if now < HOLDOUT_START else 0)),
        "journal_path": str(JOURNAL_PATH),
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_cohorts": len(exits),
        "mean_net_relative_return": (sum(rel) / len(rel)) if rel else None,
        "net_relative_hit_rate": (sum(x > 0 for x in rel) / len(rel)) if rel else None,
        "latest_exit": exits[-1] if exits else None,
        "curve": _curve(exits),
        "event_history": _event_history(ev),
        "latest_research_top10_timestamp_utc": latest_top10["timestamp_utc"],
        "latest_research_top10": latest_top10["rows"],
        "latest_research_top10_note": "Latest eligible frozen-model development snapshot; not forward holdout evidence.",
        "brokerage_orders": False,
        "strategy_modified": False,
    }
