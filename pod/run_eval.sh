#!/usr/bin/env bash
# Usage: run_eval.sh <submission_dir> <run_id> <max_min> <max_calls> <max_turns> <cmd_timeout> <concurrency> [task ids...]
set -uo pipefail
source /root/hvenv/bin/activate; cd /root/g4
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-http://127.0.0.1:8100/v1}
SUB=$1; RUN=$2; MIN=$3; CALLS=$4; TURNS=$5; TO=$6; CONC=$7; shift 7
# Faithful budget (2026-09-27): the Kaggle scorer takes the four limits from the bundle's eval_config.yaml, so use them
# whenever the bundle has one; CLI numbers are only a fallback. (Fair runs v4-v8 used 6 min/110 calls vs 5/70 on Kaggle.)
if [ "${FAITHFUL:-1}" = 1 ] && [ -f "$SUB/eval_config.yaml" ]; then
  eval "$(python3 - "$SUB/eval_config.yaml" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
for key, var in (("max_time_minutes", "MIN"), ("max_tool_calls", "CALLS"), ("max_turns", "TURNS"), ("timeout_seconds", "TO")):
    m = re.search(rf"^\s*{key}\s*:\s*([0-9.]+)", t, re.M)
    if m: print(f"{var}={m.group(1)}")
PY
)"
fi
echo "BUDGET $RUN min=$MIN calls=$CALLS turns=$TURNS timeout=$TO" >> eval/progress.log
OUT=eval/runs/$RUN; mkdir -p $OUT
IDS=(); [ $# -gt 0 ] && IDS=(--task-ids "$@")
echo "START $RUN $(date -u +%FT%TZ)" >> eval/progress.log
RUNNER=scripts/run_eval.py; TASKS=data/tasks.jsonl; SNAPS=data/raw/snapshots
if [ "${PALLETS:-0}" = 1 ]; then   # research/pallets.md 7.3: src/ layouts need the pallets runner and its wheelhouse
  RUNNER=scripts/pallets/run_eval_pallets.py; TASKS=data/pallets/harness/tasks.jsonl; SNAPS=data/pallets/harness/snapshots
  export G4_WHEELHOUSE=/root/g4/data/pallets/harness/wheels
fi
python $RUNNER eval --tasks $TASKS --snapshots-dir $SNAPS --submission-dir $SUB --results-dir $OUT \
  --sandbox subprocess --max-time-minutes $MIN --max-tool-calls $CALLS --max-turns $TURNS --timeout-seconds $TO \
  --concurrency $CONC --display quiet "${IDS[@]}" > $OUT/run.out 2>&1
echo "DONE $RUN rc=$? $(date -u +%FT%TZ) $(python -c "import json;d=json.load(open('$OUT/summary.json'));print(d.get('resolution_rate'),d.get('resolved'))" 2>/dev/null)" >> eval/progress.log
