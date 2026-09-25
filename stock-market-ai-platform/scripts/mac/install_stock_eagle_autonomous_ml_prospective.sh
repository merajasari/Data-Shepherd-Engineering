#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.stockeagleprospective"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/stock_eagle_autonomous_ml_prospective.lockdir"
UID_VALUE="$(id -u)"
INTERVAL_SECONDS=900

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv interpreter: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"

"$PYTHON" -m py_compile   ml/stock_eagle_250_autonomous_ml_prospective_v1/phase3.py   ml/stock_eagle_250_autonomous_ml_prospective_v1/scheduled_entrypoint.py

"$PYTHON" - <<'PY'
from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase3 import (
    load_contract,
    load_snapshot_manifest,
    load_snapshots,
)

contract = load_contract()
manifest = load_snapshot_manifest(contract=contract)
snapshots = load_snapshots(manifest, contract)
assert tuple(snapshots) == (
    "autonomous_ml_v1",
    "autonomous_ml_v2",
    "autonomous_ml_v3",
)
print("Prospective V1/V2/V3 fixed snapshot verification: OK")
for row in contract["fixed_snapshots"]:
    print(row["candidate_id"], row["snapshot_sha256"])
PY

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; '$PYTHON' -u -m ml.stock_eagle_250_autonomous_ml_prospective_v1.scheduled_entrypoint; else echo '[SKIP] StockEagle prospective runner already active'; fi</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/stock_eagle_autonomous_ml_prospective.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/stock_eagle_autonomous_ml_prospective.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rmdir "$LOCK_DIR" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL (fixed-snapshot prospective collector every $INTERVAL_SECONDS seconds)."
echo "Before Oct 1 it remains WAITING_FOR_PROSPECTIVE_BOUNDARY."
echo "After Oct 1 it captures same-day post-close decisions only; missed decisions are never backfilled."
echo "Logs: $LOG_DIR/stock_eagle_autonomous_ml_prospective.log"
echo "Errors: $LOG_DIR/stock_eagle_autonomous_ml_prospective.err.log"
echo "Paper only; retraining, automatic promotion, live execution, and brokerage orders are OFF."
