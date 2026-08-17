#!/bin/zsh
set -euo pipefail

LABEL="com.datashepherd.cryptoreadiness"
PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/DataShepherd"
OUT_LOG="$LOG_DIR/cryptoreadiness.out.log"
ERR_LOG="$LOG_DIR/cryptoreadiness.err.log"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$PROJECT" ]]; then
  echo "Project directory not found: $PROJECT" >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Project Python not found or not executable: $PYTHON" >&2
  exit 1
fi
if [[ ! -f "$PROJECT/ml/crypto_readiness_status.py" ]]; then
  echo "Crypto readiness status publisher not found." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
cd "$PROJECT"

# Publish one snapshot before installation. A non-ready result is valid runtime
# state, so installation continues even if the publisher exits nonzero.
"$PYTHON" -m ml.crypto_readiness_status || true

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
        <string>cd '${PROJECT}' &amp;&amp; '${PYTHON}' -m ml.crypto_readiness_status || true</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>600</integer>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>${OUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${ERR_LOG}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

sleep 2

echo
echo "===== CRYPTO READINESS LAUNCHAGENT ====="
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|runs =|pid =|last exit code' || true

echo
echo "Plist:  $PLIST"
echo "stdout: $OUT_LOG"
echo "stderr: $ERR_LOG"
echo "Snapshot: $PROJECT/data/live/crypto_readiness/readiness_status.json"
echo "Refresh interval: 10 minutes"
