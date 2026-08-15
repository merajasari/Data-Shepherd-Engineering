#!/bin/zsh
set -euo pipefail

ROOT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PY="$ROOT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptort.plist"
LOGDIR="$ROOT/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if ! "$PY" -c 'import websockets' >/dev/null 2>&1; then
  echo "Installing websockets into project virtualenv..."
  "$ROOT/.venv/bin/pip" install websockets
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.datashepherd.cryptort</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd '$ROOT' &amp;&amp; exec '$PY' -u -m ml.crypto_rt.coinbase_stream</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>$LOGDIR/crypto_rt.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGDIR/crypto_rt.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/com.datashepherd.cryptort" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.datashepherd.cryptort"
launchctl kickstart -k "gui/$(id -u)/com.datashepherd.cryptort"

echo "Installed com.datashepherd.cryptort"
echo "Source: Coinbase Exchange public WebSocket"
echo "Products: 25 USD crypto products"
echo "Ingestion: continuous real-time ticker stream"
echo "Persisted bars: closed 15-minute OHLCV approximations"
echo "Latest quotes: data/live/crypto_rt/latest_quotes.json"
echo "Status: data/live/crypto_rt/status.json"
echo "Logs: $LOGDIR/crypto_rt.out.log / crypto_rt.err.log"
