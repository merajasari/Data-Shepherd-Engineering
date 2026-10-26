# V15 compact runtime inputs

V15's decision path loaded the full 101-symbol historical JSON dataset and rebuilt
its frozen daily-context model on each invocation. Stack dumps on October 26
showed JSON decoding during feature construction; the historical input is 322.2
MiB on the 1 GiB Oracle VM. Successful collector diagnostics do not validate this
later inference stage.

The preparation module verifies each historical symbol file separately and saves
only daily closing prices. It reproduces the existing slow-context model once,
requires its exact SHA to match the immutable V7 artifact, and retains its verified
numeric snapshot. Subsequent preparations restore those exact coefficients and
prepare the previous-session daily context. It projects six daily features and
the target column rather than loading all Spark feature columns.

Live feature construction reads compact sealed JSON, checks artifact/contract/
manifest identities, source file stat signatures, universe, target session and
previous trading-session daily context. It preserves the existing historical
previous-close selection, fast features, normalization, interactions, immutable
ridge model, thresholds, exposure and checkpoint guards. This performance change
does not revise the economic definition of those features. Missing/stale inputs
fail closed rather than invoking historical preparation inside the decision
window. Runtime-input files are rebuildable derived inputs, not trade evidence.

Run `scripts/install_v15_runtime_cache.py` on the Ubuntu VM. The installer replaces
only `_build_current_feature_rows` after checking its expected content, preserving
local checkpoint protection and scheduler changes. It backs up the runner and
existing preparation units, installs an 08:30 America/New_York weekday preparation
timer, and starts preparation asynchronously. Preparation runs in the existing
650 MiB shared batch slice with a 550 MiB process-group ceiling, 50% CPU quota,
and 45-minute timeout. No live-trading service or checkpoint timer is restarted.

Inspect `sudo journalctl -u datashepherd-v15runtimeprepare.service -n 30 --no-pager`
and the service's Result/ExecMainStatus. Expect the frozen identity verification
and `Prepared YYYY-MM-DD` message. If a stored intraday snapshot belongs to that
session, preparation also performs read-only decision construction and reports
the elapsed time. It never calls the journal-writing runner. A successful cache
build alone is not a successful paper trade: confirm actual DECISION / ENTRY /
EXIT evidence at the next eligible lifecycle windows.

The first build has not been measured on the production VM. It may fail safely
at its memory/time ceiling or on an exact frozen SHA mismatch; investigate that
output rather than increasing limits or bypassing identity checks. A missed
session remains missed and is not backfilled. The contract holiday list is the
source for previous-session freshness. Intraday market snapshots and preparation
inputs remain separate.

Local validation: Python syntax checks; synthetic 101-symbol exact feature-row
comparison between original and cached paths; stale-context, source-drift and
cache-tampering rejection; weekend/holiday previous-session handling; daily
column projection equivalence; narrow installer preservation of unrelated VM
code. Production artifacts and market-time lifecycle were unavailable locally.
