# Stock Market AI Platform

An end-to-end **data engineering + machine learning market intelligence platform** built under Data Shepherd Engineering.

Rather than treating machine learning as an isolated notebook experiment, this project connects the full lifecycle: market-data ingestion, Medallion processing, feature engineering, model training, prediction services, APIs, and an interactive web dashboard.

> **Research platform:** This project is experimental. Predictions and probabilities are model outputs, not financial advice or guarantees of future market performance.

## Architecture

```text
                    DATA SHEPHERD ENGINEERING
                      STOCK MARKET AI PLATFORM

                         Tiingo Market Data API
                                  |
                                  v
                      Multi-Stock Python Ingestion
                                  |
                                  v
                    +---------------------------+
                    | BRONZE                    |
                    | Raw per-symbol market data|
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | SILVER                    |
                    | Cleaned / standardized    |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | GOLD                      |
                    | Analytics-ready prices    |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | FEATURE ENGINEERING       |
                    | 26 model features         |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | MACHINE LEARNING          |
                    | Per-symbol direction model|
                    | 5-trading-day horizon     |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | MODEL ARTIFACTS           |
                    | Weights + scaling + metrics|
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | PREDICTION SERVICE        |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | FLASK APPLICATION / APIs  |
                    +---------------------------+
                                  |
                                  v
                    +---------------------------+
                    | INTERACTIVE DASHBOARD     |
                    | Market + AI intelligence  |
                    +---------------------------+
```

## Stock Universe

The data/ML pipeline is configured for **26 equities**:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`, `CRM`, `JPM`, `BAC`, `V`, `MA`, `WMT`, `COST`, `HD`, `JNJ`, `UNH`, `LLY`, `XOM`, `CVX`, `CAT`, `NFLX`, `DIS`.

The interactive dashboard currently focuses its detailed selector and cross-model comparisons on a **Top 10** subset:

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `ORCL`.

## Data Engineering Pipeline

### Bronze
Raw daily market observations are downloaded per symbol from Tiingo and stored in a canonical per-stock structure.

### Silver
Raw observations are cleaned, typed, standardized and prepared for downstream analytical processing.

### Gold
Curated price data is stored as analytics-ready Parquet datasets used by the dashboard and feature-engineering layer.

### Feature Engineering
The ML dataset expands price/volume history into 26 numerical signals spanning returns, trend, momentum, volatility, moving-average relationships, RSI and volume behavior.

## Machine Learning Model

Each stock receives its **own binary logistic-regression model** implemented with NumPy. The model answers one research question:

> Based on the latest engineered market features, is this stock more likely to be **higher or not higher five trading days into the future?**

The target is `target_up_5d`. A probability threshold of **0.50** converts the model probability into an UP/DOWN classification.

### 26 Model Features

The current feature vector includes:

- Daily and cumulative return
- SMA 7, 20, 50 and 200
- 20-day volume moving average
- Daily volatility
- 5-, 10- and 20-day returns
- Price relative to SMA 7/20/50/200
- SMA 7 vs 20, SMA 20 vs 50, SMA 50 vs 200
- Intraday range
- Open/close range
- Volume ratio
- 5-day volume change
- 5- and 20-day volatility
- RSI 14
- 10-day momentum

### Training Methodology

For every symbol:

1. Feature rows missing the forward target or required inputs are removed.
2. Observations remain in chronological order.
3. The first **80%** of observations form the training set.
4. The final **20%** form the holdout test set.
5. Features are standardized using **training-set statistics only**.
6. Logistic regression is trained using gradient descent with L2 regularization.
7. Performance is evaluated on the later unseen test period.
8. The trained artifact is serialized for the prediction service.

Using a chronological split instead of randomly shuffling observations is important for time-series research because it better approximates training on the past and evaluating on later data.

### Evaluation

Each model records:

- Accuracy
- Precision
- Recall
- F1 score
- True positives / true negatives
- False positives / false negatives
- Majority-class baseline
- Training and test row counts

The dashboard deliberately displays **model accuracy beside the majority baseline**. A high output probability does not automatically mean a model has high validated predictive accuracy.

### Model Artifact

Each serialized model contains more than weights. It includes the symbol, target definition, five-day horizon, threshold, feature list, learned weights and bias, training feature means/standard deviations, evaluation metrics, majority baseline, and train/test counts.

This allows the prediction layer to reproduce the same feature scaling used during training.

For a deeper model explanation, see [`docs/MACHINE_LEARNING.md`](docs/MACHINE_LEARNING.md).

## Interactive Dashboard

The Flask dashboard combines market and ML information in one presentation layer. Users can select a supported Top 10 stock and update the detailed stock view without changing the overall visual design.

Current dashboard capabilities include:

- Selected-symbol market snapshot
- Latest closing price and daily change
- Five-day AI direction
- UP/DOWN model probabilities
- RSI 14
- SMA 20 / 50 / 200
- 20-day volatility
- Volume ratio
- Recent price-history visualization
- Moving-average overlays
- Latest trading-session table
- Per-symbol model performance
- Top 10 model comparison
- Prediction-strength comparison
- Accuracy vs majority-baseline comparison

## Application APIs

The Flask layer also exposes JSON endpoints:

```text
GET /api/stocks
GET /api/prices/<symbol>
GET /health
```

## Project Structure

```text
stock-market-ai-platform/
├── data-ingestion/          # API clients, symbols, ingestion and pipeline logic
├── data/
│   ├── bronze/              # Raw market data
│   ├── silver/              # Cleaned/standardized data
│   ├── gold/                # Analytics-ready data
│   └── features/            # ML feature datasets
├── ml/
│   ├── train_model.py       # Per-symbol model training
│   ├── train_all.py         # Multi-symbol model orchestration
│   └── predict.py           # Prediction logic
├── models/                  # Serialized per-symbol model artifacts
├── webapp/
│   ├── app.py               # Flask routes and presentation layer
│   ├── services/            # Market and prediction services
│   ├── static/              # CSS / JavaScript
│   └── templates/           # Dashboard UI
└── docs/                    # Architecture and ML documentation
```

## Run the Dashboard Locally

From the `stock-market-ai-platform` directory:

```bash
PYTHONPATH=. python webapp/app.py
```

Then open:

```text
http://127.0.0.1:5000
```

## Technology Stack

- Python
- Pandas
- NumPy
- Parquet
- Tiingo market data
- Flask
- Jinja2
- HTML / CSS / JavaScript
- Git / GitHub

## Roadmap

- Automated scheduled market-data refresh
- Automated Bronze -> Silver -> Gold -> Features orchestration
- Scheduled/reproducible model retraining
- Walk-forward validation and stronger backtesting
- Model versioning and monitoring
- Additional models and model comparison
- Data-quality monitoring
- Production WSGI deployment
- Public deployment and custom domain
- Cloud migration/evolution using Azure and/or Microsoft Fabric

## Disclaimer

This repository is intended for software engineering, data engineering and machine-learning research. Market predictions are uncertain. Output probability is not equivalent to validated accuracy, and historical evaluation does not guarantee future performance. Nothing here constitutes financial advice.
