# Massive Market Data Ingestion Framework

This module provides the foundation for ingesting stock market data into the Stock Market AI Platform.

## Flow

Massive API -> Python ingestion service -> Bronze layer -> Silver transformations -> Analytics

## Configuration

Create a local `.env` file:

```env
MASSIVE_API_KEY=your_key_here
```

Never commit API keys to GitHub.

## Initial milestone

- Authenticate with Massive
- Retrieve historical OHLCV data
- Normalize market data schema
- Store raw data as Bronze parquet files

Future enhancements:

- S&P 500 universe ingestion
- Incremental loading
- Data quality checks
- Azure Data Lake / Microsoft Fabric integration
