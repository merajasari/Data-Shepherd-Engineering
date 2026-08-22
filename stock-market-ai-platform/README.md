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
   - Dedicated XRP V1 research through Phase 6.
   - Frozen XRP V1 exploratory forward candidate using Ridge plus XRP/BTC/CASH hysteresis and a 24-hour minimum hold.
   - Unattended shadow-only XRP forward inference via `com.datashepherd.xrpforward`.
   - Shared V2 remains shadow-only before 2026-09-01 UTC; XRP Phase 6 remains shadow-only until a separate future-evaluation phase is explicitly created.

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
- **Phase 6:** froze the exact Ridge + `hyst_10_05_hold24` exploratory candidate without additional tuning and added shadow-only forward inference.

Frozen XRP Phase 6 contract:

```text
research status: EXPLORATORY FORWARD CANDIDATE
model: Ridge
target: btc_relative_forward_return_4h
features: 44
training rows: 106,982
decision cadence: 4h
policy: hyst_10_05_hold24
minimum hold: 24h
future boundary: 2026-09-01T00:00:00Z
promotion status: NOT PROMOTED FOR REAL TRADING
```

Policy thresholds:

```text
XRP entry:  score >= +0.0010
CASH entry: score <= -0.0010
XRP exit:   score <= +0.0005
CASH exit:  score >= -0.0005
neutral:    BTC
minimum hold: 24h
```

Frozen model:

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
```

SHA-256:

```text
4c3f69b4bd41bf69cfaf7ce0633d53fb2e5bec10d1b9c8081fd295d6bfe45553
```

Shadow service:

```text
ml/crypto_xrp_v1/forward_service.py
```

The XRP Phase 6 service verifies the frozen model and policy contract, reads authoritative reconciled Coinbase 15-minute data, reconstructs the exact 44-feature row, advances only genuinely available four-hour decisions, preserves state across cycles, and places no brokerage orders.

It deliberately does **not** write a performance journal. A separate future-evaluation phase is required before XRP forward results are scored or considered for promotion.

Phase 5 development evidence for the frozen hypothesis remains exploratory:

- decisions: 3,987
- switches: 524
- switch rate: 13.14%
- ending equity at 0 bps: 1.7463x
- ending equity at 5 bps: 1.3437x
- ending equity at 10 bps: 1.0338x
- ending equity at 20 bps: 0.6117x
- always-BTC development reference: approximately 1.0162x

The fold results remain mixed. Therefore XRP V1 remains:

- not historically validated
- not promoted for real trading
- no further threshold/hold-period tuning on the same development folds
- separate from frozen Crypto 15m V2
- brokerage execution disabled

### Crypto 15m V2

V2 changed the research question from constant risky cross-sectional allocation to a BTC / ALT / CASH regime decision.

- Phase 1: hourly market-allocation dataset
- Phase 2: walk-forward classification research
- Phase 3: hourly regime portfolio simulation
- Phase 4: exploratory turnover-control policies
- Phase 5: frozen HGB + `confirm_2` candidate for future paper evaluation

The Phase 5 freeze must not be modified in place. Any change to features, model hyperparameters, class definitions, execution policy, cost reference, XRP policy, or holdout rules requires a new research version.

## Forward crypto services

### Shared Crypto 15m V2

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

### XRP V1 Phase 6

```text
ml/crypto_xrp_v1/forward_service.py
```

Current Phase 6 state files:

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
data/model/crypto_xrp_v1/phase6/freeze_manifest.json
data/model/crypto_xrp_v1/phase6/forward_state.json
data/model/crypto_xrp_v1/phase6/forward_service_status.json
data/model/crypto_xrp_v1/phase6/shadow_latest.json
```

The XRP service remains shadow-only. No performance journal exists in the current Phase 6 forward service.

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

Frozen XRP V1 shadow forward inference:

```text
com.datashepherd.xrpforward
```

Web application:

```text
com.datashepherd.web
```

Typical status check:

```bash
launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.xrpforward   | grep -E 'state =|runs =|pid =|last exit code'

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

- shared V2 SHADOW / FORWARD mode
- current shared V2 executed sleeve
- raw V2 model prediction
- BTC / ALT / CASH probabilities
- eligible ALT count
- hourly V2 decision timestamp
- reconciliation freshness
- missing/ineligible ALT assets
- V2 forward-journal counts
- Crypto 15m V2 exploratory development evidence
- dedicated XRP V1 Phase 6 shadow state
- XRP 4-hour BTC-relative Ridge score
- XRP policy and minimum-hold state
- XRP model-hash and policy verification
- XRP/BTC/common latest-bar timestamps
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
- no XRP forward-performance scoring until a separate future-evaluation phase is explicitly created
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

1. Monitor both frozen forward services without changing either contract.
2. Preserve both Sep. 1 boundaries and do not tune from future observations.
3. Add service staleness/health alerting for reconciliation, V2 forward, XRP forward, and the web service.
4. Keep XRP performance journaling disabled until a separate future-evaluation phase is created.
5. Add forward-performance visualizations only after genuine future-evaluation observations exist.
6. Research ALT constituent-level turnover/costs in a new research version without changing the V2 Phase 5 freeze.
7. Continue stock-model work without changing frozen benchmarks.



## Stock research generations: V8 and V10

The active stock platform now presents two generations only:

- **V8** — frozen production reference and independently gated holdout monitor.
- **V10** — active research generation, including the retained automatic-tuning
  engine, purged walk-forward evaluation, fixed-winner confirmation safeguards,
  and risk-controlled automatic-tuning Cycle 2.

V10 tuning commands:

```bash
python -m ml.v10.source_panel
python -m ml.v10.auto_tuning_registry
python -m ml.v10.auto_tuning_evaluator
python -m ml.v10.auto_tuning_confirmation
python -m ml.v10.auto_tuning_cycle2_registry
python -m ml.v10.auto_tuning_cycle2_evaluator
```

New tuning artifacts are written under `data/model/v10/auto_tuning/`. Historical
`data/model/v9/` results, if present on a runtime host, are provenance records
only. They must not be relabelled as V10 evidence or used to reset confirmation
or holdout gates. V8 is not modified by the consolidation, and no real brokerage
orders are enabled.


## Site-wide Shepherd AI assistant

Every rendered HTML page can include a floating, page-aware assistant. The browser sends only
the current page title, path, visible text, the user's question, and a short in-panel conversation
history to the same-origin Flask endpoint. Password input values and arbitrary server files are
not included.

Server configuration:

```bash
OPENAI_API_KEY=your-server-side-key
SITE_AI_MODEL=gpt-4.1-mini
```

Keep `OPENAI_API_KEY` in the local server environment or uncommitted `.env`; never expose it
in JavaScript or commit it. The endpoint applies payload and per-user/IP rate limits, renders
answers as plain text, and instructs the model to distinguish development, shadow/paper, and
untouched holdout evidence. It does not place orders or provide personalized financial advice.

Verification:

```bash
python -m unittest tests.test_site_ai_service
```
