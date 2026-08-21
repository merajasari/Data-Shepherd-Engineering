#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
ARCHIVE_DIR="$LOG_DIR/archive"
LABEL="com.datashepherd.v5refresh"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v5_refresh.lockdir"
UID_VALUE="$(id -u)"

# Invoke frequently, but let Python's persistent rolling quota ledger decide
# how many Tiingo REST calls are safe right now. After each successful refresh
# invocation, regenerate the frozen V5 ranking snapshot, run the isolated V5
# forward evaluator, enter the guarded V8 EOD orchestrator, then run the V10
# prospective-confirmation cycle. A read-only convergence monitor always runs
# afterward and proves Bronze -> Silver -> Gold -> Features completion against
# the exact Tiingo target session. The final operations publisher always runs,
# even when an earlier stage fails, so the dashboard exposes the outcome.
INTERVAL_SECONDS=300
HOURLY_REQUEST_LIMIT=45

mkdir -p "$LAUNCH_DIR" "$LOG_DIR" "$ARCHIVE_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

# Archive stale stderr at install time so newly generated scheduler errors are
# easy to distinguish from historical failures. Never delete prior evidence.
if [[ -s "$LOG_DIR/v5_refresh.err.log" ]]; then
  STAMP="$(date '+%Y%m%d-%H%M%S')"
  mv "$LOG_DIR/v5_refresh.err.log" "$ARCHIVE_DIR/v5_refresh.err.$STAMP.log"
  echo "Archived previous scheduler stderr: $ARCHIVE_DIR/v5_refresh.err.$STAMP.log"
fi
: > "$LOG_DIR/v5_refresh.err.log"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR'; rc=0; { '$PYTHON' -u -m ml.run_v5_data_refresh --hourly-request-limit $HOURLY_REQUEST_LIMIT &amp;&amp; '$PYTHON' -u -m ml.run_v5_inference &amp;&amp; '$PYTHON' -u -m ml.run_paper_cycle_v5 &amp;&amp; '$PYTHON' -u -m ml.v8.eod_orchestrator &amp;&amp; '$PYTHON' -u -m ml.v10.confirmation_cycle; } || rc=\$?; conv_rc=0; '$PYTHON' -u -m ml.data_convergence || conv_rc=\$?; if [[ \$rc -eq 0 &amp;&amp; \$conv_rc -ne 0 ]]; then rc=\$conv_rc; fi; '$PYTHON' -u -m ml.operations_health --pipeline-exit-code \$rc || true; exit \$rc; else echo '[SKIP] V5 refresh already running'; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>$INTERVAL_SECONDS</integer>
<key>StandardOutPath</key><string>$LOG_DIR/v5_refresh.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v5_refresh.err.log</string>
</dict></plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
rm -rf "$LOCK_DIR"
launchctl bootstrap "gui/$UID_VALUE" "$PLIST"

echo "Installed $LABEL"
echo "Startup catch-up: enabled (RunAtLoad)"
echo "Schedule: every 5 minutes"
echo "Overlap guard: $LOCK_DIR"
echo "Rolling Tiingo scheduler limit: $HOURLY_REQUEST_LIMIT requests / 60 minutes"
echo "Catch-up policy: use all currently available rolling-hour capacity"
echo "V5 inference: regenerate rankings after each successful refresh invocation"
echo "V5 forward evaluator: automatic after inference"
echo "V8 production path: ml.v8.eod_orchestrator"
echo "V8 decision gate: ml.v8.eod_guard (fail closed)"
echo "V8 holdout runner: invoked only after the EOD decision gate opens"
echo "V8 guard output: $PROJECT_DIR/data/model/v8/eod_guard/status.json"
echo "V10 prospective confirmation: ml.v10.confirmation_cycle"
echo "V10 confirmation optimization: full reconstruction only when common feature session advances"
echo "V10 dashboard status: $PROJECT_DIR/webapp/static/generated/v10_confirmation_status.json"
echo "EOD convergence proof: ml.data_convergence"
echo "Convergence status: $PROJECT_DIR/webapp/static/generated/stock_data_convergence.json"
echo "Convergence transitions: $PROJECT_DIR/data/model/operations/data_convergence_events.jsonl"
echo "Operations health publisher: ml.operations_health"
echo "Operations dashboard status: $PROJECT_DIR/webapp/static/generated/stock_operations_health.json"
echo "Stderr archive: $ARCHIVE_DIR"
echo "Holdout safety: no brokerage orders; V8 and V10 formal holdouts remain separately gated"
echo "Logs: $LOG_DIR/v5_refresh.log"
