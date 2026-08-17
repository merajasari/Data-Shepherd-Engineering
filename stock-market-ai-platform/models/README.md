# Models and Research Lineage

This directory documents model/research lineage. Generated model artifacts belong under `data/model/`; source implementations belong under `ml/`.

## Current frozen candidates

### Stock research

Existing frozen stock research versions remain historical benchmarks. Do not overwrite a frozen model in place; create a new research version for material changes.

### Crypto 15m V2

Current shared crypto frozen candidate:

```text
research version: crypto_15m_v2
phase: 5
model: hist_gradient_boosting
policy: confirm_2
decision cadence: 1 hour
economic horizon: 4 hours
future evaluation start: 2026-09-01T00:00:00Z
XRP: excluded / separate research track
real brokerage orders: disabled
```

Frozen files:

```text
data/model/crypto_15m_v2/phase5/frozen_hgb.joblib
data/model/crypto_15m_v2/phase5/freeze_manifest.json
data/model/crypto_15m_v2/phase5/forward_state.json
data/model/crypto_15m_v2/phase5/forward_journal.csv
```

Model hash:

```text
9f2760f05fca4d3b6cc1e02fc700c4cdf7eeedc5e5d67208c62b534f3a458a6b
```

### XRP V1 Phase 6

Current dedicated XRP frozen exploratory forward candidate:

```text
research version: crypto_xrp_v1
phase: 6
research status: EXPLORATORY FORWARD CANDIDATE
model: ridge
target: btc_relative_forward_return_4h
features: 44
training rows: 106,982
policy: hyst_10_05_hold24
decision cadence: 4 hours
minimum hold: 24 hours
future boundary: 2026-09-01T00:00:00Z
promotion status: NOT PROMOTED FOR REAL TRADING
real brokerage orders: disabled
```

Frozen files:

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
data/model/crypto_xrp_v1/phase6/freeze_manifest.json
```

Model hash:

```text
4c3f69b4bd41bf69cfaf7ce0633d53fb2e5bec10d1b9c8081fd295d6bfe45553
```

Shadow-only forward inference:

```text
ml/crypto_xrp_v1/forward_service.py
```

Runtime service:

```text
com.datashepherd.xrpforward
```

The XRP service verifies the frozen model hash and policy before inference, reconstructs the same 44-feature contract from authoritative reconciled Coinbase 15-minute bars, advances only genuinely available four-hour decisions, and preserves the frozen hysteresis/minimum-hold state machine. It does not replay missed decisions, write a performance journal, place brokerage orders, or modify the shared Crypto 15m V2 candidate.

A separate future-evaluation phase is required before XRP forward observations may be scored or considered for promotion.

## Crypto 15m V2 phases

### Phase 1
Hourly BTC / ALT / CASH allocation dataset.

- 49,209 rows
- 44 features
- 2020-12-16 through 2026-08-14
- BTC 20.52%
- ALT 40.33%
- CASH 39.15%

### Phase 2
Chronological walk-forward classification.

Candidate models:

- majority class
- multinomial logistic
- HistGradientBoosting

HistGradientBoosting was the strongest candidate and was carried forward.

### Phase 3
Hourly sleeve simulation showed strong gross signal but unsustainable switching under transaction costs.

### Phase 4
Exploratory execution-policy development.

`confirm_2`:

- 2 consecutive hourly predictions required before a sleeve switch
- 2,505 executed switches vs 6,084 raw
- 58.8% switch reduction
- 4.2469x ending equity at 0 bps
- 1.2134x ending equity at 5 bps

These are exploratory development results, not untouched future validation.

### Phase 5
Frozen final development refit and future-evaluation contract.

No model/policy changes are permitted in place after Phase 5.

## Crypto 15m V1

V1 established the 15-minute feature/target contract and kept XRP isolated.

- shared universe: 24 products
- core rows: 4,713,634
- dedicated XRP rows: 170,315
- features: 44
- horizons: 15m / 1h / 4h / 24h

The first cross-sectional Top-N portfolio architecture was rejected because turnover overwhelmed the available predictive signal.

## XRP V1 dedicated research lineage

Research version:

```text
crypto_xrp_v1
```

XRP remains separate from Crypto 15m V2 because of its major historical continuity break.

### Phase 1 — discontinuity-aware dataset

- 170,315 model-ready rows
- 20 contiguous segments
- largest model-ready discontinuity: 907.11 days
- legacy era: 63,333 rows / 13 segments
- primary post-gap era: 106,982 rows / 7 segments
- primary era begins: 2023-07-14 20:45 UTC
- features: 44
- horizons: 15m / 1h / 4h / 24h
- no feature or target crosses a gap
- no Sep. 1+ future data

### Phase 2 — walk-forward regression

Primary target:

```text
btc_relative_forward_return_4h
```

Candidates:

- 4-hour BTC-relative momentum baseline
- Ridge
- HistGradientBoosting

Ridge produced the most stable OOS development signal and was carried forward for diagnostics.

Observed aggregate Ridge development metrics included approximately:

- Spearman: 0.0257
- directional accuracy: 52.1%
- positive Spearman in all eight walk-forward folds

No model was promoted or frozen in Phase 2.

### Phase 3 — OOS confidence diagnostics

Used only Phase 2 OOS Ridge predictions.

Confidence magnitude showed some aggregate discrimination, but fold stability was insufficient for threshold promotion. The highest absolute-confidence decile was approximately 53.1% directionally correct, while negative Ridge predictions were directionally more reliable than positive predictions.

No fitting or threshold promotion occurred.

### Phase 4 — exploratory economic state policies

State space:

```text
XRP / BTC / CASH
```

Fixed score policies were evaluated on non-overlapping four-hour observations under 0 / 5 / 10 / 20 bps state-switch costs.

Result:

- high turnover dominated economics
- modest switching costs destroyed most apparent threshold-policy gains
- Phase 4 policies were not promoted

Phase 4 is exploratory development evidence, not untouched validation.

### Phase 5 — exploratory turnover control

Tested:

- hysteresis
- 8h / 12h / 24h minimum holding periods
- two fixed entry/exit threshold families

Strongest development hypothesis:

```text
policy: hyst_10_05_hold24
model: ridge
target: btc_relative_forward_return_4h
decision cadence: 4 hours

