#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
UID_VALUE="$(id -u)"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

cat > "$LAUNCH_DIR/com.datashepherd.web.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.datashepherd.web</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; exec '$GUNICORN' --bind 127.0.0.1:5001 --workers 2 --timeout 120 --access-logfile '$LOG_DIR/gunicorn-access.log' --error-logfile '$LOG_DIR/gunicorn-error.log' webapp.app:app</string>
</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/web-launchd.out.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/web-launchd.err.log</string>
</dict></plist>
EOF

cat > "$LAUNCH_DIR/com.datashepherd.iexstream.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.datashepherd.iexstream</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; export IEX_SYMBOL_SET=v5 &amp;&amp; set +a &amp;&amp; export PYTHONPATH='$PROJECT_DIR/data-ingestion' &amp;&amp; exec '$PYTHON' -u data-ingestion/iex_stream.py</string>
</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/iex_stream.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/iex_stream.err.log</string>
</dict></plist>
EOF

cat > "$LAUNCH_DIR/com.datashepherd.keepawake.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.datashepherd.keepawake</string>
<key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/keepawake.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/keepawake.err.log</string>
</dict></plist>
EOF

for label in com.datashepherd.web com.datashepherd.iexstream com.datashepherd.keepawake; do
  plist="$LAUNCH_DIR/$label.plist"
  plutil -lint "$plist"
  launchctl bootout "gui/$UID_VALUE/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_VALUE" "$plist"
done

echo "Realtime Mac services installed."
echo "Web: http://127.0.0.1:5001"
echo "Live universe: 100 V5 candidates + SPY"
echo "Idle sleep prevention: enabled"
