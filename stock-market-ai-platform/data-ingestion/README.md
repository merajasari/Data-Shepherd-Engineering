# Market Data Ingestion

This module contains the historical and live market-data ingestion layer for the Stock Market AI Platform.

The current primary data source is **Tiingo**, using two complementary interfaces:

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
    -> model training / inference
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
    -> data/live/latest_quotes.json
    -> live_market_service.py
    -> Flask API
    -> dashboard live-price refresh
```

The live stream subscribes to all 26 configured symbols. Runtime live state is written to:

```text
data/live/latest_quotes.json
```

The live cache is not committed to Git.

During closed-market periods it is normal for the stream to remain connected while no fresh quote rows are present. The application falls back to latest EOD prices.

## Dedicated Service Supervision

The live IEX process now runs as its own Termux/runit service:

```text
iex-stream
```

Useful commands:

```bash
sv status iex-stream
sv restart iex-stream
tail -40 logs/iex_stream.log
```

Separating the WebSocket process from the web server allows either component to restart independently.

## Automated Historical Refresh

The repository-level `refresh_pipeline.sh` performs the scheduled historical workflow.

It first checks whether a newer EOD bar exists for a sentinel symbol. If no new timestamp is available, the full 26-symbol download and downstream rebuild are skipped.

When new EOD data is detected:

```text
Tiingo ingestion
  -> Silver
  -> Gold
  -> Features
  -> train all 26 models
```

The scheduled job runs through `crond` and uses `flock -n` to prevent overlapping executions.

This design was adopted after repeated tests demonstrated Tiingo HTTP 429 rate limiting. A low-cost sentinel request is significantly more efficient than downloading the entire universe every hour when EOD data has not changed.

## Forecast Relationship

The new 26-stock 5-day trend forecast is derived from saved model inference, not directly from live WebSocket ticks.

```text
Historical EOD -> Features -> Model -> 5-day directional probability -> Forecast score
Live IEX       -> Current displayed reference price
```

The two paths intentionally remain separate.

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

## Dependencies

The current runtime dependency file includes the production application stack:

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

The legacy `massive_client.py` wrapper remains in the repository for historical reference, but it is implemented using local code plus `requests`, `pandas`, and `python-dotenv`; a third-party `massive` package is no longer required.

## Configuration

Store credentials in a local `.env` file and never commit them.

Example:

```env
TIINGO_API_KEY=your_key_here
```

## Data Quality Goals

The ingestion layer protects downstream processing from malformed data, including:

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
