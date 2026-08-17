#!/bin/zsh
set -euo pipefail

LABEL="com.datashepherd.stockiex"
PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/DataShepherd"
OUT_LOG="$LOG_DIR/stockiex.out.log"
ERR_LOG="$LOG_DIR/stockiex.err.log"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$PROJECT" ]]; then
  echo "Project directory not found: $PROJECT" >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Project Python not found or not executable: $PYTHON" >&2
  exit 1
fi
if [[ ! -f "$PROJECT/data-ingestion/iex_stream.py" ]]; then
  echo "Tiingo IEX stream not found." >&2
  exit 1
fi
if [[ ! -f "$PROJECT/.env" ]]; then
  echo "Project .env not found; TIINGO_API_KEY must be available there." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>cd '${PROJECT}' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export IEX_SYMBOL_SET=v5 PYTHONPATH='${PROJECT}/data-ingestion' PYTHONUNBUFFERED=1 &amp;&amp; exec '${PYTHON}' -u data-ingestion/iex_stream.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${OUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${ERR_LOG}</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

sleep 3

echo "===== STOCK IEX REAL-TIME STREAM ====="
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|runs =|pid =|last exit code' || true

echo
echo "Universe: V5 (100 stocks + SPY)"
echo "Cache:    $PROJECT/data/live/latest_quotes.json"
echo "stdout:   $OUT_LOG"
echo "stderr:   $ERR_LOG"
