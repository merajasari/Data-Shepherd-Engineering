# Data Shepherd Engineering

Data Shepherd Engineering is an experimental research platform for systematic stock and crypto research, model evaluation, paper simulation, and forward paper monitoring.

> **Research and simulation only. Not financial advice. No real brokerage orders are placed by the current platform.**

## Current platform state — 2026-08-16

The project now contains two primary research/application tracks:

1. **Stocks**
   - Cross-sectional stock ranking research and dashboarding.
   - Frozen stock research versions remain available as historical benchmarks.
   - Forward/paper-trading infrastructure is separate from research artifacts.
   - The web dashboard supports stock selection, rankings, recent market information, and paper-monitoring views.

2. **Crypto**
   - Historical Coinbase 15-minute archive for 25 USD crypto products.
   - Continuous Coinbase real-time ticker ingestion.
   - Authoritative closed 15-minute REST reconciliation.
   - Crypto 15m V1 cross-sectional research.
   - Crypto 15m V2 BTC / ALT / CASH regime research.
   - Frozen Crypto 15m V2 forward candidate with an hourly decision cadence and `confirm_2` execution policy.
   - Dedicated XRP V1 research through exploratory Phase 5.
   - XRP V1 exploratory forward candidate using Ridge plus XRP/BTC/CASH hysteresis and a 24-hour minimum hold.
   - Shadow forward inference before 2026-09-01 UTC; automatic future paper evaluation begins only at/after frozen holdout boundaries.

## Crypto 15m V2 frozen candidate

The currently frozen shared crypto candidate is:

- **Model:** HistGradientBoosting classifier
- **Decision cadence:** 1 hour
- **Economic horizon:** 4 hours
- **Execution policy:** `confirm_2`
- **Confirmation rule:** a new BTC / ALT / CASH sleeve must be predicted for two consecutive hourly decisions before switching
- **Training rows:** 49,209
- **Training through:** 2026-08-14 20:00 UTC
- **Features:** 44
- **Future evaluation begins:** 2026-09-01 00:00 UTC
- **XRP:** excluded from the shared model and reserved for a separate research track
- **Brokerage execution:** disabled

### Phase 4 exploratory development evidence

The selected `confirm_2` execution rule was chosen during an explicitly exploratory turnover-control phase. These figures are **development evidence, not untouched future validation**:

- Raw hourly switches: 6,084
- Executed switches with `confirm_2`: 2,505
- Switch reduction: 58.8%
- Ending equity at 0 bps sleeve-switch cost: 4.2469x
- Ending equity at 5 bps sleeve-switch cost: 1.2134x
- Max drawdown at 0 bps: -54.99%
- Max drawdown at 5 bps: -66.43%

Important limitation: the historical cost model charges sleeve-level BTC / ALT / CASH switching but does not yet model constituent-level turnover inside the equal-weight ALT sleeve. Historical cost results are therefore optimistic.

## Crypto data

### Historical archive

The authoritative research archive is stored under:

```text
data/research/crypto_intraday/raw_15m/
```

The archive contains multiple years of 15-minute Coinbase history, with BTC history extending back approximately ten years. Assets begin at their actual Coinbase listing history rather than being synthetically backfilled.

No missing historical candles are synthesized.

### Live and reconciled data

The platform has two complementary live layers:

- **Coinbase public WebSocket** — low-latency live ticker stream.
- **Coinbase Exchange REST reconciliation** — authoritative closed 15-minute candle layer.

The reconciler continuously updates:

```text
data/research/crypto_intraday/raw_15m/
data/live/crypto_rt/reconcile_status.json
data/live/crypto_rt/latest_authoritative_15m.json
```

## Crypto 15m research history

### Crypto 15m V1

V1 built a 24-asset shared panel with XRP isolated because XRP has a large historical gap.

Phase 1 produced:

- 4,713,634 shared-core rows
- 170,315 dedicated XRP rows
- 44 features
- prediction horizons: 15m, 1h, 4h, 24h
- no feature or target crossing a missing-data gap
- no synthesized candles

Phase 2 found only a small positive cross-sectional signal in Ridge at the 4-hour BTC-relative target.

Phase 3 showed that the always-risky Top-N portfolio design failed economically because extremely high turnover overwhelmed the weak signal.

### XRP V1 — dedicated research track

XRP remains separate from the shared Crypto 15m V2 model because of its major historical continuity gap.

The model-ready XRP panel contains:

- 170,315 rows
- 20 contiguous segments
- 44 features
- 15m / 1h / 4h / 24h targets
- a 907.11-day model-ready discontinuity between January 2021 and July 2023

XRP V1 research progression:

- **Phase 1:** separated 63,333 legacy rows from 106,982 post-gap primary rows.
- **Phase 2:** compared Ridge, HistGradientBoosting, and a momentum baseline on the post-gap era only; Ridge was the most stable OOS research model.
- **Phase 3:** analyzed OOS confidence and sign asymmetry; confidence-only threshold promotion was rejected.
- **Phase 4:** tested exploratory XRP / BTC / CASH economic threshold policies; high turnover proved too cost-sensitive.
- **Phase 5:** tested hysteresis and minimum holding periods to reduce turnover.

Current exploratory forward hypothesis:

