# V14 logistic-regression paper candidate

V14 is an isolated machine-learning candidate. It does not replace or modify
the frozen V8 or V10 strategies.

## Contract

- Candidate: `v14_logistic_walk_forward_top10`
- Model: pooled NumPy logistic regression
- Target: `target_up_5d`
- Features: daily return, five- and 20-session return, price versus 20-session average, short/long volatility ratio, and volume ratio
- Training: expanding window, retrained at each eligible decision session
- Purge: five completed sessions before every decision
- Portfolio: top 10, equal weight, next-session open, five-session hold, 10-bps modeled cost
- Start: September 11, 2026 UTC
- Authority: paper only, no brokerage orders, no automatic promotion

## Run locally

From `stock-market-ai-platform`:

```bash
source .venv/bin/activate
python -m ml.v14.logistic_forward_regression
python -m ml.v14.logistic_forward
python -m ml.v14.logistic_forward_scheduled_entrypoint
python -m json.tool data/model/v14/logistic_forward/status.json
```

The runtime journal and status files are generated under
`data/model/v14/logistic_forward/`, which is intentionally excluded from Git.
Each decision records the training cutoff, row count, model hash, learned
weights, normalization statistics, predicted probabilities, and selected
symbols. The runner never reads V8/V10 outcomes to retrain or select this
candidate.
