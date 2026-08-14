#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
UID_VALUE="$(id -u)"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

if [[ ! -x "$GUNICORN" ]]; then
  echo "Missing gunicorn: $GUNICORN" >&2
  exit 1
fi

write_plist() {
  local label="$1"
  local body="$2"
  local path="$LAUNCH_DIR/$label.plist"
  print -r -- "$body" > "$path"
  plutil -lint "$path"
}

WEB_LABEL="com.datashepherd.web"
STREAM_LABEL="com.datashepherd.iexstream"
REFRESH_LABEL="com.datashepherd.v5refresh"
AWAKE_LABEL="com.datashepherd.keepawake"

write_plist "$WEB_LABEL" "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>Label</key><string>$WEB_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; exec '$GUNICORN' --bind 127.0.0.1:5001 --workers 2 --timeout 120 --access-logfile '$LOG_DIR/gunicorn-access.log' --error-logfile '$LOG_DIR/gunicorn-error.log' webapp.app:app</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/web-launchd.out.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/web-launchd.err.log</string>
</dict></plist>"

write_plist "$STREAM_LABEL" "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>Label</key><string>$STREAM_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; export IEX_SYMBOL_SET=v5 &amp;&amp; set +a &amp;&amp; exec '$PYTHON' -u data-ingestion/iex_stream.py</string>
</array>
<key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>$PROJECT_DIR/data-ingestion</string></dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/iex_stream.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/iex_stream.err.log</string>
</dict></plist>"

write_plist "$REFRESH_LABEL" "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>Label</key><string>$REFRESH_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; exec '$PYTHON' -u -m ml.run_v5_data_refresh --max-requests 45</string>
</array>
<key>StartCalendarInterval</key><dict><key>Minute</key><integer>5</integer></dict>
<key>StandardOutPath</key><string>$LOG_DIR/v5_refresh.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v5_refresh.err.log</string>
</dict></plist>"

write_plist "$AWAKE_LABEL" "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>Label</key><string>$AWAKE_LABEL</string>
<key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/keepawake.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/keepawake.err.log</string>
</dict></plist>"

for label in "$WEB_LABEL" "$STREAM_LABEL" "$REFRESH_LABEL" "$AWAKE_LABEL"; do
  launchctl bootout "gui/$UID_VALUE/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_VALUE" "$LAUNCH_DIR/$label.plist"
done

echo
echo "Installed Data Shepherd Mac LaunchAgents:"
for label in "$WEB_LABEL" "$STREAM_LABEL" "$REFRESH_LABEL" "$AWAKE_LABEL"; do
  launchctl print "gui/$UID_VALUE/$label" 2>/dev/null | grep -E 'state =|pid =' | head -2 || true
done

echo
echo "Web origin: http://127.0.0.1:5001"
echo "Live stream universe: V5 candidates + SPY"
echo "EOD refresh: minute 5 of every hour, quota-aware"
echo "Idle system sleep prevention: enabled while LaunchAgent is loaded"
