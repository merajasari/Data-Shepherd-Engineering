# Crypto Pre-Holdout Readiness Audit

The pre-holdout readiness audit is the final safety check for the frozen Shared Crypto 15m V2 and XRP V1 Phase 7 paper-evaluation paths before the untouched future boundary:

```text
2026-09-01T00:00:00+00:00
```

Run it from the project root:

```bash
python -m ml.crypto_pre_holdout_readiness
```

The command exits with:

```text
0  READY_FOR_FORWARD_EVALUATION
1  NOT_READY_FOR_FORWARD_EVALUATION
```

A nonzero result is intentional. Any failed safety condition blocks readiness until the cause is understood and corrected.

## What the audit does not do

The audit does not:

- fit or refit any model
- change any feature set
- change any threshold or policy
- advance a policy state
- append a Shared V2 forward decision
- append an XRP Phase 7 decision or realization
- inspect future performance
- place brokerage orders
- enable leverage, shorting, or derivatives

The only temporary writes are small filesystem probes used to confirm that the existing output directories are writable. Each probe is deleted immediately.

## Reconciliation checks

The audit verifies:

- `data/live/crypto_rt/reconcile_status.json` exists and is readable
- runtime status is successful
- heartbeat is no older than 45 minutes
- the reconciliation service reports at least 25 products
- the `com.datashepherd.cryptoreconcile` LaunchAgent is loaded and running on macOS

## Shared Crypto 15m V2 checks

Frozen files:

```text
data/model/crypto_15m_v2/phase5/frozen_hgb.joblib
data/model/crypto_15m_v2/phase5/freeze_manifest.json
data/model/crypto_15m_v2/phase5/forward_state.json
data/model/crypto_15m_v2/phase5/forward_journal.csv
data/model/crypto_15m_v2/phase5/forward_service_status.json
```

The audit verifies:

- every required file exists
- the actual HGB artifact SHA-256 matches the frozen manifest
- policy is exactly `confirm_2`
- confirmation requirement is exactly two hourly decisions
- decision frequency remains one hour
- future boundary is exactly Sep. 1, 2026 00:00 UTC
- brokerage order placement remains prohibited in the frozen contract
- runtime `brokerage_orders` remains `false`
- service status is successful
- heartbeat is no older than 90 minutes
- before Sep. 1, the forward journal still contains zero data rows
- before Sep. 1, runtime mode remains `SHADOW`
- operational state has the same Sep. 1 boundary
- Phase 5 output directory passes a temporary write/delete probe
- `com.datashepherd.cryptov2forward` is loaded and running on macOS

## XRP V1 Phase 6 + Phase 7 checks

Frozen Phase 6 files:

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
data/model/crypto_xrp_v1/phase6/freeze_manifest.json
data/model/crypto_xrp_v1/phase6/forward_state.json
data/model/crypto_xrp_v1/phase6/forward_service_status.json
```

Phase 7 files:

```text
data/model/crypto_xrp_v1/phase7/evaluator_manifest.json
data/model/crypto_xrp_v1/phase7/evaluation_status.json
```

The audit verifies:

- the actual frozen Ridge SHA-256 matches Phase 6
- Phase 6 policy remains exactly `hyst_10_05_hold24`
- 4-hour cadence remains frozen
- entry thresholds remain +0.001 / -0.001
- exit thresholds remain +0.0005 / -0.0005
- minimum hold remains 24 hours
- Phase 6, Phase 7, and Phase 7 runtime status all agree on the Sep. 1 boundary
- Phase 7 pins the exact Phase 6 manifest SHA-256
- Phase 7 pins the exact frozen Ridge SHA-256
- Phase 7 pins the canonical frozen policy SHA-256
- brokerage orders are disabled in Phase 6, Phase 7, and both runtime statuses
- Phase 7 has no model/policy selection or tuning
- missed decisions cannot be backfilled
- pre-holdout journal writes are prohibited
- both Phase 6 and Phase 7 runtime model/policy verification pass
- Phase 6 and Phase 7 heartbeats are no older than 90 minutes
- before Sep. 1, Phase 7 journal does not exist
- before Sep. 1, Phase 7 mode remains `WAITING_PRE_HOLDOUT`
- before Sep. 1, Phase 6 remains `SHADOW_PRE_HOLDOUT`
- Phase 7 output directory passes a temporary write/delete probe
- `com.datashepherd.xrpforward` and `com.datashepherd.xrpphase7` are loaded and running on macOS

## Readiness meaning

`READY_FOR_FORWARD_EVALUATION` means all audited prerequisites pass at the moment the command runs. It is not a performance forecast and it does not promote either candidate to real trading.

It means only that the frozen paper-evaluation machinery is internally consistent, fresh, writable, boundary-safe, and still incapable of placing real brokerage orders.

Because service freshness can change, run the audit again near the Sep. 1 boundary and whenever a service, model artifact, manifest, journal, or LaunchAgent changes.
