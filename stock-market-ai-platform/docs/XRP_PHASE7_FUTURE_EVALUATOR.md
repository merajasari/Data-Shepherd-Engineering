# XRP V1 Phase 7 — Untouched Future Paper Evaluator

## Purpose

Phase 7 is the future-only evaluation layer for the already-frozen XRP V1 Phase 6 candidate.

It does **not** fit a model, compare models, change thresholds, tune a policy, or place brokerage orders.

Frozen contract:

- research version: `crypto_xrp_v1`
- model: Ridge
- model artifact: `data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib`
- policy: `hyst_10_05_hold24`
- decision cadence: 4 hours
- target horizon: 4 hours BTC-relative
- initial/reset state: BTC
- minimum hold: 24 hours
- future evaluation boundary: `2026-09-01T00:00:00+00:00`
- brokerage orders: disabled

## Hard boundary

Before September 1, 2026 00:00 UTC, Phase 7 may write only operational readiness metadata:

- `evaluator_manifest.json`
- `evaluation_status.json`

It must not append any future-evaluation decision or realization event before the boundary.

The append-only journal path is:

```text
data/model/crypto_xrp_v1/phase7/forward_evaluation_events.jsonl
```

The expected pre-holdout mode is:

```text
WAITING_PRE_HOLDOUT
```

## Journal design

The JSONL event journal is the historical source of truth.

Each future decision can create exactly one immutable event:

```text
DECISION
```

A decision records, among other fields:

- decision timestamp
- target endpoint timestamp
- frozen model SHA-256
- frozen policy SHA-256
- frozen Ridge score
- state before / proposed / after
- reset status and reason
- minimum-hold blocking
- state-switch status
- continuity diagnostics
- `brokerage_orders: false`

After the exact +4 hour endpoint is genuinely available, Phase 7 appends exactly one matching:

```text
REALIZATION
```

A valid realization records:

- XRP 4-hour forward return
- BTC 4-hour forward return
- XRP-minus-BTC 4-hour return
- realized return for the frozen executed state
- state-switch cost
- cumulative paper equity
- always-XRP benchmark equity
- always-BTC benchmark equity
- always-CASH benchmark equity

If the exact four-hour XRP or BTC window is discontinuous, the evaluator appends an `INVALID_DATA_GAP` realization instead of manufacturing a return.

## Cost accounting

Phase 7 preserves the XRP V1 Phase 5 development cost convention rather than choosing a new one after the freeze.

It reports the frozen path in parallel under:

```text
0 bps
5 bps
10 bps
20 bps
```

per actual state change.

A reset does not incur a switching cost, matching Phase 5 accounting.

No one cost scenario is newly selected by Phase 7.

## Missed decisions

Phase 7 is intentionally a forward evaluator, not a backtest replay engine.

If the service misses one or more four-hour future decision intervals, it does not reconstruct and insert those missed decisions afterward. At the next genuinely observed decision it resets to BTC and records the number of missed intervals.

This prevents an operational outage from being silently rewritten as though every decision had been observed live.

## Derived files

The following files are replaceable operational/materialized views and are not the event-history source of truth:

```text
data/model/crypto_xrp_v1/phase7/evaluation_state.json
data/model/crypto_xrp_v1/phase7/evaluation_status.json
data/model/crypto_xrp_v1/phase7/forward_summary.json
data/model/crypto_xrp_v1/phase7/evaluator_manifest.json
```

The append-only event journal remains authoritative.

## Pre-holdout verification

Run:

```bash
python -m ml.crypto_xrp_v1.phase7 --once
```

Before September 1 the expected output includes:

```text
Mode:       WAITING_PRE_HOLDOUT
Status:     ok
Journal:    disabled before future boundary
Real orders: NO
```

Then verify that no event journal exists:

```bash
if [[ -e data/model/crypto_xrp_v1/phase7/forward_evaluation_events.jsonl ]]; then
  echo "ERROR: Phase 7 journal exists before future boundary"
else
  echo "PASS: no Phase 7 journal exists before future boundary"
fi
```

## Persistent service

Installer:

```text
scripts/install_xrp_phase7_evaluator_launchagent.sh
```

LaunchAgent label:

```text
com.datashepherd.xrpphase7
```

The installer runs one contract-verification cycle before loading the persistent evaluator.

Logs:

```text
~/Library/Logs/DataShepherd/xrpphase7.out.log
~/Library/Logs/DataShepherd/xrpphase7.err.log
```

## Safety statement

Phase 7 is paper evaluation only.

It does not:

- place brokerage orders
- use leverage
- short crypto
- use derivatives
- retrain Ridge
- modify the frozen thresholds
- change the 24-hour minimum hold
- modify Shared Crypto V2
- inspect or score any timestamp before the frozen future boundary
