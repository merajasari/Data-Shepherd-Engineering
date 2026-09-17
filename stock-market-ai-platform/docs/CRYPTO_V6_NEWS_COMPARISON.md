# Crypto V6 news comparison

Crypto V6 is a research challenger to Crypto V5. It adds only point-in-time
news features; it does not change the V5 market data, targets, folds, models,
horizons, portfolio rules, or cost assumptions.

## Safety boundary

- News is eligible only when `available_at_utc <= decision timestamp`.
- All V5 and V6 training and comparison rows precede the frozen future holdout.
- V5 inputs are hash-checked and never modified.
- V5 and V6 predictions must have identical timestamps and fold membership.
- No paper state, dashboard model, or brokerage path is changed.
- No result can automatically promote or validate V6.

## Run order

```bash
python -m ml.news_intelligence.gdelt_consolidate

python -m ml.crypto_v6.phase1 \
  --news data/research/news/gdelt/canonical/canonical_news.parquet

python -m ml.crypto_v6.phase2

python -m ml.crypto_v6.phase3
```

The consolidation stage retains the monthly Parquet partitions and also writes
`canonical_news.parquet`, with normalized-URL deduplication across months. The
earliest GDELT observation wins; later re-observations never rewrite history.

Phase 1 creates market-wide news features for the allocation layer and
asset-specific news features for the ranking layer. Decisions with no eligible
news receive zeros, so the original V5 market universe remains unchanged. The
novelty calculation uses at most the 256 most recent eligible prior articles,
which keeps the ten-year build bounded while remaining deterministic and causal.

Phase 2 trains both feature sets in the same run:

- `v5_market_only`
- `v6_market_news`

Phase 3 applies the V5 portfolio simulator and costs to both prediction sets.
The final `v6_vs_v5_comparison.json` checks primary-cost return, Sharpe,
drawdown, and 50-bps stress performance. A passing report remains
`NOT_VALIDATED_REQUIRES_HUMAN_REVIEW`.

## Reusable stock or crypto joins

The provider-neutral join command accepts either stock or crypto decision data.
The canonical news `asset_ids` must use the same symbol convention as the
decision file. For example:

```bash
python -m ml.news_intelligence.point_in_time_join \
  --news data/research/news/canonical_stock_news.parquet \
  --decisions data/research/stock_decisions.parquet \
  --asset-column symbol \
  --prefix stock_news_ \
  --output data/research/stock_decisions_with_news.parquet
```

The present GDELT acquisition contract tags crypto assets. A stock join should
therefore use a stock-tagged canonical news archive, not relabel crypto news.

## Verification

```bash
python -m py_compile \
  ml/news_intelligence/gdelt_consolidate.py \
  ml/news_intelligence/vector_features.py \
  ml/news_intelligence/point_in_time_join.py \
  ml/crypto_v6/phase1.py \
  ml/crypto_v6/phase2.py \
  ml/crypto_v6/phase3.py

python -m unittest \
  tests.test_news_gdelt_consolidate \
  tests.test_news_gdelt_consolidate_v2 \
  tests.test_news_intelligence \
  tests.test_crypto_v6_news_pipeline -v
```

After Phase 3, review:

```bash
python -m json.tool \
  data/research/crypto_ten_year/reconstruction/crypto_v6/phase3/v6_vs_v5_comparison.json

python -m json.tool \
  data/research/crypto_ten_year/reconstruction/crypto_v6/phase3/manifest.json
```
