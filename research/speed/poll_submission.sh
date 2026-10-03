#!/bin/bash
# Read-only: log one submission's status every 300 s until COMPLETE/ERROR or a 16 h deadline (speed.md sect. 7.3).
# Usage: bash research/speed/poll_submission.sh "sub6:"   (matches the newest submission whose description starts with it)
# No submits, no pushes. Output: research/speed/poll_<tag>.log. The submit time comes from the Kaggle row itself.
set -u
TAG=${1:?description prefix, e.g. sub6:}
source /Users/carson/Projects/kaggriculture/.venv/bin/activate
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HERE/poll_$(printf '%s' "$TAG" | tr -cd 'A-Za-z0-9_').log"
END=$(( $(date -u +%s) + 16 * 3600 ))
echo "$(date -u +%FT%TZ) START pid $$ tag '$TAG'" >> "$LOG"
while :; do
  out=$(kaggle competitions submissions gemma-4-developer-agent -v 2>&1)
  row=$(printf '%s\n' "$out" | grep -F ",$TAG" | head -1)
  if [ -n "$row" ]; then echo "$(date -u +%FT%TZ) $row" >> "$LOG"
  else echo "$(date -u +%FT%TZ) NO_ROW_OR_CLI_ERROR: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)" >> "$LOG"; fi
  case "$row" in *COMPLETE*|*ERROR*) echo "$(date -u +%FT%TZ) DONE" >> "$LOG"; exit 0;; esac
  if [ "$(date -u +%s)" -ge "$END" ]; then echo "$(date -u +%FT%TZ) DEADLINE_STOP" >> "$LOG"; exit 0; fi
  sleep 300
done
