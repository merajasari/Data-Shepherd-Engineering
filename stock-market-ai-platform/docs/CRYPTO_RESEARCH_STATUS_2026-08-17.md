# Crypto Research Status — 2026-08-17

This document records the current development status of the recent 15-minute / 1-hour crypto research tracks. It is deliberately separate from the frozen forward candidates.

## Frozen forward systems — unchanged

### Shared Crypto 15m V2

- Status: frozen forward candidate
- Model: HistGradientBoosting
- Decision cadence: 1 hour
- Economic horizon: 4 hours
- Policy: `confirm_2`
- Future evaluation boundary: 2026-09-01 00:00 UTC
- Brokerage orders: disabled

The Shared V2 freeze was not modified by any V3 research.

### XRP V1 Phase 6

- Status: exploratory frozen shadow-forward candidate
- Model: Ridge
- Decision cadence: 4 hours
- Economic horizon: 4 hours BTC-relative
- Policy: `hyst_10_05_hold24`
- Minimum hold: 24 hours
- Future boundary: 2026-09-01 00:00 UTC
- Brokerage orders: disabled
- Forward performance journal: disabled until a separate future-evaluation phase exists

The XRP V1 Phase 6 freeze was not modified by XRP V2 or XRP V3 research.

---

## Shared Crypto V3 — rejected current policy family

Research question:

- 15-minute decisions
- 1-hour economic horizon
- BTC / ALT / CASH state space
- HOLD by default
- state changes require confirmation, minimum hold, hysteresis, and a positive expected net switching edge after modeled costs

Leakage-safe Phase 2 model evidence was sufficient to test turnover-aware policies, but Phase 3/4 economics failed realistic cost robustness.

Best policy by cost:

| Cost | Best policy | Ending equity | Max drawdown | Switches |
|---:|---|---:|---:|---:|
| 0 bps | `hold_confirm2_1h` | 1.0917x | -63.70% | 3,439 |
| 5 bps | `hold_confirm4_4h` | 0.4929x | -83.02% | 1,053 |
| 10 bps | `hold_confirm4_4h` | 0.2910x | -88.45% | 1,053 |
| 25 bps | `hold_confirm4_4h` | 0.0598x | -96.67% | 1,053 |

Status:

```text
REJECT_CURRENT_POLICY_FAMILY
```

Interpretation:

The 15m/1h shared allocator did not survive realistic switching costs. Do not tune the same policy family further on the same OOS development evidence. Preserve the result as a failed hypothesis.

---

## XRP V2 — diagnostics only, no freeze

Research question:

- 15-minute decisions
- 1-hour XRP-minus-BTC target
- XRP / BTC / CASH allocator
- HOLD by default
- switching constrained by cost hurdle, confirmation, hysteresis, and minimum hold

Corrected accounting uses an explicit `realization_bar=true` marker and non-overlapping hourly economic realizations while decisions continue every 15 minutes.

Aligned OOS benchmark sample:

```text
realized_hour_count: 15,944
always XRP ending equity: 2.0973x
always XRP max drawdown: -74.37%
always BTC ending equity: 1.0479x
always BTC max drawdown: -54.87%
```

Reference V2 policy at 5 bps:

```text
policy: xrp_hold_c2_1h
ending equity: 1.3912x
max drawdown: -64.30%
fold fraction strategy beats BTC: 37.5%
```

Status:

```text
OVERLAY_DIAGNOSTICS_ONLY_NO_FREEZE
```

Interpretation:

Aggregate overlay evidence exists, but temporal stability and drawdown are insufficient for a freeze. Descriptive Phase 5 regime/score buckets must not become thresholds on the same OOS evidence.

---

## XRP V3 — no promotion candidate

XRP V3 was created as a fresh, separately pre-registered hypothesis rather than tuning XRP V2.

Primary hypothesis:

- BTC is the default state
- XRP is a selective overlay only
- 15-minute decisions
- 1-hour BTC-relative target
- no CASH state in the primary hypothesis
- HOLD is the default action
- switching requires positive expected net edge after transaction cost, slippage allowance, and safety buffer
- confirmation, minimum hold, and hysteresis are mandatory
- XRP V2 thresholds and score buckets are not reused

### Important Phase 2 leakage correction

The first XRP V3 Phase 2 implementation accidentally allowed other forward outcome columns such as `forward_return_15m`, `forward_return_4h`, and `forward_return_24h` into the feature set. Those initial model results are invalid development evidence and must not be used.

The corrected implementation excludes all columns matching:

```text
forward_return_*
btc_forward_return_*
btc_relative_forward_return_*
```

Corrected leakage-free Phase 2 results:

| Model | Spearman | Pearson | Sign accuracy | MAE | RMSE |
|---|---:|---:|---:|---:|---:|
| Ridge | 0.04474 | 0.03076 | 51.56% | 0.003890 | 0.006243 |
| HistGradientBoosting | 0.03780 | 0.04487 | 51.87% | 0.003869 | 0.006257 |
| 1h momentum | -0.05711 | -0.03648 | 48.01% | 0.005616 | 0.008908 |

Ridge was carried into the small pre-registered BTC-default policy grid.

### Phase 3 economic evidence

At 5 bps:

| Policy | Ending equity | Max drawdown | Switches | XRP fraction |
|---|---:|---:|---:|---:|
| `btc_default_c2_1h` | 1.6786x | -66.54% | 436 | 53.0% |
| `btc_default_c3_2h` | 2.0724x | -56.72% | 184 | 49.2% |
| `btc_default_c4_4h` | 1.1049x | -70.26% | 69 | 52.7% |

Aligned always-BTC benchmark on the same Phase 3 hourly realization sample:

```text
ending equity: 0.9856x
max drawdown: -54.87%
```

`btc_default_c3_2h` also had a monotonic cost path:

```text
0 bps:  2.2385x
5 bps:  2.0724x
10 bps: 1.6545x
25 bps: 1.3281x
```

### Phase 4 pre-registered promotion gates

Pre-registered gates required:

1. 5 bps aggregate equity above aligned always-BTC
2. positive fold fraction at least 75%
3. max drawdown better than XRP V2 5 bps reference
4. explainable cost path

Gate results at 5 bps:

| Policy | Beat BTC | Positive folds >=75% | Better drawdown than XRP V2 | Cost path explainable | All pass |
|---|---|---|---|---|---|
| `btc_default_c3_2h` | YES | NO — 37.5% | YES | YES | NO |
| `btc_default_c2_1h` | YES | NO — 62.5% | NO | YES | NO |
| `btc_default_c4_4h` | YES | NO — 50.0% | NO | NO | NO |

Status:

```text
NO_PROMOTION_CANDIDATE
```

Interpretation:

XRP V3 produced promising aggregate development economics, especially `btc_default_c3_2h`, but performance was not stable enough through time to satisfy the pre-registered fold gate. Do not tune the same V3 grid further on these OOS results. Preserve V3 as development evidence.

---

## Current platform research state

```text
Shared Crypto V2: FROZEN FORWARD CANDIDATE — unchanged
XRP V1 Phase 6: EXPLORATORY SHADOW FORWARD CANDIDATE — unchanged
Shared Crypto V3: REJECT_CURRENT_POLICY_FAMILY
XRP V2: OVERLAY_DIAGNOSTICS_ONLY_NO_FREEZE
XRP V3: NO_PROMOTION_CANDIDATE
```

No recent V3/V2 development research changed the frozen live contracts, enabled leverage/shorting/derivatives, or enabled real brokerage orders.
