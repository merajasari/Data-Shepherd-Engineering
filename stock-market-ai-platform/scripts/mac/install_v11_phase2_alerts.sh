#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v11phase2alerts"
PLIST="$LAUNCH_DIR/$LABEL.plist"
UID_VALUE="$(id -u)"

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
<string>cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v11.intraday_phase2_alerts</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>300</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v11_phase2_alerts.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v11_phase2_alerts.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"
launchctl enable "gui/$UID_VALUE/$LABEL"
launchctl kickstart -k "gui/$UID_VALUE/$LABEL"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Milestones: first DECISION, first ENTRY, first SESSION_OBSERVATION"
echo "Operational notices: scheduler/monitor failure and recovery"
echo "Production evidence writes: NONE"
echo "Paper trading only: YES"
echo "Brokerage orders: OFF"
