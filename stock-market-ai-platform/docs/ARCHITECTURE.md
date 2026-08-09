# Stock Market AI Platform — Architecture

## Overview

The Stock Market AI Platform is a multi-stock data engineering, machine-learning, and analytics system built to ingest market data, transform it through a layered data architecture, engineer predictive features, train per-symbol machine-learning models, and expose market intelligence through an interactive Flask dashboard.

The project deliberately separates ingestion, transformation, feature engineering, model training, inference, and presentation so each component can evolve independently.

> This project is an experimental research and engineering platform. Model predictions are not financial advice and should not be treated as guaranteed trading signals.

---

## Architecture at a Glance

```text
                         STOCK MARKET AI PLATFORM

                              Tiingo API
                                  |
                                  v
                    +---------------------------+
                    |     Data Ingestion        |
                    |  26-stock universe        |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |       BRONZE LAYER        |
                    | Raw canonical market data |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |       SILVER LAYER        |
                    | Cleaned / validated data  |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |        GOLD LAYER         |
                    | Analytics-ready datasets  |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |     FEATURE LAYER         |
                    | Technical / ML features   |
                    +-------------+-------------+
                                  |
                     +------------+------------+
                     |                         |
                     v                         v
          +----------------------+   +----------------------+
          |   MODEL TRAINING     |   |  MARKET ANALYTICS    |
          | Per-symbol models    |   | Price / RSI / SMA    |
          | 5-day direction      |   | volatility / volume  |
          +----------+-----------+   +----------+-----------+
                     |                          |
                     v                          |
          +----------------------+              |
          |      INFERENCE       |              |
          | UP / DOWN probability|              |
          +----------+-----------+              |
                     |                          |
                     +------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |      FLASK WEB APP        |
                    | Interactive dashboard     |
                    | Selected-stock detail     |
                    | Top-10 comparison         |
                    +---------------------------+
```

---

## 1. Stock Universe

The processing and training universe currently contains 26 equities configured in `data-ingestion/symbols.py`:

- AAPL
- MSFT
- NVDA
- AMZN
- GOOGL
- META
- TSLA
- AVGO
- AMD
- ORCL
- CRM
- JPM
- BAC
- V
- MA
- WMT
- COST
- HD
- JNJ
- UNH
- LLY
- XOM
- CVX
- CAT
- NFLX
- DIS

Centralizing this list gives ingestion and batch model training a shared definition of the supported universe.

The web dashboard currently focuses its comparison experience on a Top 10 subset:

```text
AAPL, MSFT, NVDA, AMZN, GOOGL,
META, TSLA, AVGO, AMD, ORCL
```

This distinction is intentional:

- **26-stock universe** — data processing and model-training scope.
- **Top 10 dashboard universe** — focused interactive presentation and comparison scope.

---

## 2. Data Ingestion

### Primary source

Market data is retrieved through Tiingo using the project's Tiingo client and multi-symbol ingestion pipeline.

Key components include:

```text
data-ingestion/
├── symbols.py
├── tiingo_client.py
├── tiingo_multi_ingest.py
├── bronze_writer.py
└── validators.py
```

The ingestion process:

1. Loads the configured stock universe.
2. Requests daily market data for each symbol.
3. Validates the returned dataset.
4. Writes canonical raw data into the Bronze layer.
5. Reports successful and failed symbols.

The ingestion date range is designed to support refreshed market history rather than leaving the dashboard tied to a historical snapshot.

---

## 3. Medallion Data Architecture

The platform uses a Bronze → Silver → Gold pattern, followed by a dedicated feature layer.

### Bronze

```text
data/bronze/stocks/<SYMBOL>/<SYMBOL>_prices.csv
```

Purpose:

- Preserve canonical ingested market data.
- Provide a reproducible input to downstream transformations.
- Keep ingestion concerns separate from analytical transformations.

Typical fields include symbol, timestamp, OHLC prices, and volume.

### Silver

```text
data/silver/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
```

Purpose:

- Clean and standardize Bronze data.
- Enforce expected data types and structure.
- Remove or identify invalid records.
- Prepare efficient Parquet datasets for downstream processing.

The Silver pipeline operates across the configured stock datasets rather than being tied to a single ticker.

