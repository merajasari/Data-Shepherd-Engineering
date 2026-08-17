# Data Shepherd Engineering — Project Handoff

**Last updated:** 2026-08-16  
**Active branch:** `feature/paper-trading`  
**Current focus:** Crypto 15m V2 frozen forward monitoring + XRP V1 Phase 6 shadow forward monitoring

---

## 1. Read this first

A new engineering session should read, in order:

1. `PROJECT_HANDOFF.md` — this file
2. `README.md` — current platform architecture and safety boundary
3. `models/README.md` — model/research lineage and artifact rules
4. `ml/crypto_15m_v2/phase5.py` — frozen shared V2 candidate contract
5. `ml/crypto_15m_v2/forward_service.py` — live frozen shared V2 inference
6. `ml/crypto_xrp_v1/phase6.py` — frozen XRP exploratory forward-candidate contract
7. `ml/crypto_xrp_v1/forward_service.py` — shadow-only XRP forward inference
8. `ml/crypto_rt/reconcile_15m.py` — authoritative closed-bar reconciliation
9. `webapp/services/crypto_dashboard_service.py`
10. `webapp/templates/crypto.html`
11. `docs/XRP_PHASE6_FORWARD_MONITOR.md`

Do **not** retrain or mutate the frozen shared V2 Phase 5 candidate. Do **not** change `confirm_2` in place. Do **not** backfill future-journal rows. Do **not** continue XRP threshold/hold-period tuning on the same historical development folds. Do **not** add XRP to shared V2. Do **not** place real brokerage orders.

---

## 2. Current state

Data Shepherd Engineering now has:

- authenticated stock/crypto web application at `datashepherdengineering.com`
- stock research and paper-monitoring components
- multi-year Coinbase 15-minute crypto archive
- continuous crypto data ingestion and authoritative closed-bar reconciliation
- Crypto 15m V1 research
- frozen Crypto 15m V2 BTC / ALT / CASH forward candidate
- dedicated XRP V1 research through Phase 6
- frozen XRP exploratory forward-candidate artifact and manifest
- unattended macOS LaunchAgents for web, reconciliation, shared V2 forward inference, and XRP forward inference
- Crypto dashboard with live shared V2 state and a separate XRP Phase 6 shadow monitor

The shared Crypto 15m V2 candidate is frozen before the untouched future evaluation beginning **2026-09-01 00:00 UTC**.

The XRP Phase 6 candidate is also frozen before the same date boundary, but its current service is deliberately **shadow-only** and does **not** automatically become a scored forward-performance journal. A separate future-evaluation phase must be created before XRP forward observations are scored or considered for promotion.

---

## 3. Frozen shared Crypto 15m V2 candidate

Frozen contract:

```text
research version: crypto_15m_v2
phase: 5
model: hist_gradient_boosting
features: 44
decision cadence: 1 hour
economic horizon: 4 hours
execution policy: confirm_2
future evaluation start: 2026-09-01T00:00:00Z
XRP: excluded / separate
real orders: disabled
```

Model artifact:

```text
data/model/crypto_15m_v2/phase5/frozen_hgb.joblib
```

Model SHA-256:

```text
9f2760f05fca4d3b6cc1e02fc700c4cdf7eeedc5e5d67208c62b534f3a458a6b
```

Training population:

- 49,209 rows
- through 2026-08-14 20:00 UTC
- 44 features

Phase 4 exploratory `confirm_2` evidence:

- raw hourly switches: 6,084
- executed switches: 2,505
- switch reduction: 58.8%
- ending equity at 0 bps: 4.2469x
- ending equity at 5 bps: 1.2134x
- max drawdown at 0 bps: -54.99%
- max drawdown at 5 bps: -66.43%

These are historical development results, not untouched future validation.

Current Phase 5 files:

```text
data/model/crypto_15m_v2/phase5/
├── frozen_hgb.joblib
├── freeze_manifest.json
├── forward_state.json
├── forward_journal.csv
├── forward_service_status.json
└── shadow_latest.json
```

Shared V2 forward behavior:

