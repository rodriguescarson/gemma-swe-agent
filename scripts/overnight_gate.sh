#!/usr/bin/env bash
# Kaggle GPU gate for the overnight sequence (E6, docs/PLAN_TO_FINISH.txt; tests/test_overnight_gate.py).
# Opens (exit 0, prints GATE OPEN) only when BOTH hold:
#   (a) the day's submission marker exists and was written today (UTC day) -- decide_sub9.sh writes it after submit_at
#       returns; a marker from an earlier day is stale and never opens the gate;
#   (b) the newest row of the Kaggle submissions listing is not PENDING (no GPU kernel of ours while a submission scores,
#       Carson 2026-09-26).
# Polls every GATE_POLL_S seconds (default 600), at most GATE_MAX_POLLS times (default 0 = forever); exit 1 when it gives up.
#   [MARKER=eval/overnight/sub9_submitted] [KAGGLE_BIN=...] [GATE_POLL_S=600] [GATE_MAX_POLLS=0] scripts/overnight_gate.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
MARKER=${MARKER:-eval/overnight/sub9_submitted}
KAGGLE=${KAGGLE_BIN:-$(command -v kaggle || ls "$HOME"/Library/Python/3.*/bin/kaggle .venv/bin/kaggle "$HOME"/.local/bin/kaggle 2>/dev/null | head -1)}
POLL=${GATE_POLL_S:-600}; MAX=${GATE_MAX_POLLS:-0}
now() { echo "${FAKE_NOW_EPOCH:-$(date -u +%s)}"; }   # FAKE_NOW_EPOCH: tests only
day_start() { python3 -c "import datetime as d; n=d.datetime.fromtimestamp($(now), d.timezone.utc); print(int(n.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()))"; }
# python, not stat: GNU stat reads `-f` as --file-system and prints the file system's status (tests/gnu_stat.py)
mtime() { python3 -c 'import os, sys; print(int(os.stat(sys.argv[1]).st_mtime))' "$1"; }
n=0
while :; do
  n=$((n + 1)); reason=""
  if [ ! -f "$MARKER" ]; then reason="no marker $MARKER"
  elif [ "$(mtime "$MARKER")" -lt "$(day_start)" ]; then reason="stale marker $MARKER ($(date -u -r "$(mtime "$MARKER")" 2>/dev/null || date -u -d @"$(mtime "$MARKER")")) predates today's UTC day"
  else
    listing=$("$KAGGLE" competitions submissions -c gemma-4-developer-agent -v 2>/dev/null)
    newest=$(echo "$listing" | sed -n 2p)
    if [ -z "$newest" ]; then reason="listing failed (network?)"
    elif echo "$newest" | grep -q PENDING; then reason="newest submission PENDING: $(echo "$newest" | cut -c1-120)"
    fi
  fi
  if [ -z "$reason" ]; then echo "$(date -u) GATE OPEN: marker fresh, nothing pending"; exit 0; fi
  echo "$(date -u) gate closed (poll $n): $reason"
  if [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ]; then exit 1; fi
  sleep "$POLL"
done
