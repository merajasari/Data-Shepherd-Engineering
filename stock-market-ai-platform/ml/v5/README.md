# V5 Research Framework

V5 is an isolated research track. V4 remains the frozen benchmark/control:
V5 code must not import, retrain, overwrite, or mutate V4 models, datasets,
strategy logic, paper-trading state, journal history, or monitoring behavior.

## Experiment contract

For each rebalance date, V5 will use only information available at or before
the decision timestamp. Features describe the market through that day's close;
portfolio execution must occur at the next tradable price and apply explicit
transaction costs and slippage.

For every eligible candidate, experiments predict 5-, 10-, and 20-trading-day
future performance. The primary target at each horizon is:

```text
forward stock return - forward SPY return
```

Models rank the complete eligible universe cross-sectionally. The initial
portfolio selects the Top 5 and holds 60% SPY plus a 40% V5 sleeve, equally
weighted at 8% per selected stock. This mirrors V4's high-level capital
structure without sharing implementation or runtime state.

## Validation rules

- Never use a random train/test split for strategy validation.
- Use chronological expanding-window or rolling walk-forward evaluation.
- Purge/embargo observations where forward target windows overlap a test fold.
- Fit scalers, imputers, feature selection, and models on training data only.
- A feature must be observable by the decision timestamp; execute no earlier
  than the next tradable price.
- Keep a final untouched test period and do not repeatedly tune against it.
- Include transaction costs and slippage before evaluating strategy quality.
- Do not promote V5 from one unusually strong period.
- Report performance across bull, bear, high-volatility, and sideways regimes.
- Treat survivorship bias as a known limitation of a present-day universe;
  future research should use point-in-time membership where available.

## Required scorecard

Every experiment must report cumulative and annualized return, SPY return,
excess return over SPY, Sharpe, Sortino, maximum drawdown, volatility, hit rate,
turnover, transaction costs, number of trades, and rebalance-period count.

Compare every candidate against SPY buy-and-hold, an equal-weight universe,
a simple momentum baseline, and the frozen V4 strategy. Classification accuracy
is diagnostic only; robust out-of-sample portfolio performance is the objective.

## Data preparation

The existing Silver, Gold, and Feature pipelines discover all symbol directories
and therefore require no universe-specific copies. Only V5 Bronze ingestion is
separate. Generated data remains in the existing ignored data layers; the V5
research panel is isolated at `data/model/v5/research_panel.parquet`.

Inspect the request without downloading:

```bash
PYTHONPATH=data-ingestion python data-ingestion/tiingo_v5_ingest.py --dry-run
```

Populate all 100 candidates plus SPY (an expensive, rate-limit-sensitive job):

```bash
PYTHONPATH=data-ingestion python data-ingestion/tiingo_v5_ingest.py
PYTHONPATH=data-ingestion python data-ingestion/silver_pipeline.py
PYTHONPATH=data-ingestion python data-ingestion/gold_pipeline.py
PYTHONPATH=data-ingestion python data-ingestion/feature_pipeline.py
```

Small batches and retries are supported:

```bash
PYTHONPATH=data-ingestion python data-ingestion/tiingo_v5_ingest.py \
  --symbols AAPL MSFT NVDA SPY
```

Check local coverage, then build the first multi-horizon research panel:

```bash
python -m ml.v5.prepare_dataset --validate-only
python -m ml.v5.prepare_dataset
```

The build fails unless all 100 candidate feature datasets and SPY are present.
`--allow-partial` exists only for pipeline-development smoke tests; a partial
panel must never be used for a scored V5 experiment.

The Tiingo account's request quota and supported ticker history must be checked
before the full population run. The script reports failures and exits nonzero;
it does not retry indefinitely or run automatically from the V4 daily workflow.
