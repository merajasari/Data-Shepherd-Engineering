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

FEATURE_BACKEND="${FEATURE_BACKEND:-pandas}"
case "$FEATURE_BACKEND" in
    pandas|spark) ;;
    *)
        echo "Unsupported FEATURE_BACKEND=$FEATURE_BACKEND (expected pandas or spark)" >&2
        exit 2
        ;;
esac
export FEATURE_BACKEND

echo "==================================================" | tee -a "$LOG_FILE"
echo "STOCK V8 PRODUCTION REFRESH" | tee -a "$LOG_FILE"
echo "Started: $(date)" | tee -a "$LOG_FILE"
echo "Feature backend: $FEATURE_BACKEND" | tee -a "$LOG_FILE"
echo "==================================================" | tee -a "$LOG_FILE"

python -u ml/run_v8_data_refresh.py \
2>&1 | tee -a "$LOG_FILE"

echo "==================================================" | tee -a "$LOG_FILE"
echo "V8 REFRESH INVOCATION COMPLETE" | tee -a "$LOG_FILE"
echo "Finished: $(date)" | tee -a "$LOG_FILE"
echo "==================================================" | tee -a "$LOG_FILE"
