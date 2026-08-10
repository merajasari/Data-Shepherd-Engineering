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

printf "%-40s %-8s %-26s %-26s %-20s %-24s %s\n" \
  "IP" \
  "REQ" \
  "FIRST SEEN" \
  "LAST SEEN" \
  "SOURCE" \
  "DEVICE(S)" \
  "CLASSIFICATION"

printf "%-40s %-8s %-26s %-26s %-20s %-24s %s\n" \
  "----------------------------------------" \
  "--------" \
  "--------------------------" \
  "--------------------------" \
  "--------------------" \
  "------------------------" \
  "------------------------"

extract_ips() {
    cut -d' ' -f1 "$LOG" |
    grep -E '[.:]' |
    grep -Ev '^(127\.0\.0\.1|::1|203\.0\.113\.99|-)$'
}

extract_timestamp() {
    sed -n 's/^[^[]*\[\([^]]*\)\].*/\1/p'
}

extract_ips |
sort |
uniq -c |
sort -nr |
while read -r count ip
do
    lines=$(grep -F "${ip} " "$LOG" || true)

    first_seen=$(printf '%s\n' "$lines" | head -1 | extract_timestamp)
    last_seen=$(printf '%s\n' "$lines" | tail -1 | extract_timestamp)

    [ -z "$first_seen" ] && first_seen="Unknown"
    [ -z "$last_seen" ] && last_seen="Unknown"

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

    has_social_preview=0
    has_known_bot=0
    has_script=0
    has_linkedin=0
    has_dashboard=0
    has_api=0
    has_home=0

    printf '%s\n' "$lines" | grep -Eqi 'facebookexternalhit|facebot|twitterbot' && has_social_preview=1
    printf '%s\n' "$lines" | grep -Eqi 'claude-searchbot|googlebot|bingbot|bot|crawler|spider|scanner|wget|python|okhttp|headless|selenium|playwright|phantomjs' && has_known_bot=1
    printf '%s\n' "$lines" | grep -Eqi 'curl/|wget/' && has_script=1
    printf '%s\n' "$lines" | grep -Eqi 'linkedin\.com|linkedinapp|android-app://com\.linkedin' && has_linkedin=1
    printf '%s\n' "$lines" | grep -q '"GET /dashboard' && has_dashboard=1
    printf '%s\n' "$lines" | grep -q '"GET /api/' && has_api=1
    printf '%s\n' "$lines" | grep -Eq '"GET / HTTP/' && has_home=1

    source="DIRECT / UNKNOWN"

    if [ "$has_social_preview" -eq 1 ]; then
        source="SOCIAL PREVIEW"
    elif [ "$has_known_bot" -eq 1 ]; then
        source="SEARCH / CRAWLER"
    elif [ "$has_linkedin" -eq 1 ]; then
        source="LINKEDIN"
    elif [ "$has_dashboard" -eq 1 ] || [ "$has_api" -eq 1 ]; then
        source="DASHBOARD"
    fi

    classification="UNVERIFIED / ONE-OFF"

    if [ "$has_social_preview" -eq 1 ]; then
        classification="SOCIAL PREVIEW BOT"
    elif [ "$has_known_bot" -eq 1 ]; then
        classification="KNOWN BOT"
    elif [ "$has_script" -eq 1 ]; then
        classification="SCRIPT / TEST"
    elif [ "$has_linkedin" -eq 1 ] && { [ "$has_dashboard" -eq 1 ] || [ "$has_api" -eq 1 ]; }; then
        classification="LINKEDIN / ENGAGED"
    elif [ "$has_linkedin" -eq 1 ]; then
        classification="LINKEDIN VISITOR"
    elif [ "$has_api" -eq 1 ]; then
        classification="ACTIVE DASHBOARD"
    elif [ "$count" -ge 3 ] && [ "$has_home" -eq 1 ]; then
        classification="ENGAGED BROWSER"
    fi

    printf "%-40s %-8s %-26s %-26s %-20s %-24s %s\n" \
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

unique_ips=$(extract_ips | sort -u | wc -l | tr -d ' ')
linkedin_hits=$(grep -Eic 'linkedin\.com|linkedinapp|android-app://com\.linkedin' "$LOG" || true)
bot_hits=$(grep -Eic 'facebookexternalhit|facebot|twitterbot|claude-searchbot|googlebot|bingbot|crawler|spider|scanner|headless|selenium|playwright|phantomjs' "$LOG" || true)
dashboard_hits=$(grep -Ec '"GET /dashboard|"GET /api/' "$LOG" || true)

echo "Unique observed client IPs: $unique_ips"
echo "LinkedIn-related requests:   $linkedin_hits"
echo "Bot/crawler requests:        $bot_hits"
echo "Dashboard/API requests:      $dashboard_hits"

echo
echo "Classification guide"
echo "--------------------"
echo "LINKEDIN / ENGAGED   LinkedIn-origin traffic that also used dashboard/API routes."
echo "LINKEDIN VISITOR     LinkedIn-origin browser traffic without dashboard activity."
echo "ACTIVE DASHBOARD     Browser traffic actively polling protected dashboard APIs."
echo "ENGAGED BROWSER      Repeated normal-looking browsing; not proof of a unique person."
echo "UNVERIFIED / ONE-OFF Too little evidence to call the request human or automated."
echo "KNOWN BOT            Explicit crawler/bot/automation user-agent evidence."
echo "SOCIAL PREVIEW BOT   Social-network link preview fetches."
echo "SCRIPT / TEST        curl/wget-style scripted requests."

echo
echo "Notes"
echo "-----"
echo "- One person can appear under multiple IP addresses."
echo "- Multiple people can share one IP address."
echo "- User-agent strings can be spoofed, so classifications are heuristic."
echo "- IPv4 and IPv6 are both included."
echo "- 203.0.113.99 is excluded because it was the synthetic test address."
