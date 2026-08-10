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
  "IP" "REQ" "FIRST SEEN" "LAST SEEN" "SOURCE" "DEVICE(S)" "CLASSIFICATION"
printf "%-40s %-8s %-26s %-26s %-20s %-24s %s\n" \
  "----------------------------------------" "--------" "--------------------------" "--------------------------" "--------------------" "------------------------" "------------------------"

extract_ips() {
    cut -d' ' -f1 "$LOG" | grep -E '[.:]' | grep -Ev '^(127\.0\.0\.1|::1|203\.0\.113\.99|-)$'
}

extract_timestamp() {
    sed -n 's/^[^[]*\[\([^]]*\)\].*/\1/p'
}

classify_ip() {
    ip="$1"
    count="$2"
    lines=$(grep -F "${ip} " "$LOG" || true)

    has_social_preview=0; has_known_bot=0; has_script=0; has_linkedin=0
    has_dashboard=0; has_api=0; has_home=0

    printf '%s\n' "$lines" | grep -Eqi 'facebookexternalhit|facebot|twitterbot' && has_social_preview=1
    printf '%s\n' "$lines" | grep -Eqi 'claude-searchbot|googlebot|bingbot|bot|crawler|spider|scanner|wget|python|okhttp|headless|selenium|playwright|phantomjs' && has_known_bot=1
    printf '%s\n' "$lines" | grep -Eqi 'curl/|wget/' && has_script=1
    printf '%s\n' "$lines" | grep -Eqi 'linkedin\.com|linkedinapp|android-app://com\.linkedin' && has_linkedin=1
    printf '%s\n' "$lines" | grep -q '"GET /dashboard' && has_dashboard=1
    printf '%s\n' "$lines" | grep -q '"GET /api/' && has_api=1
    printf '%s\n' "$lines" | grep -Eq '"GET / HTTP/' && has_home=1

    if [ "$has_social_preview" -eq 1 ]; then echo "SOCIAL PREVIEW BOT"
    elif [ "$has_known_bot" -eq 1 ]; then echo "KNOWN BOT"
    elif [ "$has_script" -eq 1 ]; then echo "SCRIPT / TEST"
    elif [ "$has_linkedin" -eq 1 ] && { [ "$has_dashboard" -eq 1 ] || [ "$has_api" -eq 1 ]; }; then echo "LINKEDIN / ENGAGED"
    elif [ "$has_linkedin" -eq 1 ]; then echo "LINKEDIN VISITOR"
    elif [ "$has_api" -eq 1 ]; then echo "ACTIVE DASHBOARD"
    elif [ "$count" -ge 3 ] && [ "$has_home" -eq 1 ]; then echo "ENGAGED BROWSER"
    else echo "UNVERIFIED / ONE-OFF"
    fi
}

extract_ips | sort | uniq -c | sort -nr |
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

    source="DIRECT / UNKNOWN"
    printf '%s\n' "$lines" | grep -Eqi 'facebookexternalhit|facebot|twitterbot' && source="SOCIAL PREVIEW"
    if [ "$source" = "DIRECT / UNKNOWN" ]; then printf '%s\n' "$lines" | grep -Eqi 'claude-searchbot|googlebot|bingbot|bot|crawler|spider|scanner|headless|selenium|playwright|phantomjs' && source="SEARCH / CRAWLER"; fi
    if [ "$source" = "DIRECT / UNKNOWN" ]; then printf '%s\n' "$lines" | grep -Eqi 'linkedin\.com|linkedinapp|android-app://com\.linkedin' && source="LINKEDIN"; fi
    if [ "$source" = "DIRECT / UNKNOWN" ]; then printf '%s\n' "$lines" | grep -Eq '"GET /dashboard|"GET /api/' && source="DASHBOARD"; fi

    classification=$(classify_ip "$ip" "$count")
    printf "%-40s %-8s %-26s %-26s %-20s %-24s %s\n" "$ip" "$count" "$first_seen" "$last_seen" "$source" "$devices" "$classification"
done

echo
echo "Summary"
echo "-------"

unique_ips=$(extract_ips | sort -u | wc -l | tr -d ' ')
linkedin_hits=$(grep -Eic 'linkedin\.com|linkedinapp|android-app://com\.linkedin' "$LOG" || true)
bot_hits=$(grep -Eic 'facebookexternalhit|facebot|twitterbot|claude-searchbot|googlebot|bingbot|crawler|spider|scanner|headless|selenium|playwright|phantomjs' "$LOG" || true)
dashboard_hits=$(grep -Ec '"GET /dashboard|"GET /api/' "$LOG" || true)

linkedin_engaged=0; linkedin_visitors=0; active_dashboard=0; engaged_browsers=0
known_bots=0; social_preview_bots=0; scripts=0; unverified=0

while read -r count ip
do
    classification=$(classify_ip "$ip" "$count")
    case "$classification" in
        "LINKEDIN / ENGAGED") linkedin_engaged=$((linkedin_engaged + 1)) ;;
        "LINKEDIN VISITOR") linkedin_visitors=$((linkedin_visitors + 1)) ;;
        "ACTIVE DASHBOARD") active_dashboard=$((active_dashboard + 1)) ;;
        "ENGAGED BROWSER") engaged_browsers=$((engaged_browsers + 1)) ;;
        "KNOWN BOT") known_bots=$((known_bots + 1)) ;;
        "SOCIAL PREVIEW BOT") social_preview_bots=$((social_preview_bots + 1)) ;;
        "SCRIPT / TEST") scripts=$((scripts + 1)) ;;
        *) unverified=$((unverified + 1)) ;;
    esac
done <<EOF
$(extract_ips | sort | uniq -c | sort -nr)
EOF

meaningful=$((linkedin_engaged + linkedin_visitors + active_dashboard + engaged_browsers))
automated=$((known_bots + social_preview_bots + scripts))

echo "Unique observed client IPs: $unique_ips"
echo "LinkedIn-related requests:   $linkedin_hits"
echo "Bot/crawler requests:        $bot_hits"
echo "Dashboard/API requests:      $dashboard_hits"
echo
echo "Session Classification"
echo "----------------------"
printf "%-28s %s\n" "LinkedIn engaged sessions:" "$linkedin_engaged"
printf "%-28s %s\n" "LinkedIn visitor sessions:" "$linkedin_visitors"
printf "%-28s %s\n" "Active dashboard sessions:" "$active_dashboard"
printf "%-28s %s\n" "Engaged browser sessions:" "$engaged_browsers"
printf "%-28s %s\n" "Known bot sessions:" "$known_bots"
printf "%-28s %s\n" "Social preview bot sessions:" "$social_preview_bots"
printf "%-28s %s\n" "Script/test sessions:" "$scripts"
printf "%-28s %s\n" "Unverified / one-off:" "$unverified"
printf "%-28s %s\n" "Meaningful-session signals:" "$meaningful"
printf "%-28s %s\n" "Automated-session signals:" "$automated"

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
echo "- Session counts above are IP-based signals, not guaranteed unique people."
echo "- One person can appear under multiple IP addresses; multiple people can share one IP."
echo "- User-agent strings can be spoofed, so classifications are heuristic."
echo "- IPv4 and IPv6 are both included."
echo "- 203.0.113.99 is excluded because it was the synthetic test address."
