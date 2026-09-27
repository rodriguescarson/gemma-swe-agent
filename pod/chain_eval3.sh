#!/usr/bin/env bash
# v7 (GPU0) vs v8 (GPU1), each on all 74 Kaggle-valid tasks at 2 per GPU, after the v4/v6 pair. Preflight-gated.
cd /root/g4
stop_pod() {  # every exit path: verified backup, then stop (an abort once left the pod idle for 2 h)
  sed -i "/^HOLD /d" eval/progress.log
  export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
  bash pod/backup.sh "$1" && runpodctl stop pod "$RUNPOD_POD_ID"
}
until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for t in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
echo "HOLD eval3 $(date -u +%FT%TZ)" >> eval/progress.log
bash pod/health.sh || { echo "ABORT eval3 unhealthy $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod eval3abort; exit 1; }
for b in v7 v8; do
  LORA_GATE=0 bash pod/preflight.sh submissions/$b > /root/preflight_$b.out 2>&1 || { echo "ABORT eval3 preflight $b" >> eval/progress.log; stop_pod eval3abort; exit 1; }
done
for b in v7 v8; do bash pod/canary.sh submissions/$b || { echo "ABORT eval3 canary $b" >> eval/progress.log; stop_pod eval3abort; exit 1; }; done
IDS=$(tr '\n' ' ' < data/kaggle_valid_ids.txt)
( OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/v7 p_v7 6 110 220 180 2 $IDS ) &
( OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/v8 p_v8 6 110 220 180 2 $IDS ) &
wait
echo "ALL_DONE eval3 $(date -u +%FT%TZ)" >> eval/progress.log
stop_pod eval3
