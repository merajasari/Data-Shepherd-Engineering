#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
ARCHIVE_DIR="$LOG_DIR/archive"
LABEL="com.datashepherd.v8refresh"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v8_refresh.lockdir"
UID_VALUE="$(id -u)"

INTERVAL_SECONDS="${V8_REFRESH_INTERVAL_SECONDS:-300}"
HOURLY_REQUEST_LIMIT="${TIINGO_HOURLY_REQUEST_LIMIT:-500}"
TIINGO_PLAN_VALUE="${TIINGO_PLAN:-power}"
FEATURE_BACKEND_VALUE="${FEATURE_BACKEND:-spark}"
JAVA_HOME_VALUE="${JAVA_HOME:-$(/usr/libexec/java_home -v 17)}"
RUNTIME_PATH="$PROJECT_DIR/.venv/bin:$JAVA_HOME_VALUE/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ "$TIINGO_PLAN_VALUE" != "power" ]]; then
  echo "Refusing Power scheduler installation: TIINGO_PLAN must be power." >&2
  exit 2
fi
if ! [[ "$HOURLY_REQUEST_LIMIT" =~ '^[0-9]+$' ]] || (( HOURLY_REQUEST_LIMIT < 101 || HOURLY_REQUEST_LIMIT > 10000 )); then
  echo "TIINGO_HOURLY_REQUEST_LIMIT must be between 101 and 10000 for Power." >&2
  exit 2
fi
if ! [[ "$INTERVAL_SECONDS" =~ '^[0-9]+$' ]] || (( INTERVAL_SECONDS < 60 )); then
  echo "V8_REFRESH_INTERVAL_SECONDS must be at least 60." >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 2
fi

mkdir -p "$LAUNCH_DIR" "$LOG_DIR" "$ARCHIVE_DIR"
chmod 700 "$ARCHIVE_DIR"

if [[ -s "$LOG_DIR/v8_refresh.err.log" ]]; then
  STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
  mv "$LOG_DIR/v8_refresh.err.log" "$ARCHIVE_DIR/v8_refresh.err.$STAMP.log"
  chmod 600 "$ARCHIVE_DIR/v8_refresh.err.$STAMP.log"
  echo "Archived previous V8 scheduler stderr with owner-only permissions."
fi
: > "$LOG_DIR/v8_refresh.err.log"
chmod 600 "$LOG_DIR/v8_refresh.err.log"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR'; rc=0; { '$PYTHON' -u ml/run_v8_data_refresh.py --hourly-request-limit $HOURLY_REQUEST_LIMIT &amp;&amp; '$PYTHON' -u -m ml.v10.confirmation_cycle; } || rc=\$?; conv_rc=0; '$PYTHON' -u -m ml.data_convergence || conv_rc=\$?; if [[ \$rc -eq 0 &amp;&amp; \$conv_rc -ne 0 ]]; then rc=\$conv_rc; fi; '$PYTHON' -u -m ml.operations_health --pipeline-exit-code \$rc || true; exit \$rc; else echo '[SKIP] V8 refresh already running'; fi</string>
</array>
<key>EnvironmentVariables</key><dict>
<key>FEATURE_BACKEND</key><string>$FEATURE_BACKEND_VALUE</string>
<key>TIINGO_PLAN</key><string>$TIINGO_PLAN_VALUE</string>
<key>TIINGO_HOURLY_REQUEST_LIMIT</key><string>$HOURLY_REQUEST_LIMIT</string>
<key>JAVA_HOME</key><string>$JAVA_HOME_VALUE</string>
<key>PATH</key><string>$RUNTIME_PATH</string>
</dict>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v8_refresh.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v8_refresh.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/com.datashepherd.v5refresh" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Tiingo plan: $TIINGO_PLAN_VALUE"
echo "Rolling Tiingo ceiling: $HOURLY_REQUEST_LIMIT requests / 60 minutes"
echo "Schedule: every $INTERVAL_SECONDS seconds"
echo "Feature backend: $FEATURE_BACKEND_VALUE"
echo "Universe: full 101-symbol atomic convergence"
echo "V8 decision gate: fail closed until complete"
echo "Intraday quotes: handled separately by the IEX stream"
echo "Brokerage orders: OFF"
echo "Logs: $LOG_DIR/v8_refresh.log"
