#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptov2forward.plist"
LABEL="com.datashepherd.cryptov2forward"
UID_VALUE="$(id -u)"
DOMAIN="gui/$UID_VALUE"
LOGDIR="$PROJECT/logs"
PHASE5="$PROJECT/data/model/crypto_15m_v2/phase5"
PARENT="$PHASE5/clean_forward_v2"
CLEAN="$PHASE5/clean_forward_v3"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

for required in \
  "$PHASE5/frozen_hgb.joblib" \
  "$PHASE5/freeze_manifest.json" \
  "$PHASE5/forward_state.json" \
  "$PHASE5/forward_journal.csv" \
  "$PARENT/forward_state.json" \
  "$PARENT/forward_journal.csv"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing frozen Phase 5 artifact: $required" >&2
    echo "Run: python -m ml.crypto_15m_v2.phase5" >&2
    exit 1
  fi
done

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
    <string>ml.crypto_15m_v2.forward_service_v3</string>
    <string>--poll-seconds</string>
    <string>60</string>
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
  <string>$LOGDIR/crypto_v2_forward.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGDIR/crypto_v2_forward.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
chmod 600 "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
mkdir -p "$CLEAN"
rm -f "$PHASE5/forward_service.lock" "$PARENT/forward_service.lock" "$CLEAN/forward_service.lock"
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
echo "Lane: Shared Crypto V2 Clean Forward V3"
echo "Mode before 2026-09-22 07:00 UTC: WAITING_CLEAN_BOUNDARY (no evidence rows)"
echo "Mode at/after the exact boundary: CLEAN_FORWARD paper evaluation"
echo "If the first boundary is missed: FAIL CLOSED (no late start or backfill)"
echo "Frozen model: $PHASE5/frozen_hgb.joblib"
echo "Preserved original interrupted state: $PHASE5/forward_state.json"
echo "Preserved original interrupted journal: $PHASE5/forward_journal.csv"
echo "Preserved V2 parent state: $PARENT/forward_state.json"
echo "Preserved V2 parent journal: $PARENT/forward_journal.csv"
echo "Clean state: $CLEAN/forward_state.json"
echo "Clean journal: $CLEAN/forward_journal.csv"
echo "Clean status: $CLEAN/forward_service_status.json"
echo "Clean contract: $CLEAN/clean_lane_manifest.json"
echo "Waiting snapshot: $CLEAN/waiting_latest.json"
echo "Logs: $LOGDIR/crypto_v2_forward.out.log / $LOGDIR/crypto_v2_forward.err.log"
echo "No brokerage orders are placed."
