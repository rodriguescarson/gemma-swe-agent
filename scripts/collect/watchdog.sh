#!/usr/bin/env bash
# Kill the collection if the Mac's free disk drops under MIN_GB (Docker Desktop crashed on a full disk on 2026-09-30).
MIN_GB=${MIN_GB:-3}; SESSION=${1:-collect}
while tmux has-session -t "$SESSION" 2>/dev/null; do
  free=$(df -g /System/Volumes/Data | awk 'NR==2{print $4}')
  if [ "$free" -lt "$MIN_GB" ]; then
    echo "$(date -u +%FT%TZ) WATCHDOG: ${free} GB free < ${MIN_GB}; stopping $SESSION" >> eval/collect/watchdog.log
    docker ps -q --filter ancestor=g4-pallets-linux:local | xargs -r docker kill >/dev/null 2>&1
    tmux kill-session -t "$SESSION"; break
  fi
  sleep 60
done
