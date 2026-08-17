# XRP V1 Phase 7 — Invariant Test Contract

## Purpose

This document defines the non-negotiable safety and accounting invariants for
`ml/crypto_xrp_v1/phase7.py`, the untouched future XRP paper evaluator.

The tests are intentionally about evaluator correctness, not model quality.
They do not fit models, tune thresholds, inspect future holdout performance, or
place brokerage orders.

## Test file

```text
tests/test_crypto_xrp_v1_phase7.py
```

The suite uses temporary directories and mocked market-data functions. It must
never write to the live Phase 7 paths under:

```text
data/model/crypto_xrp_v1/phase7/
```

## Locked invariants

### 1. No pre-holdout events

`_append_event()` must reject any decision timestamp before:

```text
2026-09-01T00:00:00+00:00
```

A failed pre-holdout append must not create a journal file.

### 2. Append-only uniqueness

Duplicate `event_id` values in the JSONL event journal are invalid and must be
rejected when the journal is loaded.

A future restart must never create a second realization for a decision that
already has a realization event.

### 3. First-future-decision reset

The first genuinely observed future decision resets to the frozen initial state:

```text
BTC
```

This is a reset, not a charged state switch.

### 4. No missed-decision backfill

If the evaluator misses one or more frozen 4-hour decision intervals, it must
not synthesize those decisions later. The next genuinely observed decision
resets to BTC and records how many decision intervals were missed.

### 5. Continuity breaks reset safely

An XRP continuity break between consecutive decision timestamps must force a
neutral BTC reset rather than carrying state across the gap.

### 6. Append-only journal is restart authority

If replaceable `evaluation_state.json` disagrees with the append-only decision
journal after a restart or crash, the journal-derived state wins.

### 7. Exact +4h realization endpoint

A Phase 7 realization is tied to:

```text
target_endpoint = decision_timestamp + 4 hours
```

The XRP and BTC windows must contain every 15-minute candle from the decision
timestamp through that exact endpoint, inclusive.

### 8. Data gaps are never scored

If either the XRP or BTC four-hour window is not contiguous, Phase 7 records an
`INVALID_DATA_GAP` realization. It must not attach candidate equity, gross
return, or performance scoring to that interval.

The invalid realization remains an immutable observation and is not retried or
replaced later.

### 9. Costs apply only to real state changes

The frozen Phase 7 cost scenarios are:

```text
0 bps
5 bps
10 bps
20 bps
```

A cost is subtracted only when `state_switch == true`.

Resets and unchanged states do not receive a switching cost.

### 10. Parallel accounting remains deterministic

For a valid realization, each frozen cost scenario must use the same gross
state return and differ only by its applicable switch cost.

Always-XRP and always-BTC benchmark equity must be based on the same valid
realization intervals.

### 11. Summary accounting stays internally consistent

`forward_summary.json` derivation must distinguish:

- total decisions,
- valid realizations,
- invalid data-gap realizations,
- pending realizations,
- actual state switches.

Brokerage orders must remain `false` in the derived summary.

## Running the tests

From `stock-market-ai-platform`:

```bash
python -m unittest tests.test_crypto_xrp_v1_phase7 -v
```

A successful run should report all tests as `ok` and finish with:

```text
OK
```

## Safety interpretation

Passing these tests means the evaluator's tested invariants hold under the
isolated scenarios covered by the suite. It is not evidence of future trading
performance and does not promote XRP V1 for real trading.

The frozen model, frozen execution policy, future boundary, and no-real-orders
contract remain unchanged.
