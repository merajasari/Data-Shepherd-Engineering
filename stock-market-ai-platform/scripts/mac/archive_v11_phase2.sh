#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
BACKUP_DIR="$LAUNCH_DIR/DataShepherdArchive"
UID_VALUE="$(id -u)"
LABELS=(
  "com.datashepherd.v11phase2"
  "com.datashepherd.v11phase2alerts"
)

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtualenv Python: $PYTHON" >&2
  exit 1
fi

cd "$PROJECT_DIR"
"$PYTHON" -m ml.v11.intraday_phase2_archive

mkdir -p "$BACKUP_DIR"
for label in "${LABELS[@]}"; do
  launchctl bootout "gui/$UID_VALUE/$label" 2>/dev/null || true
  plist="$LAUNCH_DIR/$label.plist"
  archived="$BACKUP_DIR/$label.plist.archived"
  if [[ -f "$plist" ]]; then
    if [[ -e "$archived" ]]; then
      echo "Archive target already exists: $archived" >&2
      exit 1
    fi
    mv "$plist" "$archived"
  fi
done

rmdir "$PROJECT_DIR/logs/v11_phase2.lockdir" 2>/dev/null || true

for label in "${LABELS[@]}"; do
  if launchctl print "gui/$UID_VALUE/$label" >/dev/null 2>&1; then
    echo "V11 scheduler remains registered: $label" >&2
    exit 1
  fi
done

"$PYTHON" -m ml.v11.intraday_phase2_archive --apply

echo "V11 Phase 2 is now an archived research reference."
echo "Schedulers disabled: ${LABELS[*]}"
echo "LaunchAgent backups: $BACKUP_DIR"
echo "V11 code, contracts, diagnostics, status, and evidence preserved."
echo "V13 locked V11 dependencies preserved in place."
echo "Maximum ongoing V11 Tiingo requests: 0"
echo "Live trading: DISABLED"
echo "Brokerage orders: OFF"
