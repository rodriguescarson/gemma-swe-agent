#!/usr/bin/env bash
# Resample the SOLVED training tasks with Gemma (on-policy) to multiply success-only rows: two concurrent passes of
# SAMPLES samples each over the ids scripts/collect/solved_ids.py reports. Adaption's floor is 10,000 rows for a 31B
# LoRA; coverage of the hard residue alone yields too few (2026-10-03: 32 solved tasks ~ 2,400 rows).
#   [SAMPLES=2] [PASS_USD=8] [MIN_FREE_GB=6] scripts/collect/resample.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
LOG=eval/collect/coverage.log
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] $*" | tee -a "$LOG"; }
until [ "$(docker ps -q --filter ancestor=g4-pallets-linux:local | wc -l | tr -d ' ')" = 0 ]; do sleep 120; done
.venv/bin/python scripts/collect/solved_ids.py solved > eval/collect/resample_ids.txt 2>> "$LOG"
n=$(wc -w < eval/collect/resample_ids.txt | tr -d ' ')
step "resample: $n solved tasks x ${SAMPLES:-2} samples x 2 passes (free $(df -g /System/Volumes/Data | awk 'NR==2{print $4}')GB)"
[ "$n" -gt 0 ] || { step "resample: nothing solved yet"; exit 0; }
for slot in A B; do
  port=8796; [ "$slot" = B ] && port=8797
  SAMPLES=${SAMPLES:-2} CONC=4 MAX_USD=${PASS_USD:-8} PORT=$port MODEL=google/gemma-4-31b-it PROVIDER=parasail/fp8 HARNESS=data/pallets/harness_train \
    bash scripts/collect/collect.sh v4h2 eval/collect/resample_ids.txt "resample_${slot}_gemma" > "eval/collect/resample_${slot}_gemma.out" 2>&1 &
  sleep 90
done
wait
step "resample done: $(for s in A B; do for k in 1 2 3; do f=eval/collect/resample_${s}_gemma/s$k/task_results.jsonl; [ -s "$f" ] && printf '%s/s%s %s/%s ' "$s" "$k" "$(grep -c '"resolved": true' "$f")" "$(wc -l < "$f" | tr -d ' ')"; done; done)"
