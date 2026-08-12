"""Focused tests for Crypto V1 Phase 6 frozen robustness audit."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ml.crypto_v1.phase6 import (
    ASSET_STABILITY_COLUMNS, BOOTSTRAP_COLUMNS, CALENDAR_COLUMNS,
    CONCENTRATION_COLUMNS, CONTROL_COLUMNS, LEAVE_ONE_OUT_COLUMNS,
    REGIME_COLUMNS, ROLLING_COLUMNS, asset_stability, bootstrap_uncertainty,
    calendar_stability, contribution_concentration, control_comparison,
    daily_signal_metrics, leave_one_asset_out, regime_stability,
    rolling_stability, run_phase6,
)

PRODUCTS = ["BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD","LTC-USD"]
MODELS = ["momentum","hist_gradient_boosting","random","equal_score"]

def synthetic_predictions():
    dates = pd.date_range("2025-01-01", periods=28, tz="UTC")
    rows = []
    for split, subset in (("development",dates[:18]),("holdout",dates[18:])):
        fold_id = "dev_01" if split=="development" else "holdout"
        for model_id in MODELS:
            for day_number,timestamp in enumerate(subset):
                regime = ("risk_on","neutral","risk_off")[day_number%3]
                for asset_number,product in enumerate(PRODUCTS):
                    if model_id=="momentum": score=len(PRODUCTS)-asset_number
                    elif model_id=="hist_gradient_boosting": score=asset_number
                    elif model_id=="random": score=((day_number*7+asset_number*3)%17)/17
                    else: score=0.0
                    actual=0.01*(3-asset_number)
                    if split=="holdout" and product in {"ETH-USD","SOL-USD"}:
                        actual *= -1
                    rows.append({
                        "timestamp_utc":timestamp,"product_id":product,
                        "actual_btc_relative_forward_return":actual,
                        "predicted_score":score,"fold_id":fold_id,"split":split,
                        "model_id":model_id,"horizon_days":7,"btc_regime":regime,
                    })
    return pd.DataFrame(rows)

def synthetic_panel():
    rows=[]
    for timestamp in pd.date_range("2025-01-01",periods=28,tz="UTC"):
        for i,product in enumerate(PRODUCTS):
            rows.append({"timestamp_utc":timestamp,"product_id":product,"return_1d":.001*(i+1)})
    return pd.DataFrame(rows)

def synthetic_phase4_daily():
    rows=[]
    for i,timestamp in enumerate(pd.date_range("2025-01-01",periods=28,tz="UTC")):
        rows.append({
            "timestamp_utc":timestamp,"split":"development" if i<18 else "holdout",
            "model_id":"momentum","strategy_id":"momentum:top_3_equal_weight:top3",
            "variant":"top_3_equal_weight","top_n":3,"cost_bps_round_trip":0.0,
            "is_rebalance":i%7==0,"turnover":.5 if i%7==0 else 0.0,
            "transaction_cost":0.0,"gross_return":0.0,"net_return":0.0,
            "gross_exposure":1.0,"net_exposure":1.0,"cash_weight":0.0,"equity":1.0,
        })
    return pd.DataFrame(rows)

def synthetic_phase4_metrics():
    return pd.DataFrame([{
        "split":"development","model_id":"momentum",
        "strategy_id":"momentum:top_3_equal_weight:top3","variant":"top_3_equal_weight",
        "top_n":3,"cost_bps_round_trip":0.0,"ending_equity":1.0,
        "cumulative_return":0.0,"maximum_drawdown":0.0,"total_turnover":1.0,
        "number_of_rebalances":2,
    }])

def synthetic_asset_attribution(predictions=None):
    x = synthetic_predictions() if predictions is None else predictions.copy()
    x = x.sort_values(
        ["split","model_id","timestamp_utc","predicted_score","product_id"],
        ascending=[True,True,True,False,True],
    )
    x["selection_rank"]=x.groupby(["split","model_id","timestamp_utc"],sort=False).cumcount()+1
    rows=[]
    for (split,model_id),g in x.groupby(["split","model_id"],sort=True):
        available=g.groupby("product_id")["timestamp_utc"].nunique()
        for top_n in (3,5):
            chosen=g[g["selection_rank"]<=top_n]
            for product,asset in chosen.groupby("product_id",sort=True):
                actual=asset["actual_btc_relative_forward_return"]
                rows.append({
                    "split":split,"model_id":model_id,"variant":f"top_{top_n}_equal_weight",
                    "top_n":top_n,"product_id":product,"selection_count":len(asset),
                    "available_day_count":int(available[product]),
                    "selection_rate":len(asset)/int(available[product]),
                    "mean_btc_relative_forward_return":actual.mean(),
                    "median_btc_relative_forward_return":actual.median(),
                    "positive_relative_return_rate":actual.gt(0).mean(),
                    "sum_btc_relative_forward_return":actual.sum(),
                })
    return pd.DataFrame(rows)

class Phase6UnitTests(unittest.TestCase):
    def setUp(self):
        self.pred=synthetic_predictions()
        self.daily=daily_signal_metrics(self.pred)
        self.asset=synthetic_asset_attribution(self.pred)

    def test_split_separation_and_equal_score_ic(self):
        self.assertEqual(set(self.daily["split"]),{"development","holdout"})
        self.assertTrue(self.daily[self.daily["model_id"]=="equal_score"]["ic"].isna().all())

    def test_output_schemas(self):
        self.assertEqual(list(rolling_stability(self.daily).columns),ROLLING_COLUMNS)
        self.assertEqual(list(calendar_stability(self.daily).columns),CALENDAR_COLUMNS)
        self.assertEqual(list(regime_stability(self.daily).columns),REGIME_COLUMNS)
        self.assertEqual(list(asset_stability(self.asset).columns),ASSET_STABILITY_COLUMNS)
        self.assertEqual(list(leave_one_asset_out(self.pred,self.daily).columns),LEAVE_ONE_OUT_COLUMNS)
        self.assertEqual(list(contribution_concentration(self.asset).columns),CONCENTRATION_COLUMNS)
        self.assertEqual(list(control_comparison(self.daily).columns),CONTROL_COLUMNS)

    def test_leave_one_out_does_not_mutate_input(self):
        before=self.pred.copy(deep=True)
        leave_one_asset_out(self.pred,self.daily)
        pd.testing.assert_frame_equal(before,self.pred)

    def test_concentration_bounds(self):
        frame=contribution_concentration(self.asset)
        for col in (
            "largest_absolute_contribution_share","positive_contribution_hhi",
            "absolute_contribution_hhi","top_1_share_of_positive_contribution",
            "top_3_share_of_positive_contribution","top_5_share_of_positive_contribution",
        ):
            x=frame[col].dropna()
            self.assertTrue((x>=0).all())
            self.assertTrue((x<=1+1e-12).all())

    def test_bootstrap_deterministic(self):
        a=bootstrap_uncertainty(self.daily,seed=1729,replicates=30,block_length=4)
        b=bootstrap_uncertainty(self.daily,seed=1729,replicates=30,block_length=4)
        self.assertEqual(list(a.columns),BOOTSTRAP_COLUMNS)
        pd.testing.assert_frame_equal(a,b)

    def test_no_future_usage(self):
        cutoff=pd.Timestamp("2025-01-12",tz="UTC")
        left=daily_signal_metrics(self.pred[self.pred["timestamp_utc"]<=cutoff].copy())
        mutated=self.pred.copy()
        mutated.loc[mutated["timestamp_utc"]>cutoff,"actual_btc_relative_forward_return"]*=1000
        right=daily_signal_metrics(mutated[mutated["timestamp_utc"]<=cutoff].copy())
        pd.testing.assert_frame_equal(left,right)

class Phase6IntegrationTests(unittest.TestCase):
    def test_run_phase6_preserves_inputs_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); phase3=root/"phase3"; phase4=root/"phase4"; phase5=root/"phase5"; out=root/"phase6"
            phase3.mkdir(); phase4.mkdir(); phase5.mkdir()
            pred=synthetic_predictions(); panel=synthetic_panel()
            p4d=synthetic_phase4_daily(); p4m=synthetic_phase4_metrics()
            asset=synthetic_asset_attribution(pred)
            prediction_path=phase3/"predictions.parquet"; panel_path=root/"research_panel_7d.parquet"
            prediction_path.write_bytes(b"immutable phase3 predictions")
            panel_path.write_bytes(b"immutable panel")
            (phase3/"manifest.json").write_text('{"phase":3}\n')
            (phase4/"manifest.json").write_text('{"phase":4}\n')
            (phase5/"manifest.json").write_text('{"phase":5}\n')
            p4d.to_csv(phase4/"portfolio_daily.csv",index=False)
            p4m.to_csv(phase4/"portfolio_metrics.csv",index=False)
            for name,frame in {
                "regime_performance.csv":pd.DataFrame({"x":[1]}),
                "relative_performance.csv":pd.DataFrame({"x":[1]}),
                "drawdown_episodes.csv":pd.DataFrame({"x":[1]}),
                "asset_attribution.csv":asset,
                "spread_diagnostics.csv":pd.DataFrame({"x":[1]}),
            }.items():
                frame.to_csv(phase5/name,index=False)
            tracked=[prediction_path,panel_path,phase3/"manifest.json",phase4/"manifest.json",
                     phase5/"manifest.json",phase4/"portfolio_daily.csv",phase4/"portfolio_metrics.csv",
                     phase5/"regime_performance.csv",phase5/"relative_performance.csv",
                     phase5/"drawdown_episodes.csv",phase5/"asset_attribution.csv",
                     phase5/"spread_diagnostics.csv"]
            before={x:x.read_bytes() for x in tracked}
            real=pd.read_parquet
            def fake(path,*args,**kwargs):
                path=Path(path)
                if path==prediction_path:return pred.copy()
                if path==panel_path:return panel.copy()
                return real(path,*args,**kwargs)
            with patch("ml.crypto_v1.phase6.pd.read_parquet",side_effect=fake), \
                 patch("ml.crypto_v1.phase6.BOOTSTRAP_REPLICATES",20):
                manifest,frames=run_phase6(phase3,phase4,phase5,root,out)
            self.assertEqual(before,{x:x.read_bytes() for x in tracked})
            self.assertIn("no fitting",manifest["policy"])
            self.assertIn("observed diagnostic period",manifest["observed_holdout_policy"])
            self.assertEqual(set(frames),{
                "rolling_stability","calendar_stability","regime_stability","asset_stability",
                "leave_one_asset_out","contribution_concentration","bootstrap_uncertainty",
                "control_comparison",
            })
            for name in ["manifest.json","rolling_stability.csv","calendar_stability.csv",
                         "regime_stability.csv","asset_stability.csv","leave_one_asset_out.csv",
                         "contribution_concentration.csv","bootstrap_uncertainty.csv",
                         "control_comparison.csv"]:
                self.assertTrue((out/name).exists(),name)

if __name__=="__main__":
    unittest.main()
