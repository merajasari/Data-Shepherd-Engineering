# StockEagle250 Autonomous ML V3

Autonomous ML V3 is a new learned generation created after Autonomous ML V2
passed eight of nine unchanged development gates but failed the
positive-excess-versus-SPY fold-consistency gate.

V2 remains preserved as rejected evidence. V3 does not relax the 60% SPY
consistency requirement and does not weaken the -30% maximum-drawdown gate.

## Fixed learned architecture

V3 keeps the same four learned components as V2:

1. **Alpha model** — predicts five-session stock return relative to SPY.
2. **Downside model** — predicts probability of a negative five-session
   absolute stock return.
3. **Tail model** — predicts the conditional 10th-percentile five-session
   absolute stock return.
4. **Benchmark-relative meta allocator** — predicts whether the learned
   tail-aware Top-10 cohort will outperform SPY over the same five-session
   horizon.

The only intentional scientific change from V2 is the allocator objective and
the residual allocation. V3 does not change the stock-level model families,
features, hyperparameters, tail quantile, Top-10 selection rule, or tail-aware
stock-weighting formula.

## Benchmark-relative learned allocation

For each inner-OOS session, the meta label is:

```text
1 if tail-aware Top-10 net return after 10 bps/side > SPY return
0 otherwise
```

The future SPY return is used only to construct a matured training label. It is
never an inference feature.

At inference time:

```text
p_active = P(Top-10 beats SPY)

active Top-10 weight = p_active
SPY weight           = 1 - p_active
cash weight          = 0
```

The active Top-10 sleeve continues to use the fixed V2 learned stock-weighting
formula:

```text
score =
    exp(
        cross_sectional_zscore(alpha_prediction)
        - downside_probability
        + cross_sectional_zscore(tail10_prediction)
    )
```

The full cohort remains non-leveraged and 100% invested between the learned
active sleeve and SPY. Transaction costs are applied to the full cohort capital
at the preregistered primary/stress rates, which is conservative for the SPY
fallback allocation.

There is no bull/bear rule, no manual SPY threshold, no cash-exposure floor,
no drawdown throttle, and no post-result parameter tuning.

## Scientific isolation

- V1 and V2 Autonomous ML evidence remains read-only.
- The same original StockEagle250 14 purged development folds are reused.
- The same nine Autonomous ML development gates are reused without relaxation.
- September 23-30, 2026 remains sealed.
- October 1+ remains untouched.
- Phase 1 calculates no V3 performance.
- No autonomous paper runtime or live execution is enabled by Phase 1.

## Phase 1

```bash
python -m unittest tests.test_stock_eagle_250_autonomous_ml_v3_phase1 -v
python -m ml.stock_eagle_250_autonomous_ml_v3.phase1
python -m json.tool data/model/stock_eagle_250_autonomous_ml_v3/phase1/manifest.json
```

Phase 2 may be implemented only after this preregistration exists.
