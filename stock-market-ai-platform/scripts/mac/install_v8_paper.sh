#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v8paper"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v8_paper.lockdir"
UID_VALUE="$(id -u)"

# Backup V8 scheduler. It never invokes the holdout runner directly. Every
# invocation goes through ml.v8.eod_orchestrator, which acquires the shared V8
# orchestration lock, runs the fail-closed EOD guard, and only then invokes the
# frozen append-only holdout runner. This makes the standalone scheduler safe
# to coexist with the main EOD refresh scheduler without concurrent V8 writes.
INTERVAL_SECONDS=300

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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v8.eod_orchestrator; else echo '[SKIP] V8 backup scheduler already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v8_paper.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v8_paper.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rm -rf "$LOCK_DIR"
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Backup schedule: every 5 minutes"
echo "Scheduler overlap guard: $LOCK_DIR"
echo "Shared V8 orchestration lock: data/model/v8/eod_guard/orchestrator.lock"
echo "Production path: python -m ml.v8.eod_orchestrator"
echo "Fail-closed gate: EOD guard must open before holdout runner invocation"
echo "Frozen V8 contract: verified by the holdout runner on every invocation"
echo "Holdout safety: no journal evidence before 2026-09-01"
echo "Brokerage orders: disabled"
echo "Logs: $LOG_DIR/v8_paper.log"
