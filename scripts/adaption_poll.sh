#!/usr/bin/env bash
# Poll one Adaption run until it ends; on success download the adapter to adapters/<name>. Runs in tmux (no tool limit).
#   scripts/adaption_poll.sh <run_id> [<name>=v11a] [<poll_s>=600]   -> eval/overnight/adaption_poll.log
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
rid=${1:?run id}; name=${2:-v11a}; poll=${3:-600}; LOG=eval/overnight/adaption_poll.log
set -a; . ~/Projects/env-backups/autoscientist-challenge/.env 2>/dev/null; set +a
last=""
while :; do
  st=$(.venv/bin/python train/adaption_train.py --status "$rid" 2>&1 | python3 -c "
import sys, json
t = sys.stdin.read()
try:
    r = json.loads(t); print(f\"{r.get('status')} iter={r.get('current_iteration')} progress={r.get('progress')} err={str(r.get('error'))[:120]} dl={r.get('download_available')}\")
except Exception: print('ERRCALL ' + t.strip()[-160:].replace(chr(10), ' '))")
  [ "$st" != "$last" ] && { echo "$(date '+%Y-%m-%d %H:%M IST') $st" >> "$LOG"; last="$st"; }
  case "$st" in succeeded*|completed*|failed*|cancelled*|error*) break;; esac
  sleep "$poll"
done
echo "$(date '+%Y-%m-%d %H:%M IST') FINAL $st" >> "$LOG"
case "$st" in succeeded*|completed*)
  .venv/bin/python train/adaption_train.py --download "$rid" --out "adapters/$name" >> "$LOG" 2>&1
  echo "$(date '+%Y-%m-%d %H:%M IST') DOWNLOADED adapters/$name: $(ls adapters/$name 2>/dev/null | tr '\n' ' ') free $(df -g /System/Volumes/Data | awk 'NR==2{print $4}')GB" >> "$LOG";;
esac
