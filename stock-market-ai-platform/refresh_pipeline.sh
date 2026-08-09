#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

PROJECT_DIR="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/refresh_pipeline.log"

cd "$PROJECT_DIR"

mkdir -p "$LOG_DIR"

set -a
source .env
set +a

echo "==================================================" | tee -a "$LOG_FILE"
echo "STOCK MARKET AI PLATFORM REFRESH" | tee -a "$LOG_FILE"
echo "Started: $(date)" | tee -a "$LOG_FILE"
echo "==================================================" | tee -a "$LOG_FILE"

CURRENT_TIMESTAMP="$(
python - <<'PY'
import csv
from pathlib import Path

path = Path(
    "data/bronze/stocks/AAPL/AAPL_prices.csv"
)

latest = 0

with path.open(
    newline="",
    encoding="utf-8",
) as handle:

    reader = csv.DictReader(handle)

    for row in reader:
        value = row.get("timestamp")

        if value:
            latest = max(
                latest,
                int(value),
            )

print(latest)
PY
)"

echo "Current AAPL Bronze timestamp: $CURRENT_TIMESTAMP" \
| tee -a "$LOG_FILE"

echo "[CHECK] Querying Tiingo for latest AAPL EOD data" \
| tee -a "$LOG_FILE"

LATEST_TIMESTAMP="$(
PYTHONPATH=data-ingestion python - <<'PY'
from datetime import date, timedelta

from tiingo_client import TiingoClient

client = TiingoClient()

today = date.today()

start = (
    today - timedelta(days=10)
).isoformat()

end = today.isoformat()

df = client.get_daily_prices(
    "AAPL",
    start,
    end,
)

if df.empty:
    print(0)
else:
    print(
        int(
            df["timestamp"].max()
        )
    )
PY
)"

echo "Tiingo AAPL timestamp: $LATEST_TIMESTAMP" \
| tee -a "$LOG_FILE"

if [[ "$LATEST_TIMESTAMP" -le "$CURRENT_TIMESTAMP" ]]; then

    echo "--------------------------------------------------" \
    | tee -a "$LOG_FILE"

    echo "NO NEW EOD DATA DETECTED" \
    | tee -a "$LOG_FILE"

    echo "Skipping full 26-stock refresh." \
    | tee -a "$LOG_FILE"

    echo "Finished: $(date)" \
    | tee -a "$LOG_FILE"

    echo "==================================================" \
    | tee -a "$LOG_FILE"

    exit 0

fi

echo "--------------------------------------------------" \
| tee -a "$LOG_FILE"

echo "NEW EOD DATA DETECTED" \
| tee -a "$LOG_FILE"

echo "Running full 26-stock pipeline..." \
| tee -a "$LOG_FILE"

echo "[1/5] Tiingo ingestion" \
| tee -a "$LOG_FILE"

PYTHONPATH=data-ingestion \
python -u data-ingestion/tiingo_multi_ingest.py \
2>&1 | tee -a "$LOG_FILE"

echo "[2/5] Silver pipeline" \
| tee -a "$LOG_FILE"

PYTHONPATH=data-ingestion \
python -u data-ingestion/silver_pipeline.py \
2>&1 | tee -a "$LOG_FILE"

echo "[3/5] Gold pipeline" \
| tee -a "$LOG_FILE"

PYTHONPATH=data-ingestion \
python -u data-ingestion/gold_pipeline.py \
2>&1 | tee -a "$LOG_FILE"

echo "[4/5] Feature pipeline" \
| tee -a "$LOG_FILE"

PYTHONPATH=data-ingestion \
python -u data-ingestion/feature_pipeline.py \
2>&1 | tee -a "$LOG_FILE"

echo "[5/5] Train all models" \
| tee -a "$LOG_FILE"

python -u ml/train_all.py \
2>&1 | tee -a "$LOG_FILE"

echo "==================================================" \
| tee -a "$LOG_FILE"

echo "REFRESH COMPLETE" \
| tee -a "$LOG_FILE"

echo "Finished: $(date)" \
| tee -a "$LOG_FILE"

echo "==================================================" \
| tee -a "$LOG_FILE"
