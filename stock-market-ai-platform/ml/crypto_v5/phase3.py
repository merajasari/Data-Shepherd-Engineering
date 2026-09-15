"""Crypto V5 Phase 3: preregistered cost-aware portfolio tournament."""
from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from ml.crypto_v5.config import (ALLOCATION_TEMPLATES,ALL_HORIZONS_DAYS,
 FUTURE_HOLDOUT_START_UTC,MAX_TURNOVER_PER_REBALANCE,MINIMUM_HOLD_DAYS,
 PHASE1_ROOT,PRIMARY_COST_BPS,ROUND_TRIP_COST_BPS,SWITCH_CONFIDENCE_MARGIN,
 RESEARCH_VERSION)

PHASE2_ROOT=PHASE1_ROOT.parent/"phase2";OUTPUT_ROOT=PHASE1_ROOT.parent/"phase3"
TOP_COUNTS=(3,5);MODELS=("ridge","hist_gradient_boosting")

def decision_dates(values,horizon):
    dates=pd.DatetimeIndex(pd.to_datetime(pd.Series(values).dropna().unique(),utc=True)).sort_values()
    if dates.empty:return dates
    out=[];due=dates[0]
    while due<=dates[-1]:
        later=dates[dates>=due]
        if not len(later):break
        out.append(later[0]);due=later[0]+pd.Timedelta(horizon,unit="D")
    return pd.DatetimeIndex(out)

def _regime(row):
    scores={s:float(row[f"predicted_{s}_return"]) for s in ("btc","alt","cash")}
    ordered=sorted(scores,key=scores.get,reverse=True);best,second=ordered[:2]
    confidence=(scores[best]-scores[second])/max(abs(scores[best]),.01)
    return ({"alt":"RISK_ON","btc":"DEFENSIVE","cash":"CASH"}[best],confidence)

def desired_weights(regime,rank_day,top_n):
    template=ALLOCATION_TEMPLATES[regime];result={"BTC-USD":float(template["BTC"]),"CASH":float(template["CASH"])}
    chosen=rank_day.nlargest(top_n,"predicted_score")["product_id"].tolist()
    if chosen:
        for asset in chosen:result[asset]=float(template["ALT"])/len(chosen)
    else:result["CASH"]+=float(template["ALT"])
    return result

def turnover(current,target):
    keys=set(current)|set(target);return .5*sum(abs(target.get(k,0)-current.get(k,0)) for k in keys)

def capped_target(current,target,cap=MAX_TURNOVER_PER_REBALANCE):
    raw=turnover(current,target)
    if raw<=cap or raw==0:return target,raw
    scale=cap/raw;keys=set(current)|set(target)
    adjusted={k:current.get(k,0)+scale*(target.get(k,0)-current.get(k,0)) for k in keys}
    return {k:v for k,v in adjusted.items() if abs(v)>1e-12},cap

def simulate(allocation,ranking,model,horizon,top_n,cost_bps):
    alloc=allocation[(allocation.model_id==model)&(allocation.horizon_days==horizon)].copy()
    rank=ranking[(ranking.model_id==model)&(ranking.horizon_days==horizon)].copy()
    dates=decision_dates(alloc.timestamp_utc,horizon);alloc=alloc.set_index("timestamp_utc")
    rank_map={t:g for t,g in rank.groupby("timestamp_utc")};weights={"CASH":1.0};equity=1.0
    regime="CASH";last_switch=None;rows=[]
    for t in dates:
        if t not in rank_map or t not in alloc.index:continue
        row=alloc.loc[t]
        if isinstance(row,pd.DataFrame):row=row.iloc[0]
        available=set(rank_map[t]["product_id"])|{"BTC-USD","CASH"};forced=sum(v for k,v in weights.items() if k not in available)
        weights={k:v for k,v in weights.items() if k in available};weights["CASH"]=weights.get("CASH",0)+forced
        proposed,confidence=_regime(row);held_days=(t-last_switch).days if last_switch is not None else 10**9
        can_switch=(proposed==regime or (held_days>=MINIMUM_HOLD_DAYS and confidence>=SWITCH_CONFIDENCE_MARGIN))
        next_regime=proposed if can_switch else regime
        target=desired_weights(next_regime,rank_map[t],top_n);target,trade_turnover=capped_target(weights,target)
        cost=equity*trade_turnover*float(cost_bps)/10000;after=max(0,equity-cost)
        actual={"BTC-USD":float(row.actual_btc_return),"CASH":0.0}
        actual.update(rank_map[t].set_index("product_id")["actual_forward_return"].astype(float).to_dict())
        period_return=sum(w*actual.get(asset,0.0) for asset,w in target.items())
        ending=max(0,after*(1+period_return))
        if next_regime!=regime:last_switch=t
        rows.append({"timestamp_utc":t,"model_id":model,"horizon_days":horizon,"top_n":top_n,
          "cost_bps_round_trip":float(cost_bps),"proposed_regime":proposed,"selected_regime":next_regime,
          "confidence":confidence,"forced_cash_weight":forced,"turnover":trade_turnover,"transaction_cost":cost,
          "gross_return":period_return,"net_return":ending/equity-1 if equity else -1,"ending_equity":ending})
        equity=ending;weights=target;regime=next_regime
    return pd.DataFrame(rows)

