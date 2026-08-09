# Market Data Ingestion Architecture

## Overview

The Stock Market AI Platform uses two coordinated Tiingo ingestion paths: historical/end-of-day REST data and live IEX WebSocket data.

## Historical Path

```text
Tiingo EOD REST API
    -> Tiingo client
    -> multi-symbol ingestion
    -> validation
    -> Bronze CSV
    -> Silver Parquet
    -> Gold Parquet
    -> Feature Parquet
```

The historical path supports analytics, model training, evaluation, and latest-EOD fallback values.

## Live Path

```text
Tiingo IEX WebSocket
    -> iex_stream.py
    -> data/live/latest_quotes.json
    -> live_market_service.py
    -> Flask live endpoints
    -> browser auto-refresh
```

The live stream subscribes to the configured 26-symbol universe. During periods without market updates, the connection may still be healthy and receive heartbeats while the live quote cache remains empty.

## Scheduled Refresh Strategy

Historical refreshes are scheduled through `crond`, but the system does not perform a full 26-symbol rebuild blindly every hour.

Current strategy:

```text
hourly cron
    -> flock overlap guard
    -> recent AAPL sentinel request
    -> compare newest Tiingo timestamp with current Bronze timestamp
        -> unchanged: stop
        -> newer: full 26-symbol refresh
                  -> Silver
                  -> Gold
                  -> Features
                  -> model retraining
```

This design reduces API consumption and avoids repeated model retraining when no new EOD bar exists.

## Rate-Limit Behavior

Repeated full-universe tests produced HTTP 429 responses from Tiingo. The architecture therefore treats API limits as an operational constraint rather than assuming that a plan description removes all throttling.

Recommended behavior includes:

- use sentinel checks for scheduled freshness detection
- avoid duplicate manual refreshes within the same rate-limit window
- stop downstream work when historical ingestion fails or no newer data is detected
- add retry/backoff and explicit rate-limit telemetry in future versions

## Live vs Historical Responsibilities

The live and EOD paths are intentionally separate.

```text
Live IEX
  -> current displayed reference price

Historical EOD
  -> OHLCV history
  -> technical indicators
  -> feature engineering
  -> model training
  -> holdout evaluation
```

The current ML model is not retrained on every live tick.

## Storage

Historical generated layers:

```text
data/bronze/
data/silver/
data/gold/
data/features/
```

Live runtime state:

```text
data/live/
```

All of these are generated/runtime data and are excluded from Git.

## Credentials

API credentials belong in `.env` and must never be committed. Error logging should avoid exposing secrets embedded in request URLs.

## Operational Supervision

On the current Termux deployment:

- `crond` supervises scheduled historical refreshes
- `stock-market-ai` supervises the WebSocket and Flask application
- runit restarts supervised services
- a Termux boot script starts the service supervisor after Android reboot

## Design Goals

- secure credential handling
- reproducible historical ingestion
- low-cost freshness detection
- clear separation of live and historical paths
- data-quality validation
- rate-limit-aware scheduling
- resilient process supervision
- scalable path toward cloud storage and orchestration

## Metadata to Track Next

Future structured run metadata should include:

- symbol
- source system
- ingestion start/end time
- newest source timestamp
- record count
- execution status
- HTTP status / rate-limit state
- downstream rebuild decision
- model retraining decision
