#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v11phase2"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v11_phase2.lockdir"
UID_VALUE="$(id -u)"
INTERVAL_SECONDS=300

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v11.intraday_phase2_scheduled_entrypoint; else echo '[SKIP] V11 Phase 2 scheduler already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v11_phase2.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v11_phase2.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Entrypoint: python -m ml.v11.intraday_phase2_scheduled_entrypoint"
echo "Collection checkpoints: decision 9:58-10:03, entry 10:03-10:08, exit 10:28-10:33 Eastern"
echo "Current activation: ENABLED for fresh paper confirmation only"
echo "Maximum Tiingo requests per session: 404 (3 checkpoints plus 1 bounded catch-up)"
echo "Same-session wake-up catch-up: enabled once after 10:33 AM Eastern"
echo "Paper trading only: YES"
echo "Brokerage orders: OFF"
echo "V8/V10 production modified: NO"
echo "Logs: $LOG_DIR/v11_phase2.log"
