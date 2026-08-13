"""BTC V1 Phase 2: pre-registered standalone BTC walk-forward modeling.

Uses only the frozen BTC V1 Phase 1 dataset. The primary target is 7-day
absolute BTC return. Validation uses expanding six-month development folds with
a 7-day purge so every training target endpoint precedes validation. Data at or
after 2026-09-01 remains a genuinely future holdout and is not evaluated while
current data ends before it.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import argparse, hashlib, json, subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.btc_v1.phase1 import MODEL_ROOT, LABELED_DATASET_PATH, REQUIRED_FEATURES, RESEARCH_VERSION

PHASE2_ROOT = MODEL_ROOT / "phase2"
HORIZON_DAYS = 7
TARGET = "forward_return_7d"
TARGET_ENDPOINT = "target_endpoint_utc_7d"
DEVELOPMENT_VALIDATION_START_UTC = pd.Timestamp("2021-07-01", tz="UTC")
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01", tz="UTC")
VALIDATION_MONTHS = 6
RANDOM_SEED = 1729
MODEL_FEATURES = tuple(REQUIRED_FEATURES)

@dataclass(frozen=True)
class Fold:
    fold_id: str
    split: str
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp
    validation_start_utc: pd.Timestamp
    validation_end_utc: pd.Timestamp
    purge_days: int
    def as_json(self):
        d = asdict(self)
        return {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k,v in d.items()}

def _sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for c in iter(lambda:f.read(1024*1024), b""): h.update(c)
    return h.hexdigest()

def _git_hash():
    try:
        return subprocess.run(["git","rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError): return None

def _month_end(ts): return ts + pd.offsets.MonthEnd(0)

def make_folds(timestamps, validation_start=DEVELOPMENT_VALIDATION_START_UTC, holdout_start=FUTURE_HOLDOUT_START_UTC):
    dates=pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(),utc=True)).sort_values()
    if dates.empty: raise ValueError("Cannot create folds without timestamps")
    validation_start=pd.Timestamp(validation_start)
    validation_start=validation_start.tz_localize("UTC") if validation_start.tzinfo is None else validation_start.tz_convert("UTC")
    holdout_start=pd.Timestamp(holdout_start)
    holdout_start=holdout_start.tz_localize("UTC") if holdout_start.tzinfo is None else holdout_start.tz_convert("UTC")
    development_end=min(dates.max(), holdout_start-pd.Timedelta(days=1))
    folds=[]; n=1
    while validation_start <= development_end:
        validation_end=min(_month_end(validation_start+pd.DateOffset(months=VALIDATION_MONTHS-1)), development_end)
        train_end=validation_start-pd.Timedelta(days=HORIZON_DAYS+1)
        folds.append(Fold(f"dev_{n:02d}","development",dates.min(),train_end,validation_start,validation_end,HORIZON_DAYS))
        validation_start=validation_end+pd.Timedelta(days=1); n+=1
    if dates.max() >= holdout_start:
        folds.append(Fold("holdout","holdout",dates.min(),holdout_start-pd.Timedelta(days=HORIZON_DAYS+1),holdout_start,dates.max(),HORIZON_DAYS))
    return folds

def load_dataset(path=LABELED_DATASET_PATH):
    path=Path(path)
    if not path.exists(): raise FileNotFoundError(path)
    df=pd.read_parquet(path).copy(); df["timestamp_utc"]=pd.to_datetime(df["timestamp_utc"],utc=True)
    missing=(set(MODEL_FEATURES)|{"timestamp_utc",TARGET,TARGET_ENDPOINT})-set(df.columns)
    if missing: raise ValueError("BTC Phase 1 dataset missing columns: "+", ".join(sorted(missing)))
    return df.sort_values("timestamp_utc").reset_index(drop=True)

def validate_fold(fold, df):
    train=df[df["timestamp_utc"].between(fold.train_start_utc,fold.train_end_utc)].copy()
    val=df[df["timestamp_utc"].between(fold.validation_start_utc,fold.validation_end_utc)].copy()
    train=train[train[TARGET].notna() & train[list(MODEL_FEATURES)].notna().all(axis=1)]
    val=val[val[TARGET].notna() & val[list(MODEL_FEATURES)].notna().all(axis=1)]
    if train.empty or val.empty: raise ValueError(f"Empty train or validation partition in {fold.fold_id}")
    if pd.to_datetime(train[TARGET_ENDPOINT],utc=True).max() >= val["timestamp_utc"].min(): raise ValueError(f"Target leakage across {fold.fold_id}")
    return train,val

def model_definitions(seed=RANDOM_SEED):
    linear=[("imputer",SimpleImputer(strategy="median")),("scaler",StandardScaler())]
    return {
      "ridge":Pipeline(linear+[("model",Ridge(alpha=10.0))]),
      "elastic_net":Pipeline(linear+[("model",ElasticNet(alpha=0.001,l1_ratio=0.25,max_iter=10000,random_state=seed))]),
      "hist_gradient_boosting":Pipeline([("imputer",SimpleImputer(strategy="median")),("model",HistGradientBoostingRegressor(learning_rate=0.05,max_iter=150,max_leaf_nodes=15,l2_regularization=1.0,random_state=seed))]),
    }

def run_phase2(dataset_path=LABELED_DATASET_PATH, output_root=PHASE2_ROOT):
    dataset_path=Path(dataset_path); before=_sha256(dataset_path); df=load_dataset(dataset_path)
    predictions=[]; fold_rows=[]
    for fold in make_folds(df["timestamp_utc"]):
        if fold.split != "development": continue
        train,val=validate_fold(fold,df)
        for model_id,definition in model_definitions().items():
            model=clone(definition).fit(train[list(MODEL_FEATURES)],train[TARGET])
            pred=model.predict(val[list(MODEL_FEATURES)])
            out=val[["timestamp_utc",TARGET]].copy().rename(columns={TARGET:"actual_forward_return_7d"})
            out["predicted_return_7d"]=pred; out["model_id"]=model_id; out["fold_id"]=fold.fold_id; out["split"]=fold.split
            predictions.append(out)
        for model_id,pred in {
            "momentum": val["return_7d"].to_numpy(float),
            "zero_return": np.zeros(len(val),dtype=float),
        }.items():
            out=val[["timestamp_utc",TARGET]].copy().rename(columns={TARGET:"actual_forward_return_7d"})
            out["predicted_return_7d"]=pred; out["model_id"]=model_id; out["fold_id"]=fold.fold_id; out["split"]=fold.split
            predictions.append(out)
        fold_rows.append(fold.as_json())
    pred=pd.concat(predictions,ignore_index=True).sort_values(["timestamp_utc","model_id"]).reset_index(drop=True)
    metrics=[]
    for (model_id,split),g in pred.groupby(["model_id","split"],sort=True):
        a=g["actual_forward_return_7d"].to_numpy(float); p=g["predicted_return_7d"].to_numpy(float)
        pos=p>0; non=~pos
        corr=float(pd.Series(p).corr(pd.Series(a))) if np.std(p)>0 else np.nan
        metrics.append({
            "model_id":model_id,"split":split,"observation_count":len(g),
            "mae":mean_absolute_error(a,p),"rmse":mean_squared_error(a,p)**0.5,
            "pearson_correlation":corr,"directional_accuracy":float(np.mean(np.sign(a)==np.sign(p))),
            "predicted_positive_rate":float(pos.mean()),
            "mean_actual_when_predicted_positive":float(np.mean(a[pos])) if pos.any() else np.nan,
            "mean_actual_when_predicted_non_positive":float(np.mean(a[non])) if non.any() else np.nan,
            "positive_actual_rate_when_predicted_positive":float(np.mean(a[pos]>0)) if pos.any() else np.nan,
        })
    metrics=pd.DataFrame(metrics)
    output_root=Path(output_root); output_root.mkdir(parents=True,exist_ok=True)
    pred_path=output_root/"predictions.parquet"; met_path=output_root/"metrics_summary.csv"; folds_path=output_root/"folds.json"
    pred.to_parquet(pred_path,index=False); metrics.to_csv(met_path,index=False); folds_path.write_text(json.dumps(fold_rows,indent=2)+"\n")
    if _sha256(dataset_path)!=before: raise RuntimeError("Frozen BTC Phase 1 dataset changed during Phase 2")
    manifest={
      "research_version":RESEARCH_VERSION,"phase":2,"stage":"standalone_btc_walk_forward_modeling",
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),"git_commit_hash":_git_hash(),
      "target":TARGET,"horizon_days":HORIZON_DAYS,"development_validation_start_utc":DEVELOPMENT_VALIDATION_START_UTC.isoformat(),
      "future_holdout_start_utc":FUTURE_HOLDOUT_START_UTC.isoformat(),"validation_months":VALIDATION_MONTHS,"purge_days":HORIZON_DAYS,
      "models":list(model_definitions().keys())+["momentum","zero_return"],"input":{"path":str(dataset_path),"sha256":before,"rows":int(len(df))},
      "outputs":{"predictions":str(pred_path),"metrics_summary":str(met_path),"folds":str(folds_path)},
      "next_step":"Review development-only BTC diagnostics. Do not tune models, thresholds, features, folds, or future holdout based on these results."
    }
    (output_root/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--dataset",type=Path,default=LABELED_DATASET_PATH); ap.add_argument("--output-root",type=Path,default=PHASE2_ROOT)
    args=ap.parse_args(argv); print(json.dumps(run_phase2(args.dataset,args.output_root),indent=2))

if __name__=="__main__": main()
