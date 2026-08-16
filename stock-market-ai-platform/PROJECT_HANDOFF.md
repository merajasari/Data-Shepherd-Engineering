# Data Shepherd Engineering — Project Handoff

**Last updated:** 2026-08-16  
**Active branch:** `feature/paper-trading`  
**Current focus:** Crypto 15m V2 frozen forward monitoring + dashboard integration

---

## 1. Read this first

A new engineering session should read, in order:

1. `PROJECT_HANDOFF.md` — this file
2. `README.md` — current platform architecture and safety boundary
3. `models/README.md` — model/research lineage and artifact rules
4. `ml/crypto_15m_v2/phase5.py` — frozen candidate contract
5. `ml/crypto_15m_v2/forward_service.py` — live frozen inference
6. `ml/crypto_rt/reconcile_15m.py` — authoritative closed-bar reconciliation
7. `webapp/services/crypto_dashboard_service.py`
8. `webapp/templates/crypto.html`

Do **not** start by retraining the frozen V2 model. Do **not** change the `confirm_2` policy in place. Do **not** backfill future-journal rows.

---

## 2. Current state

Data Shepherd Engineering now has a working authenticated web platform, stock research/paper-monitoring components, continuous crypto data ingestion, a multi-year 15-minute Coinbase research archive, Crypto 15m V1 research, Crypto 15m V2 BTC/ALT/CASH regime research, a frozen forward candidate, unattended macOS runtime services, and a live Crypto dashboard that surfaces the frozen model state.

The shared Crypto 15m V2 candidate is frozen before the untouched future evaluation beginning **2026-09-01 00:00 UTC**.

---

## 3. Most recent completed milestone

### Crypto 15m V2 Phase 5 freeze

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

---

## 4. Why `confirm_2` was frozen

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

## 7. XRP policy

XRP is intentionally excluded from the shared intraday model.

Reason:

- XRP historical 15-minute coverage contains a very large discontinuity.
- the gap is fundamentally different from ordinary isolated missing candles.
- the shared model should not absorb this history as if it were continuous.

Phase 1 already created:

```text
data/model/crypto_15m_v1/phase1/xrp_panel.parquet
```

A dedicated XRP model remains future work.

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

## 9. Frozen forward inference service

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

Latest successful shadow example:

- mode: SHADOW
- decision: 2026-08-16 20:00 UTC
- raw prediction: ALT
- executed sleeve: ALT
- eligible ALTs: 19
- probabilities:
  - ALT: 44.45%
  - CASH: 33.66%
  - BTC: 21.89%
- missing exact-hour ALT: ETC-USD
- feature-ineligible: INJ-USD, OP-USD, SHIB-USD
- journal rows before holdout: 0

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

Member-account flow now supports:

- signup
- Resend email verification
- unique user-selected username
- temporary generated password
- forced password change at first login
- authenticated dashboard access

Resend sending domain:

```text
datashepherdengineering.com
```

DKIM/SPF verification succeeded.

Do not commit `.env`, Resend API keys, Flask secrets, user passwords, or other credentials.

### Crypto dashboard

The Crypto tab now displays the frozen Crypto 15m V2 live/shadow state:

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

The old unavailable Crypto V1 block was replaced with Crypto 15m V2 research evidence.

The research-evidence section displays:

- `confirm_2`
- 6,084 raw switches
- 2,505 executed switches
- 58.8% turnover reduction
- 4.2469x at 0 bps
- 1.2134x at 5 bps
- historical development drawdowns
- explicit exploratory/not-future-validation language
- ALT constituent-cost limitation

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
- do not overwrite the Phase 5 freeze
- do not backfill the Sep. 1+ forward journal
- keep XRP separate from shared V2
- no leverage
- no shorting
- no derivatives
- no real brokerage orders in the current frozen system

---

## 13. Current known limitations

1. ALT constituent-level rebalance costs are not modeled in the V2 historical sleeve simulation.
2. Phase 4 `confirm_2` results are exploratory, not untouched validation.
3. There are no Sep. 1+ forward results yet.
4. Some ALT assets may be temporarily missing or feature-ineligible at a specific hourly decision.
5. XRP still needs its dedicated intraday model.
6. The live Crypto dashboard currently renders server-side snapshots; automatic in-place refresh is still pending.
7. The project still needs stronger operational alerting around service failure/staleness.

---

## 14. Next recommended work

### Highest priority

**Add auto-refresh to the Crypto V2 live monitor.**

The page should refresh only the live state, not reload the entire page. Use the authenticated crypto API and update:

- mode
- executed sleeve
- raw prediction
- probabilities
- eligible ALT count
- decision timestamp
- reconciliation timestamp
- missing/ineligible ALT lists
- forward journal counts

### After that

1. Build dedicated XRP research.
2. Add alerting/staleness health checks.
3. Add forward equity/performance charts after genuine Sep. 1+ rows exist.
4. Research ALT constituent-level transaction costs in a new research version; do not mutate the Phase 5 freeze.
5. Continue stock-model work without changing frozen benchmarks.

---

## 15. Resume checklist

A new session should begin with:

```bash
cd ~/Data-Shepherd-Engineering/stock-market-ai-platform
source .venv/bin/activate

git pull --ff-only origin feature/paper-trading
git status --short
git log -8 --oneline --decorate

launchctl print gui/$(id -u)/com.datashepherd.web   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptoreconcile   | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.cryptov2forward   | grep -E 'state =|runs =|pid =|last exit code'

cat data/live/crypto_rt/reconcile_status.json
cat data/model/crypto_15m_v2/phase5/forward_service_status.json
wc -l data/model/crypto_15m_v2/phase5/forward_journal.csv
```

Before Sep. 1 the journal should remain header-only.

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
6. ml/crypto_rt/reconcile_15m.py
7. webapp/services/crypto_dashboard_service.py
8. webapp/templates/crypto.html

Then inspect git status, the latest commits, and all three LaunchAgents.

Do not retrain or modify the frozen Crypto 15m V2 Phase 5 candidate.
Do not tune confirm_2.
Do not backfill future-journal rows.
Do not add XRP to the shared V2 model.
Do not place real brokerage orders.

Current next task: add in-place auto-refresh to the live Crypto V2 dashboard monitor while preserving the research/future-evaluation boundary.
```
