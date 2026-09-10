#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v14logisticforward"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v14_logistic_forward_scheduler.lockdir"
UID_VALUE="$(id -u)"
INTERVAL_SECONDS=300

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv interpreter: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON" -m ml.v14.logistic_forward_contract

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>EnvironmentVariables</key>
  <dict><key>FEATURE_BACKEND</key><string>spark</string></dict>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; '$PYTHON' -u -m ml.v14.logistic_forward_scheduler; else echo '[SKIP] V14 scheduler already running'; fi</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/v14_logistic_forward.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/v14_logistic_forward.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

if launchctl print "gui/$UID_VALUE/com.datashepherd.v8refresh" >/dev/null 2>&1; then
  echo "Shared market-data refresher detected: com.datashepherd.v8refresh"
else
  echo "WARNING: com.datashepherd.v8refresh is not loaded. V14 will wait until the shared feature snapshot is current."
fi
echo "Installed $LABEL (data readiness + V14 collector every $INTERVAL_SECONDS seconds)."
echo "Logs: $LOG_DIR/v14_logistic_forward.log and $LOG_DIR/v14_logistic_forward.err.log"
echo "Paper trading only; brokerage orders are OFF."
