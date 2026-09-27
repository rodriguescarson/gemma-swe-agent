#!/usr/bin/env bash
# Paired v4 vs v6 on the 74 Kaggle-valid tasks, 2 tasks per GPU (near the sequential scorer), one config per GPU.
cd /root/g4
until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for t in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
bash pod/health.sh || { echo "ABORT: vLLM unhealthy $(date -u +%FT%TZ)" >> eval/progress.log; exit 1; }
IDS=$(tr '\n' ' ' < data/kaggle_valid_ids.txt)
( OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/v4 p_v4 6 110 220 180 2 $IDS ) &
( OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/v6 p_v6 6 110 220 180 2 $IDS ) &
wait
echo "ALL_DONE eval2 $(date -u +%FT%TZ)" >> eval/progress.log
bash pod/backup.sh eval2 >/dev/null
sleep 2700
export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
bash pod/backup.sh eval2final && { grep -q HOLD eval/progress.log || runpodctl stop pod "$RUNPOD_POD_ID"; }
