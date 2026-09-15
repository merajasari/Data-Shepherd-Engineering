"""Crypto V5 Phase 2: fixed dual-layer chronological ML validation.

Fits allocation expected-return models and cross-sectional ranking models on
expanding folds. Produces out-of-sample predictions only; no portfolio
simulation, candidate selection, paper trading, or holdout evaluation occurs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES
from ml.crypto_v5.config import (
    ALL_HORIZONS_DAYS, FUTURE_HOLDOUT_START_UTC, PHASE1_ROOT,
    PRIMARY_HORIZON_DAYS, RESEARCH_VERSION,
)

OUTPUT_ROOT = PHASE1_ROOT.parent / "phase2"
ALLOCATION_PATH = PHASE1_ROOT / "allocation_dataset.parquet"
RANKING_PATH = PHASE1_ROOT / "ranking_dataset.parquet"
PHASE1_MANIFEST_PATH = PHASE1_ROOT / "manifest.json"
INITIAL_TRAIN_END_UTC = pd.Timestamp("2022-12-31T00:00:00Z")
VALIDATION_MONTHS = 6
PURGE_DAYS = max(ALL_HORIZONS_DAYS)
RANDOM_SEED = 1729

BREADTH_FEATURES = (
    "eligible_alt_count", "median_alt_return_1d", "median_alt_return_7d",
    "median_alt_return_30d", "alt_return_dispersion_7d",
    "median_alt_volatility_30d", "median_alt_btc_relative_7d",
    "median_alt_volume_ratio_30d", "positive_breadth_7d",
    "positive_breadth_14d", "positive_breadth_30d", "above_sma_breadth_7d",
    "above_sma_breadth_14d", "above_sma_breadth_30d",
)
FEATURES = tuple(REQUIRED_FEATURES) + BREADTH_FEATURES


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp
    validation_start_utc: pd.Timestamp
    validation_end_utc: pd.Timestamp
    purge_days: int
    def as_json(self):
        return {k: v.isoformat() if isinstance(v, pd.Timestamp) else v
                for k, v in asdict(self).items()}


def _sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def make_folds(timestamps):
    dates=pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(),utc=True)).sort_values()
    if dates.empty: raise ValueError("No Crypto V5 timestamps")
    development_end=min(dates.max(),FUTURE_HOLDOUT_START_UTC-pd.Timedelta(days=1))
    start=INITIAL_TRAIN_END_UTC+pd.Timedelta(days=1);folds=[];number=1
    while start<=development_end:
        end=min(start+pd.DateOffset(months=VALIDATION_MONTHS)-pd.Timedelta(days=1),development_end)
        folds.append(Fold(f"dev_{number:02d}",dates.min(),start-pd.Timedelta(days=PURGE_DAYS+1),start,end,PURGE_DAYS))
        start=end+pd.Timedelta(days=1);number+=1
    if not folds: raise ValueError("No Crypto V5 development folds")
    return folds


def model_definitions():
    return {
        "ridge":Pipeline([("imputer",SimpleImputer(strategy="median")),
            ("scaler",StandardScaler()),("model",Ridge(alpha=1.0))]),
        "hist_gradient_boosting":Pipeline([("imputer",SimpleImputer(strategy="median")),
            ("model",HistGradientBoostingRegressor(learning_rate=.05,max_iter=150,
                max_leaf_nodes=15,l2_regularization=1.0,random_state=RANDOM_SEED))]),
    }


def _load(path, required):
    frame=pd.read_parquet(path).copy();frame["timestamp_utc"]=pd.to_datetime(frame["timestamp_utc"],utc=True)
    missing=sorted(set(required)-set(frame.columns))
    if missing: raise ValueError(f"{path} missing columns: "+", ".join(missing))
    if (frame["timestamp_utc"]>=FUTURE_HOLDOUT_START_UTC).any():raise RuntimeError("V5 future holdout leakage")
    return frame.sort_values(["timestamp_utc"]+(["product_id"] if "product_id" in frame else [])).reset_index(drop=True)


def run_phase2(allocation_path=ALLOCATION_PATH,ranking_path=RANKING_PATH,
               phase1_manifest_path=PHASE1_MANIFEST_PATH,output_root=OUTPUT_ROOT):
    paths=[Path(allocation_path),Path(ranking_path),Path(phase1_manifest_path)]
    for path in paths:
        if not path.exists():raise FileNotFoundError(path)
    before={str(p):_sha256(p) for p in paths}
    allocation_targets=[f"{s}_forward_return_{h}d" for h in ALL_HORIZONS_DAYS for s in ("btc","alt","cash")]
    ranking_targets=[f"risk_adjusted_forward_return_{h}d" for h in ALL_HORIZONS_DAYS]
    allocation=_load(paths[0],["timestamp_utc",*FEATURES,*allocation_targets])
    ranking=_load(paths[1],["timestamp_utc","product_id",*FEATURES,*ranking_targets])
    folds=make_folds(allocation["timestamp_utc"]);models=model_definitions();allocation_rows=[];ranking_rows=[]
    output_root=Path(output_root);output_root.mkdir(parents=True,exist_ok=True)
    for fold in folds:
        atrain=allocation[allocation["timestamp_utc"].between(fold.train_start_utc,fold.train_end_utc)]
        aval=allocation[allocation["timestamp_utc"].between(fold.validation_start_utc,fold.validation_end_utc)]
        rtrain=ranking[ranking["timestamp_utc"].between(fold.train_start_utc,fold.train_end_utc)]
        rval=ranking[ranking["timestamp_utc"].between(fold.validation_start_utc,fold.validation_end_utc)]
        if any(x.empty for x in (atrain,aval,rtrain,rval)):raise ValueError(f"Empty V5 fold {fold.fold_id}")
        if atrain["timestamp_utc"].max()>=aval["timestamp_utc"].min()-pd.Timedelta(days=PURGE_DAYS):raise RuntimeError("Allocation purge violation")
        for model_id,template in models.items():
            for horizon in ALL_HORIZONS_DAYS:
                predicted={}
                for sleeve in ("btc","alt","cash"):
                    target=f"{sleeve}_forward_return_{horizon}d"
                    fitted=clone(template).fit(atrain[list(FEATURES)],atrain[target])
                    predicted[sleeve]=fitted.predict(aval[list(FEATURES)])
                    artifact=output_root/"artifacts"/"allocation"/fold.fold_id/model_id/f"{sleeve}_{horizon}d.joblib"
                    artifact.parent.mkdir(parents=True,exist_ok=True);joblib.dump(fitted,artifact)
                for i,row in aval.reset_index(drop=True).iterrows():
                    scores={s:float(predicted[s][i]) for s in predicted}
                    choice=max(("btc","alt","cash"),key=lambda s:scores[s])
                    allocation_rows.append({"timestamp_utc":row.timestamp_utc,"fold_id":fold.fold_id,
                        "model_id":model_id,"horizon_days":horizon,"predicted_sleeve":choice.upper(),
                        **{f"predicted_{s}_return":v for s,v in scores.items()},
                        **{f"actual_{s}_return":float(row[f'{s}_forward_return_{horizon}d']) for s in scores}})
                target=f"risk_adjusted_forward_return_{horizon}d"
                fitted=clone(template).fit(rtrain[list(FEATURES)],rtrain[target])
                scores=fitted.predict(rval[list(FEATURES)])
                artifact=output_root/"artifacts"/"ranking"/fold.fold_id/model_id/f"ranking_{horizon}d.joblib"
                artifact.parent.mkdir(parents=True,exist_ok=True);joblib.dump(fitted,artifact)
                for i,row in rval.reset_index(drop=True).iterrows():ranking_rows.append({
                    "timestamp_utc":row.timestamp_utc,"product_id":row.product_id,"fold_id":fold.fold_id,
                    "model_id":model_id,"horizon_days":horizon,"predicted_score":float(scores[i]),
                    "actual_risk_adjusted_return":float(row[target]),
                    "actual_forward_return":float(row[f'forward_return_{horizon}d'])})
    ap=pd.DataFrame(allocation_rows);rp=pd.DataFrame(ranking_rows)
    ap.to_parquet(output_root/"allocation_predictions.parquet",index=False)
    rp.to_parquet(output_root/"ranking_predictions.parquet",index=False)
    metrics=[]
    for layer,frame,actual,predicted in (("allocation",ap,"actual_btc_return","predicted_btc_return"),
                                        ("ranking",rp,"actual_risk_adjusted_return","predicted_score")):
        for keys,g in frame.groupby(["model_id","horizon_days"]):metrics.append({"layer":layer,
            "model_id":keys[0],"horizon_days":int(keys[1]),"observations":int(len(g)),
            "mae":float(mean_absolute_error(g[actual],g[predicted])),
            "rmse":float(mean_squared_error(g[actual],g[predicted])**.5),
            "correlation":float(g[actual].corr(g[predicted]))})
    pd.DataFrame(metrics).to_csv(output_root/"metrics.csv",index=False)
    if {str(p):_sha256(p) for p in paths}!=before:raise RuntimeError("V5 Phase 1 inputs changed")
    manifest={"research_version":RESEARCH_VERSION,"phase":2,"stage":"dual_layer_walk_forward_predictions",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),"primary_horizon_days":PRIMARY_HORIZON_DAYS,
        "validation":{"initial_train_end_utc":INITIAL_TRAIN_END_UTC.isoformat(),"months":VALIDATION_MONTHS,
                      "purge_days":PURGE_DAYS,"folds":[f.as_json() for f in folds]},
        "models":list(models),"features":list(FEATURES),"allocation_prediction_rows":int(len(ap)),
        "ranking_prediction_rows":int(len(rp)),"inputs":before,
        "outputs":{"allocation_predictions":str(output_root/"allocation_predictions.parquet"),
                   "ranking_predictions":str(output_root/"ranking_predictions.parquet"),
                   "metrics":str(output_root/"metrics.csv")},
        "policy":"prediction diagnostics only; no selection, portfolio simulation, holdout evaluation, paper trading, or brokerage orders",
        "safety":{"v4_modified":False,"paper_state_modified":False,"holdout_scored":False,"brokerage_orders":False}}
    (output_root/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--output-root",type=Path,default=OUTPUT_ROOT)
    args=ap.parse_args(argv);print(json.dumps(run_phase2(output_root=args.output_root),indent=2))
if __name__=="__main__":main()
