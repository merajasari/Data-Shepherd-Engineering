# XRP V1 Phase 6 — Frozen Exploratory Forward Monitor

**Updated:** 2026-08-16  
**Research version:** `crypto_xrp_v1`  
**Status:** EXPLORATORY FORWARD CANDIDATE  
**Trading promotion:** NOT PROMOTED FOR REAL TRADING

## Purpose

XRP remains isolated from the shared Crypto 15m V2 model because its historical 15-minute archive contains a major structural discontinuity. Phase 6 freezes the already-selected Phase 5 exploratory hypothesis without any additional model, threshold, or holding-period selection.

## Frozen contract

- model: Ridge
- target: `btc_relative_forward_return_4h`
- features: 44
- training rows: 106,982
- training population: post-major-discontinuity XRP primary era only
- training range: 2023-07-14 20:45 UTC through 2026-08-14 20:30 UTC
- decision cadence: 4 hours
- policy: `hyst_10_05_hold24`
- minimum hold: 24 hours
- neutral state: BTC
- future boundary: 2026-09-01 00:00 UTC
- brokerage orders: disabled
- leverage: disabled
- shorting: disabled
- derivatives: disabled

Policy thresholds:

```text
enter XRP:  score >= +0.0010
enter CASH: score <= -0.0010
leave XRP:  score <= +0.0005
leave CASH: score >= -0.0005
neutral:    BTC
minimum hold: 24h
```

## Frozen artifact

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
```

SHA-256:

```text
4c3f69b4bd41bf69cfaf7ce0633d53fb2e5bec10d1b9c8081fd295d6bfe45553
```

Freeze manifest:

```text
data/model/crypto_xrp_v1/phase6/freeze_manifest.json
```

## Shadow forward service

Module:

```text
ml/crypto_xrp_v1/forward_service.py
```

LaunchAgent:

```text
com.datashepherd.xrpforward
```

The service:

1. verifies the frozen Ridge artifact SHA-256;
2. verifies the frozen policy contract;
3. consumes authoritative reconciled Coinbase 15-minute data;
4. reconstructs the exact frozen 44-feature XRP row;
5. advances only genuinely available four-hour decisions;
6. preserves the XRP/BTC/CASH state machine and 24-hour minimum hold;
7. does not replay missed historical decisions;
8. does not modify the shared Crypto 15m V2 candidate;
9. does not place brokerage orders.

Before the Sep. 1 future boundary the mode is `SHADOW_PRE_HOLDOUT`.

The Phase 6 shadow service deliberately does **not** write a forward-performance journal. A separate future-evaluation phase must be created before XRP forward observations are scored, accumulated into performance statistics, or considered for promotion.

## Dashboard

The Crypto dashboard now has a separate **XRP V1 — Exploratory Forward Monitor** beneath the shared Crypto 15m V2 research evidence. It surfaces:

- current XRP/BTC/CASH shadow state;
- frozen 4-hour Ridge score;
- decision timestamp;
- policy and minimum hold;
- model-hash verification;
- policy verification;
- latest XRP/BTC/common reconciled bar timestamps;
- state transition and switch status;
- minimum-hold blocking status;
- explicit `REAL ORDERS: NO` safety state.

XRP remains visually and operationally separate from the shared Crypto 15m V2 frozen candidate.

## Next engineering priority

1. Monitor reconciliation, shared V2 forward inference, and XRP forward inference for staleness or service failures.
2. Add operational health/alerting without changing either frozen model contract.
3. Preserve the 2026-09-01 future boundary.
4. Do not backfill missed forward decisions.
5. Do not tune XRP thresholds or holding periods further on the same historical folds.
6. Keep XRP performance journaling disabled until a separate future-evaluation phase is explicitly implemented.
7. Never place real brokerage orders from this research service.
