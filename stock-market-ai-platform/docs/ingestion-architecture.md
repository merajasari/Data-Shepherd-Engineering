# Market Data Ingestion Architecture

## Flow

Massive API

-> Python ingestion service

-> Validation layer

-> Bronze parquet storage

-> Silver transformations

-> Gold analytics features

## Design Goals

- Secure API credential management
- Reusable ingestion components
- Data quality validation
- Scalable path toward Azure Data Lake and Microsoft Fabric OneLake

## Metadata to Track

- symbol
- ingestion timestamp
- record count
- source system
- execution status