### Gold

```text
data/gold/stocks/<SYMBOL>/<SYMBOL>_prices.parquet
```

Purpose:

- Produce analytics-ready datasets.
- Support dashboard market summaries.
- Serve as the source for feature engineering.

### Feature layer

```text
data/features/stocks/<SYMBOL>/<SYMBOL>_features.parquet
```

Purpose:

- Calculate technical and statistical features.
- Produce model-ready observations.
- Separate predictive features from raw/curated market data.

This separation makes it possible to improve feature engineering without redesigning the ingestion or web layers.

---

## 4. Data Quality

Data quality checks are an explicit part of the pipeline.

The platform validates conditions such as:

- Duplicate symbol/timestamp records.
- Null OHLC price values.
- Non-positive price values.
- Empty source datasets.
- Expected schema and data availability.

The objective is to prevent malformed market data from silently propagating into model training and dashboard analytics.

---

## 5. Feature Engineering

The feature pipeline transforms Gold datasets into model-ready datasets.

Features include market behavior derived from historical prices and volume, such as:

- Daily returns.
- Cumulative returns.
- Simple moving averages.
- Relative Strength Index (RSI).
- Rolling volatility.
- Volume-based measures.
- Price relationships and trend indicators.

The training pipeline explicitly excludes future-return fields from model inputs to reduce target leakage.

For the complete ML feature and training explanation, see [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md).

---

## 6. Machine-Learning Architecture

The current model predicts whether a stock will be higher **five trading days into the future**.

Each supported symbol receives its own trained model artifact.

```text
Feature dataset
      |
      v
Chronological train/test split
      |
      v
Training-only feature scaling
      |
      v
NumPy logistic regression
      |
      v
Holdout evaluation
      |
      v
models/<symbol>_direction_model.pkl
```

### Why chronological splitting matters

Financial observations are time ordered. Randomly shuffling future observations into a training set can produce unrealistic evaluation results.

The project therefore uses a chronological training/test split so the model is evaluated on observations occurring after its training period.

### Per-symbol models

`ml/train_all.py` iterates through the configured stock universe and invokes the training pipeline for each symbol.

This creates independent artifacts such as:

```text
models/aapl_direction_model.pkl
models/msft_direction_model.pkl
models/nvda_direction_model.pkl
...
```

### Evaluation

The training pipeline reports metrics including:

- Accuracy.
- Precision.
- Recall.
- F1 score.
- Majority-class baseline.

The majority baseline is particularly important. A directional model should not be considered useful merely because its raw accuracy appears high; its performance should be evaluated relative to a simple baseline and ultimately through realistic out-of-sample trading research.

---

## 7. Inference Layer

The prediction layer loads the appropriate model artifact and latest engineered feature observation for the selected symbol.

It produces information including:

```text
Prediction:          UP or DOWN
Probability UP:      model probability
Probability DOWN:    complementary probability
Model accuracy:      holdout evaluation metric
Majority baseline:   comparison benchmark
Horizon:             5 trading days
```

The Flask prediction service exposes this information to the presentation layer.

---

## 8. Market Analytics Service

`webapp/services/market_service.py` provides the dashboard with current analytical information for a requested symbol.

Examples include:

- Latest close.
- Price change.
- Percentage price change.
- RSI-14.
- SMA-20.
- SMA-50.
- SMA-200.
- 20-day volatility.
- Volume ratio.
- Recent price history.

This service keeps market-data logic out of the Flask route and HTML template.

---

## 9. Prediction Service

`webapp/services/prediction_service.py` encapsulates model inference.

Its responsibilities include:

- Resolving the model artifact for a symbol.
- Resolving the symbol's feature dataset.
- Loading portable model parameters.
- Calculating the latest model probability.
- Applying the prediction threshold.
- Returning model metrics and prediction metadata to the application.

Separating prediction logic from Flask routing keeps the application easier to test and evolve.

---

## 10. Flask Presentation Layer

The Flask application combines market analytics and model predictions.

Primary routes include:

```text
/                     Interactive dashboard
/api/stocks           Top 10 stock/model data
/api/prices/<symbol>  Recent price history
/health               Service health endpoint
```

