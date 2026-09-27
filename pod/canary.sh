#!/usr/bin/env bash
# One real task end to end before any full run: the result row must exist, with real tool calls, within 8 minutes.
cd /root/g4; B=${1:-submissions/v8}; T=${2:-rich_3006}; R=canary_$(basename $B)
rm -rf eval/runs/$R
timeout 480 bash pod/run_eval.sh $B $R 6 110 220 180 1 $T
python3 - "$R" <<'PY' || { echo "CANARY_FAIL $B $(date -u +%FT%TZ)" >> eval/progress.log; exit 1; }
import json, sys
rows = [json.loads(l) for l in open(f"eval/runs/{sys.argv[1]}/task_results.jsonl")]
assert rows and (rows[0].get("tool_calls") or 0) > 0, rows
print("canary ok", rows[0]["instance_id"], "resolved", rows[0]["resolved"], "calls", rows[0]["tool_calls"])
PY
echo "CANARY_OK $B $(date -u +%FT%TZ)" >> eval/progress.log
