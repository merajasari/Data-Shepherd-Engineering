"""Operational V8 paper portfolio runner.

Tracks the exact frozen V8 candidate in a separate append-only paper journal.
This journal is operational diagnostics only and is never used as Sep-1+ holdout
evidence. No brokerage orders are placed.

The runner also publishes a tiny latest-ranking JSON snapshot for the web
presentation layer. The Flask dashboard reads that snapshot instead of scanning
the large Phase-4 parquet on every page request.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd

from ml.v8.holdout_runner import (
    EXPECTED_SHA,
    HOLD_SESSIONS,
    TOP_N,
    COST_BPS,
    _verify_freeze,
    _load_market,
    _rank_for_date,
    _transition_notional,
)

ROOT = Path("data/model/v8/paper")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
DASHBOARD_RANKINGS_PATH = Path("data/live/v8_latest_rankings.json")


def _read_events():
    out=[]
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            line=line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except Exception: pass
    return out


def _key(e):
    return (e.get("event_type"), e.get("decision_timestamp_utc"), int(e.get("cohort_offset", -1)))


def _append(event, existing):
    if _key(event) in existing:
        return False
    ROOT.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True)+"\n")
    existing.add(_key(event))
    return True


def _write_status(**kwargs):
    ROOT.mkdir(parents=True, exist_ok=True)
    payload={
        "candidate_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256":EXPECTED_SHA,
        "brokerage_orders":False,
        "holdout_evidence":False,
        "updated_at_utc":datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")


def _write_dashboard_snapshot(decision_ts, ranking):
    """Write the current frozen-V8 ranking as a small web-friendly JSON file."""
    n=len(ranking)
    rows=[]
    for i,r in enumerate(ranking.itertuples(), start=1):
        rows.append({
            "rank":i,
            "symbol":str(r.symbol),
            "score":float(r.orthogonal_signal),
            "rank_percentile":1.0-((i-1)/max(1,n-1)),
            "selected_top10":i<=TOP_N,
        })
    payload={
        "available":True,
        "research_version":"v8",
        "candidate_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256":EXPECTED_SHA,
        "decision_date_utc":pd.Timestamp(decision_ts).isoformat(),
        "candidate_count":n,
        "feature":"distance_from_low_20d",
        "neutralization_controls":["volatility_20d","beta_60"],
        "top_n":TOP_N,
        "holding_sessions":HOLD_SESSIONS,
        "cost_bps":COST_BPS,
        "rankings":rows,
        "top10":rows[:TOP_N],
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
    }
    DASHBOARD_RANKINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp=DASHBOARD_RANKINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",",":"))+"\n", encoding="utf-8")
    tmp.replace(DASHBOARD_RANKINGS_PATH)


def main():
    _verify_freeze()
    symbols, frames, dates, date_to_idx = _load_market()
    if len(dates) < HOLD_SESSIONS + 2:
        raise RuntimeError("Insufficient V8 market history")

    events=_read_events()
    existing={_key(e) for e in events}
    decisions=[e for e in events if e.get("event_type")=="DECISION"]

    # Start cleanly from the latest completed decision date; never backdate paper history.
    if decisions:
        last_decision=max(pd.Timestamp(e["decision_timestamp_utc"]) for e in decisions)
        decision_dates=[d for d in dates if d > last_decision]
    else:
        decision_dates=[dates[-1]]

    appended=0
    snapshot_written=False
    for decision_ts in decision_dates:
        i=date_to_idx[decision_ts]
        cohort=int(i % HOLD_SESSIONS)
        ranking=_rank_for_date(decision_ts, symbols, frames)
        _write_dashboard_snapshot(decision_ts, ranking)
        snapshot_written=True
        picks=ranking.head(TOP_N)["symbol"].astype(str).tolist()
        entry_ts=dates[i+1] if i+1 < len(dates) else None
        planned_exit=dates[i+1+HOLD_SESSIONS] if i+1+HOLD_SESSIONS < len(dates) else None
        appended += int(_append({
            "event_type":"DECISION",
            "journal_type":"V8_OPERATIONAL_PAPER",
            "candidate_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256":EXPECTED_SHA,
            "decision_timestamp_utc":decision_ts.isoformat(),
            "cohort_offset":cohort,
            "symbols":picks,
            "top10_scores":{r.symbol:float(r.orthogonal_signal) for r in ranking.head(TOP_N).itertuples()},
            "entry_timestamp_utc":entry_ts.isoformat() if entry_ts is not None else None,
            "planned_exit_timestamp_utc":planned_exit.isoformat() if planned_exit is not None else None,
            "brokerage_orders":False,
            "holdout_evidence":False,
            "created_at_utc":datetime.now(timezone.utc).isoformat(),
        }, existing))

    # Migration/repair path: guarantee the web snapshot exists even if today's
    # decision was already journaled before this optimization was installed.
    if not snapshot_written and not DASHBOARD_RANKINGS_PATH.exists():
        decision_ts=dates[-1]
        ranking=_rank_for_date(decision_ts, symbols, frames)
        _write_dashboard_snapshot(decision_ts, ranking)

    events=_read_events()
    decisions=[e for e in events if e.get("event_type")=="DECISION"]
    for dec in decisions:
        if not dec.get("entry_timestamp_utc"): continue
        entry_ts=pd.Timestamp(dec["entry_timestamp_utc"])
        if entry_ts not in date_to_idx: continue
        cohort=int(dec["cohort_offset"])
        if ("ENTRY",dec["decision_timestamp_utc"],cohort) in existing: continue
        prices={}
        valid=True
        for sym in dec["symbols"]:
            if entry_ts not in frames[sym].index:
                valid=False; break
            px=float(frames[sym].loc[entry_ts,"open"])
            if not pd.notna(px) or px<=0:
                valid=False; break
            prices[sym]=px
        if not valid or entry_ts not in frames["SPY"].index: continue
        prior=[e for e in _read_events() if e.get("event_type")=="ENTRY" and int(e.get("cohort_offset",-1))==cohort]
        prior.sort(key=lambda e:e["entry_timestamp_utc"])
        previous=prior[-1]["symbols"] if prior else None
        traded=_transition_notional(previous, dec["symbols"])
        appended += int(_append({
            "event_type":"ENTRY","journal_type":"V8_OPERATIONAL_PAPER",
            "candidate_id":dec["candidate_id"],"frozen_sha256":EXPECTED_SHA,
            "decision_timestamp_utc":dec["decision_timestamp_utc"],"cohort_offset":cohort,
            "symbols":dec["symbols"],"entry_timestamp_utc":entry_ts.isoformat(),
            "entry_prices":prices,"spy_entry_open":float(frames["SPY"].loc[entry_ts,"open"]),
            "transition_notional":float(traded),"modeled_cost_rate":float(traded*COST_BPS/10000.0),
            "brokerage_orders":False,"holdout_evidence":False,
            "created_at_utc":datetime.now(timezone.utc).isoformat(),
        }, existing))

    entries=[e for e in _read_events() if e.get("event_type")=="ENTRY"]
    for ent in entries:
        cohort=int(ent["cohort_offset"])
        if ("EXIT",ent["decision_timestamp_utc"],cohort) in existing: continue
        entry_ts=pd.Timestamp(ent["entry_timestamp_utc"])
        i=date_to_idx.get(entry_ts)
        if i is None or i+HOLD_SESSIONS >= len(dates): continue
        exit_ts=dates[i+HOLD_SESSIONS]
        rets=[]; exit_prices={}; valid=True
        for sym in ent["symbols"]:
            if exit_ts not in frames[sym].index:
                valid=False; break
            p0=float(ent["entry_prices"][sym]); p1=float(frames[sym].loc[exit_ts,"open"])
            if p0<=0 or not pd.notna(p1): valid=False; break
            exit_prices[sym]=p1; rets.append(p1/p0-1.0)
        if not valid or exit_ts not in frames["SPY"].index: continue
        gross=float(sum(rets)/len(rets)); cost=float(ent["modeled_cost_rate"])
        net=float((1.0+gross)*(1.0-cost)-1.0)
        spy_ret=float(frames["SPY"].loc[exit_ts,"open"]/float(ent["spy_entry_open"])-1.0)
        appended += int(_append({
            "event_type":"EXIT","journal_type":"V8_OPERATIONAL_PAPER",
            "candidate_id":ent["candidate_id"],"frozen_sha256":EXPECTED_SHA,
            "decision_timestamp_utc":ent["decision_timestamp_utc"],"cohort_offset":cohort,
            "symbols":ent["symbols"],"entry_timestamp_utc":ent["entry_timestamp_utc"],
            "exit_timestamp_utc":exit_ts.isoformat(),"exit_prices":exit_prices,
            "gross_portfolio_return":gross,"modeled_cost_rate":cost,
            "net_portfolio_return":net,"spy_return":spy_ret,"net_relative_return":net-spy_ret,
            "brokerage_orders":False,"holdout_evidence":False,
            "created_at_utc":datetime.now(timezone.utc).isoformat(),
        }, existing))

    final=_read_events()
    _write_status(
        status="ACTIVE",
        decisions=sum(e.get("event_type")=="DECISION" for e in final),
        entries=sum(e.get("event_type")=="ENTRY" for e in final),
        exits=sum(e.get("event_type")=="EXIT" for e in final),
        appended_this_run=appended,
        dashboard_snapshot=str(DASHBOARD_RANKINGS_PATH),
    )
    print(f"V8 operational paper monitor active. Appended {appended} event(s). No brokerage orders.")
    print(f"Dashboard ranking snapshot: {DASHBOARD_RANKINGS_PATH}")


if __name__ == "__main__":
    main()
