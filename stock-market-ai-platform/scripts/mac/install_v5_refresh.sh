#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
LABEL="com.datashepherd.v5refresh"
PLIST="$LAUNCH_DIR/$LABEL.plist"
LOCK_DIR="$LOG_DIR/v5_refresh.lockdir"
UID_VALUE="$(id -u)"

# Invoke frequently, but let Python's persistent rolling quota ledger decide
# how many Tiingo REST calls are safe right now. After each successful refresh
# invocation, regenerate the frozen V5 ranking snapshot, run the isolated V5
# forward evaluator, enter the guarded V8 EOD orchestrator, then run the V10
# prospective-confirmation cycle. V10's cycle is cheap when the common feature
# session has not advanced and never reads its formal 2026-11-02+ holdout.
INTERVAL_SECONDS=300
HOURLY_REQUEST_LIMIT=45

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
<string>if mkdir '$LOCK_DIR' 2&gt;/dev/null; then trap 'rmdir &quot;$LOCK_DIR&quot; 2&gt;/dev/null || true' EXIT INT TERM; cd '$PROJECT_DIR' &amp;&amp; '$PYTHON' -u -m ml.run_v5_data_refresh --hourly-request-limit $HOURLY_REQUEST_LIMIT &amp;&amp; '$PYTHON' -u -m ml.run_v5_inference &amp;&amp; '$PYTHON' -u -m ml.run_paper_cycle_v5 &amp;&amp; '$PYTHON' -u -m ml.v8.eod_orchestrator &amp;&amp; '$PYTHON' -u -m ml.v10.confirmation_cycle; else echo '[SKIP] V5 refresh already running'; fi</string>
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
echo "Holdout safety: no brokerage orders; V8 and V10 formal holdouts remain separately gated"
echo "Logs: $LOG_DIR/v5_refresh.log"
