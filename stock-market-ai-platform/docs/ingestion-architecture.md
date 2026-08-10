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
    -> model training / inference
```

The historical path supports analytics, technical indicators, model training, evaluation, latest-EOD fallback values, and the new 26-stock five-day forecast view.

## Live Path

```text
Tiingo IEX WebSocket
    -> iex_stream.py
    -> data/live/latest_quotes.json
    -> live_market_service.py
    -> Flask live endpoints
    -> browser auto-refresh
```

The live stream subscribes to the configured 26-symbol universe. During periods without market updates, the connection may remain healthy and receive heartbeats while the live quote cache contains no current quotes.

## Forecast Path

The dashboard now exposes a market-wide five-trading-day trend forecast across all 26 symbols.

```text
Saved model inference
    -> probability_up / probability_down
    -> normalized forecast score (-100 to +100)
    -> bullish / neutral / bearish classification
    -> ranked 26-stock dashboard visualization
```

This is a directional model forecast, not a future price target.

## Scheduled Refresh Strategy

Historical refreshes are scheduled through `crond`, but the system does not perform a full 26-symbol rebuild blindly every hour.

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

Repeated full-universe tests produced HTTP 429 responses from Tiingo. The architecture therefore treats API limits as an operational constraint.

Recommended behavior includes:

- use sentinel checks for scheduled freshness detection
- avoid duplicate manual refreshes within the same rate-limit window
- stop downstream work when historical ingestion fails or no newer data is detected
- add retry/backoff and explicit rate-limit telemetry in future versions

## Live vs Historical Responsibilities

```text
Live IEX
  -> current displayed reference price

Historical EOD
  -> OHLCV history
  -> technical indicators
  -> feature engineering
  -> model training
  -> holdout evaluation
  -> 5-day directional forecast
```

The current model is not retrained on every live tick.

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

## Production Supervision

The Android/Termux deployment now separates responsibilities across four runit services:

```text
crond            scheduled historical refreshes
stock-market-ai  Gunicorn + Flask web application
iex-stream       Tiingo IEX WebSocket process
cloudflared      public Cloudflare Tunnel
```

A Termux boot script starts the service supervisor after Android reboot, and each service is enabled independently.

This separation prevents a web-server restart from unnecessarily stopping the market stream and makes failures easier to diagnose.

## Public Delivery Path

```text
Internet
  -> Cloudflare DNS / HTTPS
  -> Cloudflare Tunnel
  -> Gunicorn on 127.0.0.1:5000
  -> Flask APIs and dashboard
```

The origin port is not opened directly to the public internet.

## Design Goals

- secure credential handling
- reproducible historical ingestion
- low-cost freshness detection
- clear separation of live and historical paths
- data-quality validation
- rate-limit-aware scheduling
- resilient process supervision
- secure public delivery
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
