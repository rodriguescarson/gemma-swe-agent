#!/usr/bin/env bash
# Usage: run_eval.sh <submission_dir> <run_id> <max_min> <max_calls> <max_turns> <cmd_timeout> <concurrency> [task ids...]
set -uo pipefail
source /root/hvenv/bin/activate; cd /root/g4
export OPENAI_BASE_URL=${OPENAI_BASE_URL:-http://127.0.0.1:8100/v1}
SUB=$1; RUN=$2; MIN=$3; CALLS=$4; TURNS=$5; TO=$6; CONC=$7; shift 7
OUT=eval/runs/$RUN; mkdir -p $OUT
IDS=(); [ $# -gt 0 ] && IDS=(--task-ids "$@")
echo "START $RUN $(date -u +%FT%TZ)" >> eval/progress.log
python scripts/run_eval.py eval --tasks data/tasks.jsonl --snapshots-dir data/raw/snapshots --submission-dir $SUB --results-dir $OUT \
  --sandbox subprocess --max-time-minutes $MIN --max-tool-calls $CALLS --max-turns $TURNS --timeout-seconds $TO \
  --concurrency $CONC --display quiet "${IDS[@]}" > $OUT/run.out 2>&1
echo "DONE $RUN rc=$? $(date -u +%FT%TZ) $(python -c "import json;d=json.load(open('$OUT/summary.json'));print(d.get('resolution_rate'),d.get('resolved'))" 2>/dev/null)" >> eval/progress.log
