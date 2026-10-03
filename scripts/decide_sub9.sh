#!/bin/bash
# Pre-registered slot decision (Carson, 03 Oct 00:58 IST: "lets not waste the round"); fixed test-first on 2026-10-03
# (E3/E4/E5 in docs/PLAN_TO_FINISH.txt, tests/test_decide_sub9.py).
# At DECIDE_AT (IST HHMM), or as soon as the sample has 80 finished tasks, read the v4h2 collection sample and choose:
#   v4h2 (g4agent-v4h2 v1) iff rows >= 80 AND heredoc-as-tool-name crash rows <= 2 AND no other non-timeout crash class
#   else v4 (g4agent-sub3 v1) as the new-scorer control.
# Provider/infra errors (litellm APIError, connection refused, proxy budget) are OpenRouter's, not the bundle's: ignored.
# If the decision lands after 00:01 UTC the slot is already open: submit NOW (SUBMIT_TARGET_EPOCH=0), never "tomorrow".
# The submitted marker is written by this script after submit_at.sh returns 0, not by grepping old log lines.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DECIDE_AT=${DECIDE_AT:-0525}
R=${SAMPLE2_RESULTS:-eval/collect/pallets_v4h2_s2/s1/task_results.jsonl}
SUBMIT_AT_SH=${SUBMIT_AT_SH:-scripts/submit_at.sh}
MARKER=${MARKER:-eval/overnight/sub9_submitted}
export SUBMIT_LOG=${SUBMIT_LOG:-eval/submit_log.txt}
PROGRESS_LOG=${PROGRESS_LOG:-eval/overnight/progress.log}
mkdir -p "$(dirname "$MARKER")" "$(dirname "$SUBMIT_LOG")" "$(dirname "$PROGRESS_LOG")"
utc_hhmm() { echo "${FAKE_UTC_HHMM:-$(date -u +%H%M)}"; }   # FAKE_UTC_HHMM: tests only

until [ "$((10#$(TZ=Asia/Kolkata date +%H%M)))" -ge "$((10#$DECIDE_AT))" ] || [ "$(cat "$R" 2>/dev/null | wc -l | tr -d " ")" -ge 80 ]; do sleep 30; done
verdict=$(python3 - "$R" <<'PY'
import json, sys, os, collections
p = sys.argv[1]
if not os.path.exists(p): print("v4 no-sample"); sys.exit()
rows = [json.loads(l) for l in open(p) if l.strip()]
INFRA = ("apierror", "onnection", "refused", "budget", "timeout", "tool call budget")   # not the bundle's crash classes
def kind(e):
    e = str(e or "")
    if not e: return None
    if "Tool 'python3" in e or "Tool '/tmp/swe" in e: return "heredoc"
    if any(k in e.lower() for k in INFRA): return None
    return e[:50]
PHANTOM = ("apierror", "onnection", "refused", "key limit")   # the task never reached the model: not a row at all
real = [r for r in rows if not any(k in str(r.get("error") or "").lower() for k in PHANTOM)]
kinds = [kind(r.get("error")) for r in real]
heredoc = kinds.count("heredoc")
other = collections.Counter(k for k in kinds if k and k != "heredoc")
ok = len(real) >= 80 and heredoc <= 2 and not other
print(("v4h2" if ok else "v4") + f" rows={len(real)} infra={len(rows) - len(real)} heredoc={heredoc} other={dict(other)}")
PY
)
choice=${verdict%% *}
echo "$(date -u) [$(hostname -s)] decide_sub9: $verdict" | tee -a "$SUBMIT_LOG" >> "$PROGRESS_LOG"
# The decision is designed for ~23:55-00:30 UTC (DECIDE_AT 05:25 IST). Between 00:01 and 12:00 UTC today's slot has
# already opened: fire now (submit_at "0001" would otherwise target tomorrow, the bug of 2026-10-03). From 12:00 UTC
# the next slot is tonight: arm for 00:01.
now=$(utc_hhmm)
if [ "$((10#$now))" -ge 1 ] && [ "$((10#$now))" -lt 1200 ]; then
  export SUBMIT_TARGET_EPOCH=0; echo "$(date -u) [$(hostname -s)] decide_sub9: ${now}Z is past the 0001Z slot; submitting now" >> "$SUBMIT_LOG"
fi
if [ "$choice" = v4h2 ]; then
  KERNEL_VERSION=1 bash "$SUBMIT_AT_SH" g4agent-v4h2 0001 "sub9: v4h2 = v4 + edit helper + explicit run_command call shape (74 public: 0 crashes; Pallets s2: $verdict)"
else
  KERNEL_VERSION=1 bash "$SUBMIT_AT_SH" g4agent-sub3 0001 "sub9: v4 control on the rebuilt scorer (v4 0.12 x2 old scorer; v10.1 0.08 x2)"
fi
st=$?
if [ $st -eq 0 ]; then touch "$MARKER"; echo "$(date -u) [$(hostname -s)] decide_sub9: submit_at returned 0; marker $MARKER" >> "$PROGRESS_LOG"
else echo "$(date -u) [$(hostname -s)] decide_sub9: submit_at FAILED (exit $st); no marker" | tee -a "$SUBMIT_LOG" >> "$PROGRESS_LOG"; fi
exit $st
