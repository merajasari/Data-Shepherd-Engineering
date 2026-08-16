# Data Shepherd Engineering — Project Handoff

**Last updated:** 2026-08-16  
**Active branch:** `feature/paper-trading`  
**Current focus:** Crypto 15m V2 frozen forward monitoring + XRP V1 exploratory forward-candidate preparation

---

## 1. Read this first

A new engineering session should read, in order:

1. `PROJECT_HANDOFF.md` — this file
2. `README.md` — current platform architecture and safety boundary
3. `models/README.md` — model/research lineage and artifact rules
4. `ml/crypto_15m_v2/phase5.py` — frozen shared V2 candidate contract
5. `ml/crypto_15m_v2/forward_service.py` — live frozen shared V2 inference
6. `ml/crypto_xrp_v1/phase5.py` — XRP exploratory forward-candidate research contract
7. `ml/crypto_rt/reconcile_15m.py` — authoritative closed-bar reconciliation
8. `webapp/services/crypto_dashboard_service.py`
9. `webapp/templates/crypto.html`

Do **not** start by retraining the frozen V2 model. Do **not** change the `confirm_2` policy in place. Do **not** backfill future-journal rows. Do **not** continue XRP threshold/hold-period tuning on the same historical development folds.

---

## 2. Current state

Data Shepherd Engineering now has a working authenticated web platform, stock research/paper-monitoring components, continuous crypto data ingestion, a multi-year 15-minute Coinbase research archive, Crypto 15m V1 research, Crypto 15m V2 BTC/ALT/CASH regime research, a frozen shared V2 forward candidate, unattended macOS runtime services, a live Crypto dashboard with in-place auto-refresh, and a dedicated XRP V1 research track through exploratory Phase 5.

The shared Crypto 15m V2 candidate is frozen before the untouched future evaluation beginning **2026-09-01 00:00 UTC**.

The XRP V1 historical development sequence is also complete through Phase 5. Its current `hyst_10_05_hold24` rule is an **exploratory forward candidate only**, not a historically validated or trading-promoted strategy. The Sep. 1 boundary must remain untouched.

---

## 3. Most recent completed milestones

### Shared Crypto 15m V2 Phase 5 freeze

Frozen candidate:

- model: `hist_gradient_boosting`
- model artifact: `data/model/crypto_15m_v2/phase5/frozen_hgb.joblib`
- model SHA-256:
  `9f2760f05fca4d3b6cc1e02fc700c4cdf7eeedc5e5d67208c62b534f3a458a6b`
- training rows: 49,209
- training through: 2026-08-14 20:00 UTC
- features: 44
- decision cadence: 1 hour
- economic horizon: 4 hours
- execution policy: `confirm_2`
- initial sleeve: ALT
- future evaluation start: 2026-09-01 00:00 UTC
- XRP: separate
- real orders: disabled

Phase 5 files:

```text
data/model/crypto_15m_v2/phase5/
├── frozen_hgb.joblib
├── freeze_manifest.json
├── forward_state.json
├── forward_journal.csv
├── forward_service_status.json
└── shadow_latest.json
```

### XRP V1 Phase 5 exploratory candidate selection

Dedicated XRP code:

```text
ml/crypto_xrp_v1/
├── __init__.py
├── phase1.py
├── phase2.py
├── phase3.py
├── phase4.py
└── phase5.py
```

Current exploratory XRP hypothesis:

