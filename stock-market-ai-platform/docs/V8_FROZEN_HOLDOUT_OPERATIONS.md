# V8 Frozen Forward Holdout Operations Runbook

## Purpose

This runbook governs operation of the frozen V8 forward holdout beginning
**2026-09-01 00:00 UTC**. It covers observation, alert response, and safe
recovery only.

It does **not** authorize model changes, parameter changes, evidence deletion,
manual journal edits, holdout rescoring, or brokerage orders.

## Immutable production contract

| Item | Frozen value |
|---|---|
| Candidate | `V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS` |
| Frozen SHA-256 | `ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41` |
| Holdout boundary | `2026-09-01T00:00:00+00:00` |
| Portfolio | Top 10, equal weight |
| Entry | Next session open |
| Exit | Five sessions after entry, at the open |
| Primary modeled cost | 10 bps per dollar traded |
| Brokerage orders | Disabled |
| Production model | V8 only |
| V10 | Reconstructed development-only; not frozen |

The runner verifies the frozen SHA and contract on every eligible invocation and
fails closed if anything differs.

## Production components

| Component | Path or identifier |
|---|---|
| LaunchAgent | `~/Library/LaunchAgents/com.datashepherd.v8paper.plist` |
| Scheduler label | `com.datashepherd.v8paper` |
| Scheduler entry point | `python -m ml.v8.scheduled_entrypoint` |
| Guarded orchestrator | `python -m ml.v8.eod_orchestrator` |
| EOD guard status | `data/model/v8/eod_guard/status.json` |
| Holdout journal | `data/model/v8/holdout/journal.jsonl` |
| Holdout status | `data/model/v8/holdout/status.json` |
| Journal lock | `data/model/v8/holdout/journal.lock` |
| Orchestrator lock | `data/model/v8/eod_guard/orchestrator.lock` |
| Alert state | `data/model/v8/monitor/alert_state.json` |
| Scheduler log | `logs/v8_paper.log` |
| Scheduler error log | `logs/v8_paper.err.log` |
| Dashboard API | `/api/v8/holdout` |

The LaunchAgent runs every five minutes. The scheduler must call the monitored
entry point, never the holdout runner directly.

## Dashboard equity behavior

The headline V8 portfolio equity has two deliberately separate accounting
bases:

- **Current mark-to-market:** while a forward cohort is open, the dashboard
  values its ten positions from the lightweight Tiingo IEX live quote cache,
  with the rolling 5-minute cache as the closed-market fallback. The value is
  refreshed in the browser every 15 seconds and includes the cohort's modeled
  trading cost.
- **Completed-cohort evidence:** official V8 return, SPY return, excess return,
  drawdown, hit rate, and the completed forward curve continue to use `EXIT`
  events only.

The current mark is read-only and is explicitly labeled as such. It never
creates, edits, or replaces a journal event. If any open basket lacks complete
price coverage, the API fails closed to completed-cohort equity (or the frozen
$100,000 baseline before the first exit) and reports the missing symbols rather
than publishing a partial portfolio value.

## Expected launch timeline

### Before September 1

Expected state:

- production journal is absent or contains zero events;
- status may be `WAITING_FOR_HOLDOUT`;
- preflight reports `READY`;
- operational monitor reports `HEALTHY`;
- dashboard reports no completed cohorts;
- no brokerage orders exist.

Any pre-boundary journal event is a hard alert.

### September 1 decision session

September 1 is the first eligible **decision timestamp**. A production journal
event is not expected immediately at the market close because the frozen
contract requires the next session's opening price.

The runner waits until that next-open observation exists. It must not invent,
backfill, or substitute a price.

### After the September 2 next open and EOD refresh

Once the September 2 market data has been ingested and the fail-closed guard
opens, the first September 1 cohort can produce:

1. a `DECISION` event timestamped September 1;
2. an `ENTRY` event using the September 2 open.

The operational alert deadline is **2026-09-03 03:00 UTC**. If no eligible
journal event exists by then, the monitor raises a deduplicated macOS
notification. The alert is a request to inspect readiness and ingestion—not
permission to create evidence manually.

### First exit

The September 2 entry exits at the open five trading sessions later. Market
holidays and weekends are skipped through the SPY trading calendar. The runner
creates the `EXIT` only when the required opening prices are available.

## Journal lifecycle

### DECISION

A decision records:

- frozen candidate and SHA;
- decision timestamp;
- cohort offset;
- ranked Top 10 symbols and scores;
- next-open entry timestamp;
- planned exit timestamp when known;
- `brokerage_orders: false`.

### ENTRY

An entry records:

- the original decision identity;
- actual next-session opening prices;
- SPY opening price;
- transition notional;
- modeled 10-bps cost rate;
- `brokerage_orders: false`.

This is modeled evidence. It does not submit an order.

### EXIT

An exit records:

- entry and exit timestamps/prices;
- gross portfolio return;
- modeled cost rate;
- net portfolio return;
- SPY return;
- net relative return;
- `brokerage_orders: false`.

The journal is append-only, locked, durable, and duplicate-safe. Status JSON is
written atomically.

## Routine health checks

From the project directory with the virtual environment active:

