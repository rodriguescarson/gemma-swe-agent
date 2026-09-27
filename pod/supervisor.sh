#!/usr/bin/env bash
# Independent pod supervisor (started at boot, outlives every chain). Jobs are never trusted to stop the pod themselves.
#  - no eval/boot/train process for IDLE_MIN minutes          -> verified backup + stop
#  - job active but GPUs ~0% for GPU_IDLE_MIN minutes          -> ALERT
#  - job active but no result/log progress for STALL_MIN min  -> ALERT
#  - pod uptime beyond MAX_HOURS                               -> verified backup + stop
# Heartbeat: /root/g4/eval/supervisor.hb ; alerts: /root/g4/eval/alerts.log (the Mac monitor tails both).
IDLE_MIN=${IDLE_MIN:-10}; GPU_IDLE_MIN=${GPU_IDLE_MIN:-10}; STALL_MIN=${STALL_MIN:-20}; MAX_HOURS=${MAX_HOURS:-8}
cd /root/g4; mkdir -p eval; A=eval/alerts.log; idle=0; gpu0=0; last_sig=""; stall=0; START=$(date +%s)
alert() { echo "$(date -u +%FT%TZ) ALERT $*" >> $A; }
stop_pod() {
  echo "$(date -u +%FT%TZ) STOPPING $1" >> $A
  export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
  if bash pod/backup.sh "supervisor-$1"; then runpodctl stop pod "$RUNPOD_POD_ID"; else alert "backup failed; NOT stopping (manual action needed)"; fi
}
while true; do
  date -u +%FT%TZ > eval/supervisor.hb
  active=$(pgrep -f '^(bash pod/(chain_|run_eval|bootstrap|train)|python scripts/run_eval|python train/)' | wc -l)
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1} END {print s+0}')
  sig=$(ls -l --time-style=+%s eval/runs/*/task_results.jsonl eval/progress.log 2>/dev/null | md5sum)
  if [ "$active" -eq 0 ] && ! grep -q "^HOLD" eval/progress.log 2>/dev/null; then idle=$((idle+1)); else idle=0; fi
  [ $idle -ge $IDLE_MIN ] && { stop_pod idle; idle=0; }
  if [ "$active" -gt 0 ] && grep -q "START " eval/progress.log 2>/dev/null && [ "${util:-0}" -eq 0 ]; then gpu0=$((gpu0+1)); else gpu0=0; fi
  [ $gpu0 -eq $GPU_IDLE_MIN ] && alert "job active but GPUs at 0% for ${GPU_IDLE_MIN} min"
  if [ "$active" -gt 0 ] && [ "$sig" = "$last_sig" ]; then stall=$((stall+1)); else stall=0; fi; last_sig=$sig
  [ $stall -eq $STALL_MIN ] && alert "job active but no progress for ${STALL_MIN} min"
  grep -h "PREFLIGHT_FAIL\|ABORT" eval/progress.log 2>/dev/null | tail -1 | grep -qv "$(cat /tmp/sv_seen 2>/dev/null || echo __none__)" && { alert "$(grep -h 'PREFLIGHT_FAIL\|ABORT' eval/progress.log | tail -1)"; grep -h 'PREFLIGHT_FAIL\|ABORT' eval/progress.log | tail -1 > /tmp/sv_seen; }
  [ $(( ($(date +%s) - START) / 3600 )) -ge $MAX_HOURS ] && { alert "runtime ceiling ${MAX_HOURS} h reached"; stop_pod ceiling; }
  sleep 60
done
