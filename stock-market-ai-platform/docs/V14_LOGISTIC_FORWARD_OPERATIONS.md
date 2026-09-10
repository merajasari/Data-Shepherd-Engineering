# V14 logistic-regression paper candidate

V14 is an isolated machine-learning candidate. It does not replace or modify
the frozen V8 or V10 strategies.

## Contract

- Candidate: `v14_logistic_walk_forward_top10`
- Model: pooled NumPy logistic regression
- Target: `target_up_5d`
- Features: daily return, five- and 20-session return, price versus 20-session average, short/long volatility ratio, and volume ratio
- Training: expanding window, retrained at each eligible decision session
- Purge: five completed sessions before every decision
- Portfolio: top 10, equal weight, next-session open, five-session hold, 10-bps modeled cost
- Start: September 11, 2026 UTC
- Authority: paper only, no brokerage orders, no automatic promotion

## Run locally

From `stock-market-ai-platform`:

```bash
source .venv/bin/activate
python -m ml.v14.logistic_forward_regression
python -m ml.v14.logistic_forward
python -m ml.v14.logistic_forward_scheduled_entrypoint
python -m ml.v14.logistic_forward_scheduler_regression
python -m json.tool data/model/v14/logistic_forward/status.json
```

The runtime journal and status files are generated under
`data/model/v14/logistic_forward/`, which is intentionally excluded from Git.
Each decision records the training cutoff, row count, model hash, learned
weights, normalization statistics, predicted probabilities, and selected
symbols. The runner never reads V8/V10 outcomes to retrain or select this
candidate.

## Scheduled refresh and collection (macOS)

Install the isolated LaunchAgent from the project root:

```bash
./scripts/mac/install_v14_logistic_forward.sh
```

The job runs every five minutes while the user session is active. Each run is
serialized by a lock directory, refreshes the shared Tiingo Bronze data within
the rolling hourly request budget, propagates Silver/Gold/features, and only
then invokes the V14 collector when all required feature files are current.
Partial refreshes and quota waits are recorded in
`data/model/v14/logistic_forward/refresh_status.json` and do not create a
decision from an uncertain snapshot.

This job intentionally does not call `ml.run_v5_data_refresh`'s V8 production
publishing path: it never runs V8 inference, the V8 EOD orchestrator, or the
model-comparison refresh. If the older `com.datashepherd.v5refresh` LaunchAgent
is installed, unload that older market-data job before enabling this one so two
agents do not consume the same Tiingo quota. The existing V8 paper scheduler
may remain installed; V8/V10 state is not modified by the V14 job.

To inspect the job and logs:

```bash
launchctl print "gui/$(id -u)/com.datashepherd.v14logisticforward"
tail -f logs/v14_logistic_forward.log logs/v14_logistic_forward.err.log
python -m json.tool data/model/v14/logistic_forward/refresh_status.json
```