1. verify frozen model hash
2. identify latest safe hourly decision timestamp
3. reconstruct the frozen 44-feature row from reconciled 15-minute data
4. require BTC
5. permit sparse/ineligible ALT assets as long as frozen breadth requirements are met
6. predict BTC / ALT / CASH probabilities
7. apply frozen `confirm_2`
8. before 2026-09-01: update shadow snapshot only
9. at/after 2026-09-01: append genuinely new forward decisions
10. never replay/backfill missed holdout decisions
11. never place brokerage orders

---

## 4. Dedicated XRP V1 research lineage

XRP remains separate from shared Crypto 15m V2 because its historical archive contains a major structural discontinuity.

Model-ready XRP panel:

- 170,315 rows
- 20 contiguous segments
- 44 features
- 15m / 1h / 4h / 24h targets
- largest model-ready discontinuity: 907.11 days
- discontinuity: 2021-01-18 18:00 UTC -> 2023-07-14 20:45 UTC
- legacy era: 63,333 rows / 13 segments
- primary post-gap era: 106,982 rows / 7 segments

### Phase 1

Created discontinuity-aware XRP datasets and kept legacy/post-gap eras separate.

### Phase 2

Walk-forward regression on the post-gap era only.

Primary target:

```text
btc_relative_forward_return_4h
```

Ridge was the most stable research candidate:

- positive Spearman in all eight folds
- aggregate OOS Spearman approximately 0.0257
- aggregate directional accuracy approximately 52.1%

### Phase 3

Confidence/sign diagnostics using existing Phase 2 OOS predictions. Confidence-only threshold promotion was rejected.

### Phase 4

Exploratory XRP / BTC / CASH state policies. High turnover made fixed-threshold switching too cost-sensitive.

### Phase 5

Exploratory hysteresis and minimum-hold research.

Selected exploratory hypothesis:

```text
policy: hyst_10_05_hold24
model: Ridge
target: btc_relative_forward_return_4h
decision cadence: 4 hours

enter XRP:   score >= +0.0010
enter CASH:  score <= -0.0010
leave XRP:   score <= +0.0005
leave CASH:  score >= -0.0005
neutral:     BTC
minimum hold: 24 hours
```

Development evidence:

- decisions: 3,987
- switches: 524
- switch rate: 13.14%
- ending equity at 0 bps: 1.7463x
- ending equity at 5 bps: 1.3437x
- ending equity at 10 bps: 1.0338x
- ending equity at 20 bps: 0.6117x
- always-BTC development reference: approximately 1.0162x

Fold performance remains mixed. These are exploratory development results, not untouched validation.

### Phase 6 — frozen exploratory forward candidate

Phase 6 performs **no new model selection or threshold tuning**. It freezes the existing Phase 5 hypothesis for reproducible shadow-forward monitoring.

Frozen contract:

```text
research version: crypto_xrp_v1
phase: 6
research status: EXPLORATORY FORWARD CANDIDATE
model: Ridge
pipeline: median imputer -> StandardScaler -> Ridge(alpha=10.0)
target: btc_relative_forward_return_4h
features: 44
training rows: 106,982
training population: post-major-discontinuity primary era only
decision cadence: 4 hours
policy: hyst_10_05_hold24
minimum hold: 24 hours
future boundary: 2026-09-01T00:00:00Z
promotion status: NOT PROMOTED FOR REAL TRADING
brokerage orders: disabled
```

Frozen model:

```text
data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib
```

SHA-256:

```text
4c3f69b4bd41bf69cfaf7ce0633d53fb2e5bec10d1b9c8081fd295d6bfe45553
```

Manifest:

```text
data/model/crypto_xrp_v1/phase6/freeze_manifest.json
```

Reload equivalence at freeze: `0.0` max absolute prediction difference.

---

## 5. XRP Phase 6 shadow forward service

Module:

```text
ml/crypto_xrp_v1/forward_service.py
```

LaunchAgent:

```text
com.datashepherd.xrpforward
```

State/status files:

