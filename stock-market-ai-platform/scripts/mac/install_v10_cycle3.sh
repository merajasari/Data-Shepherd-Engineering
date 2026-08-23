#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v10cycle3"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v10_cycle3.lockdir"
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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v10.cycle3_scheduled_entrypoint; else echo '[SKIP] V10 Cycle 3 scheduler already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v10_cycle3.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v10_cycle3.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Isolated overlap guard: $LOCK_DIR"
echo "Entrypoint: python -m ml.v10.cycle3_scheduled_entrypoint"
echo "Frozen SHA verified on every runner invocation"
echo "Holdout safety: no journal evidence before 2027-01-04"
echo "V8 invocation: absent"
echo "Brokerage orders: disabled"
echo "Logs: $LOG_DIR/v10_cycle3.log"
