#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v15prospectivev7"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v15_prospective_v7.lockdir"
UID_VALUE="$(id -u)"
INTERVAL_SECONDS=300

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv interpreter: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON" -m ml.v15.intraday_prospective_v7_regression
"$PYTHON" -m ml.v15.intraday_prospective_v7_runner --prepare

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
    <string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; '$PYTHON' -u -m ml.v15.intraday_prospective_v7_scheduled_entrypoint; else echo '[SKIP] V15 V7 scheduler already running'; fi</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/v15_prospective_v7.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/v15_prospective_v7.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Schedule: guarded check every 5 minutes"
echo "First eligible session: September 21, 2026"
echo "Decision data: first six completed five-minute bars only"
echo "Risk budget: 60% invested / 40% cash"
echo "Maximum Tiingo requests per session: 303"
echo "Paper shadow only; automatic promotion is disabled."
echo "Brokerage orders are OFF."
echo "Existing V8/V10/V11/V13/V14 models are not modified."
echo "Logs: $LOG_DIR/v15_prospective_v7.log and $LOG_DIR/v15_prospective_v7.err.log"