```text
data/model/crypto_xrp_v1/phase6/forward_state.json
data/model/crypto_xrp_v1/phase6/forward_service_status.json
data/model/crypto_xrp_v1/phase6/shadow_latest.json
```

Current behavior:

- verifies exact Phase 6 frozen model hash
- verifies frozen policy contract
- consumes authoritative reconciled BTC/XRP 15-minute bars
- reconstructs the exact 44-feature model row
- evaluates only genuinely available four-hour decision timestamps
- preserves the Phase 5 hysteresis and 24-hour minimum-hold state machine
- initializes/resets to BTC when continuity is not established
- never replays historical missed decisions
- never writes a forward-performance journal
- never places real orders
- never uses leverage, shorting, or derivatives
- never modifies shared Crypto V2

First verified shadow decision on 2026-08-16:

```text
mode: SHADOW_PRE_HOLDOUT
decision: 2026-08-16T20:00:00+00:00
score: -0.0018138020080860349
state: BTC
reset: initialization
model hash verified: true
policy verified: true
brokerage orders: false
```

The service was installed as an unattended LaunchAgent and verified running with empty stderr.

---

## 6. Data layer

Historical archive:

```text
data/research/crypto_intraday/raw_15m/
```

Rules:

- actual Coinbase listing history only
- no synthetic pre-listing candles
- no synthetic missing candles
- feature/target calculations respect continuity boundaries

Authoritative closed-bar reconciler:

```text
ml/crypto_rt/reconcile_15m.py
com.datashepherd.cryptoreconcile
```

Status:

```text
data/live/crypto_rt/reconcile_status.json
data/live/crypto_rt/latest_authoritative_15m.json
```

The reconciler fetches authoritative closed Coinbase REST candles after the settle delay, merges/deduplicates into the research archive, writes status, and never fits models or places orders.

---

## 7. Runtime services on Mac

Installed and verified running on 2026-08-16:

```text
com.datashepherd.web
com.datashepherd.cryptoreconcile
com.datashepherd.cryptov2forward
com.datashepherd.xrpforward
```

Status commands:

```bash
launchctl print gui/$(id -u)/com.datashepherd.web   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.xrpforward   | grep -E 'state =|runs =|pid =|last exit code'
```

---

## 8. Web application and Crypto dashboard

Public domain:

```text
datashepherdengineering.com
```

Member-account flow supports signup, Resend email verification, unique usernames, temporary passwords, forced first-login password change, and authenticated dashboard access.

Do not commit `.env`, Resend API keys, Flask secrets, user passwords, or other credentials.

The Crypto dashboard now has two separate live-monitor areas.

### Shared Crypto 15m V2 monitor

Displays:

- SHADOW / FORWARD mode
- executed sleeve
- raw prediction
- BTC / ALT / CASH probabilities
- eligible ALT count
- decision time
- reconciled-through time
- missing/ineligible ALT assets
- forward-journal counts
- explicit `REAL ORDERS: NO`
- historical Phase 4 research evidence

### XRP V1 Phase 6 monitor

Displays:

- XRP shadow mode
- current XRP/BTC/CASH shadow state
- 4-hour BTC-relative Ridge score
- decision timestamp
- frozen `hyst_10_05_hold24` policy
- 24-hour minimum hold
- model-hash verification
- policy verification
- XRP/BTC/common latest-bar timestamps
- state transition / switch status
- minimum-hold block status
- explicit `REAL ORDERS: NO`
- warning that no XRP performance journal exists yet

Dedicated documentation:

```text
docs/XRP_PHASE6_FORWARD_MONITOR.md
```

---

## 9. Important research boundaries

Do not violate these:

- no future leakage
- no future-holdout tuning
- no synthetic missing candles
- no synthetic pre-listing candles
- no retrospective universe membership
- no crossing data gaps in features/targets
- preserve chronological validation
- preserve horizon purge rules
- keep historical exploration separate from future validation
- do not overwrite shared V2 Phase 5
- do not backfill shared V2 Sep. 1+ journal rows
- keep XRP separate from shared V2
- do not continue XRP threshold/hold-period tuning on the same development folds
- preserve XRP Sep. 1 boundary
- keep current XRP Phase 6 service shadow-only
- do not score XRP forward performance until a separate future-evaluation phase exists
- no leverage
- no shorting
- no derivatives
- no real brokerage orders

