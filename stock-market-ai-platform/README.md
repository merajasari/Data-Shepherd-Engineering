# Stock Market AI Platform

An end-to-end **data engineering, machine learning, automation, live market intelligence, forecasting, and public web platform** built by Data Shepherd Engineering.

Production site: **https://datashepherdengineering.com**

The platform combines Tiingo EOD history, Tiingo IEX live data, a Bronze/Silver/Gold/Features pipeline, 26 per-symbol ML models, five-day trend scoring, Flask APIs, Gunicorn, Cloudflare Tunnel, scheduled refreshes, runit supervision, and Android/Termux boot persistence.

> **Research platform:** predictions, probabilities, and forecast scores are experimental outputs, not financial advice or guarantees of future performance.

## Architecture

```text
Tiingo EOD API ------------------------------+
                                             |
Tiingo IEX WebSocket --> live quote cache ---+--> Flask services --> Gunicorn
                                             |                         |
EOD --> Bronze --> Silver --> Gold --> Features --> ML --> inference   |
                                             |                         |
                                             +--> 26-stock forecast ---+
                                                                       |
                                                                       v
                                                             Cloudflare Tunnel
                                                                       |
                                                                       v
                                                     datashepherdengineering.com
```

## Stock Universe

The data, training, and forecast pipeline supports 26 equities:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`, `CRM`, `JPM`, `BAC`, `V`, `MA`, `WMT`, `COST`, `HD`, `JNJ`, `UNH`, `LLY`, `XOM`, `CVX`, `CAT`, `NFLX`, `DIS`.

The detailed dashboard view still emphasizes a Top 10 subset, while the new market-wide forecast view covers all 26 symbols.

## Historical Data Pipeline

```text
Tiingo EOD
  -> Bronze CSV
  -> Silver Parquet
  -> Gold Parquet
  -> Feature Parquet
  -> model training
```

Generated files live under:

```text
data/bronze/
data/silver/
data/gold/
data/features/
```

## Live Market Data

`data-ingestion/iex_stream.py` connects to the Tiingo IEX WebSocket for all 26 configured symbols and writes runtime state to:

```text
data/live/latest_quotes.json
```

The dashboard uses live prices when available and falls back to latest EOD values outside active market periods.

## Five-Day Future Trend Forecast

`webapp/services/forecast_service.py` converts each model's existing five-trading-day UP/DOWN probabilities into a normalized trend score:

```text
forecast_score = (probability_up - probability_down) * 100
```

Interpretation:

```text
+100  strongly bullish
   0  neutral
-100  strongly bearish
```

This is a **directional model score, not a future price target**.

The dashboard displays all 26 symbols ranked from most bullish to most bearish, including model probability, holdout accuracy, and majority baseline. The forecast view appears near the top of the public dashboard before the individual-stock drill-down.

API:

```text
GET /api/forecast
```

## Machine Learning

Each symbol has an independent NumPy logistic-regression model predicting whether the stock will be higher five trading days later.

Evaluation includes:

- accuracy
- precision
- recall
- F1
- majority-class baseline

The UI intentionally exposes weak models rather than hiding them behind high confidence values. Several current models remain below their majority baseline, making model diagnostics and better validation the next major research phase.

See [`docs/MACHINE_LEARNING.md`](docs/MACHINE_LEARNING.md).

## Application APIs

```text
GET /
GET /api/stocks
GET /api/prices/<symbol>
GET /api/live
GET /api/live/<symbol>
GET /api/forecast
GET /health
```

## Browser Refresh

The dashboard polls live/forecast APIs every 10 seconds while visible. It updates live prices and the 26-stock trend view without a full page reload.

## Automated Historical Refresh

`refresh_pipeline.sh` uses a sentinel freshness check before rebuilding downstream layers.

```text
hourly cron
  -> flock overlap protection
  -> EOD sentinel check
      -> unchanged: stop
      -> new bar:
           refresh all 26
           -> Silver
           -> Gold
           -> Features
           -> retrain all 26 models
