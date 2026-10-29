#!/bin/bash
# Pre-registered slot decision with NO fallback: submit the candidate iff its faithful Kaggle-L4 eval kernel passed the rule,
# otherwise log and leave the day's slot unused (tests/test_decide_or_skip.py). The rule, fixed before the eval ran:
#   the eval kernel finished (COMPLETE), every id in data/kaggle_valid_ids.txt (the 74 graded tasks) has a row, and over those
#   rows: solved >= MIN, no row carries a crash class, summed task seconds <= DECIDE_MAX_SECS. Rows for other ids (the
#   competition's tasks.jsonl has 129, 55 of them ungradable) are not judged. A repeated id counts once, and the LAST row for
#   an id wins (as scripts/box_p4_gate.py), so an earlier crash row that a later row supersedes does not count.
#   The output download is tried up to 3 times; if every try fails (even one that left a truncated results.jsonl behind), or the
#   file is not valid JSON lines, the verdict is NO_RESULTS and the slot stays unused.
# Usage: [KERNEL_VERSION=N] decide_or_skip.sh <eval_kernel_slug> <candidate_submit_kernel> <HHMM UTC> <min_solved> <message>
# The eval kernel may still be running at HHMM: we wait for it until the end of the UTC day (the slot stays valid all day).
EVAL=$1; CAND=$2; AT=$3; MIN=$4; MSG=$5
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=${SUBMIT_LOG:-$HERE/../eval/submit_log.txt}; OUT=${DECIDE_OUT:-$HERE/../eval/decide_out}
KAGGLE=${KAGGLE_BIN:-}
if [ -z "$KAGGLE" ]; then for c in "$HERE/../.venv/bin/kaggle" "$HOME/.local/bin/kaggle"; do [ -x "$c" ] && { KAGGLE=$c; break; }; done; fi
[ -x "$KAGGLE" ] || { echo "$(date -u) [$(hostname -s)] ABORT: kaggle binary not found (KAGGLE_BIN=$KAGGLE); not armed" >> "$LOG"; exit 2; }
VALID_IDS=${DECIDE_IDS_FILE:-$HERE/../data/kaggle_valid_ids.txt}
[ -s "$VALID_IDS" ] || { echo "$(date -u) [$(hostname -s)] ABORT: valid ids file not found or empty ($VALID_IDS); not armed" >> "$LOG"; exit 2; }
export KAGGLE_BIN=$KAGGLE
TARGET=${SUBMIT_TARGET_EPOCH:-$(python3 -c 'import datetime as d, sys
n = d.datetime.now(d.timezone.utc); a = sys.argv[1]
t = n.replace(hour=int(a[:2]), minute=int(a[2:]), second=0, microsecond=0)
print(int((t if t > n else t + d.timedelta(days=1)).timestamp()))' "$AT")}
echo "$(date -u) [$(hostname -s)] decide_or_skip armed: eval=$EVAL candidate=$CAND version=${KERNEL_VERSION:-latest} min=$MIN max_secs=${DECIDE_MAX_SECS:-23000} target=$TARGET" >> "$LOG"
until [ "$(date -u +%s)" -ge "$TARGET" ]; do sleep 20; done
base=$TARGET; now=$(date -u +%s); [ "$base" -lt "$now" ] && base=$now      # the end of the slot's UTC day, even when armed late (SUBMIT_TARGET_EPOCH=0)
DAY_END=$(( base - (base % 86400) + 86400 - 900 ))
status=""
while :; do
  status=$("$KAGGLE" kernels status "carsonrodrigues/$EVAL" 2>&1 | grep -oE 'KernelWorkerStatus\.[A-Z]+' | head -1)
  case "$status" in *COMPLETE|*ERROR|*CANCEL*) break ;; esac
  [ "$(date -u +%s)" -ge "$DAY_END" ] && break
  echo "$(date -u) [$(hostname -s)] waiting for eval kernel $EVAL ($status)" >> "$LOG"; sleep "${DECIDE_POLL_S:-600}"
done
verdict="NO_EVAL status=${status:-unknown}"
if [ "$status" = "KernelWorkerStatus.COMPLETE" ]; then
  got=""
  for try in 1 2 3; do      # a failed download used to leave the slot unused (NO_RESULTS) after one attempt
    if rm -rf "$OUT" && mkdir -p "$OUT" && "$KAGGLE" kernels output "carsonrodrigues/$EVAL" -p "$OUT" >/dev/null 2>&1 && [ -f "$OUT/results.jsonl" ]; then got=1; break; fi
    echo "$(date -u) [$(hostname -s)] output download of $EVAL failed (try $try of 3)" >> "$LOG"
    [ "$try" -lt 3 ] && sleep "${DECIDE_RETRY_S:-30}"
  done
  if [ -z "$got" ]; then      # a failed try may leave a truncated results.jsonl: never judge it
    verdict="NO_RESULTS 0 0 0 0 $(wc -w < "$VALID_IDS" | tr -d ' ')"
  else
    verdict=$(python3 - "$OUT/results.jsonl" "$MIN" "${DECIDE_MAX_SECS:-23000}" "$VALID_IDS" <<'PY'
import json, re, sys
path, need, max_secs = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
valid = set(open(sys.argv[4]).read().split())
try:
    allrows = [json.loads(l) for l in open(path) if l.strip()]
    if not all(isinstance(r, dict) for r in allrows):
        raise ValueError("a row is not a JSON object")
except (OSError, ValueError):       # unreadable, truncated or garbled (JSONDecodeError and UnicodeDecodeError are ValueErrors)
    print("NO_RESULTS 0 0 0 0 %d" % len(valid)); sys.exit()
byid = {r.get("id"): r for r in allrows if r.get("id") in valid}      # the graded ids only, one row each; the last row of an id wins
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
  fi
fi
echo "$(date -u) [$(hostname -s)] decision: $verdict (fields: verdict solved rows crashes secs missing; need >= $MIN, 0 crashes, 0 missing, secs <= ${DECIDE_MAX_SECS:-23000})" >> "$LOG"
case "$verdict" in
  PASS*) SUBMIT_TARGET_EPOCH=0 SUBMIT_LOG="$LOG" KAGGLE_BIN="$KAGGLE" exec bash "$HERE/submit_at.sh" "$CAND" 0000 "$MSG" ;;
  *) echo "$(date -u) [$(hostname -s)] SKIPPED: slot left unused ($verdict)" >> "$LOG"; exit 3 ;;
esac
