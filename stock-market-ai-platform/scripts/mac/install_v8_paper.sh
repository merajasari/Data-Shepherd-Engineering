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

# Run frequently enough to catch a newly completed session. Every invocation
# first runs the read-only V8 readiness rehearsal. Only when the frozen
# contract, 100-stock universe + SPY, feature freshness/alignment, Gold
# freshness, and latest-session ranking all pass do we invoke the append-only
# paper/holdout runner. This makes the scheduler fail closed if upstream data
# is stale or incomplete. Before 2026-09-01, paper_runner still deliberately
# writes no forward-holdout journal evidence. No brokerage orders are placed.
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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.v8.readiness_check &amp;&amp; '$PYTHON' -u -m ml.v8.paper_runner; else echo '[SKIP] V8 paper runner already running'; fi</string>
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
echo "Startup check: enabled (RunAtLoad)"
echo "Schedule: every 5 minutes"
echo "Overlap guard: $LOCK_DIR"
echo "Preflight: python -m ml.v8.readiness_check"
echo "Runner: python -m ml.v8.paper_runner"
echo "Fail-closed policy: paper runner executes only when readiness is READY"
echo "Frozen V8 contract: verified on every invocation"
echo "Holdout safety: no journal evidence before 2026-09-01"
echo "Brokerage orders: disabled"
echo "Logs: $LOG_DIR/v8_paper.log"
