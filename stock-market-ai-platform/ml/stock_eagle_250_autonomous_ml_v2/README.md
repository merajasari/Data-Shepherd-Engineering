# StockEagle250 Autonomous ML V2

Autonomous ML V2 is a new learned model generation created after Autonomous ML
V1 passed eight of nine preregistered development gates but failed the
worst-fold maximum-drawdown gate.

V2 preserves V1 as rejected evidence. It does not weaken the -30% drawdown
requirement and does not add a hand-written drawdown throttle.

## Fixed learned architecture

V2 contains four learned components:

1. **Alpha model** — Histogram Gradient Boosting regression predicts
   five-session return relative to SPY.
2. **Downside model** — Histogram Gradient Boosting classification predicts the
   probability of a negative five-session absolute stock return.
3. **Tail model** — Histogram Gradient Boosting quantile regression predicts
   the conditional 10th-percentile five-session absolute stock return.
4. **Meta allocator** — Histogram Gradient Boosting classification predicts
   whether the learned Top-10 cohort will have a positive net return after
   10-bps-per-side transaction costs.

The meta allocator may train only from inner walk-forward out-of-sample alpha,
downside, and tail predictions.

## Tail-aware learned portfolio

Stocks are still selected by learned alpha. Position sizing uses all three
stock-level learned outputs under one fixed mapping:

```text
score =
    exp(
        cross_sectional_zscore(alpha_prediction)
        - downside_probability
        + cross_sectional_zscore(tail10_prediction)
    )
```

A less-negative learned 10th-percentile return therefore receives more weight,
while a higher learned downside probability receives less.

The meta allocator also receives fixed aggregate tail-risk features from the
learned Top-10. The allocator probability remains the requested gross exposure
in [0, 1]. There is no manual market regime, volatility tier, confidence tier,
drawdown throttle, exposure floor, or tail-risk threshold.

## Scientific isolation

V2 is one fixed hypothesis motivated by V1's single failed gate. There is:

- no hyperparameter search;
- no model-family search;
- no feature search;
- no allocator-threshold search;
- no post-result adjustment to the 10th-percentile level;
- no use of the September 23-30 sealed guard band;
- no use of the October 1+ untouched future sample.

The same nine Autonomous ML V1 development gates are reused without
relaxation.

## Phase 1

```bash
python -m unittest tests.test_stock_eagle_250_autonomous_ml_v2_phase1 -v
python -m ml.stock_eagle_250_autonomous_ml_v2.phase1
python -m json.tool data/model/stock_eagle_250_autonomous_ml_v2/phase1/manifest.json
```

Phase 1 computes no V2 performance. Phase 2 may be implemented only after this
preregistration exists.
