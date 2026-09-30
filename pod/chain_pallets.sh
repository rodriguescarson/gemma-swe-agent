#!/usr/bin/env bash
# Pallets transfer check (2026-09-30): CONTROL vs TREAT on the 40 packed Pallets dev tasks (hidden-like repos).
# Derived from pod/chain_pair.sh. One-round paired check (2026-09-29, Kaggle GPU quota exhausted): CONTROL vs TREAT once each on all 74 ids, one arm per GPU,
# same faithful settings, preflight and canaries as race 2; no second round. Derived from pod/chain_race2.sh.
# Race 2 (SPEC section 10): control r2_v9_eog (submissions/v9_eog = the shipped sub4) against r2_v10 (submissions/v10),
# each run twice on all 74 valid ids (data/arena_ids.txt + data/rest_ids.txt), 2 tasks per GPU. Arms swap GPUs between
# rounds so server drift hits both sides. Both arms get the faithful settings of scripts/run_eval.py (R115): README
# compaction (14,336 tokens / keep 5), the L4 clock (caps / 1.7 and clock_scale 1.7 in every agent sandbox), no editable
# install, and budgets from each bundle's eval_config.yaml (FAITHFUL=1). Pass, kill and ship rules are pre-registered in
# docs/v10/race2_checklist.md and computed by scripts/replay_l4.py.
# WRITTEN, NOT RUN: starting this chain (the GPU spend) is Carson's call. Every exit path backs up first, then stops.
cd /root/g4 || exit 1
export PALLETS=1 G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1
CONTROL=${CONTROL:-v4}; TREAT=${TREAT:-v10}
stop_pod() {  # every exit path: manifest of the race-2 runs, verified backup (HF + GitHub), then stop
  sed -i "/^HOLD /d" eval/progress.log
  for d in eval/runs/r2_* eval/runs/pl_*; do
    [ -d "$d" ] || continue
    echo "R2_MANIFEST $d rows=$(wc -l < "$d/task_results.jsonl" 2>/dev/null || echo 0) traces=$(find "$d/traces" -name 'trace_*.json' 2>/dev/null | wc -l) patches=$(find "$d/patches" -name '*.patch' 2>/dev/null | wc -l)" >> eval/progress.log
  done
  # shellcheck disable=SC2046
  export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
  bash pod/backup.sh "$1" && runpodctl stop pod "$RUNPOD_POD_ID"
}
abort() { echo "ABORT pal $1 $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod palabort; exit 1; }
run_arm() {  # <port> <bundle> <run id>: one full 74-task run, 2 tasks at a time on that GPU's server
  # shellcheck disable=SC2086  # $IDS is the space-separated task id list; it is split into arguments on purpose
  OPENAI_BASE_URL="http://127.0.0.1:$1/v1" bash pod/run_eval.sh "submissions/$2" "$3" 5 100 200 120 2 $IDS
  echo "ARM_DONE $3 $(date -u +%FT%TZ)" >> eval/progress.log
}

until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for _ in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
echo "HOLD pal $(date -u +%FT%TZ)" >> eval/progress.log
# GO gate: the Mac writes GO_PAL (content GO) after section 10.2 is green (NOGO, or 100 min without a flag -> stop).
for _ in $(seq 1 200); do [ -f GO_PAL ] && break; sleep 30; done
grep -qx GO GO_PAL 2>/dev/null || abort "no GO ($(cat GO_PAL 2>/dev/null || echo timeout))"
if [ -s data/kaggle_pins.txt ]; then VIRTUAL_ENV=/root/buildenv uv pip install -q -r data/kaggle_pins.txt; fi
bash pod/health.sh || abort unhealthy
/root/buildenv/bin/python -c "import multipart" || abort "buildenv lacks python-multipart"
IDS=$(tr '\n' ' ' < data/pallets/harness/ids.txt)
[ "$(echo "$IDS" | wc -w)" = 40 ] || abort "expected 40 pallets ids"
# CPU pre-flight (pallets.md 7.3 step 1): gold must resolve and the empty patch must not
export G4_WHEELHOUSE=/root/g4/data/pallets/harness/wheels
for m in oracle skip-agent-patch; do
  # shellcheck disable=SC2086
  /root/hvenv/bin/python scripts/pallets/run_eval_pallets.py --$m eval --tasks data/pallets/harness/tasks.jsonl \
    --snapshots-dir data/pallets/harness/snapshots --submission-dir submissions/v4 --results-dir eval/runs/pl_pre_$m \
    --sandbox subprocess --concurrency 4 --display quiet --task-ids $IDS > eval/runs/pl_pre_$m.out 2>&1
done
KEEP=$(python3 - <<'PY'
import json
def res(d): return {json.loads(l)["instance_id"]: bool(json.loads(l)["resolved"]) for l in open(f"eval/runs/pl_pre_{d}/task_results.jsonl")}
g, e = res("oracle"), res("skip-agent-patch")
print(" ".join(sorted(t for t in g if g[t] and not e.get(t, True))))
PY
)
echo "PAL_PREFLIGHT valid=$(echo $KEEP | wc -w)/40 $(date -u +%FT%TZ)" >> eval/progress.log
[ "$(echo $KEEP | wc -w)" -ge 30 ] || abort "pallets pre-flight: only $(echo $KEEP | wc -w) valid"
IDS=$KEEP
for b in $CONTROL $TREAT; do
  LORA_GATE=0 bash pod/preflight.sh "submissions/$b" > "/root/preflight_$b.out" 2>&1 || abort "preflight $b"
done
for b in $CONTROL $TREAT; do bash pod/canary.sh "submissions/$b" || abort "canary $b"; done
echo "PAL_START control=$CONTROL treat=$TREAT compaction=$G4_COMPACTION scale=$G4_L4_SCALE no_editable=$G4_NO_EDITABLE $(date -u +%FT%TZ)" >> eval/progress.log

# One round: control on GPU0, treatment on GPU1.
run_arm 8100 "$CONTROL" "pl_${CONTROL}" &
run_arm 8101 "$TREAT" "pl_${TREAT}" &
wait
python3 scripts/replay_l4.py --kill-check eval/runs --control "pl_$CONTROL" --treatment "pl_$TREAT" >> eval/progress.log 2>&1
echo "PAL_CHECK rc=$? $(date -u +%FT%TZ)" >> eval/progress.log
echo "ALL_DONE pal $(date -u +%FT%TZ)" >> eval/progress.log
stop_pod pallets
