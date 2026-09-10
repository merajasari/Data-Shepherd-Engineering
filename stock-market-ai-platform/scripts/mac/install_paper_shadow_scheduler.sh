#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.papershadow"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/paper_shadow_scheduler.lockdir"
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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.trading.paper_shadow_scheduled_entrypoint; else echo '[SKIP] Paper-shadow scheduler already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/paper_shadow_scheduler.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/paper_shadow_scheduler.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Mode: monitor-only while bridge is disabled"
echo "Entrypoint: python -m ml.trading.paper_shadow_scheduled_entrypoint"
echo "Bridge invocation: blocked"
echo "Signal exports: 0"
echo "Holdout outcomes read: NO"
echo "Production evidence modified: NO"
echo "Live credentials: absent"
echo "Brokerage orders: OFF"
echo "Logs: $LOG_DIR/paper_shadow_scheduler.log"