---

## 10. Current known limitations

1. ALT constituent-level rebalance costs are not modeled in the V2 historical sleeve simulation.
2. Shared V2 Phase 4 `confirm_2` results are exploratory, not untouched validation.
3. There are no Sep. 1+ shared V2 forward results yet.
4. Some ALT assets may be temporarily missing or feature-ineligible at a specific hourly decision.
5. XRP Phase 4/5 results are exploratory and fold performance remains mixed.
6. XRP Phase 6 has no performance journal by design; genuine forward scoring still requires a separate future-evaluation phase.
7. Operational alerting/staleness detection still needs strengthening.

---

## 11. Next recommended work

### Highest priority

**Monitor both frozen forward systems and add operational staleness/health alerting without changing either frozen contract.**

Current forward systems:

- shared Crypto 15m V2: frozen HGB + `confirm_2`
- XRP V1 Phase 6: frozen Ridge + `hyst_10_05_hold24`, shadow-only
- both are non-brokerage systems

Next implementation steps:

1. verify the XRP Phase 6 dashboard panel against live runtime files
2. add staleness/health checks for reconciliation, shared V2 forward, XRP forward, and web service
3. preserve both Sep. 1 boundaries
4. do not backfill missed decisions
5. keep XRP performance journaling disabled until a separate future-evaluation phase is explicitly created
6. never place real orders

After that:

1. Add forward equity/performance charts only after genuine future-evaluation rows exist.
2. Research ALT constituent-level transaction costs in a new research version; do not mutate shared V2 Phase 5.
3. Continue stock-model work without changing frozen benchmarks.

---

## 12. Resume checklist

A new session should begin with:

```bash
cd ~/Data-Shepherd-Engineering/stock-market-ai-platform
source .venv/bin/activate

git pull --ff-only origin feature/paper-trading
git status --short
git log -10 --oneline --decorate

launchctl print gui/$(id -u)/com.datashepherd.web   | grep -E 'state =|runs =|pid =|last exit code'
launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'
launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'
launchctl print gui/$(id -u)/com.datashepherd.xrpforward   | grep -E 'state =|runs =|pid =|last exit code'

cat data/live/crypto_rt/reconcile_status.json
cat data/model/crypto_15m_v2/phase5/forward_service_status.json
cat data/model/crypto_xrp_v1/phase6/forward_service_status.json
wc -l data/model/crypto_15m_v2/phase5/forward_journal.csv
```

Before Sep. 1 the shared V2 journal should remain header-only. XRP Phase 6 currently has no performance journal by design.

---

## 13. Bootstrap prompt for the next engineering session

```text
Continue Data Shepherd Engineering from PROJECT_HANDOFF.md.

Read, in order:
1. PROJECT_HANDOFF.md
2. README.md
3. models/README.md
4. ml/crypto_15m_v2/phase5.py
5. ml/crypto_15m_v2/forward_service.py
6. ml/crypto_xrp_v1/phase6.py
7. ml/crypto_xrp_v1/forward_service.py
8. ml/crypto_rt/reconcile_15m.py
9. webapp/services/crypto_dashboard_service.py
10. webapp/templates/crypto.html
11. docs/XRP_PHASE6_FORWARD_MONITOR.md

Then inspect git status, latest commits, and all runtime LaunchAgents.

Do not retrain or modify the frozen Crypto 15m V2 Phase 5 candidate.
Do not tune confirm_2.
Do not backfill future-journal rows.
Do not add XRP to the shared V2 model.
Do not tune XRP thresholds or hold periods further on the same historical folds.
Do not create or backfill an XRP performance journal without a new future-evaluation phase.
Do not place real brokerage orders.

Current next task: verify the live XRP Phase 6 dashboard monitor, then add service staleness/health alerting while preserving both frozen contracts and the 2026-09-01 boundaries.
```