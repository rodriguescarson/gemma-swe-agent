#!/usr/bin/env bash
# Sweep 1: four configs on the 47-task dev set, same budget. Ends with ALL_DONE and a delayed self-stop (safety net).
cd /root/g4
IDS=$(cat data/dev_ids.txt | tr '\n' ' ')
for cfg in v2 v1_t10 v1_t10_low v1; do
  bash pod/run_eval.sh submissions/$cfg sw1_$cfg 6 60 80 120 4 $IDS
done
echo "ALL_DONE sweep1 $(date -u +%FT%TZ)" >> eval/progress.log
sleep 2400
export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
bash pod/backup.sh sweep1 && { grep -q HOLD eval/progress.log || runpodctl stop pod "$RUNPOD_POD_ID"; }
