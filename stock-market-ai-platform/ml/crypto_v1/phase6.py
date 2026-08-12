"""Crypto V1 Phase 6: frozen signal robustness and stability audit.

Read-only diagnostics over immutable Phase 3/4/5 artifacts. The Phase 3
holdout has already been observed in Phases 4/5, so Phase 6 treats it only as
an observed diagnostic period, never as fresh validation for a new rule.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.config import MODEL_ROOT

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
PHASE5_ROOT = MODEL_ROOT / "phase5"
PHASE6_ROOT = MODEL_ROOT / "phase6"

PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "momentum"
CONTROL_MODEL_IDS = ("hist_gradient_boosting", "random", "equal_score")
MODEL_IDS = (PRIMARY_MODEL_ID,) + CONTROL_MODEL_IDS
TOP_COUNTS = (3, 5)
ROLLING_WINDOWS_DAYS = (90, 180, 365)
BOOTSTRAP_SEED = 1729
BOOTSTRAP_REPLICATES = 500
BOOTSTRAP_BLOCK_LENGTH = 28

ROLLING_COLUMNS = [
    "split","model_id","top_n","window_days","window_end_utc",
    "observation_count","mean_ic","median_ic","ic_positive_rate",
    "mean_top_minus_bottom_spread","median_top_minus_bottom_spread",
    "positive_spread_rate",
]
CALENDAR_COLUMNS = [
    "split","model_id","top_n","breakdown","period","observation_count",
    "mean_ic","median_ic","ic_positive_rate","mean_top_minus_bottom_spread",
    "median_top_minus_bottom_spread","positive_spread_rate",
    "mean_top_relative_return","mean_bottom_relative_return",
]
REGIME_COLUMNS = [
    "split","model_id","top_n","btc_regime","observation_count","mean_ic",
    "median_ic","ic_positive_rate","mean_top_minus_bottom_spread",
    "median_top_minus_bottom_spread","positive_spread_rate",
    "mean_top_relative_return","mean_bottom_relative_return",
]
ASSET_STABILITY_COLUMNS = [
    "model_id","variant","top_n","product_id","development_selection_count",
    "observed_holdout_selection_count","development_selection_rate",
    "observed_holdout_selection_rate","development_contribution",
    "observed_holdout_contribution","development_mean_relative_return",
    "observed_holdout_mean_relative_return","development_sign",
    "observed_holdout_sign","sign_status","contribution_change",
    "pearson_contribution_correlation","spearman_contribution_correlation",
]
LEAVE_ONE_OUT_COLUMNS = [
    "split","model_id","top_n","excluded_product_id","observation_count",
    "baseline_mean_spread","leave_one_out_mean_spread","spread_change",
    "baseline_positive_spread_rate","leave_one_out_positive_spread_rate",
]
CONCENTRATION_COLUMNS = [
    "split","model_id","variant","top_n","asset_count","positive_asset_count",
    "negative_asset_count","zero_asset_count","positive_asset_fraction",
    "total_contribution","total_positive_contribution",
    "total_negative_contribution","largest_absolute_contributor",
    "largest_absolute_contribution_share","positive_contribution_hhi",
    "absolute_contribution_hhi","top_1_share_of_positive_contribution",
    "top_3_share_of_positive_contribution","top_5_share_of_positive_contribution",
]
BOOTSTRAP_COLUMNS = [
    "split","model_id","top_n","metric","observation_count","block_length",
    "replicates","seed","observed_mean","bootstrap_mean","bootstrap_std",
    "ci_lower_2_5","ci_upper_97_5","bootstrap_positive_rate",
]
CONTROL_COLUMNS = [
    "split","model_id","top_n","observation_count","mean_ic","median_ic",
    "ic_positive_rate","mean_top_minus_bottom_spread",
    "median_top_minus_bottom_spread","positive_spread_rate",
    "mean_top_relative_return","mean_bottom_relative_return",
]

def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _require_columns(frame, required, label):
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: " + ", ".join(missing))

def _json_load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def load_inputs(phase3_root=PHASE3_ROOT, phase4_root=PHASE4_ROOT,
                phase5_root=PHASE5_ROOT, model_root=MODEL_ROOT):
    phase3_root, phase4_root = Path(phase3_root), Path(phase4_root)
    phase5_root, model_root = Path(phase5_root), Path(model_root)
    paths = {
        "phase3_predictions": phase3_root / "predictions.parquet",
        "phase3_manifest": phase3_root / "manifest.json",
        "research_panel_7d": model_root / "research_panel_7d.parquet",
        "phase4_manifest": phase4_root / "manifest.json",
        "phase4_portfolio_daily": phase4_root / "portfolio_daily.csv",
        "phase4_portfolio_metrics": phase4_root / "portfolio_metrics.csv",
        "phase5_manifest": phase5_root / "manifest.json",
        "phase5_regime_performance": phase5_root / "regime_performance.csv",
        "phase5_relative_performance": phase5_root / "relative_performance.csv",
        "phase5_drawdown_episodes": phase5_root / "drawdown_episodes.csv",
        "phase5_asset_attribution": phase5_root / "asset_attribution.csv",
        "phase5_spread_diagnostics": phase5_root / "spread_diagnostics.csv",
    }
    missing = [str(x) for x in paths.values() if not x.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 6 input(s): " + ", ".join(missing))
    predictions = pd.read_parquet(paths["phase3_predictions"])
    panel = pd.read_parquet(paths["research_panel_7d"])
    p4_daily = pd.read_csv(paths["phase4_portfolio_daily"])
    p4_metrics = pd.read_csv(paths["phase4_portfolio_metrics"])
    attribution = pd.read_csv(paths["phase5_asset_attribution"])
    predictions["timestamp_utc"] = pd.to_datetime(predictions["timestamp_utc"], utc=True)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    p4_daily["timestamp_utc"] = pd.to_datetime(p4_daily["timestamp_utc"], utc=True)
    _require_columns(predictions, {
        "timestamp_utc","product_id","actual_btc_relative_forward_return",
        "predicted_score","fold_id","split","model_id","horizon_days","btc_regime",
    }, "Phase 3 predictions")
    _require_columns(attribution, {
        "split","model_id","variant","top_n","product_id","selection_count",
        "available_day_count","selection_rate","mean_btc_relative_forward_return",
        "sum_btc_relative_forward_return",
    }, "Phase 5 asset_attribution")
    predictions = predictions[
        (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
        & predictions["model_id"].isin(MODEL_IDS)
    ].copy()
    if predictions.empty:
        raise ValueError("No frozen 7-day Phase 3 candidate/control predictions found")
    if not set(predictions["split"].dropna().unique()).issubset({"development","holdout"}):
        raise ValueError("Unexpected Phase 3 split")
    return paths, predictions, panel, p4_daily, p4_metrics, attribution

def _ranked_predictions(predictions):
    keys = ["horizon_days","model_id","fold_id","split","timestamp_utc"]
    x = predictions.sort_values(
        keys + ["predicted_score","product_id"],
        ascending=[True,True,True,True,True,False,True],
    ).copy()
    x["selection_rank"] = x.groupby(keys, sort=False).cumcount() + 1
    return x

def daily_signal_metrics(predictions):
    ranked, rows = _ranked_predictions(predictions), []
    keys = ["split","model_id","fold_id","timestamp_utc","btc_regime"]
    for values, day in ranked.groupby(keys, sort=True, dropna=False):
        score = pd.to_numeric(day["predicted_score"], errors="coerce")
        actual = pd.to_numeric(day["actual_btc_relative_forward_return"], errors="coerce")
        ic = score.corr(actual, method="spearman") if score.nunique(dropna=True) > 1 else np.nan
        for top_n in TOP_COUNTS:
            n = min(top_n, len(day)//2)
            if n <= 0:
                continue
            top, bottom = actual.iloc[:n].dropna(), actual.iloc[-n:].dropna()
            tm, bm = (top.mean() if len(top) else np.nan), (bottom.mean() if len(bottom) else np.nan)
            rows.append(dict(zip(keys, values)) | {
                "top_n": top_n, "ic": ic, "top_relative_return": tm,
                "bottom_relative_return": bm,
                "top_minus_bottom_spread": tm-bm if pd.notna(tm) and pd.notna(bm) else np.nan,
            })
    return pd.DataFrame(rows, columns=keys+[
        "top_n","ic","top_relative_return","bottom_relative_return","top_minus_bottom_spread"
    ])

def _summary(group):
    ic = pd.to_numeric(group["ic"], errors="coerce").dropna()
    sp = pd.to_numeric(group["top_minus_bottom_spread"], errors="coerce").dropna()
    top = pd.to_numeric(group["top_relative_return"], errors="coerce").dropna()
    bot = pd.to_numeric(group["bottom_relative_return"], errors="coerce").dropna()
    return {
        "observation_count": len(group),
        "mean_ic": ic.mean() if len(ic) else np.nan,
        "median_ic": ic.median() if len(ic) else np.nan,
        "ic_positive_rate": ic.gt(0).mean() if len(ic) else np.nan,
        "mean_top_minus_bottom_spread": sp.mean() if len(sp) else np.nan,
        "median_top_minus_bottom_spread": sp.median() if len(sp) else np.nan,
        "positive_spread_rate": sp.gt(0).mean() if len(sp) else np.nan,
        "mean_top_relative_return": top.mean() if len(top) else np.nan,
        "mean_bottom_relative_return": bot.mean() if len(bot) else np.nan,
    }

def rolling_stability(daily):
    rows, keys = [], ["split","model_id","top_n"]
    for values, g in daily.groupby(keys, sort=True, dropna=False):
        g = g.sort_values("timestamp_utc").reset_index(drop=True)
        for window_days in ROLLING_WINDOWS_DAYS:
            for end in g["timestamp_utc"]:
                start = end - pd.Timedelta(days=window_days-1)
                s = _summary(g[g["timestamp_utc"].between(start,end)])
                rows.append(dict(zip(keys,values)) | {
                    "window_days": window_days, "window_end_utc": end,
                    **{k:s[k] for k in ROLLING_COLUMNS if k in s}
                })
    return pd.DataFrame(rows, columns=ROLLING_COLUMNS)

def calendar_stability(daily):
    x, rows = daily.copy(), []
    x["year"] = x["timestamp_utc"].dt.year.astype(str)
    x["quarter"] = x["timestamp_utc"].dt.to_period("Q").astype(str)
    for breakdown, col in (("year","year"),("quarter","quarter"),("fold","fold_id")):
        keys = ["split","model_id","top_n",col]
        for values,g in x.groupby(keys, sort=True, dropna=False):
            split,model_id,top_n,period = values
            rows.append({"split":split,"model_id":model_id,"top_n":top_n,
                         "breakdown":breakdown,"period":str(period)} | _summary(g))
    return pd.DataFrame(rows, columns=CALENDAR_COLUMNS)

def regime_stability(daily):
    keys, rows = ["split","model_id","top_n","btc_regime"], []
    for values,g in daily.groupby(keys, sort=True, dropna=False):
        rows.append(dict(zip(keys,values)) | _summary(g))
    return pd.DataFrame(rows, columns=REGIME_COLUMNS)

def asset_stability(attribution):
    rows, keys = [], ["model_id","variant","top_n"]
    for values,g in attribution[attribution["model_id"].isin(MODEL_IDS)].groupby(keys, sort=True, dropna=False):
        dev = g[g["split"]=="development"].set_index("product_id")
        hold = g[g["split"]=="holdout"].set_index("product_id")
        products = sorted(set(dev.index)|set(hold.index))
        pair = pd.DataFrame({
            "development": dev["sum_btc_relative_forward_return"].reindex(products),
            "holdout": hold["sum_btc_relative_forward_return"].reindex(products),
        }).dropna()
        pearson = pair.corr(method="pearson").iloc[0,1] if len(pair)>1 else np.nan
        spearman = pair.corr(method="spearman").iloc[0,1] if len(pair)>1 else np.nan
        for product in products:
            d = dev.loc[product] if product in dev.index else None
            h = hold.loc[product] if product in hold.index else None
            dc = float(d["sum_btc_relative_forward_return"]) if d is not None else np.nan
            hc = float(h["sum_btc_relative_forward_return"]) if h is not None else np.nan
            ds = int(np.sign(dc)) if pd.notna(dc) else 0
            hs = int(np.sign(hc)) if pd.notna(hc) else 0
            if pd.isna(dc) or pd.isna(hc): status = "not_common"
            elif ds == hs and ds != 0: status = "persisted"
            elif ds == 0 or hs == 0: status = "zero_or_negligible"
            else: status = "reversed"
            rows.append({
                "model_id":values[0],"variant":values[1],"top_n":values[2],"product_id":product,
                "development_selection_count":d["selection_count"] if d is not None else 0,
                "observed_holdout_selection_count":h["selection_count"] if h is not None else 0,
                "development_selection_rate":d["selection_rate"] if d is not None else np.nan,
                "observed_holdout_selection_rate":h["selection_rate"] if h is not None else np.nan,
                "development_contribution":dc,"observed_holdout_contribution":hc,
                "development_mean_relative_return":d["mean_btc_relative_forward_return"] if d is not None else np.nan,
                "observed_holdout_mean_relative_return":h["mean_btc_relative_forward_return"] if h is not None else np.nan,
                "development_sign":ds,"observed_holdout_sign":hs,"sign_status":status,
                "contribution_change":hc-dc if pd.notna(dc) and pd.notna(hc) else np.nan,
                "pearson_contribution_correlation":pearson,
                "spearman_contribution_correlation":spearman,
            })
    return pd.DataFrame(rows, columns=ASSET_STABILITY_COLUMNS)

def leave_one_asset_out(predictions, baseline_daily=None):
    baseline_daily = daily_signal_metrics(predictions) if baseline_daily is None else baseline_daily.copy()
    rows = []
    for (split,model_id), g in predictions.groupby(["split","model_id"], sort=True):
        products = sorted(g["product_id"].dropna().unique())
        for top_n in TOP_COUNTS:
            base = baseline_daily[(baseline_daily["split"]==split)&(baseline_daily["model_id"]==model_id)&(baseline_daily["top_n"]==top_n)]
            bs = pd.to_numeric(base["top_minus_bottom_spread"], errors="coerce").dropna()
            bm = bs.mean() if len(bs) else np.nan
            bp = bs.gt(0).mean() if len(bs) else np.nan
            for product in products:
                reduced = g[g["product_id"]!=product]
                loo = daily_signal_metrics(reduced)
                loo = loo[loo["top_n"]==top_n]
                sp = pd.to_numeric(loo["top_minus_bottom_spread"], errors="coerce").dropna()
                lm = sp.mean() if len(sp) else np.nan
                rows.append({
                    "split":split,"model_id":model_id,"top_n":top_n,
                    "excluded_product_id":product,"observation_count":len(sp),
                    "baseline_mean_spread":bm,"leave_one_out_mean_spread":lm,
                    "spread_change":lm-bm if pd.notna(lm) and pd.notna(bm) else np.nan,
                    "baseline_positive_spread_rate":bp,
                    "leave_one_out_positive_spread_rate":sp.gt(0).mean() if len(sp) else np.nan,
                })
    return pd.DataFrame(rows, columns=LEAVE_ONE_OUT_COLUMNS)

def contribution_concentration(attribution):
    rows, keys = [], ["split","model_id","variant","top_n"]
    for values,g in attribution.groupby(keys, sort=True, dropna=False):
        c = pd.to_numeric(g["sum_btc_relative_forward_return"], errors="coerce").fillna(0.0)
        a, pos, neg = c.abs(), c[c>0].sort_values(ascending=False), c[c<0]
        pt, at = pos.sum(), a.sum()
        ps = pos/pt if pt>0 else pd.Series(dtype=float)
        ass = a/at if at>0 else pd.Series(dtype=float)
        idx = a.idxmax() if at>0 else None
        def top_share(n): return float(pos.head(n).sum()/pt) if pt>0 else np.nan
        rows.append(dict(zip(keys,values)) | {
            "asset_count":len(g),"positive_asset_count":int((c>0).sum()),
            "negative_asset_count":int((c<0).sum()),"zero_asset_count":int((c==0).sum()),
            "positive_asset_fraction":float((c>0).mean()),"total_contribution":float(c.sum()),
            "total_positive_contribution":float(pt),"total_negative_contribution":float(neg.sum()),
            "largest_absolute_contributor":g.loc[idx,"product_id"] if idx is not None else None,
            "largest_absolute_contribution_share":float(a.max()/at) if at>0 else np.nan,
            "positive_contribution_hhi":float((ps**2).sum()) if len(ps) else np.nan,
            "absolute_contribution_hhi":float((ass**2).sum()) if len(ass) else np.nan,
            "top_1_share_of_positive_contribution":top_share(1),
            "top_3_share_of_positive_contribution":top_share(3),
            "top_5_share_of_positive_contribution":top_share(5),
        })
    return pd.DataFrame(rows, columns=CONCENTRATION_COLUMNS)

def _block_bootstrap_means(values, rng, replicates, block_length):
    values = np.asarray(values,dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n == 0: return np.array([],dtype=float)
    block = max(1,min(int(block_length),n))
    starts = np.arange(0,n-block+1)
    means = np.empty(int(replicates))
    for i in range(int(replicates)):
        sample = []
        while len(sample)<n:
            start = int(rng.choice(starts))
            sample.extend(values[start:start+block].tolist())
        means[i] = float(np.mean(sample[:n]))
    return means

def bootstrap_uncertainty(daily, seed=BOOTSTRAP_SEED,
                          replicates=BOOTSTRAP_REPLICATES,
                          block_length=BOOTSTRAP_BLOCK_LENGTH):
    rows, keys = [], ["split","model_id","top_n"]
    for gi,(values,g) in enumerate(daily.groupby(keys, sort=True, dropna=False)):
        g = g.sort_values("timestamp_utc")
        for mi,metric in enumerate(("ic","top_minus_bottom_spread")):
            s = pd.to_numeric(g[metric],errors="coerce").dropna()
            rng = np.random.default_rng(int(seed)+gi*1009+mi*9176)
            boot = _block_bootstrap_means(s.to_numpy(),rng,replicates,block_length)
            rows.append(dict(zip(keys,values)) | {
                "metric":metric,"observation_count":len(s),"block_length":int(block_length),
                "replicates":int(replicates),"seed":int(seed),
                "observed_mean":float(s.mean()) if len(s) else np.nan,
                "bootstrap_mean":float(np.mean(boot)) if len(boot) else np.nan,
                "bootstrap_std":float(np.std(boot,ddof=1)) if len(boot)>1 else np.nan,
                "ci_lower_2_5":float(np.quantile(boot,.025)) if len(boot) else np.nan,
                "ci_upper_97_5":float(np.quantile(boot,.975)) if len(boot) else np.nan,
                "bootstrap_positive_rate":float(np.mean(boot>0)) if len(boot) else np.nan,
            })
    return pd.DataFrame(rows, columns=BOOTSTRAP_COLUMNS)

def control_comparison(daily):
    keys, rows = ["split","model_id","top_n"], []
    for values,g in daily.groupby(keys, sort=True, dropna=False):
        rows.append(dict(zip(keys,values)) | _summary(g))
    return pd.DataFrame(rows, columns=CONTROL_COLUMNS)

def run_phase6(phase3_root=PHASE3_ROOT, phase4_root=PHASE4_ROOT,
               phase5_root=PHASE5_ROOT, model_root=MODEL_ROOT,
               output_root=PHASE6_ROOT):
    paths,predictions,panel,p4_daily,p4_metrics,attribution = load_inputs(
        phase3_root,phase4_root,phase5_root,model_root)
    before = {name:_sha256(path) for name,path in paths.items()}
    daily = daily_signal_metrics(predictions)
    frames = {
        "rolling_stability":rolling_stability(daily),
        "calendar_stability":calendar_stability(daily),
        "regime_stability":regime_stability(daily),
        "asset_stability":asset_stability(attribution),
        "leave_one_asset_out":leave_one_asset_out(predictions,daily),
        "contribution_concentration":contribution_concentration(attribution),
        "bootstrap_uncertainty":bootstrap_uncertainty(daily),
        "control_comparison":control_comparison(daily),
    }
    output_root = Path(output_root); output_root.mkdir(parents=True,exist_ok=True)
    outputs = {name:output_root/f"{name}.csv" for name in frames}
    for name,path in outputs.items(): frames[name].to_csv(path,index=False)
    after = {name:_sha256(path) for name,path in paths.items()}
    if after != before:
        raise RuntimeError("Frozen Phase 3/4/5 inputs changed during Phase 6")
    manifest = {
        "phase":6,"research_version":"crypto_v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "objective":"Audit whether the frozen 7-day BTC-relative ranking signal is stable across time, regimes, and assets without changing any model or portfolio rule.",
        "policy":"read-only robustness diagnostics only; no fitting, retraining, retuning, threshold selection, strategy selection, universe changes, asset blacklists, regime filters, portfolio-rule changes, promotion, live execution, leverage, or derivatives",
        "primary_strategy":{"horizon_days":7,"model_id":"momentum"},
        "controls":list(CONTROL_MODEL_IDS),
        "observed_holdout_policy":"The Phase 3 holdout beginning 2025-08-01 was already observed in Phases 4 and 5. Phase 6 treats it as an observed diagnostic period, not as a fresh unbiased validation sample. No Phase 6 result may create or validate a newly invented trading rule on that same period.",
        "rolling_window_policy":{"windows_calendar_days":list(ROLLING_WINDOWS_DAYS),"selection_policy":"All predetermined windows are reported; none is selected from development or observed-holdout performance."},
        "bootstrap_policy":{"method":"deterministic moving-block bootstrap of ordered daily diagnostics","seed":BOOTSTRAP_SEED,"replicates":BOOTSTRAP_REPLICATES,"block_length_observations":BOOTSTRAP_BLOCK_LENGTH,"purpose":"descriptive uncertainty only; never parameter selection"},
        "regime_policy":"Uses only frozen btc_regime stamped upstream in Phase 3; no new regime classifier or filter.",
        "asset_policy":"Leave-one-asset-out and concentration are diagnostics only; no blacklist, whitelist, or dynamic universe rule.",
        "source_files":{name:{"path":str(path),"sha256":before[name]} for name,path in paths.items()},
        "source_row_counts":{"phase3_predictions_7d_candidate_controls":len(predictions),"research_panel_7d":len(panel),"phase4_portfolio_daily":len(p4_daily),"phase4_portfolio_metrics":len(p4_metrics),"phase5_asset_attribution":len(attribution)},
        "outputs":{name:str(path) for name,path in outputs.items()},
        "output_row_counts":{name:len(frame) for name,frame in frames.items()},
        "phase3_manifest":_json_load(paths["phase3_manifest"]),
        "phase4_manifest":_json_load(paths["phase4_manifest"]),
        "phase5_manifest":_json_load(paths["phase5_manifest"]),
    }
    (output_root/"manifest.json").write_text(json.dumps(manifest,indent=2,default=str)+"\n",encoding="utf-8")
    return manifest,frames

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-root",type=Path,default=PHASE3_ROOT)
    parser.add_argument("--phase4-root",type=Path,default=PHASE4_ROOT)
    parser.add_argument("--phase5-root",type=Path,default=PHASE5_ROOT)
    parser.add_argument("--model-root",type=Path,default=MODEL_ROOT)
    parser.add_argument("--output-root",type=Path,default=PHASE6_ROOT)
    a = parser.parse_args(argv)
    manifest,_ = run_phase6(a.phase3_root,a.phase4_root,a.phase5_root,a.model_root,a.output_root)
    print(json.dumps({"phase":manifest["phase"],"policy":manifest["policy"],"observed_holdout_policy":manifest["observed_holdout_policy"],"output_row_counts":manifest["output_row_counts"],"outputs":manifest["outputs"]},indent=2))

if __name__ == "__main__":
    main()
