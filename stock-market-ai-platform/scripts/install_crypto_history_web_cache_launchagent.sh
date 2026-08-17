#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="${HOME}/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3)"
fi

LABEL="com.datashepherd.cryptohistorywebcache"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/DataShepherd"
STDOUT_LOG="${LOG_DIR}/cryptohistorywebcache.out.log"
STDERR_LOG="${LOG_DIR}/cryptohistorywebcache.err.log"

mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"

cd "${PROJECT_ROOT}"
"${PYTHON}" -m ml.crypto_rt.history_web_cache --force

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>-m</string>
    <string>ml.crypto_rt.history_web_cache</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StandardOutPath</key>
  <string>${STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${STDERR_LOG}</string>
</dict>
</plist>
EOF

plutil -lint "${PLIST}"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" || true

sleep 1

echo "===== CRYPTO HISTORY WEB CACHE ====="
launchctl print "gui/$(id -u)/${LABEL}" 2>/dev/null | grep -E 'state =|runs =|pid =|last exit code' || true
echo
echo "Cache:  ${PROJECT_ROOT}/data/live/crypto_rt/history_web"
echo "stdout: ${STDOUT_LOG}"
echo "stderr: ${STDERR_LOG}"
echo "Refresh check: hourly; full rebuild at most once per UTC day"
