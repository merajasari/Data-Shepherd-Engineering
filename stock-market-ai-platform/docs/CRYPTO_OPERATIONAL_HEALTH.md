# Crypto Operational Health Monitoring

This document defines the read-only service-health panel on the Data Shepherd Engineering crypto dashboard.

## Scope

The health layer monitors runtime freshness only. It does **not** fit models, change thresholds, alter execution policies, write brokerage orders, or modify either frozen forward contract.

Monitored components:

1. authoritative Coinbase 15-minute reconciliation
2. frozen Shared Crypto 15m V2 forward service
3. frozen XRP V1 Phase 6 shadow-forward service
4. web dashboard request path

## Health states

```text
HEALTHY
STALE
ERROR
UNAVAILABLE
```

### HEALTHY

A readable runtime status exists and its heartbeat age is within the configured freshness window.

### STALE

The status file is readable and does not report an error, but its heartbeat is older than the configured freshness window.

### ERROR

The runtime status explicitly reports a non-success state, or a frozen-contract verification check explicitly fails.

For XRP V1 this includes:

- frozen model hash verification failure
- frozen policy verification failure

For Shared V2, an explicit model-hash verification failure is also treated as an error if present in its status payload.

### UNAVAILABLE

The expected runtime status file is missing/unreadable or has no usable heartbeat timestamp.

## Freshness thresholds

| Component | Stale threshold |
|---|---:|
| 15m reconciler | 45 minutes |
| Shared V2 forward service | 90 minutes |
| XRP V1 forward service | 90 minutes |
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

The dashboard uses `generated_at_utc`, `last_updated_utc`, or `updated_at_utc` when present. If none is available, it falls back to the runtime status file modification time.

## Overall platform state

The dashboard reports the worst current state across the four monitored components using this severity order:

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
```

The dashboard health panel and `launchctl` answer different questions:

- dashboard heartbeat monitoring: **Is the runtime producing fresh readable state?**
- `launchctl`: **Is the configured macOS process currently loaded/running, and what was its last exit code?**

## Safety boundary

Operational monitoring is presentation/observability only.

It does not change:

- Shared V2 HGB model
- Shared V2 `confirm_2` policy
- Shared V2 hourly decision cadence
- XRP V1 Ridge model
- XRP V1 `hyst_10_05_hold24` policy
- XRP V1 four-hour decision cadence
- Sep. 1, 2026 future-evaluation boundaries
- brokerage execution state

Real brokerage orders remain disabled.
