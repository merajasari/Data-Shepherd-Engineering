# Crypto Sep 1+ Untouched Forward Performance

## Purpose

The Crypto dashboard has a dormant **Untouched Forward Performance** section for the future paper-evaluation period beginning:

```text
2026-09-01T00:00:00+00:00
```

This section is presentation-only. It does not fit models, change thresholds, alter execution state, create journal rows, backfill missed decisions, or place brokerage orders.

Before the boundary, and after the boundary until at least one genuine realization exists, each track displays:

```text
AWAITING_FUTURE_OBSERVATIONS
```

No development, exploratory, OOS, or historical simulation result is allowed to populate these cards.

## Shared Crypto V2

Source:

```text
data/model/crypto_15m_v2/phase5/forward_journal.csv
```

Only rows satisfying both conditions are used:

- `decision_timestamp_utc >= 2026-09-01T00:00:00Z`
- `status == REALIZED`

Displayed candidate performance uses the journal's frozen 5 bps sleeve-switch accounting and `equity` path.

The displayed benchmark is **Always BTC**, compounded from the same realized-hour `btc_realized_return_1h` observations used by the frozen forward journal.

Displayed fields include:

- genuine forward decision count,
- realized count,
- pending count,
- executed sleeve switches,
- candidate equity multiple,
- candidate cumulative return,
- candidate max drawdown,
- always-BTC equity multiple,
- always-BTC cumulative return,
- always-BTC max drawdown,
- latest realized timestamp,
- explicit `REAL ORDERS: NO`.

Shared V2 remains governed by the frozen HGB + `confirm_2` contract. This dashboard layer does not modify it.

## XRP V1 Phase 7

Source:

```text
data/model/crypto_xrp_v1/phase7/forward_summary.json
```

The card activates only after Phase 7 has at least one `VALID` untouched future realization.

The displayed candidate performance uses the Phase 7 frozen **5 bps per actual state change** accounting path:

```text
equity_5bps
max_drawdown_5bps
```

The displayed benchmark is Phase 7's **Always BTC** path:

```text
always_btc_equity
always_btc_max_drawdown
```

Displayed fields include:

- decision count,
- valid realization count,
- pending realization count,
- invalid data-gap realization count,
- state-switch count,
- candidate 5 bps equity multiple,
- candidate cumulative return,
- candidate max drawdown,
- always-BTC equity multiple,
- always-BTC cumulative return,
- always-BTC max drawdown,
- latest realized decision timestamp,
- explicit `REAL ORDERS: NO`.

The Phase 7 event journal remains append-only and authoritative. The dashboard does not read pre-holdout observations into performance statistics.

## Interpretation rule

These cards are **future paper-evaluation evidence**, not permission to tune either frozen candidate.

If future performance is poor, the result must remain visible. The frozen contract must not be changed in place to improve the displayed result. Any new hypothesis requires a new research version.
