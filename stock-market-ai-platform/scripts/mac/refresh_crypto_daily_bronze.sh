#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
LOGDIR="$PROJECT/logs"
LOCKDIR="$PROJECT/data/live/crypto_daily_bronze_refresh.lock"

cd "$PROJECT"
mkdir -p "$LOGDIR" "$PROJECT/data/live"

if [[ ! -x "$PYTHON" ]]; then
    echo "Missing Python: $PYTHON" >&2
    exit 1
fi

# Prevent overlapping full-history refreshes.
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "Another daily Bronze refresh is already running."
    exit 0
fi

cleanup() {
    rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# End is exclusive. At any time after UTC midnight this includes
# yesterday's fully completed UTC daily candle and never today's
# incomplete candle.
END_UTC="$(date -u +%Y-%m-%dT00:00:00Z)"
START_UTC="2021-07-01T00:00:00Z"

echo "=============================================="
echo "Crypto daily Bronze refresh"
echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Range:   $START_UTC -> $END_UTC exclusive"
echo "=============================================="

"$PYTHON" -m ml.crypto_v1.ingest \
    --start "$START_UTC" \
    --end "$END_UTC" \
    --granularity daily

"$PYTHON" - <<'PY'
from pathlib import Path
import pandas as pd
from ml.crypto_v1.config import CRYPTO_UNIVERSE

root = Path("data/bronze/crypto/coinbase_exchange/daily")

latest = {}
problems = []

for product in CRYPTO_UNIVERSE:
    path = root / product / "candles.csv"

    if not path.exists():
        problems.append(f"{product}: missing candles.csv")
        continue

    df = pd.read_csv(path)

    required = {
        "product_id", "provider", "granularity",
        "timestamp_utc", "open", "high", "low",
        "close", "volume",
    }

    missing = required - set(df.columns)
    if missing:
        problems.append(
            f"{product}: missing columns {sorted(missing)}"
        )
        continue

    if df.empty:
        problems.append(f"{product}: empty dataset")
        continue

    ts = pd.to_datetime(df["timestamp_utc"], utc=True)

    duplicates = int(
        df.duplicated(["product_id", "timestamp_utc"]).sum()
    )

    if duplicates:
        problems.append(
            f"{product}: {duplicates} duplicate rows"
        )

    latest[product] = ts.max()

if problems:
    raise SystemExit(
        "DAILY BRONZE VALIDATION FAILED\n" +
        "\n".join(problems)
    )

if len(latest) != len(CRYPTO_UNIVERSE):
    raise SystemExit(
        f"Expected {len(CRYPTO_UNIVERSE)} products; "
        f"validated {len(latest)}"
    )

oldest_latest = min(latest.values())
newest_latest = max(latest.values())

print()
print("DAILY BRONZE VALIDATION: PASS")
print("products:", len(latest))
print("oldest latest candle:", oldest_latest)
print("newest latest candle:", newest_latest)

for product in CRYPTO_UNIVERSE:
    print(f"{product:12s} latest={latest[product]}")
PY

echo
echo "Completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