enter XRP:   score >= +0.0010
enter CASH:  score <= -0.0010
leave XRP:   score <= +0.0005
leave CASH:  score >= -0.0005
neutral:     BTC
minimum hold: 24 hours
```

Aggregate exploratory evidence:

- decisions: 3,987
- switches: 524
- switch rate: 13.14%
- ending equity at 0 bps: 1.7463x
- ending equity at 5 bps: 1.3437x
- ending equity at 10 bps: 1.0338x
- ending equity at 20 bps: 0.6117x
- always-BTC development reference: approximately 1.0162x

Fold results remain mixed, so this policy is **not promoted**.

### Phase 6 — reproducible exploratory forward freeze

Phase 6 performs no new model selection or threshold tuning. It freezes the existing Phase 5 exploratory hypothesis for reproducible forward monitoring.

Training/freeze contract:

- post-gap primary XRP era only
- 106,982 training rows
- 44 features
- Ridge pipeline: median imputation -> StandardScaler -> Ridge(alpha=10.0)
- target: `btc_relative_forward_return_4h`
- policy: `hyst_10_05_hold24`
- decision cadence: 4 hours
- minimum hold: 24 hours
- future boundary: 2026-09-01T00:00:00Z
- promotion status: NOT PROMOTED FOR REAL TRADING

Shadow-forward rules:

- no further historical threshold/hold-period tuning on the same folds
- preserve the Sep. 1 boundary
- no performance journal in the current XRP shadow service
- no historical replay/backfill of missed decisions
- no real brokerage orders
- no leverage
- no shorting
- no derivatives
- do not combine XRP into Crypto 15m V2

## Artifact rules

- source code: commit
- tests: commit
- scripts: commit
- documentation: commit
- generated model artifacts: generally do not commit unless explicitly required
- runtime state: do not commit
- API keys/secrets: never commit
- `.env`: never commit

## Research rules

Every new model version should document:

- objective
- feature contract
- target contract
- universe rules
- missing-data policy
- time split
- purge/embargo
- candidate models
- selection rule
- transaction-cost assumptions
- holdout policy
- promotion/freeze decision
- model/artifact hashes when frozen

Historical exploration must never be presented as future validation.