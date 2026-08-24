#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
LABEL="com.datashepherd.v8evidencealerts"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PROJECT_ROOT/logs/v8_evidence_alerts.log"
UID_VALUE="$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_ROOT/logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_ROOT' &amp;&amp; '$PYTHON' -u -m ml.v8.evidence_milestone_monitor</string>
</array>
<key>StartInterval</key><integer>300</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$LOG</string>
<key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"
launchctl enable "gui/$UID_VALUE/$LABEL"
launchctl kickstart -k "gui/$UID_VALUE/$LABEL"

echo "Installed $LABEL"
echo "Schedule: every 5 minutes"
echo "Milestones: first DECISION, first ENTRY, first EXIT"
echo "Failure/recovery alerts remain handled by ml.v8.operational_monitor"
echo "Production evidence writes: NONE"
echo "Brokerage orders: OFF"
