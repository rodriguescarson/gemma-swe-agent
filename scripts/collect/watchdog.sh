#!/usr/bin/env bash
# Kill Docker emulation containers if the Mac's free disk drops under MIN_GB (Docker Desktop crashed on a full disk on
# 2026-09-30). SESSION=<name>: guard while that tmux session lives and kill it too. SESSION=-: standalone, guards every
# g4-pallets-linux container whatever launched it (2026-10-04: a screen ran unguarded). tests/test_watchdog.py.
#   scripts/collect/watchdog.sh [SESSION|-]   [MIN_GB=3] [WATCHDOG_SLEEP_S=60] [WATCHDOG_MAX_LOOPS=0]
MIN_GB=${MIN_GB:-3}; SESSION=${1:-collect}; n=0
while :; do
  if [ "$SESSION" != "-" ] && ! tmux has-session -t "$SESSION" 2>/dev/null; then break; fi
  free=$(df -g /System/Volumes/Data | awk 'NR==2{print $4}')
  if [ "$free" -lt "$MIN_GB" ]; then
    echo "$(date -u +%FT%TZ) WATCHDOG: ${free} GB free < ${MIN_GB}; killing emulation containers (session $SESSION)" >> eval/collect/watchdog.log
    for c in $(docker ps -q --filter ancestor=g4-pallets-linux:local); do docker kill "$c" >/dev/null 2>&1; done
    [ "$SESSION" != "-" ] && { tmux kill-session -t "$SESSION"; break; }
  fi
  n=$((n + 1)); [ "${WATCHDOG_MAX_LOOPS:-0}" -gt 0 ] && [ "$n" -ge "${WATCHDOG_MAX_LOOPS}" ] && break
  sleep "${WATCHDOG_SLEEP_S:-60}"
done
