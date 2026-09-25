# StockEagle250 Autonomous ML Prospective Comparison V1

This protocol compares Autonomous ML V1, V2, and V3 on genuinely unseen
October 2026+ evidence without modifying any of the three model algorithms.

It exists because repeated development changes on the same 14 folds would
increase the risk of tuning to those folds. The prospective comparison instead
freezes one final snapshot per already-defined architecture before the future
boundary and evaluates those snapshots side-by-side afterward.

## Evidence boundaries

- Development decisions end: 2026-09-15 UTC.
- Maximum development target endpoint: 2026-09-22 UTC.
- Sealed guard band: 2026-09-23 through 2026-09-30.
- First prospective decision boundary: 2026-10-01 UTC.
- The guard band is neither training nor evaluation evidence.

## Candidate snapshots

The three candidates remain exactly their existing learned architectures:

- Autonomous ML V1 — alpha + downside + absolute-profitability meta allocator.
- Autonomous ML V2 — V1 plus learned 10th-percentile tail risk.
- Autonomous ML V3 — V2 stock-level learners plus benchmark-relative meta
  allocation with residual capital in SPY.

Before October 1, one final snapshot for each architecture is fit from the
already-authorized development rows only. Snapshot creation uses each
candidate's existing Phase-1 contract and Phase-2 training implementation.
There is no feature, model-family, parameter, threshold, quantile, or
candidate search.

Snapshots are fixed during the prospective evaluation. No retraining on
prospective outcomes is allowed.

## Prospective evaluation

All three snapshots receive the same eligible decision sessions. Each uses its
already-preregistered Top-10 / next-open / fifth-close / five-sleeve policy and
its own fixed allocation logic.

The first formal human review requires at least 60 completed cohorts for every
candidate on the same decision clock. Earlier observations may be displayed as
descriptive evidence but may not select, modify, promote, or reject a model.

The review is comparative and descriptive. There is no automatic winner,
automatic promotion, live trading, or brokerage authority. A new Autonomous
ML generation must not be created from prospective results before the formal
review threshold is reached.

## Phase 1

Phase 1 validates the existing V1/V2/V3 development evidence and seals the
prospective protocol. It does not read October data and calculates no
prospective performance.

```bash
python -m unittest tests.test_stock_eagle_250_autonomous_ml_prospective_v1_phase1 -v
python -m ml.stock_eagle_250_autonomous_ml_prospective_v1.phase1
python -m json.tool data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase1/manifest.json
```

Phase 2 builds and hashes the three fixed pre-boundary snapshots. Phase 3 will
be the append-only prospective evidence runner and must fail closed before the
October 1 boundary.
