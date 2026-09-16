# Crypto Operational Health Monitoring

This document defines the read-only service-health panel on the Data Shepherd Engineering crypto dashboard.

## Scope

The health layer monitors runtime freshness only. It does **not** fit models, change thresholds, alter execution policies, write brokerage orders, or modify either frozen forward contract.

Monitored components:

1. authoritative Coinbase 15-minute reconciliation
2. frozen Shared Crypto 15m V2 forward service
3. frozen XRP V1 Phase 6 shadow-forward service
4. XRP V1 Phase 7 future evaluator
5. web dashboard request path

## Health states

```text
HEALTHY
STALE
ERROR
UNAVAILABLE
```

### HEALTHY

A readable runtime status exists and its heartbeat age is within the configured freshness window.

For XRP Phase 7, `WAITING_PRE_HOLDOUT` is a healthy readiness state before 2026-09-01 00:00 UTC when the frozen model/policy checks pass and no future-evaluation journal exists.

### STALE

The status file is readable and does not report an error, but its heartbeat is older than the configured freshness window.

### ERROR

The runtime status explicitly reports a non-success state, or a frozen-contract verification check explicitly fails.

For XRP V1 this includes:

- frozen model hash verification failure
- frozen policy verification failure

For XRP Phase 7 it also includes:

- brokerage orders unexpectedly reported as enabled
- a Phase 7 journal existing while the evaluator is still in `WAITING_PRE_HOLDOUT`

For Shared V2, an explicit model-hash verification failure is also treated as an error if present in its status payload.

### UNAVAILABLE

The expected runtime status file is missing/unreadable or has no usable heartbeat timestamp.

## Freshness thresholds

| Component | Stale threshold |
|---|---:|
| 15m reconciler | 45 minutes |
| Shared V2 forward service | 90 minutes |
| XRP V1 forward service | 90 minutes |
| XRP Phase 7 evaluator | 90 minutes |
| Web dashboard request path | 5 minutes |

The dashboard web card is generated during the request itself and therefore represents request-path liveness. It is **not** a substitute for checking the macOS LaunchAgent process state.

## Runtime files

### Reconciliation

```text
data/live/crypto_rt/reconcile_status.json
```

### Shared V2 forward

```text
data/model/crypto_15m_v2/phase5/forward_service_status.json
```

### XRP V1 Phase 6 forward

```text
data/model/crypto_xrp_v1/phase6/forward_service_status.json
```

### XRP V1 Phase 7 evaluator

```text
data/model/crypto_xrp_v1/phase7/evaluation_status.json
```

Before the untouched future boundary, Phase 7 should report:

```text
mode: WAITING_PRE_HOLDOUT
status: ok
journal_exists: false
model_sha256_verified: true
policy_verified: true
brokerage_orders: false
```

At or after the boundary, the same status file becomes the evaluator heartbeat while the append-only event journal is maintained separately.

The dashboard uses `generated_at_utc`, `last_updated_utc`, or `updated_at_utc` when present. If none is available, it falls back to the runtime status file modification time.

## Overall platform state

The dashboard reports the worst current state across the five monitored components using this severity order:

```text
HEALTHY < STALE < UNAVAILABLE < ERROR
```

This is deliberately conservative: a single error marks the overall operational panel as `ERROR` even if the other services are healthy.

## Process-level checks

Use `launchctl` for authoritative macOS process state:

```bash
launchctl print gui/$(id -u)/com.datashepherd.web \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.xrpforward \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.xrpphase7 \
  | grep -E 'state =|runs =|pid =|last exit code'
```

The dashboard health panel and `launchctl` answer different questions:

- dashboard heartbeat monitoring: **Is the runtime producing fresh readable state?**
- `launchctl`: **Is the configured macOS process currently loaded/running, and what was its last exit code?**

## Shared V2 stale-lock recovery

The Shared V2 service owns `forward_service.lock` with its process ID. At startup it now:

1. preserves the lock and exits when that PID is still alive
2. reclaims the lock when the PID is dead or the lock content is invalid
3. publishes a `STARTING` heartbeat before loading data or running inference
4. replaces that heartbeat with an explicit `status: ok` result after successful frozen-model verification

This lets the `KeepAlive` LaunchAgent recover after an unclean service stop without deleting a live service's lock. It does not backfill a missed decision or change the append-only forward evidence boundary.

## Safety boundary

Operational monitoring is presentation/observability only.

It does not change:

- Shared V2 HGB model
- Shared V2 `confirm_2` policy
- Shared V2 hourly decision cadence
- XRP V1 Ridge model
- XRP V1 `hyst_10_05_hold24` policy
- XRP V1 four-hour decision cadence
- XRP Phase 7 future-evaluation accounting contract
- Sep. 1, 2026 future-evaluation boundaries
- brokerage execution state

Real brokerage orders remain disabled.
