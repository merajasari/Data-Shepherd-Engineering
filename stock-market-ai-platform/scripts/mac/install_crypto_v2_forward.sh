#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptov2forward.plist"
LABEL="com.datashepherd.cryptov2forward"
LOGDIR="$PROJECT/logs"
PHASE5="$PROJECT/data/model/crypto_15m_v2/phase5"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

for required in \
  "$PHASE5/frozen_hgb.joblib" \
  "$PHASE5/freeze_manifest.json" \
  "$PHASE5/forward_state.json" \
  "$PHASE5/forward_journal.csv"; do
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
    <string>ml.crypto_15m_v2.forward_service</string>
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
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PHASE5/forward_service.lock"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed $LABEL"
echo "Mode before 2026-09-01 UTC: SHADOW (no forward journal rows)"
echo "Mode at/after 2026-09-01 UTC: FORWARD paper evaluation"
echo "Frozen model: $PHASE5/frozen_hgb.joblib"
echo "State: $PHASE5/forward_state.json"
echo "Journal: $PHASE5/forward_journal.csv"
echo "Status: $PHASE5/forward_service_status.json"
echo "Shadow snapshot: $PHASE5/shadow_latest.json"
echo "Logs: $LOGDIR/crypto_v2_forward.out.log / crypto_v2_forward.err.log"
echo "No brokerage orders are placed."
