# Stock Market AI Platform — Architecture

## Overview

The Stock Market AI Platform is a multi-stock data engineering, machine-learning, live-market, automation, and analytics system. It now contains two coordinated data paths: a historical/end-of-day pipeline used for analytics and model training, and a live Tiingo IEX WebSocket path used for intraday reference prices.

The architecture deliberately separates ingestion, transformation, feature engineering, training, inference, live market state, presentation, scheduling, and process supervision so each layer can evolve independently.

> Experimental research platform. Model outputs are not financial advice or guaranteed trading signals.

## Architecture at a Glance

```text
                         STOCK MARKET AI PLATFORM

               +------------------ TIINGO ------------------+
               |                                             |
               v                                             v
          EOD REST API                                 IEX WebSocket
               |                                             |
               v                                             v
            Bronze                                   Live Quote Cache
               |                                             |
               v                                             |
            Silver                                           |
               |                                             |
               v                                             |
             Gold --------------------+                      |
               |                      |                      |
               v                      v                      |
            Features             Market Analytics            |
               |                      |                      |
               v                      |                      |
         Model Training               |                      |
               |                      |                      |
               v                      |                      |
            Inference                 |                      |
               +-----------+----------+----------------------+
                           |
                           v
                    Flask Services / APIs
                           |
                           v
                   Interactive Dashboard
                           |
                           v
                   10-second browser polling
```

## 1. Stock Universe

The processing and training universe contains 26 equities configured centrally in `data-ingestion/symbols.py`:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`, `CRM`, `JPM`, `BAC`, `V`, `MA`, `WMT`, `COST`, `HD`, `JNJ`, `UNH`, `LLY`, `XOM`, `CVX`, `CAT`, `NFLX`, `DIS`.

The dashboard currently emphasizes a Top 10 subset for comparison and detailed navigation.

## 2. Historical Ingestion

`data-ingestion/tiingo_multi_ingest.py` retrieves daily Tiingo price history for the configured symbols and writes canonical Bronze CSV files.

The historical ingestion window uses a dynamic current end date rather than a fixed snapshot.

Flow:

```text
Tiingo EOD API
    -> validation
    -> Bronze CSV
    -> Silver Parquet
    -> Gold Parquet
    -> Feature Parquet
```

## 3. Live IEX Ingestion

`data-ingestion/iex_stream.py` provides the intraday market path.

Responsibilities:

- connect to Tiingo IEX over WebSocket
- subscribe to all 26 configured symbols
- process informational messages and heartbeats
- receive market updates when available
- maintain the latest quote per symbol
- write runtime state to `data/live/latest_quotes.json`
- terminate cleanly rather than entering an unwanted reconnect loop on Ctrl+C

The live cache is runtime state and is intentionally ignored by Git.

## 4. Medallion Data Architecture

### Bronze

```text
data/bronze/stocks/<SYMBOL>/<SYMBOL>_prices.csv
```

Preserves canonical ingested OHLCV observations.

### Silver

```text
data/silver/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
```

Cleans, standardizes, validates, and types Bronze records.

### Gold

```text
data/gold/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
```

Provides analytics-ready market data used by the web application and feature pipeline.

### Features

```text
data/features/stocks/<SYMBOL>/<SYMBOL>_features.parquet
```

Contains model-ready technical and statistical features.

## 5. Machine-Learning Architecture

Each symbol receives its own NumPy logistic-regression artifact predicting five-trading-day direction.

```text
Feature data
  -> chronological 80/20 split
  -> training-only standardization
  -> logistic regression + L2
  -> holdout evaluation
  -> serialized model artifact
  -> prediction service
```

Metrics include accuracy, precision, recall, F1, and majority-class baseline. Several current models remain below baseline; the architecture treats that transparently as a research finding.

## 6. Live Market Service

`webapp/services/live_market_service.py` isolates the Flask application from the file-based live cache.

It returns a consistent quote structure even when no live tick is available. The UI can therefore use:

```text
live quote available -> LIVE IEX price
no live quote        -> latest EOD price
```

This prevents the dashboard from depending on active market hours to render successfully.

## 7. Flask Presentation Layer

The Flask app combines three service concerns:

- historical market analytics
- saved-model inference
- live IEX quote state

Current routes include:

```text
/
/api/stocks
/api/prices/<symbol>
/api/live
/api/live/<symbol>
/health
```

The selected-stock market card shows live price state when available. The Top 10 table also includes a Price column that can transition from EOD to live values.

## 8. Browser Auto-Refresh

`webapp/static/js/dashboard.js` polls live Flask endpoints every 10 seconds while the page is visible.

It updates:

- the selected stock's main price
- the LIVE IEX / LATEST EOD indicator
- the Top 10 Price column

The page does not need a full browser reload for new live values.

Polling is paused while the tab is hidden to avoid unnecessary requests.

## 9. Automated EOD Refresh

`refresh_pipeline.sh` orchestrates historical refreshes.

The first design ran the entire 26-symbol historical pipeline on every schedule. After encountering Tiingo HTTP 429 responses during repeated testing, the architecture was changed to use a low-cost sentinel check.

Current flow:

```text
cron at minute 05
      |
      v
