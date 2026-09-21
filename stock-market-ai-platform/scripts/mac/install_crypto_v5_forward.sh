#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptov5forward.plist"
LABEL="com.datashepherd.cryptov5forward"
UID_VALUE="$(id -u)"
DOMAIN="gui/$UID_VALUE"
LOGDIR="$PROJECT/logs"
PHASE4="$PROJECT/data/research/crypto_ten_year/reconstruction/crypto_v5/phase4"
CLEAN="$PROJECT/data/research/crypto_ten_year/reconstruction/crypto_v5/phase5/clean_forward_v1"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

for required in \
  "$PHASE4/selected_contract.json" \
  "$PHASE4/artifacts/allocation_btc_3d.joblib" \
  "$PHASE4/artifacts/allocation_alt_3d.joblib" \
  "$PHASE4/artifacts/allocation_cash_3d.joblib" \
  "$PHASE4/artifacts/ranking_3d.joblib"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing frozen Crypto V5 artifact: $required" >&2
    echo "Rebuild and verify Crypto V5 Phase 4 before installing the paper service." >&2
    exit 1
  fi
done

cd "$PROJECT"
"$PYTHON" -m ml.crypto_v5.forward_service --once

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
    <string>ml.crypto_v5.forward_service</string>
    <string>--poll-seconds</string>
    <string>300</string>
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
  <string>$LOGDIR/crypto_v5_forward.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGDIR/crypto_v5_forward.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
chmod 600 "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
mkdir -p "$CLEAN"
rm -f "$CLEAN/forward_service.lock"
launchctl enable "$DOMAIN/$LABEL"
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  echo "launchctl bootstrap failed; retrying with the macOS legacy user-agent loader." >&2
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
fi
launchctl kickstart -k "$DOMAIN/$LABEL"
sleep 2
if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "LaunchAgent did not remain loaded: $DOMAIN/$LABEL" >&2
  exit 1
fi

echo "Installed $LABEL"
echo "Lane: Crypto V5 Clean Paper V1"
echo "Observation begins: 2026-09-22 07:00 UTC / 2026-09-22 00:00 Pacific"
echo "First eligible completed daily decision: 2026-09-23 00:00 UTC"
echo "Starting paper equity: USD 100,000"
echo "Decision cadence: every 3 completed UTC daily candles"
echo "Late or missed decision policy: FAIL CLOSED, NO BACKFILL"
echo "Status: $CLEAN/forward_service_status.json"
echo "State: $CLEAN/paper_state.json"
echo "Journal: $CLEAN/paper_events.jsonl"
echo "Logs: $LOGDIR/crypto_v5_forward.out.log / $LOGDIR/crypto_v5_forward.err.log"
echo "No brokerage orders are placed."
