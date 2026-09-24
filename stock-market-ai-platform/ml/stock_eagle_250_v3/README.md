# StockEagle250 V3

StockEagle250 V3 is a new research generation created after the V2 fixed
SPY-trend regime overlay failed its preregistered development gates.

## Why V3 exists

V2 showed that portfolio-level risk control can materially reduce left-tail
drawdown, but its trend-conditioned exposure map sacrificed too much return.
Most notably, the V2 NEGATIVE_HIGH_VOL state moved to 100% cash even though the
saved pre-guard V1 Ridge portfolio returns were positive on average in that
state.

V3 therefore keeps the exact V1 Ridge cross-sectional ranking and removes SPY
trend direction from the risk-control rule. It tests one fixed, continuous
volatility-budget hypothesis:

> Preserve full stock exposure when completed-session 20-day SPY realized
> volatility is at or below its lagged 252-session median baseline. When
> volatility is above the baseline, scale gross stock exposure by
> baseline_volatility / current_volatility.

The result is always in [0, 1], never uses leverage, and remains strictly
positive whenever both volatility inputs are valid and positive. If the inputs
are not ready, V3 fails closed to cash.

## Fixed candidate

- Candidate: `ridge_v1_rank_volatility_budget_v3`
- Ranking source: unchanged `ridge_fixed_v1`
- SPY trend direction: not used
- Volatility lookback: 20 completed sessions
- Baseline: lagged rolling median of 20-session volatility over 252 sessions
- Baseline minimum history: 60 sessions
- Primary cost: 10 bps per side
- Stress cost: 20 bps per side
- Positions per cohort: 10
- Overlapping cohorts: 5
- No leverage, no shorting, no derivatives

There is one candidate. No threshold, exposure, model, or hyperparameter search
is permitted.

## Evidence boundaries

The V3 development source is still capped at the same saved V1 development
evidence whose target endpoints are no later than September 22, 2026 UTC.

- September 23 through September 30 remains a sealed guard band.
- October 1, 2026 remains the untouched future boundary.
- V3 Phase 1 does not calculate V3 performance.
- V3 Phase 1 does not read the guard band or future sample.
- V3 does not modify V1, V2, V5, V8, V10, V14, V15, or forward journals.

## Phase 1

Phase 1 validates the preserved V2 rejection evidence and preregisters the one
fixed V3 volatility-budget candidate before any V3 performance is calculated.

```bash
python -m unittest tests.test_stock_eagle_250_v3_phase1 -v
python -m ml.stock_eagle_250_v3.phase1
python -m json.tool data/model/stock_eagle_250_v3/phase1/manifest.json
```

The Phase 2 evaluation must be implemented only after this contract exists.
