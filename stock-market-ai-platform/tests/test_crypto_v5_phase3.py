import unittest
import pandas as pd
from ml.crypto_v5.config import MAX_TURNOVER_PER_REBALANCE
from ml.crypto_v5.phase3 import capped_target, decision_dates, turnover


class CryptoV5Phase3Test(unittest.TestCase):
    def test_turnover_cap_is_enforced(self):
        current={"CASH":1.0};target={"BTC-USD":.3,"ALT1-USD":.3,"ALT2-USD":.3,"CASH":.1}
        adjusted,used=capped_target(current,target)
        self.assertAlmostEqual(used,MAX_TURNOVER_PER_REBALANCE)
        self.assertLessEqual(turnover(current,adjusted),MAX_TURNOVER_PER_REBALANCE+1e-12)
        self.assertAlmostEqual(sum(adjusted.values()),1.0)

    def test_decision_dates_do_not_overlap_horizon(self):
        dates=pd.date_range("2026-01-01",periods=12,freq="D",tz="UTC")
        selected=decision_dates(dates,3)
        self.assertTrue(all((b-a).days>=3 for a,b in zip(selected,selected[1:])))


if __name__=="__main__":unittest.main()
