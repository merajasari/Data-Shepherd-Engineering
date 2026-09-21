#!/bin/zsh
set -u

MODE="audit"
if [[ "${1:-}" == "--apply" ]]; then
  MODE="apply"
elif [[ -n "${1:-}" && "${1:-}" != "--audit" ]]; then
  echo "Usage: zsh scripts/mac/audit_model_services.sh [--audit|--apply]" >&2
  exit 2
fi

USER_ID="$(id -u)"
DOMAIN="gui/$USER_ID"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_DIR="$LAUNCH_DIR/DataShepherd-Archived/$STAMP"

# These jobs directly operate the selected model lanes or provide shared web,
# market-data, reconciliation, and awake-host infrastructure required by them.
KEEP_LABELS=(
  com.datashepherd.web
  com.datashepherd.keepawake
  com.datashepherd.iexstream
  com.datashepherd.v8refresh
  com.datashepherd.v8paper
  com.datashepherd.v8evidencealerts
  com.datashepherd.v10cycle3
  com.datashepherd.v10cycle3acceleratedv2
  com.datashepherd.v14logisticforward
  com.datashepherd.v15prospectivev7
  com.datashepherd.cryptort
  com.datashepherd.cryptoreconcile
  # Historical label; the current installer targets Shared Crypto V2 Clean
  # Forward V3 and must remain active despite the v2 label.
  com.datashepherd.cryptov2forward
  com.datashepherd.cryptov5forward
)

# Explicitly superseded or archived lanes. --apply unloads only these labels.
ARCHIVE_LABELS=(
  com.datashepherd.v5refresh
  com.datashepherd.v10cycle3accelerated
  com.datashepherd.v11phase2
  com.datashepherd.v11phase2alerts
  com.datashepherd.v13sessionpreflight
  com.datashepherd.v13sessioncollect
  com.datashepherd.v13quoterecoverypreflight
  com.datashepherd.v13quoterecoverycollect
  com.datashepherd.papershadow
)

contains_label() {
  local wanted="$1"
  shift
  local candidate
  for candidate in "$@"; do
    [[ "$candidate" == "$wanted" ]] && return 0
  done
  return 1
}

is_loaded() {
  launchctl print "$DOMAIN/$1" >/dev/null 2>&1
}

plist_for() {
  echo "$LAUNCH_DIR/$1.plist"
}

echo "DATA SHEPHERD MAC SERVICE AUDIT"
echo "Mode: $MODE"
echo "Domain: $DOMAIN"
echo

echo "APPROVED SERVICES"
for label in "${KEEP_LABELS[@]}"; do
  plist="$(plist_for "$label")"
  loaded="NO"
  installed="NO"
  is_loaded "$label" && loaded="YES"
  [[ -f "$plist" ]] && installed="YES"
  printf 'KEEP    %-48s loaded=%-3s plist=%s\n' "$label" "$loaded" "$installed"
done
echo

echo "SUPERSEDED SERVICES"
archive_count=0
for label in "${ARCHIVE_LABELS[@]}"; do
  plist="$(plist_for "$label")"
  loaded="NO"
  installed="NO"
  is_loaded "$label" && loaded="YES"
  [[ -f "$plist" ]] && installed="YES"
  printf 'ARCHIVE %-48s loaded=%-3s plist=%s\n' "$label" "$loaded" "$installed"

  if [[ "$MODE" == "apply" && ( "$loaded" == "YES" || "$installed" == "YES" ) ]]; then
    mkdir -p "$ARCHIVE_DIR"
    launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
    launchctl disable "$DOMAIN/$label" >/dev/null 2>&1 || true
    if [[ -f "$plist" ]]; then
      mv "$plist" "$ARCHIVE_DIR/"
    fi
    archive_count=$((archive_count + 1))
  fi
done
echo

echo "UNCLASSIFIED DATA SHEPHERD SERVICES"
unknown_count=0
loaded_labels=("${(@f)$(launchctl list 2>/dev/null | awk '$3 ~ /^com[.]datashepherd[.]/ {print $3}' | sort -u)}")
plist_labels=("${(@f)$(find "$LAUNCH_DIR" -maxdepth 1 -type f -name 'com.datashepherd.*.plist' -exec basename {} .plist \; 2>/dev/null | sort -u)}")
all_labels=("${loaded_labels[@]}" "${plist_labels[@]}")
for label in "${(@u)all_labels}"; do
  [[ -z "$label" ]] && continue
  if ! contains_label "$label" "${KEEP_LABELS[@]}" && ! contains_label "$label" "${ARCHIVE_LABELS[@]}"; then
    printf 'REVIEW  %s\n' "$label"
    unknown_count=$((unknown_count + 1))
  fi
done
[[ "$unknown_count" -eq 0 ]] && echo "None"
echo

echo "PROJECT PROCESSES"
process_rows="$(ps -axo pid=,command= | grep -E 'Data-Shepherd-Engineering|com[.]datashepherd|ml[.]' | grep -v -E 'grep -E|audit_model_services' || true)"
if [[ -n "$process_rows" ]]; then
  echo "$process_rows"
else
  echo "No matching processes found."
fi
echo

echo "CRONTAB REFERENCES"
cron_rows="$(crontab -l 2>/dev/null | grep -E 'Data-Shepherd-Engineering|datashepherd|stock-market-ai-platform' || true)"
if [[ -n "$cron_rows" ]]; then
  echo "$cron_rows"
  echo "REVIEW: cron entries are reported but never changed automatically."
else
  echo "None"
fi
echo

if [[ "$MODE" == "apply" ]]; then
  echo "Archived service count: $archive_count"
  if [[ "$archive_count" -gt 0 ]]; then
    echo "Recoverable plist backup: $ARCHIVE_DIR"
  else
    echo "No superseded service was loaded or installed."
  fi
  echo "Model data, evidence journals, logs, and source files were not changed."
else
  echo "AUDIT ONLY: nothing was changed."
  echo "Review this output, then run with --apply to unload and archive only the explicit superseded list."
fi
