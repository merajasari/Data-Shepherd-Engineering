# Crypto Forward Validation Summary + Dashboard Header Match

This change combines two presentation/read-only improvements.

## Dashboard header sizing

The Stock and Crypto dashboard headers now intentionally match the landing-page brand sizing contract:

- header spacing: 45px top, 30px bottom
- brand gap: 22px
- logo box: 220 x 125 px
- logo visual scale: 1.55x
- logo object fit: contain
- landing-style logo shadow
- eyebrow size: 0.75rem
- platform title: `clamp(2.1rem, 4vw, 3.7rem)`
- subtitle: 1.05rem

On narrow screens (<=650px), the dashboard header follows the landing layout with a stacked brand and a 185 x 105 px logo box.

This is visual-only. Dashboard data, authentication, model inference, and execution logic are unchanged.

## Post-boundary forward validation summary

The crypto dashboard also gains a dormant forward-sample summary for the two frozen future-evaluation tracks:

- Shared Crypto V2
- XRP V1 Phase 7

The summary is derived only from the existing untouched Sep. 1+ forward-performance payload.

### Fixed minimum sample

The assessment gate is fixed at:

```text
30 genuine realized future observations per track
```

Before the minimum is reached, the dashboard reports:

```text
AWAITING_MINIMUM_FUTURE_SAMPLE
```

and shows the number of genuine observations still required.

After 30 realizations, the dashboard reports a descriptive candidate-vs-BTC result:

- `OUTPERFORMING_BENCHMARK`
- `MATCHING_BENCHMARK`
- `UNDERPERFORMING_BENCHMARK`

It also displays:

- candidate cumulative return
- always-BTC cumulative return
- excess return versus BTC
- candidate max drawdown
- BTC max drawdown
- whether drawdown is better, matching, or worse than BTC

### Important research boundary

This summary is not a tuning or selection phase.

It does **not**:

- refit either model
- alter a frozen policy
- select thresholds
- change cost assumptions
- backfill missed future observations
- promote either candidate automatically
- place brokerage orders

The fixed 30-observation gate is an operational reporting threshold, not a performance target. Results remain untouched forward evidence and must be interpreted as such.

## Frozen systems remain unchanged

These changes do not modify:

- Shared Crypto V2 frozen HGB artifact or `confirm_2` policy
- XRP V1 frozen Ridge artifact or `hyst_10_05_hold24` policy
- Shared V2 forward journal-writing behavior
- XRP Phase 7 append-only evaluation behavior
- Sep. 1, 2026 future boundary
- brokerage-order prohibition