```text
policy: hyst_10_05_hold24
model: Ridge
target: btc_relative_forward_return_4h
decision cadence: 4h

XRP entry:  score >= +0.0010
CASH entry: score <= -0.0010
XRP exit:   score <= +0.0005
CASH exit:  score >= -0.0005
neutral:    BTC
minimum hold: 24h
```

Phase 5 development evidence for this hypothesis:

- decisions: 3,987
- switches: 524
- switch rate: 13.14%
- ending equity at 0 bps: 1.7463x
- ending equity at 5 bps: 1.3437x
- ending equity at 10 bps: 1.0338x
- ending equity at 20 bps: 0.6117x
- always-BTC development reference: approximately 1.0162x

The fold results remain mixed. Therefore this is an **exploratory forward candidate only**:

- not historically validated
- not promoted for real trading
- no further threshold/hold-period tuning on the same development folds
- XRP remains separate from frozen Crypto 15m V2
- untouched future boundary remains 2026-09-01 00:00 UTC
- brokerage execution remains disabled

### Crypto 15m V2

V2 changed the research question from constant risky cross-sectional allocation to a BTC / ALT / CASH regime decision.

- Phase 1: hourly market-allocation dataset
- Phase 2: walk-forward classification research
- Phase 3: hourly regime portfolio simulation
- Phase 4: exploratory turnover-control policies
- Phase 5: frozen HGB + `confirm_2` candidate for future paper evaluation

The Phase 5 freeze must not be modified in place. Any change to features, model hyperparameters, class definitions, execution policy, cost reference, XRP policy, or holdout rules requires a new research version.

## Forward crypto service

The frozen shared V2 forward inference service:

```text
ml/crypto_15m_v2/forward_service.py
```

It:

- verifies the frozen model SHA-256 before inference
- reconstructs the exact frozen 44-feature contract
- reads authoritative reconciled 15-minute data
- produces BTC / ALT / CASH probabilities
- applies the frozen `confirm_2` policy
- records a shadow snapshot before the holdout boundary
- writes only genuinely new forward decisions at/after 2026-09-01 UTC
- never backfills missed holdout decisions
- never places brokerage orders

Current Phase 5 state files:

```text
data/model/crypto_15m_v2/phase5/frozen_hgb.joblib
data/model/crypto_15m_v2/phase5/freeze_manifest.json
data/model/crypto_15m_v2/phase5/forward_state.json
data/model/crypto_15m_v2/phase5/forward_journal.csv
data/model/crypto_15m_v2/phase5/forward_service_status.json
data/model/crypto_15m_v2/phase5/shadow_latest.json
```

The next XRP engineering step is separate: create a reproducible XRP frozen-candidate artifact/manifest and a shadow-only XRP forward inference service using the exact Phase 5 exploratory rule without further historical tuning.

## macOS background services

The Mac runtime uses LaunchAgents.

Crypto reconciliation:

```text
com.datashepherd.cryptoreconcile
```

Frozen Crypto V2 forward inference:

```text
com.datashepherd.cryptov2forward
```

Web application:

```text
com.datashepherd.web
```

Typical status check:

```bash
launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.web   | grep -E 'state =|runs =|pid =|last exit code'
```

## Web application

The member web application includes:

- account signup
- email verification through Resend
- unique username selection
- temporary-password onboarding
- forced password change on first login
- stock dashboard
- crypto dashboard
- authenticated API endpoints
- paper/research-only monitoring

The crypto page now surfaces:

- SHADOW / FORWARD mode
- current executed sleeve
- raw model prediction
- BTC / ALT / CASH probabilities
- eligible ALT count
- hourly decision timestamp
- reconciliation freshness
- missing/ineligible ALT assets
- forward-journal counts
- Crypto 15m V2 exploratory development evidence
- explicit no-real-orders status
- automatic in-place live-state refresh

## Email

Domain sending is configured through Resend for:

```text
datashepherdengineering.com
```

The domain has verified DKIM/SPF records. Production signup email uses the configured Resend API key from the local `.env`.

Never commit API keys, passwords, tokens, or `.env` contents.

## Research guardrails

The following rules are intentional and should be preserved:

- no future leakage
- no synthetic missing candles
- no retrospective universe membership
- chronological walk-forward evaluation
- horizon-aware purging
- frozen holdout boundaries
- no tuning on future holdout results
- development and future-forward evidence clearly labeled
- generated research artifacts kept separate from source
- XRP kept separate from the shared Crypto 15m V2 model
- no further XRP historical threshold/hold-period tuning on the same development folds
- no leverage, shorting, derivatives, or real brokerage execution in the frozen candidates

## Repository workflow

Primary active branch:

```text
feature/paper-trading
```

Typical update flow:

```bash
git pull --ff-only origin feature/paper-trading
python -m py_compile <changed-python-files>
```

Generated model/data artifacts should not be committed unless explicitly intended. Source, tests, scripts, templates, and documentation should be reviewed separately from generated runtime state.

## Immediate next work

1. Freeze the XRP V1 exploratory forward candidate reproducibly with an artifact/manifest.
2. Build shadow-only XRP forward inference using the exact frozen `hyst_10_05_hold24` rule.
3. Preserve both Sep. 1 future boundaries and do not tune from future observations.
4. Add service staleness/health alerting.
5. Add forward-performance visualizations only after genuine Sep. 1+ observations exist.
6. Research ALT constituent-level turnover/costs in a new research version without changing the V2 Phase 5 freeze.
7. Continue stock-model work without changing frozen benchmarks.
