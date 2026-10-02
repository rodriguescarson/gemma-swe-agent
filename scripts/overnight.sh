#!/usr/bin/env bash
# One overnight sequence, no manual stops (Carson, 2026-10-03 00:50 IST). Resumable: every step skips itself when its
# output already exists. Runs inside tmux with caffeinate. Log: eval/overnight/progress.log.
#
#  1. wait for the collect2 chain (sample 1 v4h -> pre-flight of the 159 -> sample 2 v4h2 on the valid ids)
#  2. teacher pass: qwen/qwen3-coder (Apache-2.0) through the same harness on the valid ids, capture on
#  3. sample 3: v4h2 again (more Gemma data) if disk and time allow
#  4. rows: build_sft over all captures (per-sample verdicts), validate (train/validate_rows.py, eval sets excluded)
#  5. Adaption: upload + launch v11a ONLY if validation passed and rows >= 10,000 (Carson's go of 2026-10-02)
#  6. Kaggle, after the 05:30 IST quota reset, strictly in order and each waited to completion:
#     g4-l4-lora-probe (G-A) -> g4-l4-v4h (74) -> g4-l4-v4-wh28 (74, control) -> g4-l4-v4h-think (10)
#  7. summary
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python; LOG=eval/overnight/progress.log; mkdir -p eval/overnight data/v11
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] $*" | tee -a "$LOG"; }
free_gb() { df -g /System/Volumes/Data | awk 'NR==2{print $4}'; }
VALID=eval/preflight/train159/valid_ids.txt

step "overnight start; free ${free_gb:-?}GB"
# 1. the collect2 chain
until ! tmux has-session -t collect2 2>/dev/null; do sleep 120; done
step "collect2 chain finished: preflight $(cat eval/preflight/train159/report.txt 2>/dev/null | head -1); sample2 rows $(wc -l < eval/collect/pallets_v4h2_s2/s1/task_results.jsonl 2>/dev/null || echo 0)"
[ -s "$VALID" ] || { step "no valid ids from preflight; using train_ids.txt"; VALID=data/pallets/train_ids.txt; }

# 2. teacher pass
if ! grep -q ALL_DONE eval/collect/pallets_qwen_t1/progress.log 2>/dev/null; then
  if [ "$(free_gb)" -ge 6 ]; then
    step "teacher pass start (qwen/qwen3-coder, $(wc -l < "$VALID") tasks)"
    SAMPLES=1 CONC=4 MAX_USD=15 MODEL=qwen/qwen3-coder PROVIDER=any HARNESS=data/pallets/harness_train \
      bash scripts/collect/collect.sh v4h2 "$VALID" pallets_qwen_t1 > eval/collect/pallets_qwen_t1.out 2>&1
    step "teacher pass done: $(tail -1 eval/collect/pallets_qwen_t1.out)"
  else
    step "teacher pass SKIPPED: $(free_gb)GB free < 6"
  fi
fi

# 3. sample 3 (Gemma, v4h2) if there is time before the Kaggle window needs attention (it does not; Kaggle runs remotely)
if ! grep -q ALL_DONE eval/collect/pallets_v4h2_s3/progress.log 2>/dev/null; then
  if [ "$(free_gb)" -ge 6 ]; then
    step "sample 3 start (v4h2)"
    SAMPLES=1 CONC=4 MAX_USD=10 HARNESS=data/pallets/harness_train bash scripts/collect/collect.sh v4h2 "$VALID" pallets_v4h2_s3 > eval/collect/pallets_v4h2_s3.out 2>&1
    step "sample 3 done: $(tail -1 eval/collect/pallets_v4h2_s3.out)"
  else
    step "sample 3 SKIPPED: $(free_gb)GB free < 6"
  fi
fi

# 4. rows
PAIRS=()
for d in pallets_v4h_s1 pallets_v4h2_s2 pallets_qwen_t1 pallets_v4h2_s3; do
  c=eval/collect/$d/capture_s1.jsonl; r=eval/collect/$d/s1/task_results.jsonl
  [ -s "$c" ] && [ -s "$r" ] && PAIRS+=(--pair "$c=$r")
done
step "building rows from ${#PAIRS[@]} pair args"
$PY train/build_sft.py "${PAIRS[@]}" --tasks data/pallets/harness_train/tasks.jsonl --out data/v11/rows_v1.jsonl \
  --exclude-ids data/pallets/dev40_ids.txt --exclude-ids data/pallets/holdout_ids.txt > eval/overnight/build_rows.out 2>&1
step "build_sft: $(tr -d '\n' < eval/overnight/build_rows.out | cut -c1-300)"
$PY train/validate_rows.py data/v11/rows_v1.jsonl --exclude-ids data/pallets/dev40_ids.txt --exclude-ids data/pallets/holdout_ids.txt \
  --min-rows 10000 --report eval/overnight/rows_report.json > eval/overnight/validate_rows.out 2>&1
