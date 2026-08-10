# Stock Market AI Platform — Architecture

## Overview

The Stock Market AI Platform is a 26-stock data engineering, machine-learning, live-market, forecasting, automation, and public web system.

It now contains four coordinated paths:

1. historical/end-of-day ingestion and Medallion processing
2. live Tiingo IEX market data
3. five-day ML inference and 26-stock trend scoring
4. public delivery through Gunicorn and Cloudflare Tunnel

> Experimental research platform. Forecasts are directional model outputs, not guaranteed trading signals or future price targets.

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
               |
               v
            Silver
               |
               v
             Gold --------------------+
               |                      |
               v                      v
            Features             Market Analytics
               |
               v
         Model Training
               |
               v
            Inference
               |
               +--> 26-stock forecast score
               |
               +----------------------+----------------------+
                                      |
                                      v
                              Flask services / APIs
                                      |
                                      v
                                   Gunicorn
                                      |
                                      v
                              Cloudflare Tunnel
                                      |
                                      v
                     datashepherdengineering.com
                                      |
                                      v
                              Browser dashboard
```

## 1. Stock Universe

The processing, training, live-stream, and forecast universe contains 26 equities configured centrally in `data-ingestion/symbols.py`.

The detailed dashboard still emphasizes a Top 10 subset, while the new forecast view ranks all 26 models.

## 2. Historical Ingestion

`data-ingestion/tiingo_multi_ingest.py` retrieves daily Tiingo history and writes Bronze CSV files.

```text
Tiingo EOD
  -> Bronze CSV
  -> Silver Parquet
  -> Gold Parquet
  -> Feature Parquet
```

The historical path supplies analytics, feature engineering, training, evaluation, and EOD fallback prices.

## 3. Live IEX Ingestion

`data-ingestion/iex_stream.py` connects to Tiingo IEX over WebSocket, subscribes to all 26 symbols, and writes:

```text
data/live/latest_quotes.json
```

Live state is runtime-only and ignored by Git.

The IEX process now runs as its own runit service named:

```text
iex-stream
```

This separates live-feed failures from web-server failures.

## 4. Medallion Architecture

```text
data/bronze/stocks/<SYMBOL>/<SYMBOL>_prices.csv
data/silver/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
data/gold/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
data/features/stocks/<SYMBOL>/<SYMBOL>_features.parquet
```

Bronze preserves canonical source observations, Silver standardizes/validates them, Gold provides analytics-ready data, and Features contains model-ready signals.

## 5. Machine-Learning Architecture

Each symbol receives its own NumPy logistic-regression artifact predicting five-trading-day direction.

```text
Features
  -> chronological 80/20 split
  -> training-only standardization
  -> logistic regression + L2
  -> holdout evaluation
  -> serialized artifact
  -> prediction service
```

Metrics include accuracy, precision, recall, F1, and majority baseline.

## 6. Forecast Layer

`webapp/services/forecast_service.py` converts existing model probabilities into a market-wide trend score:

```text
forecast_score = (probability_up - probability_down) * 100
```

Score range:

```text
-100 ... 0 ... +100
bearish   neutral   bullish
```

The forecast API returns all 26 symbols ranked from most bullish to most bearish:

```text
GET /api/forecast
```

The forecast is intentionally described as a **directional trend score**, not a future price forecast.

## 7. Flask Services and APIs

Current routes:

```text
/
/api/stocks
/api/prices/<symbol>
/api/live
/api/live/<symbol>
/api/forecast
/health
```

The presentation layer combines historical analytics, saved-model inference, live quote state, and market-wide forecast data.

## 8. Browser Layer

`webapp/static/js/dashboard.js` refreshes live and forecast state every 10 seconds while the page is visible.

The page includes:

- live/EOD selected-stock price
- Top 10 live price table
- 26-stock five-day forecast view
- bullish / neutral / bearish summary counts
- model probability, accuracy, and baseline context

## 9. Scheduled EOD Refresh

```text
cron at minute 05
      |
      v
flock overlap guard
      |
      v
EOD sentinel freshness check
      |
      +--> unchanged -> stop
      |
      v
new EOD bar
      -> refresh 26 symbols
      -> Silver
      -> Gold
      -> Features
      -> retrain 26 models
```

The sentinel design reduces unnecessary Tiingo calls and retraining.

## 10. Production Web Server

The public application no longer relies on Flask/Werkzeug's development server.

`stock-market-ai` now runs Gunicorn:

```text
gunicorn
  --bind 127.0.0.1:5000
  --workers 2
  --timeout 120
  webapp.app:app
```

Gunicorn logs are written under `logs/`.

## 11. Cloudflare Public Edge

The public request path is:

```text
Internet
  -> Cloudflare DNS
  -> Cloudflare Universal HTTPS
  -> named Cloudflare Tunnel: data-shepherd
  -> 127.0.0.1:5000
  -> Gunicorn
  -> Flask
```

Public hostnames:

```text
https://datashepherdengineering.com
https://www.datashepherdengineering.com
```

The origin does not require a public inbound port. `cloudflared` establishes outbound tunnel connections from the Termux device.

## 12. Service Supervision

Termux Services/runit supervises four independent services:

```text
crond
stock-market-ai
iex-stream
cloudflared
```

Responsibilities:

- `crond`: scheduled historical refresh
- `stock-market-ai`: Gunicorn web server
- `iex-stream`: Tiingo IEX WebSocket
- `cloudflared`: permanent Cloudflare Tunnel

This is more fault-isolated than the earlier design where the IEX process and Flask server shared one supervisor script.

## 13. Boot Persistence

The existing `~/.termux/boot/` startup path starts `runsvdir`. Because all production services are enabled, they can return after Android/Termux restart without manually launching each process.

## 14. Runtime and Secret Boundaries

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

Cloudflare credentials are also secret runtime state and must not be committed:

```text
~/.cloudflared/cert.pem
~/.cloudflared/*.json
```

## 15. Operational Verification

```bash
sv status crond
sv status stock-market-ai
sv status iex-stream
sv status cloudflared
curl -I http://127.0.0.1:5000
curl -I https://datashepherdengineering.com
curl -s https://datashepherdengineering.com/health
```

A healthy local response should show `Server: gunicorn`. A healthy public response is proxied through Cloudflare and returns HTTP 200.

## 16. Current Strengths

The architecture now demonstrates:

- 26-symbol historical and live market coverage
- Bronze/Silver/Gold/Feature layering
- rate-limit-aware sentinel refreshes
- per-symbol model artifacts
- transparent baseline comparisons
- 26-stock trend scoring
- browser auto-refresh
- Gunicorn production serving
- Cloudflare DNS + HTTPS + Tunnel
- independent runit services
- Android boot persistence
- public custom-domain deployment

## 17. Planned Evolution

### Machine learning

- walk-forward validation
- probability calibration
- stronger baselines and model families
- feature/coefficients diagnostics
- model versioning and drift monitoring

### Trading research

- realistic backtesting
- transaction costs and slippage
- historical forecast logging
- paper-trading evaluation

### Platform engineering

- incremental EOD ingestion
- structured observability and alerts
- conventional cloud/container deployment when scale requires it
- automated deployment and secrets management

## Design Philosophy

Machine learning is one layer of the system. Reliable market intelligence depends on reliable data, reproducible transformations, transparent evaluation, resilient automation, and production-grade delivery.

## Related Documentation

- [`../README.md`](../README.md)
- [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md)
- [`ingestion-architecture.md`](ingestion-architecture.md)
- [`OPERATIONS.md`](OPERATIONS.md)
