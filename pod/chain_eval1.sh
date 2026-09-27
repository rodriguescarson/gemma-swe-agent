#!/usr/bin/env bash
# Waits for boot, then: parity oracle (CPU) + two GPU lanes of 74-task evals. Ends with ALL_DONE and a delayed self-stop.
cd /root/g4
until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for t in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
bash pod/health.sh || { echo "ABORT: vLLM unhealthy $(date -u +%FT%TZ)" >> eval/progress.log; exit 1; }
cp data/kaggle_valid_ids.txt data/v74.txt
IDS=$(tr '\n' ' ' < data/v74.txt)
source /root/hvenv/bin/activate
( rm -rf eval/runs/parity; mkdir -p eval/runs/parity
  python scripts/run_eval.py --oracle eval --tasks data/tasks.jsonl --snapshots-dir data/raw/snapshots --submission-dir submissions/v3 \
    --results-dir eval/runs/parity --sandbox subprocess --concurrency 12 --display quiet > eval/runs/parity/run.out 2>&1
  echo "DONE parity $(date -u +%FT%TZ)" >> eval/progress.log ) &
( for v in v4 v5; do OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/$v h_$v 6 110 220 180 8 $IDS; done ) &
( for v in v3 v5; do OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/$v h_${v}_g1 6 110 220 180 8 $IDS; done ) &
wait
echo "ALL_DONE eval1 $(date -u +%FT%TZ)" >> eval/progress.log
sleep 2700
export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
bash pod/backup.sh eval1 && { grep -q HOLD eval/progress.log || runpodctl stop pod "$RUNPOD_POD_ID"; }
