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


## Phase 3: fixed-snapshot prospective journal

Phase 3 binds the exact three snapshot SHA-256 values produced by Phase 2:

```text
V1  4e2b88904f4c17d7df0552559191bf18735ddc5611ee6550731be108f5281932
V2  d2c1754a54074958567a18c6c2d45bb21d6a0d000ed6bf3d679f8f945766fca5
V3  aeecdb9f82082163f65ce6b3bb2645472529faa2507a4e0daa34d5802e6b80de
```

The runner uses a single append-only JSONL journal for all three candidates.
Each decision is one `DECISION_BATCH`, so V1/V2/V3 always share the exact same
prospective decision timestamp. Mechanical lifecycle events are likewise stored
as `ENTRY_BATCH` and `EXIT_BATCH`.

A decision can be created only on the same New York calendar date as the
completed source session and only after 16:05 ET. If that decision opportunity
is missed, it is reported as missed and is never reconstructed later.

The forward clock remains exactly the development clock:

- decision from completed daily features;
- entry at the next completed session open;
- exit at the fifth completed session close after the decision;
- five overlapping cohort sleeves;
- 10 bps/side primary and 20 bps/side stress accounting;
- V1/V2 residual capital remains cash;
- V3 residual capital remains SPY.

Before October 1 the runner can be installed safely: it validates the fixed
snapshot hashes and reports `WAITING_FOR_PROSPECTIVE_BOUNDARY` without
reading prospective market sessions or writing decisions.

Run the Phase 3 unit tests and one pre-boundary verification:

```bash
python -m unittest tests.test_stock_eagle_250_autonomous_ml_prospective_v1_phase3 -v
python -m ml.stock_eagle_250_autonomous_ml_prospective_v1.phase3
```

Install the 15-minute fail-closed collector:

```bash
zsh scripts/mac/install_stock_eagle_autonomous_ml_prospective.sh
```

Runtime evidence is written only under:

```text
data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase3/
  journal.jsonl
  status.json
```

The runner never retrains or replaces the fixed snapshots, never alters V1,
V2, V3, or another model's journal, never automatically chooses a winner, and
never places brokerage orders.
