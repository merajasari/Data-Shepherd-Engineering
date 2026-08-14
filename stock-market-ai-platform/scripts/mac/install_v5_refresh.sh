#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v5refresh"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v5_refresh.lockdir"
UID_VALUE="$(id -u)"

# Invoke frequently, but let Python's persistent rolling quota ledger decide
# how many Tiingo REST calls are safe right now. This allows a startup catch-up
# to consume available capacity immediately while never intentionally exceeding
# the configured 45 attempts in any rolling 60-minute scheduler window.
INTERVAL_SECONDS=300
HOURLY_REQUEST_LIMIT=45

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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; exec '$PYTHON' -u -m ml.run_v5_data_refresh --hourly-request-limit $HOURLY_REQUEST_LIMIT; else echo '[SKIP] V5 refresh already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v5_refresh.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v5_refresh.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rm -rf "$LOCK_DIR"
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Startup catch-up: enabled (RunAtLoad)"
echo "Schedule: every 5 minutes"
echo "Overlap guard: $LOCK_DIR"
echo "Rolling Tiingo scheduler limit: $HOURLY_REQUEST_LIMIT requests / 60 minutes"
echo "Catch-up policy: use all currently available rolling-hour capacity"
echo "Logs: $LOG_DIR/v5_refresh.log"
