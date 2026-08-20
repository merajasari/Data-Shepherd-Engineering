# Data Shepherd Engineering — V8 Frozen Platform Milestone

**Milestone date:** 2026-08-19  
**Branch:** `feature/paper-trading`  
**Purpose:** Durable recovery point after the V6/V7 research path, V8 candidate selection/freeze, forward-monitoring buildout, model-comparison rebuild, V8 operational migration, and dashboard performance work.

## Why this milestone exists

This document is intentionally a checkpoint. If later research, dashboard work, or operational changes move the project in a bad direction, return to the Git history around this milestone rather than trying to reconstruct the V8 state from memory.

The most important invariant is that the V8 research candidate is already frozen. Operational/dashboard work must not silently change its specification.

## Research path to this point

### V6
V6 was the next stock-model research track after the earlier V4/V5 work. It was explored as a research candidate but was not selected as the final operational model and is intentionally excluded from the current model-performance comparison.

### V7
V7 focused heavily on robustness and conditional/context diagnostics. Important phases included continuous breadth incremental-information testing after SPY declines and episode/context heterogeneity diagnostics. The work produced useful evidence but did not become the final candidate; V7 is also intentionally excluded from the current model-performance comparison.

A representative V7 Phase 7 result tested continuous 5-session cross-sectional breadth after prior SPY 20-session declines of at least 5%, controlling for SPY 5-session and 20-session returns. Its robustness gates passed, but no candidate was frozen and the future holdout remained sealed.

### V8
V8 became the selected stock research line. Across Phases 1–6 the project narrowed and stress-tested the candidate, including pre-freeze robustness and concentration/name-exposure checks. Phase 7 formally froze the exact candidate.

## Frozen V8 candidate

**Candidate ID:** `V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS`

**Frozen SHA-256:** `ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41`

### Signal contract
- Raw feature: `distance_from_low_20d`
- Neutralization: same-day cross-sectional residualization
- Controls: `volatility_20d`, `beta_60`
- Ranking direction: higher residual signal ranks higher
- Signal ID: `DISTANCE_ONLY`

### Portfolio contract
- Long only
- Fully invested
- No leverage
- No shorting
- Top 10
- Equal weight

### Execution contract
- Decision information: completed trading session only
- Entry: next trading-session open
- Exit: open five trading sessions after entry
- Holding period: 5 trading sessions
- Cohort offsets: 0, 1, 2, 3, 4
- No cohort selection

### Cost contract
- Primary cost: 10 bps per dollar traded
- Cost basis: actual equal-weight transition notional
- First entry is charged
- No forced final liquidation

### Explicit non-rules
The frozen strategy does **not** dynamically tune costs, holding period, Top-N, market regime, high-volatility filters, or signal weights.

## Holdout boundary and research safety

The formal forward holdout starts at:

`2026-09-01T00:00:00+00:00`

At freeze time:
- candidate frozen = true
- development research closed = true
- future holdout scored = false
- brokerage orders = false

The frozen SHA is the contract. A holdout result is valid only if it is generated from that exact specification. Do not optimize the candidate using post-freeze/holdout evidence.

## Forward holdout monitoring

The project now has a dedicated V8 frozen holdout runner and read-only dashboard monitoring.

Key components:
- `ml/v8/holdout_runner.py`
- `webapp/services/v8_holdout_service.py`
- `webapp/static/js/v8_holdout_monitor.js`
- `scripts/install_v8_holdout_monitor_launchagent.sh`

Behavior:
- Before 2026-09-01 UTC: status only; no holdout journal evidence.
- After the boundary: append-only DECISION / ENTRY / EXIT evidence.
- Duplicate events are skipped.
- Dashboard monitoring is read-only.
- No brokerage orders.
- The frozen SHA is enforced.

The macOS LaunchAgent is designed to wake periodically, perform its check, and exit. Therefore `state = not running` with `last exit code = 0` between scheduled runs is healthy behavior.

## V8 operational paper monitor

A separate operational paper-monitoring path exists because we still want current operational visibility without contaminating the sealed forward holdout.

Key components:
- `ml/v8/paper_runner.py`
- `scripts/install_v8_paper_monitor_launchagent.sh`
- operational paper journal/state consumed by the dashboard

This monitor:
- uses the frozen V8 candidate
- is paper/diagnostic only
- never sends brokerage orders
- must never be treated as formal holdout evidence
- runs on a periodic LaunchAgent cadence

The runner also publishes a lightweight dashboard ranking snapshot:

`data/live/v8_latest_rankings.json`

This snapshot is important to dashboard performance because the web request path should not scan research-scale V8 Parquet data merely to render current rankings.

## Stock model performance comparison

The comparison chart is intentionally a historical/research comparison and must remain separate from operational paper accounting.

Current comparison set:
- V4
- V5
- V8
- SPY benchmark

Explicitly excluded:
- V6
- V7
- live paper balance

The latest reconstructed comparison produced at this milestone reported approximately:
- V4: 2016-10-25 through 2026-08-07, final normalized $100k equity about $247,544.87
- V5: 2021-07-01 through 2026-08-07, final normalized $100k equity about $260,554.18
- V8: 2016-10-26 through 2026-08-14, final normalized $100k equity about $654,317.43
- SPY: 2016-10-25 through 2026-08-14, final normalized $100k equity about $423,694.11

These are reconstructed comparison figures, not promises of future performance and not the formal Sep-2026+ holdout.

