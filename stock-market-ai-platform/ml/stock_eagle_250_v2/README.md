# StockEagle250 V2

StockEagle250 V2 is a separate risk-controlled research generation. It does not
change or revive the rejected StockEagle250 V1 candidates.

## Hypothesis

V1 established that the fixed Ridge ranker had useful cross-sectional evidence
but failed the preregistered worst-fold maximum-drawdown gate. V2 keeps that
ranking fixed and tests one new portfolio-level hypothesis: a V10-style SPY
market-state overlay may reduce left-tail risk without destroying the ranking
edge.

The V10 reference contributes its completed-session-only 20-session SPY trend,
20-session realized volatility, lagged 252-session median-volatility baseline,
four market states, all-cohort evaluation, and risk-adjusted robustness
discipline. V2 does not copy or modify V10 artifacts.

## Fixed exposure map

| Market state | Gross stock exposure | Cash |
|---|---:|---:|
| Positive trend, normal volatility | 100% | 0% |
| Positive trend, high volatility | 75% | 25% |
| Negative trend, normal volatility | 50% | 50% |
| Negative trend, high volatility | 0% | 100% |
| State inputs not ready | 0% | 100% |

There is one candidate, no model search, no threshold search, and no exposure
search. The primary cost is 10 bps per side and the stress cost is 20 bps per
side.

## Evidence boundaries

V2 may consume only saved V1 out-of-sample development predictions whose target
endpoints are no later than September 22, 2026 UTC. September 23 through
September 30 is a sealed guard band. The new untouched future boundary is
October 1, 2026 UTC.

Phase 1 validates the contract and source evidence without calculating V2
performance:

```bash
python -m unittest tests.test_stock_eagle_250_v2_phase1 -v
python -m ml.stock_eagle_250_v2.phase1
python -m json.tool data/model/stock_eagle_250_v2/phase1/manifest.json
```

Phase 1 cannot freeze a candidate, paper trade, place orders, or modify V1,
V5, V8, V10, V14, V15, or any existing forward journal.


## Phase 2 fixed development evaluation

Phase 2 applies the single preregistered exposure overlay to the saved V1 Ridge
out-of-sample portfolio periods. It reproduces the V1 10-bps results before
scoring V2, evaluates V2 at 10-bps primary and 20-bps stress costs, and reports
fold, market-state, and calendar-year diagnostics.

All eleven gates from the Phase 1 contract are required. Passing them can only
qualify the candidate for human review; it does not freeze or activate it.

```bash
python -m unittest tests.test_stock_eagle_250_v2_phase2 -v
python -m ml.stock_eagle_250_v2.phase2
python -m json.tool data/model/stock_eagle_250_v2/phase2/qualification.json
```
