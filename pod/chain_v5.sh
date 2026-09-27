#!/usr/bin/env bash
# v5 at 2 tasks per GPU (closer to sequential scoring than 8), 74 tasks split across the two GPUs.
cd /root/g4
bash pod/health.sh || { echo "ABORT v5 unhealthy $(date -u +%FT%TZ)" >> eval/progress.log; exit 1; }
head -37 data/v74.txt > /tmp/a.txt; tail -n +38 data/v74.txt > /tmp/b.txt
( OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/v5 h_v5a 6 110 220 180 2 $(tr '\n' ' ' < /tmp/a.txt) ) &
( OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/v5 h_v5b 6 110 220 180 2 $(tr '\n' ' ' < /tmp/b.txt) ) &
wait
echo "ALL_DONE v5 $(date -u +%FT%TZ)" >> eval/progress.log
sleep 2700
export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
bash pod/backup.sh v5 && { grep -q HOLD eval/progress.log || runpodctl stop pod "$RUNPOD_POD_ID"; }