### Selected-stock experience

Users can select a stock from the dashboard dropdown. The detailed dashboard then updates for that symbol while retaining the overall visual design.

The selected-stock view includes market metrics, technical indicators, AI prediction information, and recent price history.

### Top 10 comparison

The dashboard also presents comparison information for the Top 10 universe so users can evaluate multiple stocks without losing the richer selected-stock detail view.

This gives the UI two analytical levels:

```text
Portfolio-level comparison
          +
Selected-stock deep dive
```

---

## 11. Repository Data Strategy

Generated datasets are runtime artifacts and are intentionally excluded from ongoing Git tracking.

The repository tracks the engineering system rather than every refreshed copy of market data.

### Tracked

```text
Source code
Pipeline definitions
Configuration
ML implementation
Flask application
Documentation
Tests
```

### Generated / ignored

```text
data/bronze/
data/silver/
data/gold/
data/features/
models/*.pkl
```

### Never commit

```text
.env
API keys
credentials
secrets
```

This prevents normal market-data refreshes from creating large, noisy Git commits and keeps sensitive credentials out of source control.

---

## 12. End-to-End Processing Flow

A complete refresh follows this conceptual sequence:

```text
1. Tiingo ingestion
       |
2. Bronze market data
       |
3. Silver transformation
       |
4. Gold transformation
       |
5. Feature engineering
       |
6. Train/retrain symbol models
       |
7. Run inference
       |
8. Flask services
       |
9. Interactive dashboard
```

Because each stage has a distinct responsibility, the architecture can later be orchestrated or scheduled without collapsing everything into one monolithic script.

---

## 13. Current Architecture Strengths

The current implementation demonstrates several production-oriented engineering principles:

- Layered data architecture.
- Multi-symbol ingestion.
- Central stock-universe configuration.
- Explicit data-quality validation.
- Columnar Parquet processing downstream of Bronze.
- Dedicated feature layer.
- Chronological ML evaluation.
- Training-only feature scaling.
- Per-symbol model artifacts.
- Baseline-aware model evaluation.
- Separation of market and prediction services.
- API endpoints for dashboard data.
- Interactive multi-stock presentation.
- Generated-data isolation from source control.
- Secret isolation through environment configuration.

---

## 14. Planned Evolution

The architecture is designed to support several future improvements.

### Data engineering

- Incremental ingestion rather than full historical reloads.
- Pipeline orchestration and scheduling.
- Stronger schema contracts.
- Automated quality gates.
- Pipeline observability and structured logging.
- Cloud-backed storage.

### Machine learning

- Walk-forward validation.
- Backtesting with transaction costs.
- Probability calibration.
- Hyperparameter research.
- Cross-sectional and market-regime features.
- Additional model families.
- Model registry and experiment tracking.
- Drift monitoring.

### Application

- Public deployment.
- Production WSGI hosting.
- `DataShepherdEngineering.com` custom domain.
- Automated market-data refresh.
- Richer Top 10 comparison charts.
- Expanded stock-universe navigation.
- Historical prediction tracking.

### Trading research

Before any model is considered for automated execution, the project should add a rigorous research layer covering:

- Walk-forward backtesting.
- Transaction costs and slippage.
- Position sizing.
- Maximum exposure.
- Drawdown controls.
- Risk-adjusted performance.
- Paper trading.
- Monitoring and kill-switch behavior.

Prediction accuracy alone is not sufficient evidence of a profitable or safe trading strategy.

---

## 15. Design Philosophy

Data Shepherd Engineering treats the stock-market project as an engineering system first and an ML experiment second.

The core principle is:

> Reliable predictions require reliable data, reproducible transformations, leakage-aware evaluation, measurable baselines, and disciplined risk research.

The architecture therefore builds upward from data quality and reproducibility rather than treating the machine-learning model as an isolated component.

---

## Related Documentation

- [`../README.md`](../README.md) — Stock Market AI Platform overview and setup.
- [`MACHINE_LEARNING.md`](MACHINE_LEARNING.md) — detailed machine-learning design, features, training, evaluation, and limitations.
- [`../../README.md`](../../README.md) — Data Shepherd Engineering repository overview.
