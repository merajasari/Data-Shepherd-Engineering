# V10 Cycle 3 Accelerated Paper-Forward Protocol

## Decision

On 2026-09-04, before any accelerated V10 outcome existed, a separate
prospective paper-forward lane was authorized for the already frozen Cycle 3
candidate.

- Candidate: `c3_confirm2_blend50`
- Frozen candidate SHA-256:
  `2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38`
- First eligible decision session: 2026-09-08
- Last eligible decision session: 2026-12-18
- Original independent confirmation boundary: 2027-01-04, unchanged
- V8: unchanged
- Automatic promotion: disabled
- Live trading: disabled
- Brokerage orders: disabled

The September 8 boundary is the next full NYSE session after the September 7
Labor Day closure. The authoritative holiday calendar is published at
<https://www.nyse.com/trade/hours-calendars>.

## Scientific separation

This lane does not rename or backfill the original January holdout. It writes to
`data/model/v10/cycle3/accelerated_forward/`, while the January confirmation
continues to use `data/model/v10/cycle3/holdout/`.

An accelerated decision is admissible only when all of the following are true:

1. The exact frozen candidate identity verifies.
2. The source market session has completed.
3. The Top 10 selection is journaled before the next eligible market open.
4. The fixed Top-10, equal-weight, next-open, five-session, 10-bps contract is
   unchanged.
5. The event is paper-only and has no brokerage authority.

A missed decision remains missed. It cannot be reconstructed after its entry
open is known. Journal rows are deterministic, duplicate-safe, append-only and
hash-chained.

The accelerated decision window ends on December 18 so its five-session
positions finish before January. At the January 4 boundary, the accelerated
runner becomes read-only and the independent confirmation remains separate.

## Fixed review checkpoints

A complete block contains one completed exit from each of cohort offsets 0
through 4. Partial blocks and overlapping individual exits remain diagnostic;
only complete blocks enter promotion metrics.

### Eight-block review

After eight complete blocks, V10 becomes eligible for a human-reviewed
provisional paper-champion decision only when:

- operational integrity is intact;
- mean V10 return after modeled cost is positive;
- mean paired V10 minus V8 net return is non-negative;
- mean V10 minus SPY return is non-negative; and
- V10 maximum cohort drawdown is not worse than V8 by more than 10 percentage
  points.

### Twelve-block review

After twelve complete blocks, V10 becomes eligible for a stronger, limited-live
review only when all eight-block gates pass and:

- at least five completed defensive-regime exits exist; and
- mean defensive V10 minus V8 net return is positive.

Eligibility never activates trading. Any promotion still requires a separate
human decision and separate authority. Changing the candidate after inspecting
results creates a new candidate and requires a new prospective boundary.

## macOS installation

Run from the project root after pulling the branch:

```bash
python -m py_compile \
  ml/v10/cycle3_accelerated_forward_contract.py \
  ml/v10/cycle3_accelerated_forward_journal.py \
  ml/v10/cycle3_accelerated_forward_runner.py \
  ml/v10/cycle3_accelerated_scheduled_entrypoint.py \
  ml/v10/cycle3_accelerated_forward_regression.py

python -m ml.v10.cycle3_accelerated_forward_regression
python -m ml.v10.cycle3_accelerated_forward_contract
zsh scripts/mac/install_v10_cycle3_accelerated.sh
```

Verify the scheduler and isolated status:

```bash
launchctl print \
  "gui/$(id -u)/com.datashepherd.v10cycle3accelerated"

python -m ml.v10.cycle3_accelerated_scheduled_entrypoint

python -m json.tool \
  data/model/v10/cycle3/accelerated_forward/status.json

tail -n 100 logs/v10_cycle3_accelerated.log
tail -n 100 logs/v10_cycle3_accelerated.err.log
```

Before September 8 the expected status is
`WAITING_FOR_ACCELERATED_BOUNDARY`, with zero evidence events. After each market
close, the shared daily feature data must be current before the following open.
Stale or missing data fails closed and missed predictions are never backfilled.
