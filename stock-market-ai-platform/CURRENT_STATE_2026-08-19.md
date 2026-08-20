# Data Shepherd Engineering — Current State / Recovery Checkpoint

**Checkpoint date:** 2026-08-19 18:47 PT  
**Active development branch:** `feature/paper-trading`  
**Recovery branch:** `checkpoint/v8-frozen-platform-2026-08-19`  
**Detailed milestone:** `docs/MILESTONE_2026-08-19_V8_FROZEN_PLATFORM.md`

## Purpose

This file marks a deliberate major engineering checkpoint. If later model research, dashboard changes, or operational work goes in the wrong direction, preserve any new journals/data and return to this checkpoint rather than reconstructing the state from memory.

## Stock research lineage

- **V4:** historical benchmark and reconstructed comparison line.
- **V5:** historical benchmark and reconstructed comparison line.
- **V6:** exploratory research only; not selected; excluded from the current model-performance comparison.
- **V7:** robustness/context research including breadth incremental-information and episode/context heterogeneity diagnostics; not selected; excluded from the current model-performance comparison.
- **V8:** selected stock research line. Phases 1–6 narrowed and stress-tested the candidate. Phase 7 formally froze the exact candidate.

## Frozen V8 contract

```text
candidate: V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS
status: FROZEN
SHA-256: ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41
future holdout start: 2026-09-01T00:00:00+00:00
future holdout scored at checkpoint: false
development research closed: true
brokerage orders: false
```

Signal:
- `distance_from_low_20d`
- same-day cross-sectional residualization
- neutralization controls: `volatility_20d`, `beta_60`
- higher residual signal ranks higher

Portfolio/execution:
- long-only, fully invested, no leverage, no shorting
- Top 10, equal weight
- completed-session information only
- entry at next trading-session open
- exit at open five trading sessions after entry
- five cohort offsets: 0–4; no cohort selection
- 10 bps per dollar traded using actual equal-weight transition notional

No dynamic Top-N, holding-period, cost, regime, high-volatility, or signal-weight tuning is part of frozen V8.

## V8 forward systems

### Formal holdout

Components:
- `ml/v8/holdout_runner.py`
- `webapp/services/v8_holdout_service.py`
- `webapp/static/js/v8_holdout_monitor.js`
- `scripts/install_v8_holdout_monitor_launchagent.sh`

Rules:
- before Sep 1 UTC: status only, no holdout evidence
- after boundary: append-only DECISION / ENTRY / EXIT evidence
- duplicate events skipped
- exact frozen SHA enforced
- dashboard read-only
- no brokerage orders
- no retrospective backfill/tuning

### Operational paper monitor

Components:
- `ml/v8/paper_runner.py`
- `scripts/install_v8_paper_monitor_launchagent.sh`
- `data/live/v8_latest_rankings.json` lightweight ranking snapshot

The operational paper monitor uses frozen V8 for current visibility but is **not formal holdout evidence**. It must never contaminate or replace the Sep-1+ holdout journal.

## Model performance comparison

The dedicated comparison chart is a historical/research comparison and is intentionally separate from operational paper accounting.

Included:
- V4
- V5
- V8
- SPY

Excluded:
- V6
- V7
- live paper balance

Checkpoint reconstruction figures:

```text
V4: 2016-10-25 -> 2026-08-07 | $247,544.87 | +147.54%
V5: 2021-07-01 -> 2026-08-07 | $260,554.18 | +160.55%
V8: 2016-10-26 -> 2026-08-14 | $654,317.43 | +554.32%
SPY: 2016-10-25 -> 2026-08-14 | $423,694.11 | +323.69%
```

All are normalized historical/reconstructed comparison series, not promises and not the future holdout. The chart defaults to a 3-year view while retaining longer ranges/full history.

**Do not modify this MODEL PERFORMANCE COMPARISON chart as a side effect of operational V8 dashboard work.**

## Dashboard migration and performance architecture

