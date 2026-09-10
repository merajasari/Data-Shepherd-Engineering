#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
UID_VALUE="$(id -u)"
PREFLIGHT_LABEL="com.datashepherd.v13sessionpreflight"
COLLECT_LABEL="com.datashepherd.v13sessioncollect"
PREFLIGHT_PLIST="$LAUNCH_DIR/$PREFLIGHT_LABEL.plist"
COLLECT_PLIST="$LAUNCH_DIR/$COLLECT_LABEL.plist"

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON" -m ml.v13.regime_overlay_session_automation --mode status

cat > "$PREFLIGHT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$PREFLIGHT_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; exec '$PYTHON' -u -m ml.v13.regime_overlay_session_automation --mode preflight</string>
</array>
<key>StartCalendarInterval</key><dict><key>Month</key><integer>9</integer><key>Day</key><integer>8</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>55</integer></dict>
<key>StandardOutPath</key><string>$LOG_DIR/v13_session_preflight.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v13_session_preflight.err.log</string>
<key>ProcessType</key><string>Background</string>
</dict></plist>
EOF

cat > "$COLLECT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$COLLECT_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; exec '$PYTHON' -u -m ml.v13.regime_overlay_session_automation --mode collect</string>
</array>
<key>StartCalendarInterval</key><dict><key>Month</key><integer>9</integer><key>Day</key><integer>8</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
<key>StandardOutPath</key><string>$LOG_DIR/v13_session_collect.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v13_session_collect.err.log</string>
<key>ProcessType</key><string>Background</string>
</dict></plist>
EOF

plutil -lint "$PREFLIGHT_PLIST"
plutil -lint "$COLLECT_PLIST"

launchctl bootout "gui/$UID_VALUE/$PREFLIGHT_LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE/$COLLECT_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PREFLIGHT_PLIST"
launchctl bootstrap "gui/$UID_VALUE" "$COLLECT_PLIST"

echo "Installed $PREFLIGHT_LABEL for 6:55 AM local time"
echo "Installed $COLLECT_LABEL for 7:00 AM local time"
echo "Target session: 2026-09-08 only"
echo "Maximum collection attempts: 1"
echo "No backfill: enforced"
echo "Paper trading only: YES"
echo "Live trading: DISABLED"
echo "Brokerage orders: OFF"
echo "Keep the Mac awake, powered, online, and logged in through 7:05 AM."
