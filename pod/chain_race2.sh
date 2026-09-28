#!/usr/bin/env bash
# Race 2 (SPEC section 10): control r2_v9_eog (submissions/v9_eog = the shipped sub4) against r2_v10 (submissions/v10),
# each run twice on all 74 valid ids (data/arena_ids.txt + data/rest_ids.txt), 2 tasks per GPU. Arms swap GPUs between
# rounds so server drift hits both sides. Both arms get the faithful settings of scripts/run_eval.py (R115): README
# compaction (14,336 tokens / keep 5), the L4 clock (caps / 1.7 and clock_scale 1.7 in every agent sandbox), no editable
# install, and budgets from each bundle's eval_config.yaml (FAITHFUL=1). Pass, kill and ship rules are pre-registered in
# docs/v10/race2_checklist.md and computed by scripts/replay_l4.py.
# WRITTEN, NOT RUN: starting this chain (the GPU spend) is Carson's call. Every exit path backs up first, then stops.
cd /root/g4 || exit 1
export G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1
CONTROL=v9_eog; TREAT=v10
stop_pod() {  # every exit path: manifest of the race-2 runs, verified backup (HF + GitHub), then stop
  sed -i "/^HOLD /d" eval/progress.log
  for d in eval/runs/r2_*; do
    [ -d "$d" ] || continue
    echo "R2_MANIFEST $d rows=$(wc -l < "$d/task_results.jsonl" 2>/dev/null || echo 0) traces=$(find "$d/traces" -name 'trace_*.json' 2>/dev/null | wc -l) patches=$(find "$d/patches" -name '*.patch' 2>/dev/null | wc -l)" >> eval/progress.log
  done
  # shellcheck disable=SC2046
  export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
  bash pod/backup.sh "$1" && runpodctl stop pod "$RUNPOD_POD_ID"
}
abort() { echo "ABORT race2 $1 $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod race2abort; exit 1; }
run_arm() {  # <port> <bundle> <run id>: one full 74-task run, 2 tasks at a time on that GPU's server
  # shellcheck disable=SC2086  # $IDS is the space-separated task id list; it is split into arguments on purpose
  OPENAI_BASE_URL="http://127.0.0.1:$1/v1" bash pod/run_eval.sh "submissions/$2" "$3" 5 100 200 120 2 $IDS
  echo "ARM_DONE $3 $(date -u +%FT%TZ)" >> eval/progress.log
}

until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for _ in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
echo "HOLD race2 $(date -u +%FT%TZ)" >> eval/progress.log
# GO gate: the Mac writes GO_RACE2 (content GO) after section 10.2 is green (NOGO, or 100 min without a flag -> stop).
for _ in $(seq 1 200); do [ -f GO_RACE2 ] && break; sleep 30; done
grep -qx GO GO_RACE2 2>/dev/null || abort "no GO ($(cat GO_RACE2 2>/dev/null || echo timeout))"
if [ -s data/kaggle_pins.txt ]; then VIRTUAL_ENV=/root/buildenv uv pip install -q -r data/kaggle_pins.txt; fi
bash pod/health.sh || abort unhealthy
/root/buildenv/bin/python -c "import multipart" || abort "buildenv lacks python-multipart"
IDS=$(cat data/arena_ids.txt data/rest_ids.txt | tr '\n' ' ')
[ "$(echo "$IDS" | wc -w)" = 74 ] || abort "expected 74 task ids"
for b in $CONTROL $TREAT; do
  LORA_GATE=0 bash pod/preflight.sh "submissions/$b" > "/root/preflight_$b.out" 2>&1 || abort "preflight $b"
done
for b in $CONTROL $TREAT; do bash pod/canary.sh "submissions/$b" || abort "canary $b"; done
echo "RACE2_START control=$CONTROL treat=$TREAT compaction=$G4_COMPACTION scale=$G4_L4_SCALE no_editable=$G4_NO_EDITABLE $(date -u +%FT%TZ)" >> eval/progress.log

# Round 1: control on GPU0, v10 on GPU1.
run_arm 8100 "$CONTROL" "r2_${CONTROL}_1" &
run_arm 8101 "$TREAT" "r2_${TREAT}_1" &
wait
# Kill rule (pre-registered): v10 below v9_eog - 3, or any v10 crash class above 0 -> no run 2. A checker failure also stops.
python3 scripts/replay_l4.py --kill-check eval/runs --control "r2_$CONTROL" --treatment "r2_$TREAT" >> eval/progress.log 2>&1
kc=$?
if [ "$kc" -ne 0 ]; then echo "KILL race2 after run 1 (rc=$kc) $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod race2kill; exit 1; fi

# Round 2: arms swap GPUs.
run_arm 8100 "$TREAT" "r2_${TREAT}_2" &
run_arm 8101 "$CONTROL" "r2_${CONTROL}_2" &
wait
AGAINST=eval/runs/r_v4; [ -d "$AGAINST" ] || AGAINST=eval/race1/runs/r_v4
python3 scripts/replay_l4.py --race2 eval/runs --against "$AGAINST" > eval/race2_kpis.txt 2>&1
echo "RACE2_KPIS rc=$? $(tail -1 eval/race2_kpis.txt) $(date -u +%FT%TZ)" >> eval/progress.log
python3 scripts/replay_l4.py --race2 eval/runs --against "$AGAINST" --json > eval/race2_kpis.json 2>/dev/null
echo "ALL_DONE race2 $(date -u +%FT%TZ)" >> eval/progress.log
stop_pod race2
