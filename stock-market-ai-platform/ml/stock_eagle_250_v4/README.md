# StockEagle250 V4

StockEagle250 V4 is a new research generation created after V3 improved return
retention but still failed three preregistered development gates.

## Why V4 exists

V2 and V3 both tried to control portfolio risk using broad SPY market state.
V2's trend/volatility state discarded too much Ridge edge. V3's continuous SPY
volatility budget preserved much more return, but it still did not deliver the
required median drawdown improvement or retain V1's median Calmar.

V4 changes the *kind* of risk signal instead of tuning the V2/V3 market
thresholds. The stock ranking remains exactly the saved V1 Ridge ranking.
Exposure is conditioned only on the cross-sectional strength of the Ridge
predictions available at each decision time.

## One fixed confidence signal

For each saved out-of-sample decision session:

1. Sort all eligible symbols by `prediction_ridge_fixed_v1`, descending.
2. Compute the mean prediction of ranks 1-10.
3. Compute the mean prediction of ranks 11-20.
4. Selection margin = top-10 mean minus ranks-11-to-20 mean.
5. Robust scale = median absolute deviation of all eligible Ridge predictions
   from their cross-sectional median.
6. Standardized confidence = selection margin / robust scale.

The current standardized confidence is then compared only with the prior 252
completed out-of-sample decision sessions, excluding the current session.
At least 60 prior sessions are required for the empirical percentile.

The one fixed exposure rule is:

```text
if confidence history is not ready or confidence is invalid:
    gross stock exposure = 50%
else:
    confidence_percentile = fraction of prior confidence values <= current
    gross stock exposure = 50% + 50% * confidence_percentile
```

So valid exposure is continuously between 50% and 100%. There is no SPY trend
or SPY volatility input, no leverage, and no parameter search.

The 50% floor and the continuous percentile rule are fixed before any V4
performance is calculated. They may not be changed after Phase 2 results.

## Evidence boundaries

- Development target endpoints remain capped at September 22, 2026 UTC.
- September 23 through September 30 remains a sealed guard band.
- October 1, 2026 remains the untouched future boundary.
- Phase 1 does not calculate V4 performance.
- No V1, V2, V3, V5, V8, V10, V14, V15, or forward journal is modified.
- Paper trading, freezing, automatic promotion, and brokerage remain disabled.

## Phase 1

```bash
python -m unittest tests.test_stock_eagle_250_v4_phase1 -v
python -m ml.stock_eagle_250_v4.phase1
python -m json.tool data/model/stock_eagle_250_v4/phase1/manifest.json
```

Phase 2 may be implemented only after this preregistration exists.
