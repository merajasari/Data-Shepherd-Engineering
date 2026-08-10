#!/data/data/com.termux/files/usr/bin/bash

set -u

LOG="logs/gunicorn-access.log"

if [ ! -f "$LOG" ]; then
    echo "Visitor log not found: $LOG"
    exit 1
fi

echo
echo "Data Shepherd Visitor Report"
echo "============================"
echo

printf "%-40s %-8s %-22s %-22s %-22s %-24s %s\n" \
  "IP" \
  "REQ" \
  "FIRST SEEN" \
  "LAST SEEN" \
  "SOURCE" \
  "DEVICE(S)" \
  "CLASSIFICATION"

printf "%-40s %-8s %-22s %-22s %-22s %-24s %s\n" \
  "----------------------------------------" \
  "--------" \
  "----------------------" \
  "----------------------" \
  "----------------------" \
  "------------------------" \
  "------------------------"

awk '
{
    ip=$1

    if (
        ip != "127.0.0.1" &&
        ip != "::1" &&
        ip != "203.0.113.99" &&
        ip != "-" &&
        (ip ~ /\./ || ip ~ /:/)
    ) {
        print ip
    }
}
' "$LOG" |
sort |
uniq -c |
sort -nr |
while read -r count ip
do
    lines=$(awk -v ip="$ip" '$1 == ip {print}' "$LOG")

    first_seen=$(printf '%s\n' "$lines" | head -1 | sed -n 's/.*\[\([^]]*\)\].*/\1/p')
    last_seen=$(printf '%s\n' "$lines" | tail -1 | sed -n 's/.*\[\([^]]*\)\].*/\1/p')

    devices=""

    printf '%s\n' "$lines" | grep -qi "iPhone" && devices="${devices}iPhone, "
    printf '%s\n' "$lines" | grep -qi "Android" && devices="${devices}Android, "
    printf '%s\n' "$lines" | grep -qi "Macintosh" && devices="${devices}Mac, "
    printf '%s\n' "$lines" | grep -qi "Windows" && devices="${devices}Windows, "
    printf '%s\n' "$lines" | grep -qi "CrOS" && devices="${devices}ChromeOS, "
    printf '%s\n' "$lines" | grep -qi "Ubuntu" && devices="${devices}Ubuntu, "
    printf '%s\n' "$lines" | grep -qi "Linux" && devices="${devices}Linux, "
    printf '%s\n' "$lines" | grep -qi "curl/" && devices="${devices}curl, "

    devices=$(printf '%s' "$devices" | sed 's/, $//')
    [ -z "$devices" ] && devices="Unknown"

    source="DIRECT / UNKNOWN"

    if printf '%s\n' "$lines" | grep -Eqi 'linkedin\.com|linkedinapp|android-app://com\.linkedin'; then
        source="LINKEDIN"
    elif printf '%s\n' "$lines" | grep -Eqi 'facebookexternalhit|facebot|twitterbot'; then
        source="SOCIAL PREVIEW"
    elif printf '%s\n' "$lines" | grep -Eqi 'googlebot|bingbot|claude-searchbot|crawler|spider'; then
        source="SEARCH / CRAWLER"
    elif printf '%s\n' "$lines" | grep -q '/dashboard'; then
        source="DASHBOARD"
    fi

    classification="HUMAN-LIKE"

    if printf '%s\n' "$lines" | grep -Eqi 'facebookexternalhit|facebot|twitterbot'; then
        classification="SOCIAL PREVIEW BOT"
    elif printf '%s\n' "$lines" | grep -Eqi 'claude-searchbot|googlebot|bingbot|bot|crawler|spider|scanner|wget|python|okhttp'; then
        classification="LIKELY BOT"
    elif printf '%s\n' "$lines" | grep -qi 'curl/'; then
        classification="SCRIPT / TEST"
    elif printf '%s\n' "$lines" | grep -Eqi 'linkedin\.com|linkedinapp|android-app://com\.linkedin'; then
        classification="LINKEDIN VISITOR"
    elif printf '%s\n' "$lines" | grep -q '/api/'; then
        classification="ACTIVE DASHBOARD"
    fi

    printf "%-40s %-8s %-22s %-22s %-22s %-24s %s\n" \
      "$ip" \
      "$count" \
      "$first_seen" \
      "$last_seen" \
      "$source" \
      "$devices" \
      "$classification"
done

echo
echo "Summary"
echo "-------"

unique_ips=$(awk '
{
    ip=$1
    if (
        ip != "127.0.0.1" &&
        ip != "::1" &&
        ip != "203.0.113.99" &&
        ip != "-" &&
        (ip ~ /\./ || ip ~ /:/)
    ) {
        print ip
    }
}
' "$LOG" | sort -u | wc -l | tr -d ' ')

linkedin_hits=$(grep -Eic 'linkedin\.com|linkedinapp|android-app://com\.linkedin' "$LOG" || true)
bot_hits=$(grep -Eic 'facebookexternalhit|facebot|twitterbot|claude-searchbot|googlebot|bingbot|crawler|spider|scanner' "$LOG" || true)
dashboard_hits=$(grep -Ec '"GET /dashboard|"GET /api/' "$LOG" || true)

echo "Unique observed client IPs: $unique_ips"
echo "LinkedIn-related requests:   $linkedin_hits"
echo "Bot/crawler requests:        $bot_hits"
echo "Dashboard/API requests:      $dashboard_hits"

echo
echo "Notes"
echo "-----"
echo "- One person can appear under multiple IP addresses."
echo "- Multiple people can share one IP address."
echo "- IPv4 and IPv6 are both included."
echo "- 203.0.113.99 is excluded because it was the synthetic test address."