```

This reduces unnecessary Tiingo calls and avoids repeated retraining when EOD data has not advanced.

## Production Web Deployment

The public request path is:

```text
https://datashepherdengineering.com
          |
          v
Cloudflare DNS + Universal HTTPS
          |
          v
Cloudflare Tunnel
          |
          v
127.0.0.1:5000
          |
          v
Gunicorn
          |
          v
Flask application
```

The same tunnel also routes:

```text
https://www.datashepherdengineering.com
```

The origin port is not directly exposed to the public Internet; Cloudflare Tunnel establishes outbound connections from the Termux device.

## Service Supervision

The Termux/runit production stack now uses four independent services:

```text
crond
stock-market-ai
iex-stream
cloudflared
```

Responsibilities:

- **crond** — scheduled EOD freshness checks and conditional rebuilds
- **stock-market-ai** — Gunicorn serving `webapp.app:app` on `127.0.0.1:5000`
- **iex-stream** — Tiingo IEX WebSocket process
- **cloudflared** — named Cloudflare Tunnel `data-shepherd`

Separating the IEX stream from the web service allows runit to restart either component independently.

All four services are enabled with Termux Services and participate in the existing Android boot-persistence workflow.

## Production Verification

Local Gunicorn check:

```bash
curl -I http://127.0.0.1:5000
```

Expected header:

```text
Server: gunicorn
```

Public check:

```bash
curl -I https://datashepherdengineering.com
curl -s https://datashepherdengineering.com/health
```

A healthy public response uses HTTP/2 through Cloudflare and reports `"status":"healthy"`.

## Dependencies

The current Python dependency file includes:

```text
flask
gunicorn
numpy
pandas
pyarrow
python-dotenv
requests
websocket-client
```

## Project Structure

```text
stock-market-ai-platform/
├── data-ingestion/
│   ├── symbols.py
│   ├── tiingo_client.py
│   ├── tiingo_multi_ingest.py
│   ├── iex_stream.py
│   ├── silver_pipeline.py
│   ├── gold_pipeline.py
│   └── feature_pipeline.py
├── ml/
│   ├── train_model.py
│   ├── train_all.py
│   └── predict.py
├── webapp/
│   ├── app.py
│   ├── services/
│   │   ├── market_service.py
│   │   ├── prediction_service.py
│   │   ├── live_market_service.py
│   │   └── forecast_service.py
│   ├── static/js/dashboard.js
│   └── templates/index.html
├── docs/
├── refresh_pipeline.sh
├── run_platform.sh
└── README.md
```

## Runtime / Secret Boundaries

Do not commit:

```text
.env
data/bronze/
data/silver/
data/gold/
data/features/
data/live/
models/*.pkl
logs/
run/
*.lock
~/.cloudflared/cert.pem
~/.cloudflared/*.json
```

Cloudflare tunnel credentials are secrets and remain outside the repository.

## Technology Stack

Python, Flask, Gunicorn, Jinja2, Pandas, NumPy, Parquet, Tiingo EOD API, Tiingo IEX WebSocket, websocket-client, JavaScript, Bash, cron/cronie, flock, runit, Termux Services, Cloudflare DNS, Cloudflare Tunnel, HTTPS, Git, and GitHub.

## Roadmap

Primary next steps:

- walk-forward / rolling-window model validation
- probability calibration
- stronger baseline and model-family comparisons
- historical prediction logging
- realistic backtesting with costs/slippage
- incremental EOD ingestion
- structured observability and alerts
- model/version tracking
- eventual migration from Android/Termux to a conventional cloud/container deployment if scale requires it

## Disclaimer

This repository is for software engineering, data engineering, and machine-learning research. Market predictions are uncertain. Model output probability and forecast score are not equivalent to validated predictive accuracy or expected investment returns. Nothing in this project constitutes financial advice.
