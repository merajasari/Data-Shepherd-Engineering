#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v10cycle3acceleratedv2"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v10_cycle3_accelerated_v2.lockdir"
UID_VALUE="$(id -u)"
INTERVAL_SECONDS=300

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON" -m ml.v10.cycle3_accelerated_forward_v2_contract

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>EnvironmentVariables</key><dict>
<key>FEATURE_BACKEND</key><string>spark</string>
</dict>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v10.cycle3_accelerated_v2_scheduled_entrypoint; else echo '[SKIP] accelerated V10 scheduler already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v10_cycle3_accelerated_v2.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v10_cycle3_accelerated_v2.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Feature backend: spark"
echo "First eligible decision session: 2026-09-10"
echo "No missed decision may be backfilled"
echo "Original January 4 confirmation: unchanged"
echo "Automatic promotion: disabled; human review required"
echo "V8 invocation: absent"
echo "Brokerage orders: disabled"
echo "Logs: $LOG_DIR/v10_cycle3_accelerated_v2.log"
