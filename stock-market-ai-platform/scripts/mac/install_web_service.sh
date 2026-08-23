#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.web"
PLIST="$LAUNCH_DIR/$LABEL.plist"
UID_VALUE="$(id -u)"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$GUNICORN" ]]; then
  echo "Missing Gunicorn executable: $GUNICORN" >&2
  exit 1
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; exec '$GUNICORN' --bind 127.0.0.1:5001 --workers 1 --timeout 120 --access-logfile '$LOG_DIR/gunicorn-access.log' --error-logfile '$LOG_DIR/gunicorn-error.log' webapp.app:app</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/web-launchd.out.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/web-launchd.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Bind: 127.0.0.1:5001"
echo "Workers: 1"
echo "Timeout: 120 seconds"
echo "KeepAlive: enabled"
echo "Application: webapp.app:app"
echo "Logs: $LOG_DIR/gunicorn-error.log"
