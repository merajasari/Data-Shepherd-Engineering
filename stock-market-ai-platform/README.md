# Stock Market AI Platform

An end-to-end **data engineering, machine learning, automation, and live market intelligence platform** built by Data Shepherd Engineering.

The platform now combines historical Tiingo EOD data, a live Tiingo IEX WebSocket feed, Medallion data processing, feature engineering, per-symbol machine-learning models, Flask APIs, an auto-refreshing dashboard, scheduled refresh logic, service supervision, and Android boot persistence.

> **Research platform:** model predictions and probabilities are experimental outputs, not financial advice or guarantees of future performance.

## Architecture

```text
Tiingo EOD API ------------------------------+
                                             |
Tiingo IEX WebSocket --> live quote cache ---+--> Flask services --> dashboard
                                             |
EOD --> Bronze --> Silver --> Gold --> Features --> ML --> inference
```

The two data paths serve different purposes:

- **EOD path:** reproducible historical data, feature generation, training, evaluation, and fallback market values.
- **Live path:** current IEX reference prices cached at runtime and exposed through Flask without retraining the model on every tick.

## Stock Universe

The data and ML pipeline supports 26 equities:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`, `CRM`, `JPM`, `BAC`, `V`, `MA`, `WMT`, `COST`, `HD`, `JNJ`, `UNH`, `LLY`, `XOM`, `CVX`, `CAT`, `NFLX`, `DIS`.

The primary dashboard currently emphasizes a Top 10 subset:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`.

## Data Engineering Pipeline

Historical market data is stored in a layered structure:

```text
data/bronze/stocks/<SYMBOL>/<SYMBOL>_prices.csv
data/silver/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
data/gold/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
data/features/stocks/<SYMBOL>/<SYMBOL>_features.parquet
```

- **Bronze** preserves canonical ingested observations.
- **Silver** cleans, types, validates, and standardizes records.
- **Gold** provides analytics-ready price data.
- **Features** contains model-ready technical and statistical signals.

Generated data is intentionally excluded from Git.

## Live Market Data

`data-ingestion/iex_stream.py` connects to the Tiingo IEX WebSocket and subscribes to all 26 configured symbols.

The stream writes runtime state to:

```text
data/live/latest_quotes.json
```

`webapp/services/live_market_service.py` reads that cache and provides safe fallback behavior. When a live quote is unavailable, the dashboard continues to display the latest EOD value rather than failing.

The browser polls the live APIs every **10 seconds** while the page is visible. The selected symbol and Top 10 Price column can switch automatically between:

```text
● LIVE IEX
LATEST EOD
```

## Machine Learning

Each symbol receives its own binary logistic-regression model implemented in NumPy. The target asks whether the stock will be higher five trading days in the future.

```text
target_up_5d = 1  -> higher five trading days later
target_up_5d = 0  -> not higher five trading days later
```

The current model uses 26 engineered features spanning returns, moving averages, price-vs-trend relationships, volume, volatility, RSI, and momentum.

Training uses a chronological 80/20 split, training-only standardization, gradient descent, L2 regularization, and a 0.50 classification threshold.

Evaluation includes accuracy, precision, recall, F1, and a majority-class baseline. The dashboard deliberately shows **accuracy next to baseline** because a high model output probability is not the same thing as validated predictive accuracy.

Several current models remain below their majority baseline. That is treated as a research result, not hidden by the UI. The next ML phase is walk-forward validation, stronger baselines, calibration, feature analysis, and additional model families.

See [`docs/MACHINE_LEARNING.md`](docs/MACHINE_LEARNING.md) for details.

## Flask Application and APIs

The Flask layer combines market analytics, model inference, and live quote state.

Current routes include:

```text
GET /
GET /api/stocks
GET /api/prices/<symbol>
GET /api/live
GET /api/live/<symbol>
GET /health
```

The dashboard provides selected-stock detail, recent price history, technical indicators, five-day model output, model-quality metrics, Top 10 comparison, and live prices when available.

## Automated Refresh

`refresh_pipeline.sh` controls the historical refresh workflow.

The job uses a **sentinel check** before rebuilding the entire pipeline:

```text
cron
  -> check latest AAPL EOD timestamp
      -> no new EOD data: stop
      -> new EOD data:
           refresh 26 symbols
           -> Silver
           -> Gold
           -> Features
           -> retrain 26 models
```

This avoids making 26 historical requests and retraining every model when no new daily bar exists.

The cron schedule runs at minute `05` of each hour and is protected by `flock`, preventing overlapping refresh jobs.

## Service Supervision and Boot Persistence

The current Android/Termux deployment uses `termux-services` / `runit`.

Supervised services:

```text
crond
stock-market-ai
```

The `stock-market-ai` service runs both the IEX WebSocket process and the Flask application. Both services are enabled under runit.

A boot script under `~/.termux/boot/` starts the service supervisor after Android reboot. Reboot recovery was tested successfully: `runsvdir`, `crond`, the stock-market service, the live stream, and Flask all returned automatically, and the dashboard responded with HTTP 200.

## Operations

Common commands:

```bash
sv status crond
sv status stock-market-ai
sv restart stock-market-ai
sv down stock-market-ai
sv up stock-market-ai
crontab -l
curl -I http://127.0.0.1:5000
```

The repository also contains `run_platform.sh` for manual PID-based start/stop/status/restart control when runit is not being used.

## Runtime Files and Logging

Runtime artifacts are not committed:

```text
data/live/
logs/
run/
*.lock
models/*.pkl
```

Typical logs include:

```text
logs/iex_stream.log
logs/webapp.log
logs/refresh_pipeline.log
logs/cron.log
```

Never commit `.env`, API tokens, credentials, or other secrets.

## Project Structure

```text
stock-market-ai-platform/
├── data-ingestion/
│   ├── tiingo_client.py
│   ├── tiingo_multi_ingest.py
│   ├── iex_stream.py
│   ├── silver_pipeline.py
│   ├── gold_pipeline.py
│   └── feature_pipeline.py
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   ├── features/
│   └── live/
├── ml/
│   ├── train_model.py
│   ├── train_all.py
│   └── predict.py
├── models/
├── webapp/
│   ├── app.py
│   ├── services/
│   │   ├── market_service.py
│   │   ├── prediction_service.py
│   │   └── live_market_service.py
│   ├── static/js/dashboard.js
│   └── templates/index.html
├── docs/
├── refresh_pipeline.sh
├── run_platform.sh
└── README.md
```

## Technology Stack

Python, Flask, Jinja2, Pandas, NumPy, Parquet, Tiingo EOD API, Tiingo IEX WebSocket, `websocket-client`, HTML, CSS, JavaScript, Bash, cron/cronie, `flock`, runit, Termux Services, Git, and GitHub.

## Roadmap

Priorities include:

- walk-forward and rolling-window validation
- realistic backtesting with costs and slippage
- probability calibration
- feature and coefficient diagnostics
- stronger model baselines and new model families
- incremental EOD ingestion
- structured logging and health monitoring
- production WSGI deployment
- containerization and cloud deployment
- public deployment at `DataShepherdEngineering.com`

## Disclaimer

This repository is for software engineering, data engineering, and machine-learning research. Market predictions are uncertain. Model output probability is not equivalent to validated predictive accuracy. Historical results do not guarantee future performance. Nothing in this project constitutes financial advice.