```text
policy: hyst_10_05_hold24
model: Ridge
target: btc_relative_forward_return_4h
decision cadence: 4 hours

enter XRP:  score >= +0.0010
enter CASH: score <= -0.0010
leave XRP:  score <= +0.0005
leave CASH: score >= -0.0005
neutral: BTC
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

Fold performance remains mixed. This candidate is **not promoted for trading**.

---

## 4. Why `confirm_2` was frozen for shared V2

Crypto 15m V2 Phase 3 showed a strong gross regime signal but unacceptable raw hourly switching.

Raw HGB hourly simulation:

- switches: 6,084
- ending equity at 0 bps: 3.722965x
- ending equity at 5 bps: 0.177597x

Phase 4 explored fixed turnover-control policies. `confirm_2` was the only tested policy that remained above starting equity at the 5 bps sleeve-switch assumption.

`confirm_2` exploratory evidence:

- executed switches: 2,505
- switch reduction: 58.8%
- ending equity at 0 bps: 4.246942x
- ending equity at 5 bps: 1.213351x
- max drawdown at 0 bps: -54.99%
- max drawdown at 5 bps: -66.43%

**Research-status warning:** Phase 4 is exploratory. The Phase 3 OOS results had already been inspected before Phase 4 policies were defined. Therefore these Phase 4 figures are not untouched validation.

---

## 5. Crypto 15m V2 research lineage

### Phase 1 — hourly BTC / ALT / CASH allocation dataset

Output:

```text
data/model/crypto_15m_v2/phase1/market_allocation_1h.parquet
```

Observed dataset:

- rows: 49,209
- date range: 2020-12-16 17:00 UTC through 2026-08-14 20:00 UTC
- features: 44
- target distribution:
  - BTC: 10,099 (20.52%)
  - ALT: 19,845 (40.33%)
  - CASH: 19,265 (39.15%)

### Phase 2 — walk-forward classification

Models:

- majority-class baseline
- multinomial logistic regression
- HistGradientBoosting

HGB summary:

- weighted accuracy: 0.422269
- weighted balanced accuracy: 0.356516
- weighted log loss: 1.064313
- mean selected 4h forward return: 0.000220
- mean excess vs BTC: 0.000043773
- mean excess vs ALT: 0.000108
- prediction fractions:
  - BTC: 1.13%
  - ALT: 54.28%
  - CASH: 44.59%

### Phase 3 — hourly portfolio simulation

Gross signal was strong, but frequent sleeve switching destroyed results under costs.

### Phase 4 — exploratory turnover control

Selected `confirm_2` as the candidate execution rule.

### Phase 5 — frozen future candidate

No further tuning is permitted without creating a new research version.

---

## 6. Crypto 15m V1 lineage

Crypto 15m V1 used a shared cross-sectional model universe with XRP isolated.

Phase 1:

- 24 shared assets
- XRP separate
- shared panel rows: 4,713,634
- dedicated XRP rows: 170,315
- 44 features
- horizons: 15m / 1h / 4h / 24h
- no synthesized candles
- no feature/target crossing a missing-data gap

Phase 2:

- Ridge had a small positive 4-hour BTC-relative cross-sectional ranking signal.
- HistGradientBoosting was approximately flat for ranking.
- momentum was negative.

Phase 3:

- Top-3 / Top-5 overlapping 4-hour designs were rejected.
- Turnover was extreme.
- even zero-cost portfolios lost money.
- transaction costs made the designs unusable.

This failure motivated V2's BTC / ALT / CASH regime architecture.

---

## 7. Dedicated XRP V1 research track

XRP remains intentionally excluded from the shared Crypto 15m V2 model.

Reason:

- XRP historical 15-minute coverage contains a major structural discontinuity.
- the raw archive audit identified approximately 905 days of missing history.
- the leakage-safe model-ready panel places the largest continuity break at 907.11 days, from 2021-01-18 18:00 UTC to 2023-07-14 20:45 UTC.
- XRP must remain a separate research version rather than being absorbed into the shared V2 universe.

### XRP Phase 1 — discontinuity-aware dataset

Source:

```text
data/model/crypto_15m_v1/phase1/xrp_panel.parquet
```

Observed model-ready panel:

- total rows: 170,315
- contiguous segments: 20
- features: 44
- horizons: 15m / 1h / 4h / 24h
- no feature or target crosses a missing-data gap
- future boundary: 2026-09-01 00:00 UTC

Era split:

- legacy era: 63,333 rows / 13 segments / 2019-03-01 through 2021-01-18
- primary post-gap era: 106,982 rows / 7 segments / 2023-07-14 through 2026-08-14

### XRP Phase 2 — walk-forward regression

Primary target:

```text
btc_relative_forward_return_4h
```

Models:

- 4-hour BTC-relative momentum baseline
- Ridge regression
- HistGradientBoosting regression

Validation:

- post-gap primary era only
- expanding chronological walk-forward folds
- 4-hour target purge
- eight OOS folds
- no Sep. 1+ observations

Ridge was the most stable candidate:

- positive Spearman in all eight folds
- aggregate OOS Spearman approximately 0.0257
- aggregate directional accuracy approximately 52.1%

No model was promoted during Phase 2.

### XRP Phase 3 — confidence diagnostics

Phase 3 used only existing Phase 2 OOS Ridge predictions.

Findings:

- prediction magnitude showed some aggregate discrimination
- highest absolute-confidence decile had approximately 53.1% directional accuracy
- confidence performance was not stable enough across folds to define a trading threshold
- negative Ridge predictions were directionally more reliable than positive predictions

No threshold was promoted.

### XRP Phase 4 — exploratory economic policies

Phase 4 introduced XRP / BTC / CASH state policies on a non-overlapping 4-hour grid.

Fixed exploratory thresholds:

- zero
- +/-0.0005
- +/-0.0010
- +/-0.0020

Switching-cost scenarios:

- 0 bps
- 5 bps
- 10 bps
- 20 bps

Finding:

- raw policy economics were highly sensitive to turnover
- frequent state switching destroyed the apparent edge after modest transaction costs
- Phase 4 rejected high-turnover threshold switching as a promotion candidate

**Research-status warning:** Phase 4 was designed after inspection of earlier XRP results and is exploratory development evidence, not untouched validation.

### XRP Phase 5 — turnover-controlled exploratory research

Phase 5 tested hysteresis plus 8h / 12h / 24h minimum holding periods.

The strongest exploratory hypothesis was `hyst_10_05_hold24`, defined above.

Its aggregate development evidence:

- decisions: 3,987
- switches: 524
- switch rate: 13.14%
- ending equity at 0 bps: 1.7463x
- ending equity at 5 bps: 1.3437x
- ending equity at 10 bps: 1.0338x
- ending equity at 20 bps: 0.6117x
- always-BTC development reference: approximately 1.0162x

The 24-hour hold materially reduced turnover compared with Phase 4, but fold performance remains mixed.

### XRP forward-candidate rules from this point

- `hyst_10_05_hold24` is an **EXPLORATORY FORWARD CANDIDATE** only.
- do not continue tuning thresholds or holding periods on the same development folds.
- do not add XRP to frozen Crypto 15m V2.
- do not describe Phase 4/5 results as untouched validation.
- preserve 2026-09-01 00:00 UTC as the untouched forward boundary.
- any XRP forward service must initially be shadow/research only.
- no brokerage orders.
- no leverage.
- no shorting.
- no derivatives.

The next XRP engineering step is to create a reproducible frozen-candidate artifact/manifest and shadow-only forward inference path without changing the selected rule.

---

## 8. Data layer

### Historical

Authoritative archive:

```text
data/research/crypto_intraday/raw_15m/
```

Rules:

- actual Coinbase listing history only
- no synthetic pre-listing candles
- no synthetic missing candles
- feature/target calculations must respect continuity boundaries

### Continuous low-latency feed

Service/module:

```text
ml/crypto_rt/coinbase_stream.py
```

The public Coinbase WebSocket provides live ticker data.

### Authoritative closed-bar reconciliation

Module:

```text
ml/crypto_rt/reconcile_15m.py
```

LaunchAgent:

```text
com.datashepherd.cryptoreconcile
```

Current expected behavior:

- poll continuously
- after the settle delay, fetch authoritative closed Coinbase REST candles
- merge/deduplicate into the research archive
- write status
- never fit models
- never create targets
- never place orders

Status files:

```text
data/live/crypto_rt/reconcile_status.json
data/live/crypto_rt/latest_authoritative_15m.json
```

A reconciliation lock bug was fixed on 2026-08-16. The corrected lock code writes the process ID with `fd.write(...)`.

---

## 9. Frozen shared V2 forward inference service

Module:

```text
ml/crypto_15m_v2/forward_service.py
```

LaunchAgent:

```text
com.datashepherd.cryptov2forward
```

Behavior:

1. verify frozen model hash
2. identify latest safe hourly decision timestamp
3. reconstruct the frozen 44-feature row from reconciled 15-minute data
4. require BTC
5. permit missing/ineligible ALT assets as long as the frozen minimum ALT breadth requirement is satisfied
6. predict BTC / ALT / CASH probabilities
7. apply frozen `confirm_2`
8. before 2026-09-01: update shadow snapshot only
9. at/after 2026-09-01: append genuinely new forward decisions
10. never replay/backfill missed holdout decisions
11. never place brokerage orders

The strict “every ALT must have the exact decision candle” behavior was corrected on 2026-08-16 because it did not match the V2 frozen feature contract.

---

## 10. Runtime services on Mac

Installed and running:

```text
com.datashepherd.web
com.datashepherd.cryptoreconcile
com.datashepherd.cryptov2forward
```

Status:

```bash
launchctl print gui/$(id -u)/com.datashepherd.web   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'
```

All three were verified running on 2026-08-16.

---

## 11. Web application

Public domain:

```text
datashepherdengineering.com
```

Member-account flow supports:

- signup
- Resend email verification
- unique user-selected username
- temporary generated password
- forced password change at first login
- authenticated dashboard access

Do not commit `.env`, Resend API keys, Flask secrets, user passwords, or other credentials.

### Crypto dashboard

The Crypto tab displays the frozen Crypto 15m V2 live/shadow state:

- mode
- executed sleeve
- raw prediction
- BTC / ALT / CASH probabilities
- eligible ALT count
- decision time
- reconciled-through time
- missing/ineligible ALT assets
- forward journal counts
- explicit `REAL ORDERS: NO`
- Crypto 15m V2 exploratory research evidence
- automatic in-place live-state refresh

---

## 12. Important research boundaries

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
- do not overwrite the shared V2 Phase 5 freeze
- do not backfill the Sep. 1+ shared V2 forward journal
- keep XRP separate from shared V2
- do not continue XRP threshold/hold-period tuning on the same development folds
- preserve the XRP Sep. 1 forward boundary
- no leverage
- no shorting
- no derivatives
- no real brokerage orders in the current frozen/exploratory systems

---

## 13. Current known limitations

1. ALT constituent-level rebalance costs are not modeled in the V2 historical sleeve simulation.
2. Shared V2 Phase 4 `confirm_2` results are exploratory, not untouched validation.
3. There are no Sep. 1+ forward results yet.
4. Some ALT assets may be temporarily missing or feature-ineligible at a specific hourly decision.
5. XRP Phase 4/5 results are exploratory and fold performance remains mixed.
6. XRP does not yet have a reproducible frozen artifact/manifest or forward shadow service.
7. The project still needs stronger operational alerting around service failure/staleness.

---

## 14. Next recommended work

### Highest priority

**Freeze the XRP V1 exploratory forward candidate reproducibly and build shadow-only forward monitoring.**

The exact historical-development rule is already selected and must not be tuned further on the same folds:

```text
hyst_10_05_hold24
Ridge
4h BTC-relative target
+0.0010 / -0.0010 entry thresholds
+0.0005 / -0.0005 exit hysteresis
BTC neutral state
24h minimum hold
```

Next implementation steps:

1. create a reproducible XRP candidate model artifact and manifest
2. record model/data/feature hashes and the exact rule contract
3. create shadow-only forward inference before Sep. 1
4. preserve state without backfilling missed forward decisions
5. begin genuine forward journaling only at/after 2026-09-01 UTC
6. never place real orders

### After that

1. Add alerting/staleness health checks.
2. Add forward equity/performance charts after genuine Sep. 1+ rows exist.
3. Research ALT constituent-level transaction costs in a new research version; do not mutate the shared V2 Phase 5 freeze.
4. Continue stock-model work without changing frozen benchmarks.

---

## 15. Resume checklist

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

cat data/live/crypto_rt/reconcile_status.json
cat data/model/crypto_15m_v2/phase5/forward_service_status.json
wc -l data/model/crypto_15m_v2/phase5/forward_journal.csv
```

Before Sep. 1 the shared V2 journal should remain header-only.

---

## 16. Bootstrap prompt for the next engineering session

```text
Continue Data Shepherd Engineering from PROJECT_HANDOFF.md.

Read, in order:
1. PROJECT_HANDOFF.md
2. README.md
3. models/README.md
4. ml/crypto_15m_v2/phase5.py
5. ml/crypto_15m_v2/forward_service.py
6. ml/crypto_xrp_v1/phase5.py
7. ml/crypto_rt/reconcile_15m.py
8. webapp/services/crypto_dashboard_service.py
9. webapp/templates/crypto.html

Then inspect git status, latest commits, and all runtime LaunchAgents.

Do not retrain or modify the frozen Crypto 15m V2 Phase 5 candidate.
Do not tune confirm_2.
Do not backfill future-journal rows.
Do not add XRP to the shared V2 model.
Do not tune XRP thresholds or hold periods further on the same historical folds.
Do not place real brokerage orders.

Current next task: freeze the exact XRP V1 hyst_10_05_hold24 exploratory candidate reproducibly and build shadow-only XRP forward monitoring while preserving the 2026-09-01 future boundary.
```