#!/bin/bash
# sub28 = v12b_55 (GAPS 'sub28 re-registered', 31 Oct): v12b with max_time_minutes 5.5. The owner approved it on 31 Oct ("v12b
# at 5.5 min", one submission once its tests pass). It submits to Kaggle, so it refuses unless CARSON_APPROVED_SUB28=yes.
#  1. ship.sh eval   -> kernels/g4-l4-v12b55-p312 (full Mac suite + Linux gate + the 74-task 4x L4 eval kernel, run as
#                       g4-eval74-v3 on its Python 3.12 image).
#  2. ship.sh submit -> kernels/g4agent-v12b-55 (suite and gate again + the CPU submission kernel).
#  3. After the weekly GPU quota reset (RESET_AT, default 00:10 UTC Saturday 31 Oct) and with nothing PENDING: push the eval
#     kernel and wait for its output (eval/kaggle/g4-l4-v12b55-p312/results.jsonl).
#  4. The pre-registered gate: 74 rows of the valid ids, 0 crash rows, solved >= 26, summed secs <= 21,500. FAIL -> stop.
#  5. Push the submission kernel once and submit that version with tag sub28:.
# Every step is idempotent (ship rebuilds; push_wait skips output already present; submit_at skips a tag already on Kaggle).
#   CARSON_APPROVED_SUB28=yes nohup bash eval/arm_sub28_v12b55.sh >/dev/null 2>&1 &
[ "${CARSON_APPROVED_SUB28:-}" = yes ] || { echo "sub28 not approved: Carson approves each Kaggle submission (CARSON_APPROVED_SUB28=yes)" >&2; exit 2; }
cd /Users/carson/Projects/gemma-swe-agent || exit 1
B=v12b_55; EVAL=g4-l4-v12b55-p312; SLUG=g4agent-v12b-55; TAG="sub28:"
MIN_SOLVED=26; MAX_SECS=21500
LOG=eval/arm_sub28_v12b55.out; SP=${SP:-${TMPDIR:-/tmp}}
K=$PWD/.venv/bin/kaggle
RESET_AT=${RESET_AT:-$(date -u -j -f "%Y-%m-%d %H:%M:%S" "2026-10-31 00:10:00" +%s)}
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
push_version() {   # push once, wait for COMPLETE, print the pushed version number
  local slug=$1 out; out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh "$slug" 2>&1); echo "$out" >> "$LOG"
  echo "$out" | grep -q "COMPLETE\|output already present" || return 1
  echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1
}
# ---- 0. the pre-registration and the pinned bundle must be in this checkout
[ -f "submissions/$B/eval_config.yaml" ] && [ -f tests/test_v12b_55_bundle.py ] || { say "submissions/$B or its test missing; stop"; exit 1; }
grep -q "^### sub28 re-registered: v12b_55" docs/GAPS_2026-10-06.md || { say "GAPS has no sub28 re-registration; stop"; exit 1; }
# ---- 1-2. package both kernels (tests run inside ship.sh)
say "ship $B eval"
bash scripts/ship.sh "submissions/$B" "$EVAL" eval --ids data/kaggle_valid_ids.txt --pin original --kernel-id g4-eval74-v3 > "$SP/ship_${B}_eval.log" 2>&1
grep -q "SHIP OK: kernels/$EVAL" "$SP/ship_${B}_eval.log" || { say "$B eval ship FAILED (see $SP/ship_${B}_eval.log); stop"; exit 1; }
say "ship $B submit"
bash scripts/ship.sh "submissions/$B" "$SLUG" submit > "$SP/ship_${B}_submit.log" 2>&1
grep -q "SHIP OK: kernels/$SLUG" "$SP/ship_${B}_submit.log" || { say "$B submit ship FAILED (see $SP/ship_${B}_submit.log); stop"; exit 1; }
say "$B SHIP OK (eval and submit)"
# ---- 3. the L4 run, after the quota reset and with nothing scoring
until [ "$(date -u +%s)" -ge "$RESET_AT" ]; do sleep 300; done
until nothing_pending; do say "waiting: a submission is PENDING (no Kaggle runs while one scores)"; sleep 600; done
say "push eval kernel $EVAL"
push_version "$EVAL" > /dev/null || { say "eval kernel $EVAL push/run failed (GPU quota?); stop, no submission"; exit 1; }
# ---- 4. the gate
verdict=$(python3 - "eval/kaggle/$EVAL/results.jsonl" "$MIN_SOLVED" "$MAX_SECS" data/kaggle_valid_ids.txt <<'PY'
import json, re, sys
path, need, max_secs = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
valid = set(open(sys.argv[4]).read().split())
try:
    allrows = [json.loads(l) for l in open(path) if l.strip()]
except (OSError, ValueError):
    print("NO_RESULTS 0 0 0 0 %d" % len(valid)); sys.exit()
byid = {r.get("id"): r for r in allrows if isinstance(r, dict) and r.get("id") in valid}
rows, missing = list(byid.values()), len(valid - set(byid))
crash = re.compile(r"not found\.|Tool '[^']+' not found|ContextWindowExceeded|maximum context length|prompt contains at least|"
                   r"KeyError|Context variable not found|No LlmAgent model available")
solved = sum(bool(r.get("resolved")) for r in rows)
crashes = sum(bool(crash.search(str(r.get("err") or ""))) for r in rows)
secs = sum(float(r.get("secs") or 0) for r in rows)
ok = rows and missing == 0 and solved >= need and crashes == 0 and secs <= max_secs
print(("PASS" if ok else "FAIL"), solved, len(rows), crashes, int(secs), missing)
PY
)
say "gate: $verdict (fields: verdict solved rows crashes secs missing; need >= $MIN_SOLVED, 0 crashes, 0 missing, secs <= $MAX_SECS)"
case "$verdict" in PASS*) ;; *) say "$TAG NOT submitted: the L4 gate did not pass"; exit 3 ;; esac
# ---- 5. submit on the first free slot
until nothing_pending; do say "$B passed; waiting: a submission is PENDING"; sleep 600; done
V=$(push_version "$SLUG") || { say "$B submission kernel push/run failed; stop"; exit 1; }
MSG="$TAG v12b_55 = v12b (hidden 0.17) with max_time_minutes 5.5, nothing else; the budget is the one systematic difference from the best public lineages (research/assumptions_2026-10-31); L4 74: $verdict; expectation 0.12-0.19"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh "$SLUG" 0000 "$MSG" "$TAG" >> "$LOG" 2>&1
rc=$?
say "$TAG ($B) submit_at exited $rc"
say "chain done"
exit "$rc"
