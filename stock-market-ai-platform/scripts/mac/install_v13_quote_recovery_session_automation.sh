#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/mac/install_v13_quote_recovery_session_automation.sh \
    --target-session YYYY-MM-DD \
    --source-session YYYY-MM-DD

Installs two fail-closed LaunchAgents for one already-authorized V13 paper-only
session: a 6:55 AM Pacific preflight and a 7:00 AM Pacific collection attempt.
This installer does not create authorization, publish context, renew a lease,
request market data, append evidence, or grant brokerage authority.
EOF
}

TARGET_SESSION=""
SOURCE_SESSION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-session)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      TARGET_SESSION="$2"
      shift 2
      ;;
    --source-session)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      SOURCE_SESSION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$TARGET_SESSION" || -z "$SOURCE_SESSION" ]]; then
  usage >&2
  exit 2
fi

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
UID_VALUE="$(id -u)"
PREFLIGHT_LABEL="com.datashepherd.v13quoterecoverypreflight"
COLLECT_LABEL="com.datashepherd.v13quoterecoverycollect"
PREFLIGHT_PLIST="$LAUNCH_DIR/$PREFLIGHT_LABEL.plist"
COLLECT_PLIST="$LAUNCH_DIR/$COLLECT_LABEL.plist"
MODULE="ml.v13.regime_overlay_quote_recovery_session_automation"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

case "$(date +%Z)" in
  PST|PDT) ;;
  *)
    echo "The Mac system timezone must be Pacific (PST/PDT) before installation." >&2
    exit 1
    ;;
esac

cd "$PROJECT_DIR"

"$PYTHON" - "$TARGET_SESSION" "$SOURCE_SESSION" <<'PY'
import sys

from ml.v13.regime_overlay_quote_recovery_session_automation import (
    _session_dates,
    get_session_status,
)

target_session, source_session = sys.argv[1:3]
_session_dates(target_session, source_session)
state = get_session_status(
    target_session=target_session,
    source_session=source_session,
)
allowed = {
    "AUTHORIZED",
    "READY_FOR_AUTOMATIC_QUOTE_RECOVERY_COLLECTION",
}
if state.get("status") not in allowed:
    raise SystemExit(
        "V13 quote-recovery automation must be explicitly authorized "
        "before scheduler installation; observed status="
        + str(state.get("status"))
    )
print("Authorization status:", state["status"])
print("Target session:", target_session)
print("Source session:", source_session)
PY

IFS='-' read -r TARGET_YEAR TARGET_MONTH_RAW TARGET_DAY_RAW <<< "$TARGET_SESSION"
TARGET_MONTH=$((10#$TARGET_MONTH_RAW))
TARGET_DAY=$((10#$TARGET_DAY_RAW))

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

cat > "$PREFLIGHT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$PREFLIGHT_LABEL</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; exec '$PYTHON' -u -m $MODULE --mode preflight --target-session '$TARGET_SESSION' --source-session '$SOURCE_SESSION'</string>
</array>
<key>StartCalendarInterval</key><dict><key>Month</key><integer>$TARGET_MONTH</integer><key>Day</key><integer>$TARGET_DAY</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>55</integer></dict>
<key>StandardOutPath</key><string>$LOG_DIR/v13_quote_recovery_preflight.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v13_quote_recovery_preflight.err.log</string>
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
<string>cd '$PROJECT_DIR' &amp;&amp; set -a &amp;&amp; source .env &amp;&amp; set +a &amp;&amp; export FEATURE_BACKEND=spark &amp;&amp; exec '$PYTHON' -u -m $MODULE --mode collect --target-session '$TARGET_SESSION' --source-session '$SOURCE_SESSION' --apply</string>
</array>
<key>StartCalendarInterval</key><dict><key>Month</key><integer>$TARGET_MONTH</integer><key>Day</key><integer>$TARGET_DAY</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
<key>StandardOutPath</key><string>$LOG_DIR/v13_quote_recovery_collect.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/v13_quote_recovery_collect.err.log</string>
<key>ProcessType</key><string>Background</string>
</dict></plist>
EOF

plutil -lint "$PREFLIGHT_PLIST"
plutil -lint "$COLLECT_PLIST"

launchctl bootout "gui/$UID_VALUE/$PREFLIGHT_LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE/$COLLECT_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$PREFLIGHT_PLIST"
launchctl bootstrap "gui/$UID_VALUE" "$COLLECT_PLIST"

echo "Installed $PREFLIGHT_LABEL for 6:55 AM Pacific on $TARGET_SESSION"
echo "Installed $COLLECT_LABEL for 7:00 AM Pacific on $TARGET_SESSION"
echo "Source session: $SOURCE_SESSION"
echo "Maximum collection attempts: 1"
echo "Maximum market-data requests: 104"
echo "Quote recovery: one full 101-symbol batch after 5 seconds"
echo "No retry after the attempt: enforced"
echo "No backfill: enforced"
echo "Paper trading only: YES"
echo "Live trading: DISABLED"
echo "Brokerage orders: OFF"
echo "Keep the Mac awake, powered, online, and logged in through 7:05 AM Pacific."