The stock dashboard is now V8-centered for current operational rankings/predictions/paper/holdout monitoring. Historical V4/V5 remain only where intentionally needed for comparison/history.

Critical performance rule: **the synchronous `/dashboard` request must not perform research-scale computation.**

Implemented performance architecture:
1. V8 paper runner publishes `data/live/v8_latest_rankings.json`.
2. Normal web rendering reads the small snapshot instead of scanning large V8 research Parquet.
3. Market/Parquet reads use modification-time caching where applicable.
4. Recent-price work is limited to the UI-required tail.
5. Top-10 price/change/RSI enrichment is no longer part of blocking HTML generation.
6. Top-10 secondary values load asynchronously after the page shell is visible.
7. Future expensive widgets should follow the same pattern: background precompute -> compact artifact/API -> lazy browser load.

Do not reintroduce multi-symbol Parquet scans, historical reconstruction, model fitting, or large transformations into the request path.

## Operational distinction that must remain clear

- **Historical model comparison:** normalized reconstructed V4/V5/V8/SPY research series.
- **V8 operational paper portfolio:** actual paper-process state from its own operational start/capital base.
- **V8 formal forward holdout:** untouched Sep-1+ append-only evidence under the frozen SHA.
- **Brokerage execution:** disabled.

These are different accounting/evidence systems and must not be spliced together merely to make one continuous equity curve.

## Crypto state remains protected

This stock milestone does not replace or mutate the existing crypto freezes:
- Crypto 15m V2 frozen HGB + `confirm_2`, future boundary Sep 1, 2026 UTC.
- XRP V1 Phase 6 frozen exploratory Ridge + `hyst_10_05_hold24`, shadow-only unless a separate future-evaluation phase is created.
- No real brokerage orders.

Existing crypto-specific documentation remains authoritative for those contracts.

## Important code breadcrumbs

```text
ed4fbe7  Freeze V8 candidate and add forward holdout monitoring
5dc739b  / c268e47  chart interaction/range work
9583810 / fb2b9f8 / d94f336  full-history reconstruction build/fixes
3e6c228  V8 paper runner + broader V8 operational dashboard migration
50baa1c  lightweight V8 ranking snapshot/caching
072d226  market-data caching/performance
500af99 / 27ece39  lazy Top-10 enrichment / non-blocking dashboard work
```

## Recovery procedure

1. Preserve any post-checkpoint journals, status files, and genuinely new holdout evidence before changing code.
2. Check out or branch from `checkpoint/v8-frozen-platform-2026-08-19`.
3. Verify frozen V8 SHA equals `ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41`.
4. Never overwrite/backfill the formal holdout journal to make it match historical expectations.
5. Restore/reinstall V8 paper and holdout LaunchAgents if necessary.
6. Restart the web LaunchAgent.
7. Verify the dashboard consumes `data/live/v8_latest_rankings.json` and does not synchronously scan research-scale files.

Useful checks:

```bash
cd ~/Data-Shepherd-Engineering/stock-market-ai-platform
source .venv/bin/activate

git status --short
git log --oneline -20
cat data/model/v8/phase7/frozen_candidate.sha256
ls -lh data/live/v8_latest_rankings.json

launchctl print gui/$(id -u)/com.datashepherd.v8papermonitor | grep -E 'state =|runs =|pid =|last exit code'
launchctl print gui/$(id -u)/com.datashepherd.v8holdoutmonitor | grep -E 'state =|runs =|pid =|last exit code'
launchctl print gui/$(id -u)/com.datashepherd.web | grep -E 'state =|runs =|pid =|last exit code'
```

## Rules for work after this checkpoint

Any material change to frozen V8 becomes a **new model/version/candidate**. Do not silently edit V8 and continue calling it V8. Keep future-holdout evidence untouched, keep operational paper evidence separate, and preserve the no-orders boundary unless an explicit future project phase deliberately changes it.

This checkpoint is the preferred rollback point for the V8 stock platform as of August 19, 2026.
