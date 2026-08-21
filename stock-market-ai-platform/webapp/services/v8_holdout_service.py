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
READINESS_PATH = Path("data/model/v8/readiness/status.json")
V8_RANKED_PATH = Path("data/model/v8/phase4/fixed_complementarity_ranked_panel.parquet")


def _read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


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
    if event_type == "EXIT": return event.get("exit_timestamp_utc")
    if event_type == "ENTRY": return event.get("entry_timestamp_utc")
    return event.get("decision_timestamp_utc")


def _event_history(events):
    rows = []
    for event in events:
        event_type = event.get("event_type")
        if event_type not in {"DECISION", "ENTRY", "EXIT"}: continue
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


def _latest_v8_rankings():
    if not V8_RANKED_PATH.exists(): return {"timestamp_utc": None, "rows": []}
    try:
        panel = pd.read_parquet(V8_RANKED_PATH, columns=["timestamp_utc", "symbol", "score", "score_id", "rank_descending"])
        panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True, errors="coerce")
        panel = panel[(panel["score_id"] == "DISTANCE_ONLY") & panel["timestamp_utc"].notna() & (panel["timestamp_utc"] < HOLDOUT_START)].copy()
        if panel.empty: return {"timestamp_utc": None, "rows": []}
        latest_ts = panel["timestamp_utc"].max()
        latest = panel[panel["timestamp_utc"] == latest_ts].sort_values(["rank_descending", "symbol"], ascending=[True, True])
        rows = []
        for _, row in latest.iterrows():
            rank = int(row["rank_descending"])
            rows.append({"rank": rank, "symbol": str(row["symbol"]), "score": float(row["score"]), "selected_top10": rank <= 10, "target_weight": 0.10 if rank <= 10 else 0.0})
        return {"timestamp_utc": latest_ts.isoformat(), "rows": rows}
    except Exception:
        return {"timestamp_utc": None, "rows": []}


def _curve(exits):
    if not exits: return []
    by_cohort = {i: {"strategy": 1.0, "spy": 1.0} for i in range(5)}
    points = []
    for e in sorted(exits, key=lambda x: x.get("exit_timestamp_utc", "")):
        c = int(e["cohort_offset"])
        by_cohort[c]["strategy"] *= 1.0 + float(e["net_portfolio_return"])
        by_cohort[c]["spy"] *= 1.0 + float(e["spy_return"])
        active = [v for v in by_cohort.values() if v["strategy"] != 1.0 or v["spy"] != 1.0]
        points.append({"timestamp_utc": e["exit_timestamp_utc"], "strategy_normalized": 100000.0 * sum(v["strategy"] for v in active) / len(active), "spy_normalized": 100000.0 * sum(v["spy"] for v in active) / len(active)})
    return points


def get_v8_holdout_dashboard():
    now = pd.Timestamp.now(tz="UTC")
    status = _read_json(STATUS_PATH)
    readiness = _read_json(READINESS_PATH)
    ev = _events()
    decisions = [e for e in ev if e.get("event_type") == "DECISION"]
    entries = [e for e in ev if e.get("event_type") == "ENTRY"]
    exits = [e for e in ev if e.get("event_type") == "EXIT"]
    rel = [float(e["net_relative_return"]) for e in exits if e.get("net_relative_return") is not None]
    latest_rankings = _latest_v8_rankings()
    checks = readiness.get("checks") or {}
    rehearsal_details = checks.get("ranking_top10_details") or []
    rehearsal_symbols = checks.get("ranking_top10") or []
    if rehearsal_details:
        latest_top10 = rehearsal_details[:10]
    elif rehearsal_symbols:
        score_by_symbol = {row["symbol"]: row.get("score") for row in latest_rankings["rows"]}
        latest_top10 = [
            {
                "rank": i + 1,
                "symbol": symbol,
                "score": score_by_symbol.get(symbol),
                "selected_top10": True,
                "target_weight": 0.10,
            }
            for i, symbol in enumerate(rehearsal_symbols[:10])
        ]
    else:
        latest_top10 = latest_rankings["rows"][:10]

    if now < HOLDOUT_START: state = "WAITING_FOR_HOLDOUT"
    elif not exits: state = status.get("status", "ACTIVE_WAITING_FOR_COMPLETED_COHORT")
    else: state = "ACTIVE"

    return {
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256": EXPECTED_SHA,
        "frozen_sha_verified": readiness.get("frozen_sha256") == EXPECTED_SHA and bool(checks.get("frozen_contract_verified")),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "state": state,
        "days_until_holdout": max(0, int((HOLDOUT_START - now).total_seconds() // 86400) + (1 if now < HOLDOUT_START else 0)),
        "readiness_status": readiness.get("status", "UNKNOWN"),
        "readiness_updated_at_utc": readiness.get("updated_at_utc"),
        "readiness_failures": readiness.get("failures", []),
        "readiness_warnings": readiness.get("warnings", []),
        "feature_common_latest_utc": checks.get("feature_common_latest_utc"),
        "gold_common_latest_utc": checks.get("gold_common_latest_utc"),
        "ranking_timestamp_utc": checks.get("ranking_timestamp_utc"),
        "ranking_eligible_count": checks.get("ranking_eligible_count"),
        "journal_path": str(JOURNAL_PATH),
        "journal_event_count": len(ev),
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_cohorts": len(exits),
        "mean_net_relative_return": (sum(rel) / len(rel)) if rel else None,
        "net_relative_hit_rate": (sum(x > 0 for x in rel) / len(rel)) if rel else None,
        "latest_exit": exits[-1] if exits else None,
        "curve": _curve(exits),
        "event_history": _event_history(ev),
        "latest_research_top10_timestamp_utc": checks.get("ranking_timestamp_utc") or latest_rankings["timestamp_utc"],
        "latest_research_top10": latest_top10,
        "latest_research_top10_note": "Latest frozen-model readiness rehearsal; not forward holdout evidence." if (rehearsal_details or rehearsal_symbols) else "Latest eligible frozen-model development snapshot; not forward holdout evidence.",
        "latest_research_rankings_timestamp_utc": latest_rankings["timestamp_utc"],
        "latest_research_rankings": latest_rankings["rows"],
        "brokerage_orders": False,
        "strategy_modified": False,
    }
