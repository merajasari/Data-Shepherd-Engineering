#!/bin/zsh
set -euo pipefail
LABEL="com.datashepherd.cryptoticker"
PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/DataShepherd"
OUT_LOG="$LOG_DIR/cryptoticker.out.log"
ERR_LOG="$LOG_DIR/cryptoticker.err.log"
DOMAIN="gui/$(id -u)"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
[[ -x "$PYTHON" ]] || { echo "Python not found: $PYTHON" >&2; exit 1; }
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${LABEL}</string>
<key>ProgramArguments</key><array><string>/bin/zsh</string><string>-lc</string><string>cd '${PROJECT}' &amp;&amp; exec '${PYTHON}' -m ml.crypto_rt.ticker_stream</string></array>
<key>WorkingDirectory</key><string>${PROJECT}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ProcessType</key><string>Background</string>
<key>ThrottleInterval</key><integer>10</integer>
<key>StandardOutPath</key><string>${OUT_LOG}</string>
<key>StandardErrorPath</key><string>${ERR_LOG}</string>
<key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
</dict></plist>
EOF
plutil -lint "$PLIST"
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"
sleep 2
echo "===== CRYPTO REAL-TIME TICKER ====="
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|runs =|pid =|last exit code' || true
echo "Cache: $PROJECT/data/live/crypto_rt/latest_tickers.json"
echo "stdout: $OUT_LOG"
echo "stderr: $ERR_LOG"
