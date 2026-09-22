#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="$PROJECT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptov5forward.plist"
LABEL="com.datashepherd.cryptov5forward"
UID_VALUE="$(id -u)"
DOMAIN="gui/$UID_VALUE"
LOGDIR="$PROJECT/logs"
PHASE4="$PROJECT/data/research/crypto_ten_year/reconstruction/crypto_v5/phase4"
CLEAN="$PROJECT/data/research/crypto_ten_year/reconstruction/crypto_v5/phase5/clean_forward_v2"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

for required in \
  "$PHASE4/selected_contract.json" \
  "$PHASE4/artifacts/allocation_btc_3d.joblib" \
  "$PHASE4/artifacts/allocation_alt_3d.joblib" \
  "$PHASE4/artifacts/allocation_cash_3d.joblib" \
  "$PHASE4/artifacts/ranking_3d.joblib"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing frozen Crypto V5 artifact: $required" >&2
    echo "Rebuild and verify Crypto V5 Phase 4 before installing the paper service." >&2
    exit 1
  fi
done

cd "$PROJECT"
"$PYTHON" -m unittest discover -s tests -p 'test_crypto_v5_forward_service.py' -v
"$PYTHON" -m ml.crypto_v5.forward_service --once

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>-m</string>
    <string>ml.crypto_v5.forward_service</string>
    <string>--poll-seconds</string>
    <string>300</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>$LOGDIR/crypto_v5_forward.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGDIR/crypto_v5_forward.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
chmod 600 "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
mkdir -p "$CLEAN"
rm -f "$CLEAN/forward_service.lock"
launchctl enable "$DOMAIN/$LABEL"
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  echo "launchctl bootstrap failed; retrying with the macOS legacy user-agent loader." >&2
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
fi
launchctl kickstart -k "$DOMAIN/$LABEL"
sleep 2
if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "LaunchAgent did not remain loaded: $DOMAIN/$LABEL" >&2
  exit 1
fi

STATUS="$CLEAN/forward_service_status.json"
RUNNING_PID="$(launchctl print "$DOMAIN/$LABEL" | awk '/pid =/{print $3; exit}')"
if [[ -z "$RUNNING_PID" ]]; then
  echo "Crypto V5 V2 LaunchAgent has no running PID." >&2
  exit 1
fi
case "$RUNNING_PID" in
  *[!0-9]*)
    echo "Crypto V5 V2 LaunchAgent returned a non-numeric PID: $RUNNING_PID" >&2
    exit 1
    ;;
esac
for _ in {1..30}; do
  STATUS_PID="$("$PYTHON" - "$STATUS" <<'PY' 2>/dev/null || true
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.exists():
    print(json.loads(path.read_text(encoding="utf-8")).get("service_pid", ""))
PY
)"
  [[ "$STATUS_PID" == "$RUNNING_PID" ]] && break
  sleep 1
done
"$PYTHON" - "$STATUS" "$RUNNING_PID" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_pid = int(sys.argv[2])
if not path.exists():
    raise SystemExit(f"Crypto V5 V2 heartbeat was not created: {path}")
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"Crypto V5 V2 heartbeat is not healthy: {payload}")
if payload.get("lane_id") != "crypto_v5_clean_forward_v2":
    raise SystemExit(f"Unexpected Crypto V5 lane: {payload.get('lane_id')}")
if payload.get("contract_verified") is not True:
    raise SystemExit("Crypto V5 V2 contract verification failed")
if int(payload.get("service_pid", -1)) != expected_pid:
    raise SystemExit(
        f"Crypto V5 V2 heartbeat PID {payload.get('service_pid')} "
        f"does not match LaunchAgent PID {expected_pid}"
    )
print(f"Crypto V5 V2 persistent heartbeat: VERIFIED (PID {expected_pid})")
PY

echo "Installed $LABEL"
echo "Lane: Crypto V5 Clean Paper V2"
echo "Archived lane preserved: Crypto V5 Clean Paper V1"
echo "Observation begins: 2026-09-23 07:00 UTC / 2026-09-23 00:00 Pacific"
echo "First eligible completed daily decision: 2026-09-24 00:00 UTC / 2026-09-23 17:00 Pacific"
echo "Starting paper equity: USD 100,000"
echo "Decision cadence: every 3 completed UTC daily candles"
echo "Late or missed decision policy: FAIL CLOSED, NO BACKFILL"
echo "Status: $CLEAN/forward_service_status.json"
echo "State: $CLEAN/paper_state.json"
echo "Journal: $CLEAN/paper_events.jsonl"
echo "Logs: $LOGDIR/crypto_v5_forward.out.log / $LOGDIR/crypto_v5_forward.err.log"
echo "No brokerage orders are placed."