**Do not casually modify the MODEL PERFORMANCE COMPARISON chart while doing V8 operational dashboard work.** It was deliberately preserved as its own comparison artifact.

## Dashboard migration to V8

The stock dashboard is being migrated away from older V4/V5 operational references so that current operational rankings, predictions, paper monitoring, and holdout monitoring are V8-centered. Historical V4/V5 lines remain where they are intentionally part of the model-comparison research chart.

The operational paper portfolio is conceptually distinct from reconstructed model-comparison wealth: reconstructed histories answer “how would the model have performed under the historical simulation contract?” while the paper journal answers “what did the operational paper process actually record from its start?” They should not be spliced into one equity series with incompatible capital histories.

## Dashboard performance architecture

Page-load latency became a major engineering issue after adding long historical charts and V8 operational data. The current direction is to keep research-scale computation and files out of synchronous HTML rendering.

### Performance changes already made
1. V8 ranking data is published by the background paper runner into the small `data/live/v8_latest_rankings.json` snapshot.
2. Dashboard services read that snapshot rather than scanning the large V8 ranked Parquet during normal page requests.
3. Market/Parquet reads have been cached by modification time where appropriate.
4. Recent-price work was reduced to the small history tail required by the UI.
5. Top-10 enrichment (price/change/RSI) was moved out of the blocking initial HTML-render path and into lazy asynchronous loading.
6. The initial dashboard should render useful structure first and populate expensive secondary data afterward.

### Performance rule going forward
Do **not** add expensive Parquet scans, model reconstruction, multi-symbol technical calculations, or large-history transformations to the synchronous `/dashboard` request. Precompute them in background jobs, publish compact JSON/cache artifacts, or expose lazy API endpoints.

## Historical chart work

The old portfolio-equity chart was rebuilt to match the interaction model of the full crypto-market-history chart, including range controls and interactive behavior. Historical reconstruction was expanded from roughly 90 days to nearly 10 years.

A full V4 reconstruction created 2,459 observations from 2016-10-25 through 2026-08-07. The subsequent direction changed from a single V4 equity chart toward the dedicated multi-model performance comparison described above.

The model comparison should default to a useful shorter viewing window (3 years was selected for initial display) while retaining longer range options, including the full available history.

## Current architecture boundaries

Keep these concepts separate:

**Research comparison** — historical reconstructed V4/V5/V8 + SPY, normalized for comparison.

**V8 operational paper monitor** — current paper process, operational visibility, not formal holdout evidence.

**V8 frozen forward holdout** — begins 2026-09-01 UTC, exact frozen SHA, append-only evidence, no tuning.

**Brokerage execution** — not enabled by this milestone; no orders are sent.

## Recovery procedure

If future work destabilizes the project:

1. Stop and identify the last known-good commit around this milestone on `feature/paper-trading`.
2. Preserve any new data/journals before resetting code.
3. Verify the V8 frozen SHA is still:
   `ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41`
4. Verify the formal holdout journal was not rewritten or backfilled improperly.
5. Restore the code to this milestone or create a recovery branch from it.
6. Reinstall/restart the V8 paper and holdout LaunchAgents if needed.
7. Restart the web LaunchAgent.
8. Confirm the dashboard uses the lightweight V8 ranking snapshot and does not perform research-scale work synchronously.

Useful local checks:

```bash
cd ~/Data-Shepherd-Engineering/stock-market-ai-platform
source .venv/bin/activate

git status --short
git log --oneline -15

cat data/model/v8/phase7/frozen_candidate.sha256
ls -lh data/live/v8_latest_rankings.json

launchctl print gui/$(id -u)/com.datashepherd.v8papermonitor \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.v8holdoutmonitor \
  | grep -E 'state =|runs =|pid =|last exit code'

launchctl print gui/$(id -u)/com.datashepherd.web \
  | grep -E 'state =|runs =|pid =|last exit code'
```

## Known important commits in this development sequence

These commits were explicitly observed during the milestone work and are useful breadcrumbs:
- `ed4fbe7` — Freeze V8 candidate and add forward holdout monitoring
- `5dc739b`, `c268e47` — portfolio/model chart interaction work
- `9583810`, `fb2b9f8`, `d94f336` — full-history reconstruction build/fixes
- `3e6c228` — V8 paper runner and broader V8 dashboard operational migration
- `50baa1c` — lightweight V8 dashboard ranking snapshot/caching work
- `072d226` — market-data caching/performance work
- `500af99`, `27ece39` — lazy Top-10 dashboard enrichment/performance work

The documentation commit containing this file is itself the preferred human-readable checkpoint marker after those changes.

## What must not be lost

- Frozen V8 candidate specification and SHA
- Sep 1, 2026 forward-holdout boundary
- Append-only holdout evidence discipline
- Separation of operational paper data from formal holdout evidence
- V6/V7 exclusion from the model-performance comparison
- V4/V5/V8/SPY historical comparison artifact
- No brokerage orders
- Background-precompute / lightweight-snapshot / lazy-load dashboard architecture
- The rule that future model changes become a new version/candidate rather than silently altering frozen V8

---

**Milestone statement:** V8 is now a formally frozen research candidate with a protected future holdout, a separate operational paper monitor, historical model-comparison infrastructure, and a dashboard architecture being moved away from research-scale synchronous computation. This is a safe return point before further model or platform experimentation.
