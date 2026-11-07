#!/usr/bin/env bash
# Budget ladder L1 (pre-registered in docs/GAPS_2026-10-06.md, "Budget ladder L1 pre-registered", 2026-11-07).
#  1. wait for the weekly Kaggle GPU quota reset (Saturday 00:00 UTC) plus 5 minutes;
#  2. push kernels/g4-ladder-v12b8 (runs as g4-eval74-v3 on 4x L4: v12b at 8 minutes on scripts/ladder/subset55.txt with
#     scripts/ladder/snapshot_hook.py) and wait for its output (scripts/kaggle_push_wait.sh);
#  3. gate A(i) from the files: snapshot rows for at least 53 of 55 tasks and no hook errors, else stop here;
#  4. scripts/ladder/ladder_patches.py -> eval/ladder/l1/labels.json, then a CPU rescore kernel (make_eval_kernel.py
#     --patches, runs as g4-rescore-fair; no GPU quota) and its output;
#  5. scripts/ladder/ladder_analyze.py -> eval/ladder/l1/analysis.txt.
# Nothing here submits to the competition. Log: eval/arm_ladder_l1.out (START/DONE lines per step).
set -u
cd "$(dirname "$0")/.."
LOG=eval/arm_ladder_l1.out; L1=eval/kaggle/g4-ladder-v12b8; OUT=eval/ladder/l1; RS=g4-ladder-rescore
say() { echo "$(date -u '+%F %T UTC') $*" >> "$LOG"; }
RESET=${LADDER_START_EPOCH:-$(python3 -c "import datetime as d; print(int(d.datetime(2026,11,7,0,5,tzinfo=d.timezone.utc).timestamp()))")}
say "START chain (pid $$); push not before $(date -u -r "$RESET" '+%F %T UTC')"
while [ "$(date +%s)" -lt "$RESET" ]; do sleep 60; done
if .venv/bin/kaggle competitions submissions -c gemma-4-developer-agent -v 2>/dev/null | grep -qE ',(SubmissionStatus\.)?PENDING(,|$)'; then
  say "a competition submission is PENDING; L1 is an eval kernel and does not touch it, continuing"
fi
say "START L1 push+wait"
KAGGLE_BIN=.venv/bin/kaggle bash scripts/kaggle_push_wait.sh g4-ladder-v12b8 >> "$LOG" 2>&1; rc=$?
say "DONE L1 push+wait rc=$rc"
if grep -q "LADDER_ABORT" "$L1"/*.log 2>/dev/null; then say "STOP: kernel aborted after task 1 (hook wrote nothing or logged an error)"; exit 3; fi
[ "$rc" -eq 0 ] && [ -s "$L1/results.jsonl" ] || { say "STOP: no L1 results"; exit 1; }
python3 - "$L1" >> "$LOG" 2>&1 <<'PY' || { say "STOP: gate A(i) failed"; exit 4; }
import json, os, sys
d = sys.argv[1]; ids = [l.strip() for l in open("scripts/ladder/subset55.txt") if l.strip()]
snap = os.path.join(d, "snapshots.jsonl"); err = os.path.join(d, "snapshots.jsonl.err")
tasks = {json.loads(l)["task"] for l in open(snap)} if os.path.exists(snap) else set()
e = open(err).read().strip() if os.path.exists(err) else ""
rows = [json.loads(l) for l in open(os.path.join(d, "results.jsonl"))]
dt = {}
for l in open(snap):
    r = json.loads(l); dt[r["task"]] = dt.get(r["task"], 0) + r.get("dt", 0)
print("GATE A(i): tasks with snapshot rows %d of %d; hook errors %r; rows %d; solved %d; crash-like rows %d; mean hook s/task %.2f"
      % (len(tasks & set(ids)), len(ids), e[:200], len(rows), sum(r["resolved"] for r in rows),
         sum(1 for r in rows if str(r.get("err") or "").startswith("EXC")), sum(dt.values()) / max(1, len(dt))))
sys.exit(0 if len(tasks & set(ids)) >= 53 and not e else 1)
PY
say "START rescore build"
mkdir -p "$OUT"
python3 scripts/ladder/ladder_patches.py "$L1" "$OUT" >> "$LOG" 2>&1 || { say "STOP: ladder_patches failed"; exit 5; }
.venv/bin/python scripts/make_eval_kernel.py submissions/v12b "$RS" --patches "$OUT/labels.json" --kernel-id g4-rescore-fair --pin original >> "$LOG" 2>&1 \
  || { say "STOP: rescore kernel build failed"; exit 6; }
say "START rescore push+wait (CPU)"
KAGGLE_BIN=.venv/bin/kaggle bash scripts/kaggle_push_wait.sh "$RS" >> "$LOG" 2>&1; rc=$?
say "DONE rescore push+wait rc=$rc"
[ "$rc" -eq 0 ] && [ -s "eval/kaggle/$RS/results.jsonl" ] || { say "STOP: no rescore results"; exit 7; }
python3 scripts/ladder/ladder_analyze.py "$L1" "$OUT" "eval/kaggle/$RS/results.jsonl" --ids scripts/ladder/subset55.txt > "$OUT/analysis.txt" 2>&1
say "DONE analysis rc=$? -> $OUT/analysis.txt"
say "chain done"
