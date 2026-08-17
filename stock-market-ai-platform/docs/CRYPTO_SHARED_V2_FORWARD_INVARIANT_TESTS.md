# Shared Crypto V2 Forward Invariant Tests

## Purpose

This test suite protects the frozen Shared Crypto V2 forward-evaluation service before the untouched future boundary at `2026-09-01T00:00:00+00:00`.

The tests are operational/regression safeguards only. They do not fit models, tune thresholds, change the frozen `confirm_2` policy, inspect future holdout outcomes, or place brokerage orders.

## Test file

```text
tests/test_crypto_15m_v2_forward_service.py
```

Run with:

```bash
python -m unittest tests.test_crypto_15m_v2_forward_service -v
```

## Protected invariants

The suite locks down the following behaviors:

1. `confirm_2` requires two consecutive predictions away from the current executed sleeve before switching.
2. A prediction that returns to the current sleeve clears any pending confirmation candidate.
3. A decision timestamp already present in the forward journal cannot be appended again.
4. An older timestamp cannot be inserted into the journal after a newer decision.
5. The first confirmation hour remains in the existing sleeve; only the second matching confirmation may switch.
6. Hourly realization uses the exact `decision_timestamp + 1h` endpoint.
7. Missing exact endpoint candles are not synthesized, interpolated, or forward-filled.
8. A realization is unavailable unless the frozen minimum number of ALT assets has both exact endpoint candles.
9. The frozen 5 bps transaction cost is charged only when `sleeve_switch == 1`.
10. Finalizing an already-realized row is idempotent and cannot compound performance twice.
11. Pre-holdout shadow runs cannot append to the forward journal or advance `confirm_2` execution state.
12. A missed future decision hour produces `gap_detected_no_backfill`; the missing hour is never inserted later.
13. Re-running the same future hour after process restart remains `already_processed` and cannot duplicate a journal row.

## Filesystem isolation

Every test redirects these module paths to a temporary directory:

```text
PHASE5_ROOT
JOURNAL_PATH
STATE_PATH
SHADOW_PATH
SERVICE_STATUS_PATH
LOCK_PATH
```

The suite must never write to:

```text
data/model/crypto_15m_v2/phase5/frozen_hgb.joblib
data/model/crypto_15m_v2/phase5/freeze_manifest.json
data/model/crypto_15m_v2/phase5/forward_state.json
data/model/crypto_15m_v2/phase5/forward_journal.csv
data/model/crypto_15m_v2/phase5/shadow_latest.json
data/model/crypto_15m_v2/phase5/forward_service_status.json
```

The frozen model and manifest are not needed by the unit tests. Contract/model loading is mocked where an end-to-end service cycle is being exercised.

## Shared V2 versus XRP Phase 7

Shared V2 and XRP Phase 7 intentionally have different persistence contracts.

XRP Phase 7 uses an append-only JSONL event journal as authoritative state after a crash. Shared V2 uses a CSV decision/realization journal together with a mutable operational state JSON. Therefore these Shared V2 tests protect the restart/idempotency guarantees actually implemented by Shared V2—especially duplicate-hour suppression and no backfill—rather than claiming XRP-style journal state reconstruction.

## Transaction-cost invariant

For a realized Shared V2 row:

```text
cost_rate = sleeve_switch * 5 / 10,000
net_return = (1 + gross_return) * (1 - cost_rate) - 1
```

Therefore:

- no state change => zero transaction cost;
- actual sleeve switch => exactly 5 bps in the frozen accounting convention.

A raw prediction change by itself does not create a transaction cost. A cost exists only when frozen `confirm_2` changes the executed sleeve.

## Holdout safety

Before September 1, Shared V2 remains in `SHADOW` mode. A shadow cycle may refresh operational metadata and the separate shadow snapshot, but it must not:

- append a forward decision,
- modify a forward realization,
- advance the executed sleeve,
- advance pending confirmation state,
- create a paper performance observation.

## No missed-hour backfill

If the latest genuine observed future decision is more than one hour after the latest journal decision, the service must return:

```text
gap_detected_no_backfill
```

and must not synthesize or insert the missing historical decision hour. This keeps the future journal aligned to what the live service genuinely observed.

## Scope

These tests establish software invariants. Passing them does not establish investment performance, statistical validity, or promotion eligibility. Untouched future performance remains governed by the September 1 forward-evaluation boundary and the fixed future-sample assessment shown on the dashboard.
