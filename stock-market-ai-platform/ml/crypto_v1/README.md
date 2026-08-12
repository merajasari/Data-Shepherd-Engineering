# Crypto V1 Research Foundation

Crypto V1 is isolated from Stock V4, Stock V5, and the production dashboard.
Phase 1 provides a provider-neutral historical candle boundary, a Coinbase
adapter, Bronze ingestion, versioned research contracts, and storage paths.
Phase 2 adds strict Bronze validation and leakage-safe daily research datasets;
it does not train a model or execute trades.

## Architecture

```text
MarketDataProvider
  -> CoinbaseExchangeProvider (initial adapter)
  -> data/bronze/crypto/{provider}/{granularity}/{pair}/
  -> data/silver/crypto/       canonical cleaned OHLCV (Phase 2)
  -> data/gold/crypto/         aligned eligible cross-sectional panel (Phase 2)
  -> data/features/crypto/     point-in-time features and targets (Phase 2)
  -> data/model/crypto_v1/     models, rankings, scorecards (Phase 2)
  -> RankingConsumer           backtest and future paper simulator
```

Generated data directories are ignored by Git and are created by their writer.
No component imports or writes Stock V4/V5 paths.

## Point-in-time eligibility

Universe membership is only a candidate list. For every date, exclude a pair
until its observed first candle plus the configured minimum history, and require
trailing (not forward-filled or future) dollar-volume history. A current listing
must never be backfilled into dates before Coinbase data actually exists.
Missing Coinbase intervals remain missing; do not synthesize zero-volume bars.

## Feature and target roadmap

Targets are 1/3/7-day forward asset returns, matching BTC forward returns,
asset-minus-BTC relative returns, and within-date percentile/rank labels.
Features include 1/3/7/14/30-day momentum, realized volatility, volume change,
moving-average distance, drawdown, BTC trend/regime, asset/BTC correlation, and
relative strength. Funding, open interest, basis, and perpetual-market signals
require future provider interfaces because spot OHLCV cannot supply them.

All features are timestamped at the completed candle and shifted when execution
timing requires it. Validation is chronological walk-forward with an untouched
final holdout. Portfolio evaluation includes fees, slippage, and turnover; uses
Top 3/Top 5 equal weights; prohibits leverage; and benchmarks BTC buy-and-hold.

## Commands

Validate a request without networking:

```bash
python -m ml.crypto_v1.ingest --start 2020-01-01 --end 2026-01-01 --dry-run
```

Ingest the full daily universe (end is exclusive):

```bash
python -m ml.crypto_v1.ingest --start 2020-01-01 --end 2026-01-01
```

Prepare all Phase 2 datasets after ingestion:

```bash
python -m ml.crypto_v1.prepare_dataset
```

Ingest a small daily subset or an hourly development sample:

```bash
python -m ml.crypto_v1.ingest --start 2020-01-01 --end 2026-01-01 --products BTC-USD ETH-USD
python -m ml.crypto_v1.ingest --start 2026-01-01 --end 2026-01-08 --granularity hourly --products BTC-USD
```

Coinbase Exchange caps a response at 300 candles. The adapter requests at most
299 buckets per call, traverses the requested half-open interval, filters any
out-of-range response rows, and deduplicates boundaries. Coinbase warns that
historical candles can be incomplete when no trades occurred and should not be
polled frequently. This adapter is research-only and contains no order methods.
