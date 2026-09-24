#!/bin/zsh
set -euo pipefail

PROJECT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
SCRIPT="$PROJECT/scripts/mac/refresh_crypto_daily_bronze.sh"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.cryptodailybronze.plist"
LABEL="com.datashepherd.cryptodailybronze"
DOMAIN="gui/$(id -u)"
LOGDIR="$PROJECT/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

if [[ ! -x "$SCRIPT" ]]; then
    echo "Missing executable refresh script: $SCRIPT" >&2
    exit 1
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>$SCRIPT</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT</string>

    <!--
      Run once daily at 17:05 local time.
      This local schedule runs after UTC midnight in Pacific time.
      UTC execution time shifts with daylight-saving time.
    -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>17</integer>
        <key>Minute</key>
        <integer>5</integer>
    </dict>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>$LOGDIR/crypto_daily_bronze.out.log</string>

    <key>StandardErrorPath</key>
    <string>$LOGDIR/crypto_daily_bronze.err.log</string>

</dict>
</plist>
EOF

plutil -lint "$PLIST"
chmod 600 "$PLIST"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true

launchctl enable "$DOMAIN/$LABEL"

if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "bootstrap failed; trying legacy loader" >&2
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load -w "$PLIST"
fi

echo
echo "Installed: $LABEL"
echo "Schedule: daily at 17:05 local time"
echo "Refresh script: $SCRIPT"
echo "stdout: $LOGDIR/crypto_daily_bronze.out.log"
echo "stderr: $LOGDIR/crypto_daily_bronze.err.log"
