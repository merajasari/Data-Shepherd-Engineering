#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptoreconcile.plist"
LABEL="com.datashepherd.cryptoreconcile"
LOGDIR="$PROJECT/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>-m</string>
    <string>ml.crypto_rt.reconcile_15m</string>
    <string>--poll-seconds</string>
    <string>60</string>
    <string>--settle-seconds</string>
    <string>45</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>$LOGDIR/crypto_reconcile.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGDIR/crypto_reconcile.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PROJECT/data/live/crypto_rt/reconcile_15m.lock"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed $LABEL"
echo "Authoritative archive: $PROJECT/data/research/crypto_intraday/raw_15m"
echo "Status: $PROJECT/data/live/crypto_rt/reconcile_status.json"
echo "Latest closed bars: $PROJECT/data/live/crypto_rt/latest_authoritative_15m.json"
echo "Logs: $LOGDIR/crypto_reconcile.out.log / crypto_reconcile.err.log"
