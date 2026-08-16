"""Crypto 15m V2 Phase 2: hourly BTC/ALT/CASH walk-forward validation.

Research only: no brokerage integration, order placement, leverage, or live trading.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATASET=Path('data/model/crypto_15m_v2/phase1/market_allocation_1h.parquet')
MANIFEST=Path('data/model/crypto_15m_v2/phase1/manifest.json')
OUT=Path('data/model/crypto_15m_v2/phase2')
HOLDOUT=pd.Timestamp('2026-09-01T00:00:00Z')
LABELS=('BTC','ALT','CASH')
PURGE=pd.Timedelta(hours=4)
VAL_DAYS=90
MAX_FOLDS=12

def models():
    return {
      'multinomial_logistic':Pipeline([('imputer',SimpleImputer(strategy='median')),('scaler',StandardScaler()),('model',LogisticRegression(C=1.0,max_iter=3000,solver='lbfgs',random_state=1729))]),
      'hist_gradient_boosting':Pipeline([('imputer',SimpleImputer(strategy='median')),('model',HistGradientBoostingClassifier(learning_rate=.05,max_iter=150,max_leaf_nodes=15,l2_regularization=1.0,random_state=1729))])
    }

def choose_return(df,pred):
    m={'BTC':df.btc_forward_return_4h.to_numpy(float),'ALT':df.alt_forward_return_4h.to_numpy(float),'CASH':df.cash_forward_return_4h.to_numpy(float)}
    return np.array([m[x][i] for i,x in enumerate(pred)],float)

def run():
    meta=json.loads(MANIFEST.read_text())
    df=pd.read_parquet(DATASET)
    df['timestamp_utc']=pd.to_datetime(df.timestamp_utc,utc=True)
    df=df[df.timestamp_utc<HOLDOUT].sort_values('timestamp_utc').reset_index(drop=True)
    feats=list(meta['feature_columns'])
    first=df.timestamp_utc.min().floor('h')
    last=df.timestamp_utc.max().floor('h')
    starts=list(pd.date_range(first+pd.Timedelta(days=365),last,freq=f'{VAL_DAYS}D',tz='UTC'))[-MAX_FOLDS:]
    metric_rows=[]; preds=[]
    for n,vs in enumerate(starts,1):
        ve=min(vs+pd.Timedelta(days=VAL_DAYS),HOLDOUT)
        te=vs-PURGE
        tr=df[df.timestamp_utc<te].copy(); va=df[(df.timestamp_utc>=vs)&(df.timestamp_utc<ve)].copy()
        if tr.empty or va.empty: continue
        fold=f'fold_{n:02d}'
        candidates={'majority_class':None,**models()}
        for mid,model in candidates.items():
            if model is None:
                pred=np.repeat(tr.allocation_target.value_counts().idxmax(),len(va)).astype(object); proba=None; classes=None
            else:
                model.fit(tr[feats],tr.allocation_target); pred=model.predict(va[feats]); proba=model.predict_proba(va[feats]); classes=model.named_steps['model'].classes_
            selected=choose_return(va,pred)
            actual=va.allocation_target.to_numpy(object)
            ll=np.nan
            if proba is not None:
                try: ll=float(log_loss(actual,proba,labels=list(classes)))
                except ValueError: pass
            counts=pd.Series(pred).value_counts()
            metric_rows.append({'fold_id':fold,'model_id':mid,'observation_count':len(va),'accuracy':accuracy_score(actual,pred),'balanced_accuracy':balanced_accuracy_score(actual,pred),'log_loss':ll,'mean_selected_forward_return_4h':selected.mean(),'mean_excess_vs_btc':np.mean(selected-va.btc_forward_return_4h.to_numpy(float)),'mean_excess_vs_alt':np.mean(selected-va.alt_forward_return_4h.to_numpy(float)),'btc_prediction_fraction':counts.get('BTC',0)/len(va),'alt_prediction_fraction':counts.get('ALT',0)/len(va),'cash_prediction_fraction':counts.get('CASH',0)/len(va)})
            tmp=va[['timestamp_utc','allocation_target']].copy(); tmp['fold_id']=fold; tmp['model_id']=mid; tmp['predicted_label']=pred; tmp['selected_forward_return_4h']=selected
            if proba is not None:
                idx={c:i for i,c in enumerate(classes)}
                for lab in LABELS: tmp[f'prob_{lab.lower()}']=proba[:,idx[lab]] if lab in idx else np.nan
            preds.append(tmp)
        print(f'[SUCCESS] {fold} train={len(tr):,} validation={len(va):,} {vs} -> {ve}')
    m=pd.DataFrame(metric_rows); p=pd.concat(preds,ignore_index=True)
    summary=[]
    for mid,g in m.groupby('model_id'):
        w=g.observation_count.to_numpy(float)
        def wa(c):
            x=pd.to_numeric(g[c],errors='coerce').to_numpy(float); ok=np.isfinite(x); return float(np.average(x[ok],weights=w[ok])) if ok.any() else np.nan
        summary.append({'model_id':mid,'fold_count':len(g),'observation_count':int(g.observation_count.sum()),'weighted_accuracy':wa('accuracy'),'weighted_balanced_accuracy':wa('balanced_accuracy'),'weighted_log_loss':wa('log_loss'),'mean_selected_forward_return_4h':wa('mean_selected_forward_return_4h'),'mean_excess_vs_btc':wa('mean_excess_vs_btc'),'mean_excess_vs_alt':wa('mean_excess_vs_alt'),'btc_prediction_fraction':wa('btc_prediction_fraction'),'alt_prediction_fraction':wa('alt_prediction_fraction'),'cash_prediction_fraction':wa('cash_prediction_fraction')})
    s=pd.DataFrame(summary).sort_values('model_id')
    OUT.mkdir(parents=True,exist_ok=True); p.to_parquet(OUT/'predictions.parquet',index=False); m.to_csv(OUT/'fold_metrics.csv',index=False); s.to_csv(OUT/'metrics_summary.csv',index=False)
    (OUT/'manifest.json').write_text(json.dumps({'research_version':'crypto_15m_v2','phase':2,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'models':['majority_class','multinomial_logistic','hist_gradient_boosting'],'validation_days':VAL_DAYS,'purge_hours':4,'future_holdout_start_utc':HOLDOUT.isoformat(),'xrp_policy':'excluded from shared universe','policy':'research validation only; no portfolio simulation or live trading'},indent=2)+'\n')
    return s

def main(argv=None):
    s=run(); print('CRYPTO 15M V2 PHASE 2'); print('='*100); print(s.to_string(index=False)); print(f'Output: {OUT/"metrics_summary.csv"}'); print('XRP remains separate. Future holdout untouched.')

if __name__=='__main__': main()
