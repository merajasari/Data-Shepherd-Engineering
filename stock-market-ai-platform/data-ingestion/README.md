# Market Data Ingestion

This module contains the historical and live market-data ingestion layer for the Stock Market AI Platform.

The current primary data source is **Tiingo**, using two different interfaces:

- Tiingo daily/EOD REST data for the historical pipeline
- Tiingo IEX WebSocket data for live intraday reference prices

## Historical Flow

```text
Tiingo EOD API
    -> tiingo_client.py
    -> tiingo_multi_ingest.py
    -> validation
    -> Bronze CSV
    -> Silver Parquet
    -> Gold Parquet
    -> Feature Parquet
```

The configured ingestion universe contains 26 symbols in `symbols.py`.

Historical Bronze files are written to:

```text
data/bronze/stocks/<SYMBOL>/<SYMBOL>_prices.csv
```

The end date is dynamic so scheduled refreshes can detect newly available daily bars.

## Live Flow

```text
Tiingo IEX WebSocket
    -> iex_stream.py
    -> latest quote cache
    -> Flask live market service
    -> live API endpoints
    -> dashboard
```

Runtime live state is written to:

```text
data/live/latest_quotes.json
```

The live cache is not committed to Git.

## Key Files

```text
symbols.py                 shared 26-symbol universe
tiingo_client.py           Tiingo REST client
tiingo_multi_ingest.py     multi-symbol historical ingestion
iex_stream.py              live Tiingo IEX WebSocket stream
bronze_writer.py           Bronze persistence
validators.py              source-data checks
silver_pipeline.py         Bronze -> Silver
gold_pipeline.py           Silver -> Gold
feature_pipeline.py        Gold -> feature datasets
```

## Automated Refresh

The repository-level `refresh_pipeline.sh` performs the scheduled historical workflow.

It first checks whether a newer EOD bar exists for a sentinel symbol. If no new timestamp is available, the full 26-symbol download and downstream rebuild are skipped.

When new EOD data is detected:

```text
Tiingo ingestion
  -> Silver
  -> Gold
  -> Features
  -> train all models
```

This design was adopted after repeated test refreshes demonstrated Tiingo HTTP 429 rate limiting. A sentinel request is much more efficient than downloading the full universe every hour when EOD data has not changed.

## Configuration

Store credentials in a local `.env` file and never commit them.

Example:

```env
TIINGO_API_KEY=your_key_here
```

The exact environment-variable name should match the current Tiingo client implementation.

## Runtime Operation

The live stream is normally supervised through the `stock-market-ai` runit service on the current Termux deployment.

Useful checks:

```bash
sv status stock-market-ai
tail -20 logs/iex_stream.log
cat data/live/latest_quotes.json
```

During closed-market periods it is normal for the stream to connect, subscribe, receive heartbeats, and have no current symbol quotes. The web application falls back to latest EOD values.

## Data Quality Goals

The ingestion layer is responsible for protecting downstream processing from malformed data, including:

- empty responses
- duplicate symbol/timestamp rows
- null OHLC fields
- invalid or non-positive prices
- unexpected schemas

## Future Improvements

- incremental EOD pulls rather than broad historical windows
- structured ingestion metadata and observability
- retry/backoff logic for transient API errors
- explicit rate-limit telemetry
- persistent live event storage for intraday research
- cloud-backed storage and orchestration
