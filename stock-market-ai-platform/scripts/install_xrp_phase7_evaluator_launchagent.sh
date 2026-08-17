#!/bin/zsh
set -euo pipefail

LABEL="com.datashepherd.xrpphase7"
PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/DataShepherd"
OUT_LOG="$LOG_DIR/xrpphase7.out.log"
ERR_LOG="$LOG_DIR/xrpphase7.err.log"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$PROJECT" ]]; then
  echo "Project directory not found: $PROJECT" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Project Python not found or not executable: $PYTHON" >&2
  exit 1
fi

if [[ ! -f "$PROJECT/ml/crypto_xrp_v1/phase7.py" ]]; then
  echo "XRP Phase 7 evaluator not found." >&2
  exit 1
fi

if [[ ! -f "$PROJECT/data/model/crypto_xrp_v1/phase6/frozen_ridge.joblib" ]]; then
  echo "Frozen XRP Ridge artifact not found. Run Phase 6 first." >&2
  exit 1
fi

if [[ ! -f "$PROJECT/data/model/crypto_xrp_v1/phase6/freeze_manifest.json" ]]; then
  echo "XRP Phase 6 freeze manifest not found. Run Phase 6 first." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

# Verify the evaluator contract before installing the persistent service.
cd "$PROJECT"
"$PYTHON" -m ml.crypto_xrp_v1.phase7 --once

cat > "$PLIST" <<EOF
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
        <string>ml.crypto_xrp_v1.phase7</string>
        <string>--poll-seconds</string>
        <string>60</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>${OUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>${ERR_LOG}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

plutil -lint "$PLIST"

launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

sleep 2

echo
echo "===== XRP PHASE 7 EVALUATOR LAUNCHAGENT ====="
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|runs =|pid =|last exit code' || true

echo
echo "Plist:  $PLIST"
echo "stdout: $OUT_LOG"
echo "stderr: $ERR_LOG"
echo
echo "Before Sep 1, 2026 the evaluator remains readiness-only and cannot append evaluation events."
echo "At/after the boundary it records paper-evaluation events only. No brokerage orders are placed."
