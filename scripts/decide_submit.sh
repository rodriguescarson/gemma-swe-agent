#!/bin/bash
# Pre-registered nightly choice between a candidate and a fallback bundle, decided by a faithful Kaggle-L4 eval kernel.
# Usage: decide_submit.sh <eval_kernel_slug> <candidate_submit_kernel> <fallback_submit_kernel> <HHMM UTC> <min_solved> <msg_candidate> <msg_fallback>
# Rule (fixed before the eval ran): submit the candidate iff its eval kernel finished, solved >= min_solved of its rows,
# no row carries a crash class (unknown tool, context overflow, KeyError, post-invocation), and the summed task seconds are at
# most DECIDE_MAX_SECS (default 13158 = 1.15 x v4's 11,442 s L4 run). Otherwise the fallback.
# The eval kernel may still be running at HHMM: we wait for it until the end of the UTC day (the day's slot stays valid).
EVAL=$1; CAND=$2; FALL=$3; AT=$4; MIN=$5; MSG_C=$6; MSG_F=$7
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=${SUBMIT_LOG:-$HERE/submit_log.txt}; KAGGLE=${KAGGLE_BIN:-kaggle}; OUT=${DECIDE_OUT:-$HERE/decide_out}
TARGET=${SUBMIT_TARGET_EPOCH:-$(python3 -c 'import datetime as d, sys
n = d.datetime.now(d.timezone.utc); a = sys.argv[1]
t = n.replace(hour=int(a[:2]), minute=int(a[2:]), second=0, microsecond=0)
print(int((t if t > n else t + d.timedelta(days=1)).timestamp()))' "$AT")}
echo "$(date -u) [$(hostname -s)] decide armed: eval=$EVAL candidate=$CAND fallback=$FALL min=$MIN target=$TARGET" >> "$LOG"
until [ "$(date -u +%s)" -ge "$TARGET" ]; do sleep 20; done
DAY_END=$(( TARGET - (TARGET % 86400) + 86400 - 900 ))
status=""
while :; do
  status=$("$KAGGLE" kernels status "carsonrodrigues/$EVAL" 2>&1 | grep -oE 'KernelWorkerStatus\.[A-Z]+' | head -1)
  case "$status" in *COMPLETE|*ERROR|*CANCEL*) break ;; esac
  [ "$(date -u +%s)" -ge "$DAY_END" ] && break
  echo "$(date -u) [$(hostname -s)] waiting for eval kernel $EVAL ($status)" >> "$LOG"; sleep 600
done
choice=$FALL; msg=$MSG_F; why="eval status ${status:-unknown}"
if [ "$status" = "KernelWorkerStatus.COMPLETE" ]; then
  rm -rf "$OUT" && mkdir -p "$OUT" && "$KAGGLE" kernels output "carsonrodrigues/$EVAL" -p "$OUT" >/dev/null 2>&1
  verdict=$(python3 - "$OUT/results.jsonl" "$MIN" "${DECIDE_MAX_SECS:-13158}" <<'PY'
import json, re, sys
path, need, max_secs = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
try:
    rows = [json.loads(l) for l in open(path) if l.strip()]
except OSError:
    print("NO_RESULTS 0 0 0"); sys.exit()
crash = re.compile(r"not found\.|Tool '[^']+' not found|ContextWindowExceeded|maximum context length|prompt contains at least|"
                   r"KeyError|Context variable not found|No LlmAgent model available")
solved = sum(bool(r.get("resolved")) for r in rows)
crashes = sum(bool(crash.search(str(r.get("err") or ""))) for r in rows)
secs = sum(float(r.get("secs") or 0) for r in rows)
ok = rows and solved >= need and crashes == 0 and secs <= max_secs
print(("PASS" if ok else "FAIL"), solved, len(rows), crashes, int(secs))
PY
)
  why="eval $verdict (solved rows crashes secs), need >= $MIN, 0 crashes, secs <= ${DECIDE_MAX_SECS:-13158}"
  case "$verdict" in PASS*) choice=$CAND; msg=$MSG_C ;; esac
fi
echo "$(date -u) [$(hostname -s)] decision: $choice ($why)" >> "$LOG"
SUBMIT_TARGET_EPOCH=0 SUBMIT_LOG="$LOG" KAGGLE_BIN="$KAGGLE" exec bash "$HERE/submit_at.sh" "$choice" 0000 "$msg"
