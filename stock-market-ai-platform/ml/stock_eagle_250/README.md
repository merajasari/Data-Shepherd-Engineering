# StockEagle250

StockEagle250 is an isolated next-generation learned stock-model research lane
for the configured 250-stock candidate universe. SPY is benchmark context only.

## Current status

Phase 1 is a foundation and readiness audit. It verifies:

- exactly 250 unique candidate stocks plus benchmark-only SPY;
- preservation of the original frozen 100-stock universe as a subset;
- availability and readability of all 251 historical feature datasets;
- per-symbol eligibility after 252 observed sessions;
- duplicate-timestamp absence; and
- zero authority to paper trade, place orders, or modify V5, V8, V10, V14, or V15.

Phase 1 does not select features, targets, a model family, costs, a holding
period, or a future holdout boundary. Those decisions must be preregistered
before scored development begins.

## Run

```bash
python -m unittest tests.test_stock_eagle_250_phase1 -v
python -m ml.stock_eagle_250.phase1
python -m json.tool data/model/stock_eagle_250/phase1/manifest.json
```

Use `--strict` only when the command should return a failure status if any
historical feature file is missing, unreadable, or contains duplicate
timestamps.
