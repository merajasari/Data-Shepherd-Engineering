"""Read-only crypto dashboard service.

Presents frozen Crypto V1 research simulation plus the frozen Crypto 15m V2
shadow/forward service state and V2 exploratory research evidence. Presentation
only: never fits models or places orders.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from ml.crypto_v1.config import CRYPTO_UNIVERSE, MODEL_ROOT

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
V2_PHASE4_ROOT = Path("data/model/crypto_15m_v2/phase4")
V2_PHASE5_ROOT = Path("data/model/crypto_15m_v2/phase5")
V2_STATUS_PATH = V2_PHASE5_ROOT / "forward_service_status.json"
V2_JOURNAL_PATH = V2_PHASE5_ROOT / "forward_journal.csv"
V2_POLICY_SUMMARY_PATH = V2_PHASE4_ROOT / "policy_summary.csv"
V2_PHASE4_MANIFEST_PATH = V2_PHASE4_ROOT / "manifest.json"
RECONCILE_STATUS_PATH = Path("data/live/crypto_rt/reconcile_status.json")
PRIMARY_HORIZON_DAYS=7; PRIMARY_MODEL_ID="momentum"; PRIMARY_VARIANT="top_5_equal_weight"; PRIMARY_TOP_N=5; PRIMARY_COST_BPS=25.0; DISPLAY_STARTING_EQUITY=100000.0

def _read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()
def _read_json(path):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception: return {}
def _read_predictions():
    path=PHASE3_ROOT/"predictions.parquet"
    if not path.exists(): return pd.DataFrame()
    f=pd.read_parquet(path); f["timestamp_utc"]=pd.to_datetime(f["timestamp_utc"],utc=True); return f
def _primary_daily():
    d=_read_csv(PHASE4_ROOT/"portfolio_daily.csv")
    if d.empty:return d
    d["timestamp_utc"]=pd.to_datetime(d["timestamp_utc"],utc=True)
    m=d["split"].eq("holdout")&d["model_id"].eq(PRIMARY_MODEL_ID)&d["variant"].eq(PRIMARY_VARIANT)&pd.to_numeric(d["top_n"],errors="coerce").eq(PRIMARY_TOP_N)&pd.to_numeric(d["cost_bps_round_trip"],errors="coerce").eq(PRIMARY_COST_BPS)
    return d.loc[m].sort_values("timestamp_utc").reset_index(drop=True)
def _btc_daily():
    d=_read_csv(PHASE4_ROOT/"portfolio_daily.csv")
    if d.empty:return d
    d["timestamp_utc"]=pd.to_datetime(d["timestamp_utc"],utc=True)
    m=d["split"].eq("holdout")&d["model_id"].eq(PRIMARY_MODEL_ID)&d["variant"].eq("btc_benchmark")&pd.to_numeric(d["cost_bps_round_trip"],errors="coerce").eq(PRIMARY_COST_BPS)
    return d.loc[m].sort_values("timestamp_utc").reset_index(drop=True)
def _latest_rankings():
    p=_read_predictions()
    if p.empty:return None,[]
    f=p[(p["split"]=="holdout")&(p["model_id"]==PRIMARY_MODEL_ID)&(p["horizon_days"]==PRIMARY_HORIZON_DAYS)].copy()
    if f.empty:return None,[]
    latest=f["timestamp_utc"].max(); day=f[f["timestamp_utc"]==latest].sort_values(["predicted_score","product_id"],ascending=[False,True]); rows=[]; count=len(day)
    for rank,row in enumerate(day.itertuples(index=False),1):
        score=float(row.predicted_score); rows.append({"rank":rank,"product_id":row.product_id,"score":score,"score_pct":score*100,"rank_percentile":(1-(rank-1)/max(1,count-1))*100,"top5":rank<=PRIMARY_TOP_N})
    return latest.isoformat(),rows
def _equity_history(primary,btc):
    if primary.empty:return []
    bm=dict(zip(btc["timestamp_utc"],pd.to_numeric(btc["equity"],errors="coerce"))) if not btc.empty else {}
    return [{"timestamp":r.timestamp_utc.isoformat(),"equity":DISPLAY_STARTING_EQUITY*float(r.equity),"btc_equity":DISPLAY_STARTING_EQUITY*float(bm[r.timestamp_utc]) if r.timestamp_utc in bm and pd.notna(bm[r.timestamp_utc]) else None,"is_rebalance":bool(r.is_rebalance)} for r in primary.itertuples(index=False)]
def _v2_live():
    s=_read_json(V2_STATUS_PATH); r=_read_json(RECONCILE_STATUS_PATH)
    if not s:return {"available":False,"message":"Frozen Crypto 15m V2 forward service status is not available yet."}
    probs=s.get("probabilities",{}); journal=_read_csv(V2_JOURNAL_PATH); realized=journal[journal.get("status",pd.Series(dtype=str)).eq("REALIZED")] if not journal.empty and "status" in journal else pd.DataFrame()
    equity=float(pd.to_numeric(realized.get("equity",pd.Series(dtype=float)),errors="coerce").dropna().iloc[-1]) if not realized.empty and pd.to_numeric(realized.get("equity",pd.Series(dtype=float)),errors="coerce").notna().any() else 1.0
    return {"available":True,"mode":s.get("mode","UNKNOWN"),"action":s.get("action"),"decision_timestamp_utc":s.get("decision_timestamp_utc"),"generated_at_utc":s.get("generated_at_utc"),"raw_predicted_label":s.get("raw_predicted_label"),"current_executed_label":s.get("current_executed_label"),"prob_btc":float(probs.get("BTC",0)),"prob_alt":float(probs.get("ALT",0)),"prob_cash":float(probs.get("CASH",0)),"alt_asset_count":int(s.get("alt_asset_count",0)),"missing_alts":s.get("missing_decision_candle_alts",[]),"ineligible_alts":s.get("feature_ineligible_alts",[]),"brokerage_orders":bool(s.get("brokerage_orders",False)),"reconcile_boundary":r.get("latest_expected_bar_start_utc"),"reconcile_product_count":r.get("product_count"),"journal_rows":max(0,len(journal)),"realized_rows":len(realized),"paper_equity_multiple":equity}
def _v2_research_evidence():
    summary=_read_csv(V2_POLICY_SUMMARY_PATH); manifest=_read_json(V2_PHASE4_MANIFEST_PATH)
    if summary.empty or "policy" not in summary:return {"available":False}
    row=summary[summary["policy"]=="confirm_2"]
    if row.empty:return {"available":False}
    r=row.iloc[0]
    return {"available":True,"policy":"confirm_2","confirmation_hours":2,"ending_equity_0bps":float(r["ending_equity_0bps"]),"ending_equity_5bps":float(r["ending_equity_5bps"]),"executed_switches":int(r["executed_switches"]),"switch_reduction_fraction":float(r["switch_reduction_fraction"]),"max_drawdown_0bps":float(r["max_drawdown_0bps"]),"max_drawdown_5bps":float(r["max_drawdown_5bps"]),"raw_switches":6084,"research_status":manifest.get("research_status","EXPLORATORY ONLY. Phase 3 OOS results were already inspected before policy selection."),"future_validation_rule":manifest.get("future_validation_rule"),"cost_limitation":manifest.get("cost_limitation"),"holdout_start":"2026-09-01T00:00:00+00:00"}
def get_crypto_dashboard_payload():
    primary=_primary_daily(); btc=_btc_daily(); ranking_timestamp,rankings=_latest_rankings(); live=_v2_live(); evidence=_v2_research_evidence()
    if primary.empty:return {"available":False,"message":"Crypto V1 Phase 4 artifacts are not available on this machine.","universe":list(CRYPTO_UNIVERSE),"rankings":rankings,"ranking_timestamp":ranking_timestamp,"live_v2":live,"v2_research":evidence}
    current_multiple=float(primary["equity"].iloc[-1]); current_equity=DISPLAY_STARTING_EQUITY*current_multiple; cumulative_return=current_multiple-1; peak=pd.to_numeric(primary["equity"],errors="coerce").cummax(); drawdown=pd.to_numeric(primary["equity"],errors="coerce")/peak-1; btc_multiple=float(btc["equity"].iloc[-1]) if not btc.empty else None; btc_return=btc_multiple-1 if btc_multiple is not None else None; excess=cumulative_return-btc_return if btc_return is not None else None; lr=primary[primary["is_rebalance"].astype(str).str.lower().isin(["true","1"])]
    return {"available":True,"mode":"frozen_research_simulation","starting_equity":DISPLAY_STARTING_EQUITY,"current_equity":current_equity,"net_change":current_equity-DISPLAY_STARTING_EQUITY,"cumulative_return":cumulative_return,"btc_return":btc_return,"excess_return_vs_btc":excess,"max_drawdown":float(drawdown.min()) if len(drawdown) else 0,"observation_count":max(0,len(primary)-1),"rebalance_count":int(primary["is_rebalance"].astype(str).str.lower().isin(["true","1"]).sum()),"latest_rebalance_timestamp":lr["timestamp_utc"].max().isoformat() if not lr.empty else None,"ranking_timestamp":ranking_timestamp,"top_five":rankings[:5],"rankings":rankings,"equity_history":_equity_history(primary,btc),"universe":list(CRYPTO_UNIVERSE),"live_v2":live,"v2_research":evidence,"contract":{"research_version":"crypto_v1","model_id":PRIMARY_MODEL_ID,"horizon_days":PRIMARY_HORIZON_DAYS,"variant":PRIMARY_VARIANT,"top_n":PRIMARY_TOP_N,"round_trip_cost_bps":PRIMARY_COST_BPS,"benchmark":"BTC-USD","leverage":False,"real_orders":False}}
