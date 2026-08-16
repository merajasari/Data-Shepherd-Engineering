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

## XRP

XRP remains separate due to a major historical discontinuity.

Do not combine XRP into the shared V2 model without creating a new research version and explicitly revisiting continuity, validation, and cost assumptions.

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
