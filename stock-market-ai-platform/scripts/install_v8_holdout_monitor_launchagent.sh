#!/bin/zsh
set -euo pipefail
ROOT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PY="$ROOT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.v8holdoutmonitor.plist"
LOGDIR="$ROOT/logs"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"
if [[ ! -x "$PY" ]]; then echo "Missing venv python: $PY"; exit 1; fi
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.datashepherd.v8holdoutmonitor</string>
<key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>ml.v8.holdout_runner</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>StartInterval</key><integer>300</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$LOGDIR/v8_holdout_monitor.out.log</string>
<key>StandardErrorPath</key><string>$LOGDIR/v8_holdout_monitor.err.log</string>
</dict></plist>
EOF
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/com.datashepherd.v8holdoutmonitor" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.datashepherd.v8holdoutmonitor"
echo "===== V8 FROZEN HOLDOUT MONITOR ====="
launchctl print "gui/$(id -u)/com.datashepherd.v8holdoutmonitor" | grep -E 'state =|runs =|pid =|last exit code' || true
echo "Cadence: every 5 minutes; append-only; duplicates skipped"
echo "Holdout start: 2026-09-01 UTC"
echo "Frozen SHA: ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
echo "No brokerage orders. Before Sep 1, no holdout journal evidence is written."
