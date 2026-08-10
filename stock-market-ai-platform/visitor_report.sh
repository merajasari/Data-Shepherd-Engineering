#!/data/data/com.termux/files/usr/bin/bash

LOG="logs/gunicorn-access.log"

echo
echo "Visitor Report"
echo "=============="
echo

printf "%-18s %-10s %-24s %-28s %s\n" \
  "IP" \
  "REQUESTS" \
  "LAST SEEN" \
  "DEVICE(S)" \
  "CLASSIFICATION"

printf "%-18s %-10s %-24s %-28s %s\n" \
  "------------------" \
  "----------" \
  "------------------------" \
  "----------------------------" \
  "----------------------"

awk '$1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $1 != "127.0.0.1" && $1 != "203.0.113.99" {print $1}' "$LOG" |
sort |
uniq -c |
sort -nr |
while read count ip
do
    last_seen=$(grep "^$ip " "$LOG" | tail -1 | sed -n 's/.*\[\([^]]*\)\].*/\1/p')

    agents=$(grep "^$ip " "$LOG")

    devices=""

    echo "$agents" | grep -qi "iPhone" && devices="${devices}iPhone, "
    echo "$agents" | grep -qi "Android" && devices="${devices}Android, "
    echo "$agents" | grep -qi "Macintosh" && devices="${devices}Mac, "
    echo "$agents" | grep -qi "Windows" && devices="${devices}Windows, "
    echo "$agents" | grep -qi "Linux" && devices="${devices}Linux, "
    echo "$agents" | grep -qi "curl/" && devices="${devices}curl, "

    devices=$(echo "$devices" | sed 's/, $//')

    [ -z "$devices" ] && devices="Unknown"

    classification="HUMAN-LIKE"

    echo "$agents" | grep -Eqi 'bot|crawler|spider|scanner|wget|python|okhttp' &&
        classification="LIKELY BOT"

    echo "$agents" | grep -qi 'curl/' &&
        classification="SCRIPT / TEST"

    printf "%-18s %-10s %-24s %-28s %s\n" \
      "$ip" \
      "$count" \
      "$last_seen" \
      "$devices" \
      "$classification"
done