VOK=$?
step "validate_rows exit $VOK: $(python3 -c "import json; r=json.load(open('eval/overnight/rows_report.json')); print({k: r[k] for k in ('rows','tasks','rows_per_task','stages','problems')})" 2>/dev/null)"

# 5. Adaption (only on a clean validation with the 10k floor)
if [ "$VOK" = 0 ] && ! [ -s eval/overnight/adaption_launch.out ]; then
  step "Adaption: uploading rows and launching v11a (validation passed)"
  $PY train/adaption_train.py data/v11/rows_v1.jsonl --name v11a --launch > eval/overnight/adaption_launch.out 2>&1
  step "Adaption: $(grep -E 'dataset|LAUNCHED|Error|error' eval/overnight/adaption_launch.out | head -3 | tr '\n' ' ' | cut -c1-300)"
else
  step "Adaption: NOT launched (validation exit $VOK or already launched)"
fi

# 6. Kaggle after the quota reset (05:30 IST = 00:00 UTC) AND after today's submission has finished scoring (no GPU
#    kernels of ours while a submission scores: Carson 2026-09-26), one kernel at a time
until [ "$(date -u +%H%M)" -ge "0005" ] && [ "$(date -u +%H%M)" -lt "2300" ]; do sleep 120; done
until ! kaggle competitions submissions -c gemma-4-developer-agent -v 2>/dev/null | sed -n 2p | grep -q PENDING; do sleep 600; done
step "no submission pending; starting the Kaggle kernel sequence"
push_wait() {  # <slug>
  local slug=$1 st
  if [ -s "eval/kaggle/$slug/results.jsonl" ] || [ -s "eval/kaggle/$slug/lora_probe.json" ]; then step "$slug: output already present, skip"; return; fi
  step "$slug: push"
  kaggle kernels push -p "kernels/$slug" >> eval/overnight/kaggle.out 2>&1 || { step "$slug: push FAILED"; return; }
  sleep 120
  while :; do
    st=$(kaggle kernels status "carsonrodrigues/$slug" 2>&1 | grep -oE 'KernelWorkerStatus\.[A-Z]+' | head -1)
    case "$st" in *COMPLETE|*ERROR|*CANCEL*) break ;; esac
    sleep 300
  done
  step "$slug: $st"
  mkdir -p "eval/kaggle/$slug"; kaggle kernels output "carsonrodrigues/$slug" -p "eval/kaggle/$slug" >> eval/overnight/kaggle.out 2>&1 || true
  step "$slug: output $(ls eval/kaggle/$slug 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
}
push_wait g4-l4-lora-probe
push_wait g4-l4-v4h
push_wait g4-l4-v4-wh28
push_wait g4-l4-v4h-think

# 7. summary
{
  echo "OVERNIGHT SUMMARY $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST')"
  echo "preflight: $(cat eval/preflight/train159/report.txt 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
  for d in pallets_v4h_s1 pallets_v4h2_s2 pallets_qwen_t1 pallets_v4h2_s3; do
    r=eval/collect/$d/s1/task_results.jsonl; [ -s "$r" ] || continue
    echo "$d: rows $(wc -l < "$r") solved $(grep -c '"resolved": true' "$r") heredoc-crash $(grep -c "Tool 'python3" "$r") spent \$$(tail -1 eval/collect/$d/proxy_s1.jsonl 2>/dev/null | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["spent_usd"])' 2>/dev/null)"
  done
  echo "rows: $(python3 -c "import json; r=json.load(open('eval/overnight/rows_report.json')); print(r['rows'], 'rows', r['tasks'], 'tasks, ok', r['ok'])" 2>/dev/null)"
  echo "adaption: $(grep -E 'LAUNCHED|not launched|NOT launched|Error' eval/overnight/adaption_launch.out eval/overnight/progress.log 2>/dev/null | tail -1 | cut -c1-200)"
  for s in g4-l4-lora-probe g4-l4-v4h g4-l4-v4-wh28 g4-l4-v4h-think; do echo "$s: $(grep "$s:" "$LOG" | tail -1 | cut -c1-160)"; done
  [ -s eval/kaggle/g4-l4-lora-probe/lora_probe.json ] && python3 -c "import json; r=json.load(open('eval/kaggle/g4-l4-lora-probe/lora_probe.json')); print('G-A', r.get('GA'), r.get('checks'), 'prefix', r.get('prefix'))"
  for s in g4-l4-v4h g4-l4-v4-wh28; do [ -s eval/kaggle/$s/results.jsonl ] && echo "$s: solved $(python3 -c "import json; rows=[json.loads(l) for l in open('eval/kaggle/$s/results.jsonl')]; print(sum(bool(r.get('resolved')) for r in rows), '/', len(rows), 'mean secs', round(sum(float(r.get('secs') or 0) for r in rows)/max(1,len(rows))))")"; done
} > eval/overnight/summary.txt
step "ALL DONE; summary in eval/overnight/summary.txt"