flock overlap guard
      |
      v
query recent AAPL EOD data
      |
      +--> no newer timestamp -> stop
      |
      v
new EOD bar exists
      |
      v
refresh all 26 symbols
      -> Silver
      -> Gold
      -> Features
      -> train all models
```

This avoids unnecessary downstream work and materially reduces API usage.

## 10. Cron and Overlap Protection

The refresh is scheduled through `crond`.

The current crontab uses `flock -n` so an hourly invocation exits if the previous refresh is still running. This protects against duplicate ingestion, duplicate model training, and race conditions caused by overlapping jobs.

## 11. Process Supervision

The Android/Termux deployment now uses `termux-services` and runit.

Supervised services:

```text
crond
stock-market-ai
```

The `stock-market-ai` runit service launches:

```text
Tiingo IEX WebSocket process
Flask web application
```

It monitors both child processes and exits if either child fails, allowing runit to restart the service.

## 12. Boot Persistence

The Google Play Termux build supports boot scripts from:

```text
~/.termux/boot/
```

The configured boot script starts `runsvdir`. Because `crond` and `stock-market-ai` are enabled services, both return automatically after Android reboot.

This behavior was tested successfully. After reboot, the following were verified without manually launching the platform:

- `runsvdir` running
- `crond` running
- `stock-market-ai` running
- Flask returning HTTP 200

## 13. Manual Process Manager

`run_platform.sh` remains available as a manual process manager and supports:

```text
start
stop
status
restart
```

It uses PID files and duplicate-process checks. Under normal persistent operation, runit is the preferred supervisor.

## 14. Runtime and Repository Boundaries

Tracked source should include code, scripts, documentation, configuration templates, and tests.

Generated/runtime state is ignored:

```text
data/bronze/
data/silver/
data/gold/
data/features/
data/live/
models/*.pkl
logs/
run/
*.lock
```

Secrets such as `.env` and API tokens must never be committed.

## 15. Operational Verification

Useful checks:

```bash
sv status crond
sv status stock-market-ai
pgrep -a runsvdir
crontab -l
curl -I http://127.0.0.1:5000
```

A healthy web service returns HTTP 200.

## 16. Current Strengths

The current architecture demonstrates:

- multi-symbol market ingestion
- layered Bronze/Silver/Gold/Feature data design
- live WebSocket ingestion
- EOD fallback behavior
- per-symbol model artifacts
- chronological evaluation
- baseline-aware reporting
- browser-side live refresh
- API-efficient sentinel scheduling
- `flock` overlap protection
- cron automation
- runit service supervision
- Android reboot persistence
- generated-data isolation from source control

## 17. Planned Evolution

### Data engineering

- incremental historical ingestion
- stronger schema contracts and data-quality gates
- structured logging and monitoring
- cloud-backed storage

### Machine learning

- walk-forward validation
- rolling-window experiments
- probability calibration
- stronger baselines
- feature diagnostics
- tree-based and pooled models
- experiment tracking and model versioning
- drift monitoring

### Application and operations

- production WSGI server
- public deployment
- custom domain `DataShepherdEngineering.com`
- containerization
- alerting and health monitoring
- cloud migration/evolution

### Trading research

- realistic backtesting
- transaction costs and slippage
- risk-adjusted metrics
- position sizing and exposure limits
- paper trading

## Design Philosophy

The platform treats machine learning as one layer in a larger engineering system. Reliable market intelligence depends on reliable data, reproducible transformations, transparent evaluation, disciplined automation, and operational resilience.

## Related Documentation

- [`../README.md`](../README.md) — platform overview
- [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md) — detailed model design
- [`ingestion-architecture.md`](ingestion-architecture.md) — ingestion and refresh design
