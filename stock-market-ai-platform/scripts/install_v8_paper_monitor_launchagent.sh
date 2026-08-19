#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$ROOT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.v8papermonitor.plist"
LABEL="com.datashepherd.v8papermonitor"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array><string>$PYTHON</string><string>-m</string><string>ml.v8.paper_runner</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>StartInterval</key><integer>300</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$ROOT/logs/v8_paper_monitor.out.log</string>
<key>StandardErrorPath</key><string>$ROOT/logs/v8_paper_monitor.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "V8 operational paper monitor installed."
echo "Cadence: every 5 minutes"
echo "Frozen candidate only; no brokerage orders; never used as holdout evidence."