def summarize(frame):
    net=frame.net_return.astype(float);ending=float(frame.ending_equity.iloc[-1]);h=int(frame.horizon_days.iloc[0]);n=len(frame)
    years=n*h/365.25;ann=ending**(1/years)-1 if years and ending>0 else np.nan
    vol=net.std(ddof=1)*np.sqrt(365.25/h);down=net[net<0];sortino=(net.mean()/down.std(ddof=1)*np.sqrt(365.25/h)) if len(down)>1 and down.std()>0 else np.nan
    path=pd.concat([pd.Series([1.0]),frame.ending_equity],ignore_index=True);dd=path/path.cummax()-1
    first=frame.iloc[0]
    return {"model_id":first.model_id,"horizon_days":h,"top_n":int(first.top_n),"cost_bps_round_trip":float(first.cost_bps_round_trip),
      "observations":n,"starting_equity":1.0,"ending_equity":ending,"cumulative_return":ending-1,"annualized_return":ann,
      "annualized_volatility":vol,"sharpe":net.mean()/net.std(ddof=1)*np.sqrt(365.25/h) if net.std()>0 else np.nan,
      "sortino":sortino,"maximum_drawdown":float(dd.min()),"positive_period_rate":float((net>0).mean()),
      "total_turnover":float(frame.turnover.sum()),"total_transaction_cost":float(frame.transaction_cost.sum()),
      "cash_fraction":float((frame.selected_regime=="CASH").mean())}

def run_phase3(phase2_root=PHASE2_ROOT,output_root=OUTPUT_ROOT):
    phase2_root=Path(phase2_root);output_root=Path(output_root)
    allocation=pd.read_parquet(phase2_root/"allocation_predictions.parquet");ranking=pd.read_parquet(phase2_root/"ranking_predictions.parquet")
    for f in (allocation,ranking):f["timestamp_utc"]=pd.to_datetime(f.timestamp_utc,utc=True)
    if (allocation.timestamp_utc>=FUTURE_HOLDOUT_START_UTC).any() or (ranking.timestamp_utc>=FUTURE_HOLDOUT_START_UTC).any():raise RuntimeError("V5 holdout leakage")
    frames=[];metrics=[]
    for model in MODELS:
      for horizon in ALL_HORIZONS_DAYS:
       for top_n in TOP_COUNTS:
        for cost in ROUND_TRIP_COST_BPS:
         frame=simulate(allocation,ranking,model,horizon,top_n,cost)
         if frame.empty:raise ValueError(f"Empty V5 portfolio {model}/{horizon}/{top_n}/{cost}")
         frames.append(frame);metrics.append(summarize(frame))
    daily=pd.concat(frames,ignore_index=True);summary=pd.DataFrame(metrics).sort_values(["horizon_days","model_id","top_n","cost_bps_round_trip"])
    output_root.mkdir(parents=True,exist_ok=True);daily.to_parquet(output_root/"portfolio_periods.parquet",index=False);summary.to_csv(output_root/"portfolio_metrics.csv",index=False)
    primary=summary[summary.cost_bps_round_trip==PRIMARY_COST_BPS].copy()
    frontier=primary[(primary.maximum_drawdown>=-.50)&(primary.annualized_return>0)].sort_values(["sharpe","annualized_return"],ascending=False)
    frontier.to_csv(output_root/"development_frontier.csv",index=False)
    manifest={"research_version":RESEARCH_VERSION,"phase":3,"stage":"cost_aware_portfolio_tournament","generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "candidate_count":int(len(summary)),"models":list(MODELS),"horizons_days":list(ALL_HORIZONS_DAYS),"top_counts":list(TOP_COUNTS),
      "cost_bps_round_trip":list(ROUND_TRIP_COST_BPS),"selection_status":"NOT_SELECTED","development_frontier_rows":int(len(frontier)),
      "policy":"development comparison only; no holdout evaluation, paper trading, brokerage orders, or V4 mutation",
      "safety":{"v4_modified":False,"paper_state_modified":False,"holdout_scored":False,"brokerage_orders":False},
      "outputs":{"portfolio_periods":str(output_root/"portfolio_periods.parquet"),"portfolio_metrics":str(output_root/"portfolio_metrics.csv"),"development_frontier":str(output_root/"development_frontier.csv")}}
    (output_root/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8");return manifest

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--phase2-root",type=Path,default=PHASE2_ROOT);ap.add_argument("--output-root",type=Path,default=OUTPUT_ROOT);a=ap.parse_args(argv);print(json.dumps(run_phase3(a.phase2_root,a.output_root),indent=2))
if __name__=="__main__":main()
