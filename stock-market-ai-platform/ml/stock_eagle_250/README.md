# StockEagle250

StockEagle250 is an isolated next-generation learned stock-model research lane
for the configured 250-stock candidate universe. SPY is benchmark context only.

## Current status

Phase 1 is a foundation and readiness audit. It verifies:

- exactly 250 unique candidate stocks plus benchmark-only SPY;
- preservation of the original frozen 100-stock universe as a subset;
- availability and readability of all 251 historical feature datasets;
- per-symbol eligibility after 252 observed sessions;
- duplicate-timestamp absence; and
- zero authority to paper trade, place orders, or modify V5, V8, V10, V14, or V15.

Phase 1 does not select features, targets, a model family, costs, a holding
period, or a future holdout boundary. Those decisions must be preregistered
before scored development begins.

## Historical backfill

The backfill entry point is restricted to the 150 additions. It skips complete
feature datasets, reuses existing Bronze history, limits new Tiingo requests,
and processes only those additions through Silver, Gold, and Features.

```bash
python -m ml.stock_eagle_250.backfill --dry-run
python -m ml.stock_eagle_250.backfill --max-requests 45
```

Rerun the second command as needed. It is resume-safe. A higher explicit request
cap may be used only when the configured Tiingo plan supports it.

## Readiness audit

```bash
python -m unittest \
  tests.test_stock_eagle_250_backfill \
  tests.test_stock_eagle_250_phase1 \
  -v

python -m ml.stock_eagle_250.phase1
python -m json.tool data/model/stock_eagle_250/phase1/manifest.json
```

Use Phase 1 `--strict` only when the command should return a failure status if
any historical feature file is missing, unreadable, or contains duplicate
timestamps.

## Phase 2 research panel

Phase 2 freezes the development design before any model is fit. It builds:

- next-session-open through fifth-session-close returns relative to SPY;
- same-timestamp cross-sectional percentile-rank features;
- 252-session point-in-time eligibility;
- six-month expanding walk-forward folds with exact endpoint purging; and
- a development-only panel that cannot include decisions or outcomes from the
  untouched future holdout beginning September 23, 2026 UTC.

The only preregistered learned candidates for the next phase are fixed Ridge
regression and fixed histogram gradient boosting. Phase 2 does not fit them.

```bash
python -m unittest tests.test_stock_eagle_250_phase2 -v
python -m ml.stock_eagle_250.phase2
python -m json.tool data/model/stock_eagle_250/phase2/manifest.json
python -m json.tool data/model/stock_eagle_250/phase2/folds.json
```


## Guarded final pre-holdout refresh

Before fitting either registered candidate, run the one-time incremental refresh
through the final permitted pre-holdout session. The workflow is fixed to
September 22, 2026 and refuses any request for September 23 or later. It covers
all 250 candidates plus benchmark-only SPY, merges overlapping Tiingo rows into
the existing Bronze histories, rebuilds Silver/Gold/Features, and fails closed
unless all 251 feature files reach the cutoff.

It does not fit or score models, enable paper trading, place orders, modify saved
model artifacts, or read/write existing forward journals.

```bash
python -m unittest tests.test_stock_eagle_250_pre_holdout_refresh -v

python -m ml.stock_eagle_250.pre_holdout_refresh --dry-run

python -m ml.stock_eagle_250.pre_holdout_refresh \
  --end-date 2026-09-22 \
  --max-requests 251

python -m ml.stock_eagle_250.phase1 --strict
python -m ml.stock_eagle_250.phase2
```

Do not proceed to Phase 3 unless the refresh reports
`Ready for Phase 2 rebuild: True`, the Phase 2 manifest reports
`future_holdout_rows_read: 0`, and its maximum development target endpoint
remains strictly earlier than September 23, 2026 UTC.