```bash
python -m ml.v8.production_preflight
python -m ml.v8.operational_monitor
```

Expected results:

```text
Status: READY
Status: HEALTHY
Production evidence modified: NO
Brokerage orders: OFF
```

Inspect the loaded scheduler:

```bash
launchctl print "gui/$(id -u)/com.datashepherd.v8paper"
```

Inspect recent logs:

```bash
tail -n 80 logs/v8_paper.log
tail -n 80 logs/v8_paper.err.log
```

Inspect status without modifying it:

```bash
python -m json.tool data/model/v8/eod_guard/status.json
python -m json.tool data/model/v8/holdout/status.json
python -m json.tool data/model/v8/monitor/alert_state.json
```

A missing holdout status before the first eligible run is normal.

Count and view journal events without editing the file:

```bash
wc -l data/model/v8/holdout/journal.jsonl
tail -n 20 data/model/v8/holdout/journal.jsonl
```

Check the local API:

```bash
curl --max-time 15 -sS http://127.0.0.1:5001/api/v8/holdout | python -m json.tool
```

## Alert meanings

| Alert | Meaning | First safe action |
|---|---|---|
| `orchestrator_failure` | Scheduled guarded run raised an exception | Inspect both V8 logs |
| `frozen_contract` | SHA or immutable rule differs | Stop; do not bypass verification |
| `scheduler_contract` | Installed plist is missing or unsafe | Reinstall the tracked LaunchAgent |
| `scheduler_unloaded` | macOS job is not loaded | Inspect with `launchctl print` |
| `journal_invalid` | JSONL contains an unreadable event | Stop; preserve file unchanged |
| `journal_duplicates` | Duplicate event key detected | Stop; preserve file unchanged |
| `pre_boundary_evidence` | Evidence appeared before September 1 | Stop and preserve all artifacts |
| `first_evidence_missing` | No first cohort after the declared deadline | Check ingestion and EOD guard |
| `status_invalid` | Status JSON cannot be parsed | Inspect logs and filesystem health |
| `runner_status` | Runner reported a hard unhealthy state | Inspect status and logs |

Notifications are deduplicated. The same active failure does not alert every
five minutes. A recovery notification is issued after all monitored checks
return to healthy.

## Safe recovery procedures

### Refresh code safely

```bash
git status
git pull --ff-only origin fix/video-v12-v8-v10-consolidation
```

If `git status` shows tracked local changes, stop and review them before
pulling. Do not reset or force.

### Reinstall the tracked LaunchAgent

```bash
zsh scripts/mac/install_v8_paper.sh
python -m ml.v8.production_preflight
python -m ml.v8.operational_monitor
```

This replaces the plist with the repository-defined scheduler contract. It does
not modify holdout evidence.

### Recheck data readiness

```bash
python -m ml.v8.readiness_check
python -m ml.v8.eod_guard
```

These checks must be allowed to fail closed. Do not invoke the holdout runner
directly to bypass a closed guard.

### Restart the dashboard only

Dashboard restart is separate from evidence collection. First identify the
Gunicorn master, then send the configured graceful reload signal. Do not kill
unrelated Python processes.

```bash
ps -ww -ax | grep "[g]unicorn.*webapp.app:app"
```

If the API is healthy, no restart is required.

## Prohibited actions during the holdout

Do not:

- edit, truncate, replace, reorder, or delete `journal.jsonl`;
- manually create a `DECISION`, `ENTRY`, or `EXIT`;
- run the holdout runner directly to bypass the EOD guard;
- change the frozen candidate, SHA, Top 10 rule, weighting, entry, exit, or cost;
- retrain or retune V8;
- use holdout outcomes to modify V8 or select a replacement;
- activate a V10 holdout—V10 was not frozen;
- backfill unavailable next-open or exit prices;
- force the guard open;
- connect this evidence runner to a brokerage;
- place orders from any holdout component;
- remove locks to resolve concurrency;
- use `git reset --hard`, force pushes, or destructive filesystem commands as
  an operational recovery shortcut.

If evidence appears suspicious, preserve the journal, status, logs, frozen
artifacts, and timestamps exactly as they are. Diagnose from copies or
read-only commands.

## Evidence interpretation

Before completed exits, the dashboard must say that evidence is insufficient.
As cohorts complete, it may report forward equity versus SPY, net returns after
the fixed cost, hit rate, Sharpe, drawdown, and volatility.

Reconstructed V4/V5/V8/V10 comparisons remain separate from this genuine V8
forward evidence. Forward results are not a guarantee, forecast, or instruction
to trade.


## Operational change control

The protected runtime source hashes are registered in:

```text
ml/v8/operational_lock_manifest.json
```

Verify them with:

```bash
python -m ml.v8.operational_change_control
```

Any mismatch produces `Status: BLOCKED`. A protected runtime change is not
authorized merely because it appears reasonable or passes an isolated test.
It requires explicit review, a complete suite pass, and deliberate re-locking.
Holdout outcomes must never be used to justify such a change.

Run the complete release gate with:

```bash
python -m ml.v8.complete_validation_suite
```

The suite must report `Status: PASSED` before the operational state can be
considered verified.
