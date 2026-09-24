# StockEagle250 Autonomous ML V1

This is a new StockEagle250 model family. It is not V6 and it does not modify
the V1-V5 research generations.

The goal is an autonomous learned paper-trading system rather than another
hand-authored market-state, volatility, confidence, or drawdown overlay.

## Learned architecture

The fixed architecture contains three learned components:

1. **Alpha model** — Histogram Gradient Boosting regression predicts each
   stock's executable five-session return relative to SPY.
2. **Downside model** — Histogram Gradient Boosting classification predicts the
   probability that the stock loses money over that same horizon.
3. **Meta allocator** — Histogram Gradient Boosting classification predicts
   whether the alpha-selected Top-10 cohort will produce a positive net return
   after the fixed transaction-cost assumption.

All three components learn from matured labels only. The meta allocator may be
trained only from inner walk-forward out-of-sample alpha/downside predictions,
never from in-sample fitted predictions.

The allocator probability becomes requested gross exposure within the
non-leveraged safety range 0 to 100 percent. Top-10 position sizes are driven by
learned alpha and downside outputs under one fixed normalization rule.

## Autonomous paper lifecycle

The intended forward-paper service will automatically:

- refresh point-in-time features;
- detect newly matured five-session labels;
- retrain the fixed learner stack without parameter search;
- hash and persist each model snapshot;
- score the current Stock250 universe;
- create learned Top-10 positions, weights, and total exposure;
- manage scheduled paper entries and exits;
- journal decisions, training cutoffs, source hashes, entries, and exits;
- fail closed on incomplete or stale data;
- never backfill a missed decision as if it occurred live.

This lane is paper-only. Connecting it to real-money execution is outside this
research lane and is not enabled here.

## Evidence boundary

The lane reuses the original StockEagle250 point-in-time development panel and
14 purged walk-forward folds.

- September 23 through September 30, 2026 remains sealed.
- October 1, 2026 remains the untouched future boundary.
- V1-V5 artifacts remain preserved.
- V5 Phase 2 is not consumed by this model family.
- Phase 1 calculates no model performance.

## Phase 1

```bash
python -m unittest tests.test_stock_eagle_250_autonomous_ml_v1_phase1 -v
python -m ml.stock_eagle_250_autonomous_ml_v1.phase1
python -m json.tool data/model/stock_eagle_250_autonomous_ml_v1/phase1/manifest.json
```

Phase 2 will implement the preregistered nested walk-forward development
evaluation. Hyperparameters, targets, features, and portfolio mapping may not be
changed after Phase 1 results are written.
