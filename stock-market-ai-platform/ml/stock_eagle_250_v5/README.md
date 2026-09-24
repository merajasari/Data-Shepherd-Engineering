# StockEagle250 V5

StockEagle250 V5 is a final fixed risk-control research generation built after
V2, V3, and V4 all failed the unchanged development qualification gates.

## Why V5 exists

V4 showed that cross-sectional Ridge confidence improved fold consistency versus
SPY and improved drawdown in every fold, but it still sacrificed too much median
return versus V1 Ridge and did not reach the required median drawdown
improvement or median Calmar gate.

V5 changes the risk signal again instead of tuning any V2/V3/V4 threshold. It
keeps the exact V1 Ridge ranking and uses only the strategy's own previously
completed V1-equivalent cohort outcomes to measure drawdown.

This is intentionally the final fixed hypothesis on this development sample.
If V5 fails the unchanged gates, the research should stop rather than create
another tuned development generation.

## Fixed self-drawdown throttle

Within each development fold, maintain a five-sleeve, full-exposure V1 Ridge
shadow account at the primary 10-bps-per-side cost. The shadow account is a
risk-state reference only; V5 does not modify V1.

At each decision timestamp:

1. Start from a $100,000 shadow account split equally across five sleeves.
2. Apply only prior cohorts whose target endpoint is strictly earlier than the
   current decision timestamp.
3. A cohort is applied to the sleeve assigned by its original decision-order
   index modulo five.
4. Measure current shadow-account drawdown from its prior completed-equity peak.
5. Set V5 gross stock exposure from that drawdown using one fixed linear rule:

```text
drawdown = shadow_equity / shadow_peak - 1

gross_exposure =
    clip(1.0 - 2.5 * abs(drawdown), 0.50, 1.00)
```

Examples:

- 0% drawdown -> 100% stocks
- -5% drawdown -> 87.5% stocks
- -10% drawdown -> 75% stocks
- -15% drawdown -> 62.5% stocks
- -20% or worse -> 50% stocks

The strict-completion rule `target_endpoint < decision_timestamp` prevents the
current decision from seeing same-session or future cohort outcomes.

The throttle references the full-exposure V1 shadow account rather than V5's
own throttled account, so the signal is fixed and comparable across primary and
stress-cost evaluations.

## Fixed research constraints

- Ranking source remains `ridge_fixed_v1`.
- Top 10 stocks, equal weight within invested exposure.
- Five overlapping cohorts.
- Primary cost: 10 bps per side.
- Stress cost: 20 bps per side.
- Exposure range: 50% to 100%.
- No SPY trend or volatility input.
- No prediction-confidence input.
- No leverage, shorting, derivatives, model search, threshold search,
  hyperparameter search, or exposure search.
- The exact same eleven V2/V3/V4 development gates are reused without
  relaxation.

## Evidence boundaries

- Development target endpoints remain capped at September 22, 2026 UTC.
- September 23 through September 30 remains a sealed guard band.
- October 1, 2026 remains the untouched future boundary.
- Phase 1 does not calculate V5 performance.
- No existing model artifact or forward journal is modified.
- Paper trading, freezing, automatic promotion, and brokerage remain disabled.

## Phase 1

```bash
python -m unittest tests.test_stock_eagle_250_v5_phase1 -v
python -m ml.stock_eagle_250_v5.phase1
python -m json.tool data/model/stock_eagle_250_v5/phase1/manifest.json
```

Phase 2 may be implemented only after this preregistration exists.
