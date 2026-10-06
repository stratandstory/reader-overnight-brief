#!/bin/bash
# Optional: run Reader automatically on this Mac.
#   ./schedule.sh on        collect news every 30 minutes; write the brief at 6:30 AM on weekdays
#   ./schedule.sh collect   collect news every 30 minutes and package each weekday morning at 6:30;
#                           you run ./brief run yourself (or ./brief run --package <date> for a morning you missed)
#   ./schedule.sh off       remove every job
#   ./schedule.sh status    which jobs are installed, and the last line of each log
# The Mac has to be awake for a job to run. If it is asleep at 6:30, the 6:30 job runs when it wakes; the
# package still covers news to 6:30. In "on" mode the brief writes the morning package itself.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

write_plist() {  # label, schedule xml, arguments...
  local label="$1" schedule="$2"; shift 2
  local args=""
  for a in "$@"; do args="$args<string>$a</string>"; done
  cat > "$AGENTS/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args</array>
  $schedule
  <key>StandardOutPath</key><string>$DIR/data/$label.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/$label.log</string>
</dict></plist>
PLIST
}

WEEKDAYS_630=""
for d in 1 2 3 4 5; do
  WEEKDAYS_630="$WEEKDAYS_630<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>"
done

remove() {  # label
  launchctl bootout "$DOMAIN" "$AGENTS/$1.plist" 2>/dev/null || true
  rm -f "$AGENTS/$1.plist"
}

case "$1" in
  collect)
    mkdir -p "$AGENTS" "$DIR/data"
    write_plist com.reader.collect "<key>StartInterval</key><integer>1800</integer>" "$DIR/brief" collect
    write_plist com.reader.package "<key>StartCalendarInterval</key><array>$WEEKDAYS_630</array>" "$DIR/brief" package
    remove com.reader.brief
    for label in com.reader.collect com.reader.package; do
      launchctl bootout "$DOMAIN" "$AGENTS/$label.plist" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
    done
    echo "Scheduled: news collection every 30 minutes, and the morning package at 6:30 AM Monday to Friday (free)."
    echo "No brief is written automatically; run ./brief run when you want one."
    echo "Log: $DIR/data/com.reader.collect.log. To stop: ./schedule.sh off"
    ;;
  on)
    mkdir -p "$AGENTS" "$DIR/data"
    write_plist com.reader.collect "<key>StartInterval</key><integer>1800</integer>" "$DIR/brief" collect
    write_plist com.reader.brief "<key>StartCalendarInterval</key><array>$WEEKDAYS_630</array>" "$DIR/brief" run --notify
    remove com.reader.package
    for label in com.reader.collect com.reader.brief; do
      launchctl bootout "$DOMAIN" "$AGENTS/$label.plist" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
    done
    echo "Scheduled: news collection every 30 minutes, and the brief at 6:30 AM Monday to Friday."
    echo "Logs are in $DIR/data/. To stop: ./schedule.sh off"
    ;;
  off)
    for label in com.reader.collect com.reader.package com.reader.brief; do
      remove "$label"
    done
    echo "Schedule removed."
    ;;
  status)
    found=0
    for label in com.reader.collect com.reader.package com.reader.brief; do
      if [ -f "$AGENTS/$label.plist" ]; then
        found=1
        case "$label" in
          com.reader.collect) what="collect news every 30 minutes" ;;
          com.reader.package) what="morning package at 6:30 AM, Monday to Friday" ;;
          com.reader.brief) what="write the brief at 6:30 AM, Monday to Friday" ;;
        esac
        target="$(plutil -extract ProgramArguments.0 raw "$AGENTS/$label.plist" 2>/dev/null)"
        if [ -n "$target" ] && [ "$target" != "$DIR/brief" ]; then
          echo "On, for a Reader folder elsewhere ($(dirname "$target")):  $what"
          continue
        fi
        echo "On:  $what"
        if [ -f "$DIR/data/$label.log" ]; then
          last="$(grep -v '^ ' "$DIR/data/$label.log" | tail -1)"
          [ -n "$last" ] && echo "     last: $last"
        fi
      fi
    done
    [ "$found" = 1 ] || echo "Nothing is scheduled. ./schedule.sh collect or ./schedule.sh on to start."
    ;;
  *)
    echo "Usage: ./schedule.sh on | collect | off | status"
    exit 1
    ;;
esac
