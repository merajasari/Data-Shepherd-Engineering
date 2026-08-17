#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${HOME}/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then PYTHON="$(command -v python3)"; fi
LABEL="com.datashepherd.realtimestockjournals"
OLD_LABEL="com.datashepherd.v5shadowcomparisonjournal"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/DataShepherd"
mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"

# Retire the old hourly comparison scheduler; the continuous collector replaces it.
launchctl bootout "gui/$(id -u)/${OLD_LABEL}" 2>/dev/null || true

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${LABEL}</string>
<key>ProgramArguments</key><array><string>${PYTHON}</string><string>-m</string><string>ml.run_realtime_stock_journals</string></array>
<key>WorkingDirectory</key><string>${PROJECT_ROOT}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>5</integer>
<key>StandardOutPath</key><string>${LOG_DIR}/realtimestockjournals.out.log</string>
<key>StandardErrorPath</key><string>${LOG_DIR}/realtimestockjournals.err.log</string>
</dict></plist>
EOF
plutil -lint "${PLIST}"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"
sleep 1

echo "===== REAL-TIME STOCK JOURNALS ====="
launchctl print "gui/$(id -u)/${LABEL}" | grep -E 'state =|runs =|pid =|last exit code' || true
echo
echo "Cadence: 5 seconds while quotes change; duplicate quote snapshots are skipped"
echo "V4 journal: ${PROJECT_ROOT}/data/paper_trading/realtime_equity_journal.jsonl"
echo "Comparison journal: ${PROJECT_ROOT}/data/paper_trading/v5_shadow/comparison_journal.jsonl"
echo "Official Sep 1+ V5 holdout remains untouched"
