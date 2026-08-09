# Data Shepherd Engineering

Data Shepherd Engineering is a hands-on data engineering and machine learning portfolio focused on building production-style data platforms from ingestion through analytics and AI.

## Featured Project: Stock Market AI Platform

The repository now includes an end-to-end multi-stock market intelligence platform that combines data engineering, feature engineering, machine learning, APIs, and an interactive Flask dashboard.

The current stock universe contains 26 equities. The web dashboard provides detailed selectable analysis for a Top 10 group while the broader pipeline processes and trains models across all configured symbols.

### End-to-End Architecture

```text
Tiingo Market Data API
        |
        v
Python Multi-Stock Ingestion
        |
        v
BRONZE - Raw market data
        |
        v
SILVER - Cleaned and standardized data
        |
        v
GOLD - Analytics-ready market data
        |
        v
FEATURE ENGINEERING
Technical, momentum, volatility and volume features
        |
        v
MACHINE LEARNING
Per-symbol 5-trading-day direction models
        |
        v
MODEL ARTIFACTS + PREDICTION SERVICE
        |
        v
FLASK API / PRESENTATION LAYER
        |
        v
INTERACTIVE MARKET + AI DASHBOARD
```

## What the Platform Demonstrates

- Multi-symbol market-data ingestion
- Medallion architecture: Bronze, Silver and Gold
- Data validation and transformation
- Parquet analytical datasets
- Technical-indicator and feature engineering
- 26-feature ML input vector
- Per-symbol binary logistic-regression models
- Time-ordered 80/20 train/test evaluation
- Accuracy, precision, recall and F1 measurement
- Majority-class baseline comparison
- 5-trading-day UP/DOWN direction probabilities
- Multi-model training across 26 configured equities
- Flask application and JSON APIs
- Interactive Top 10 stock selector
- Price history, moving averages, RSI, volatility and volume analytics
- Cross-stock model comparison dashboard

## Technology Stack

**Data Engineering:** Python, Pandas, Parquet, Tiingo API, Medallion Architecture  
**Machine Learning:** NumPy, feature engineering, logistic regression, model serialization  
**Application:** Flask, Jinja2, HTML, CSS, JavaScript  
**Engineering:** Git, GitHub

The architecture is intentionally portable and can evolve toward Microsoft Fabric, OneLake, Azure Data Factory, Azure Databricks, Delta Lake, Azure Machine Learning and Power BI.

## Repository

The primary implementation is located in [`stock-market-ai-platform/`](stock-market-ai-platform/).

See the [Stock Market AI Platform README](stock-market-ai-platform/README.md) for architecture, model design, features, evaluation methodology and usage.

See the [Machine Learning Model Guide](stock-market-ai-platform/docs/MACHINE_LEARNING.md) for a deeper explanation of how the AI/ML layer works.

## Current Direction

The next evolution of the platform includes automated scheduled refreshes, stronger model validation and backtesting, model monitoring, production deployment, and a public web experience.

## Disclaimer

This project is an experimental research and engineering platform. Model output probabilities are not the same as validated predictive accuracy, and nothing in this repository should be interpreted as financial advice or a guarantee of investment performance.

## Author

**Meraj Asari**  
Data Engineer | Azure Data Engineer | Database Developer
