"""Read-only V8 dashboard, paper-portfolio, and holdout service."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
HOLDOUT_ROOT = Path("data/model/v8/holdout")
HOLDOUT_JOURNAL = HOLDOUT_ROOT / "journal.jsonl"
HOLDOUT_STATUS = HOLDOUT_ROOT / "status.json"
PAPER_ROOT = Path("data/model/v8/paper")
PAPER_JOURNAL = PAPER_ROOT / "journal.jsonl"
PAPER_STATUS = PAPER_ROOT / "status.json"
RANKED_PANEL = Path("data/model/v8/phase4/fixed_complementarity_ranked_panel.parquet")
FREEZE_SPEC = Path("data/model/v8/phase7/frozen_candidate_spec.json")


def _events(path):
    out=[]
    if path.exists():
        for line in path.read_text().splitlines():
            line=line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except Exception: pass
    return out


def _curve(exits, start=100000.0):
    by_cohort={i:{"strategy":1.0,"spy":1.0,"active":False} for i in range(5)}
    points=[]
    for e in sorted(exits,key=lambda x:x.get("exit_timestamp_utc","")):
        c=int(e["cohort_offset"])
        by_cohort[c]["strategy"]*=1.0+float(e["net_portfolio_return"])
        by_cohort[c]["spy"]*=1.0+float(e["spy_return"])
        by_cohort[c]["active"]=True
        active=[v for v in by_cohort.values() if v["active"]]
        points.append({
            "timestamp_utc":e["exit_timestamp_utc"],
            "strategy_equity":start*sum(v["strategy"] for v in active)/len(active),
            "spy_equity":start*sum(v["spy"] for v in active)/len(active),
        })
    return points


def _paper_payload():
    ev=_events(PAPER_JOURNAL)
    decisions=[e for e in ev if e.get("event_type")=="DECISION"]
    entries=[e for e in ev if e.get("event_type")=="ENTRY"]
    exits=[e for e in ev if e.get("event_type")=="EXIT"]
    curve=_curve(exits)
    latest_decision=decisions[-1] if decisions else None
    latest_entry=entries[-1] if entries else None
    equity=curve[-1]["strategy_equity"] if curve else 100000.0
    spy=curve[-1]["spy_equity"] if curve else 100000.0
    status={}
    if PAPER_STATUS.exists():
        try: status=json.loads(PAPER_STATUS.read_text())
        except Exception: status={}
    return {
        "state":status.get("status","WAITING_FOR_FIRST_RUN"),
        "starting_equity":100000.0,
        "equity":equity,
        "total_return":equity/100000.0-1.0,
        "spy_equity":spy,
        "spy_return":spy/100000.0-1.0,
        "excess_return":equity/100000.0-spy/100000.0,
        "decisions":len(decisions),"entries":len(entries),"completed_cohorts":len(exits),
        "latest_decision":latest_decision,"latest_entry":latest_entry,
        "latest_top10":latest_decision.get("symbols",[]) if latest_decision else [],
        "curve":curve,
        "brokerage_orders":False,
        "holdout_evidence":False,
        "journal_path":str(PAPER_JOURNAL),
    }


def _ranking_payload():
    spec={}
    if FREEZE_SPEC.exists():
        try: spec=json.loads(FREEZE_SPEC.read_text())
        except Exception: spec={}
    if not RANKED_PANEL.exists():
        return {
            "available":False,"candidate_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256":EXPECTED_SHA,"rankings":[],"top10":[],"candidate_count":100,
        }
    p=pd.read_parquet(RANKED_PANEL)
    if "score_id" in p.columns:
        p=p[p["score_id"].astype(str)=="DISTANCE_ONLY"].copy()
    p["timestamp_utc"]=pd.to_datetime(p["timestamp_utc"],utc=True)
    latest=p["timestamp_utc"].max()
    d=p[p["timestamp_utc"]==latest].copy()
    score_col="score" if "score" in d.columns else "orthogonal_signal"
    d=d.sort_values([score_col,"symbol"],ascending=[False,True]).reset_index(drop=True)
    rows=[]
    n=len(d)
    for i,r in d.iterrows():
        rows.append({
            "rank":i+1,"symbol":str(r["symbol"]),"score":float(r[score_col]),
            "rank_percentile":1.0-(i/max(1,n-1)),"selected_top10":i<10,
            "sector":str(r.get("sector","")) if hasattr(r,"get") else "",
        })
    return {
        "available":True,
        "candidate_id":spec.get("candidate_id","V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS"),
        "frozen_sha256":EXPECTED_SHA,
        "decision_date_utc":latest.isoformat(),
        "candidate_count":n,
        "feature":"distance_from_low_20d",
        "neutralization_controls":["volatility_20d","beta_60"],
        "top_n":10,"holding_sessions":5,"cost_bps":10,
        "rankings":rows,"top10":rows[:10],
    }


def _holdout_payload():
    now=pd.Timestamp.now(tz="UTC")
    status={}
    if HOLDOUT_STATUS.exists():
        try: status=json.loads(HOLDOUT_STATUS.read_text())
        except Exception: status={}
    ev=_events(HOLDOUT_JOURNAL)
    decisions=[e for e in ev if e.get("event_type")=="DECISION"]
    entries=[e for e in ev if e.get("event_type")=="ENTRY"]
    exits=[e for e in ev if e.get("event_type")=="EXIT"]
    rel=[float(e["net_relative_return"]) for e in exits if e.get("net_relative_return") is not None]
    state="WAITING_FOR_HOLDOUT" if now<HOLDOUT_START else (status.get("status","ACTIVE_WAITING_FOR_COMPLETED_COHORT") if not exits else "ACTIVE")
    return {
        "candidate_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256":EXPECTED_SHA,"holdout_start_utc":HOLDOUT_START.isoformat(),"state":state,
        "days_until_holdout":max(0,int((HOLDOUT_START-now).total_seconds()//86400)+(1 if now<HOLDOUT_START else 0)),
        "decisions":len(decisions),"entries":len(entries),"completed_cohorts":len(exits),
        "mean_net_relative_return":sum(rel)/len(rel) if rel else None,
        "net_relative_hit_rate":sum(x>0 for x in rel)/len(rel) if rel else None,
        "latest_exit":exits[-1] if exits else None,
        "curve":[{"timestamp_utc":x["timestamp_utc"],"strategy_normalized":x["strategy_equity"],"spy_normalized":x["spy_equity"]} for x in _curve(exits)],
        "brokerage_orders":False,"strategy_modified":False,
    }


def get_v8_holdout_dashboard():
    """Single lightweight endpoint used by all V8 page widgets."""
    holdout=_holdout_payload()
    return {**holdout,"dashboard":_ranking_payload(),"paper":_paper_payload()}
