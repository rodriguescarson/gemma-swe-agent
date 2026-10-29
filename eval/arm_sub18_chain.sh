#!/bin/bash
# sub18 chain (16 Oct 2026, GAPS "The public LB-0.24 bundle as a control, and the sub18 amendment"): wait for ship.sh
# (SHIP_PID, SHIP_LOG) -> SHIP OK -> kaggle_push_wait.sh g4agent-pub024 (CPU kernel v1 builds submission.zip) -> wait for the
# box's END of p4_pub024 on origin (its backup hook pushes eval/a6000/results/p4_pub024/ before the END message) -> gate VALID
# (74 rows, 0 crash rows, by scripts/box_p4_gate.py) -> submit_at.sh tag sub18:, no target time (submits at once when nothing
# is pending; after 2026-10-17T00:00Z it simply lands on the next slot). Re-run by hand if dead (every step is idempotent):
#   SHIP_PID=<pid> SHIP_LOG=<log> bash eval/arm_sub18_chain.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub18_chain.out
SHIP=${SHIP_LOG:?SHIP_LOG}
: "${SHIP_PID:?SHIP_PID}"
echo "$(date -u) armed: waiting for ship pid $SHIP_PID ($SHIP)" >> "$LOG"
while kill -0 "$SHIP_PID" 2>/dev/null; do sleep 30; done
if ! grep -q "SHIP OK: kernels/g4agent-pub024" "$SHIP"; then echo "$(date -u) ship.sh did not print SHIP OK; chain stops (see $SHIP)" >> "$LOG"; exit 1; fi
echo "$(date -u) SHIP OK; pushing kernels/g4agent-pub024" >> "$LOG"
KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/kaggle_push_wait.sh g4agent-pub024 >> "$LOG" 2>&1 || { echo "$(date -u) kaggle_push_wait failed; chain stops" >> "$LOG"; exit 1; }
echo "$(date -u) kernel COMPLETE; waiting for the box END of p4_pub024 (origin polled every 300 s)" >> "$LOG"
while :; do
  git fetch -q origin wip/gemma-agent 2>/dev/null
  if git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null | grep -q "step=p4_pub024 | END done: done=74/74"; then break; fi
  sleep 300
done
echo "$(date -u) box END seen for p4_pub024" >> "$LOG"
for i in 1 2 3; do git pull -q --rebase --autostash origin wip/gemma-agent && break; sleep 10; done
GATE=$(.venv/bin/python scripts/box_p4_gate.py eval/a6000/results/p4_pub024/results.jsonl 2>&1 | tail -1)
echo "$(date -u) gate: $GATE" >> "$LOG"
if ! { echo "$GATE" | grep -q " crash 0 " && echo "$GATE" | grep -q " missing 0 "; }; then
  echo "$(date -u) p4_pub024 is not VALID (crash or missing rows); sub18 NOT submitted" >> "$LOG"; exit 1
fi
MSG="sub18: pub024 = the public notebook honghanhhh/gemma-4-baseline-lb-0-24, byte-identical (CONTROL; the author's one sample 0.24); lineage matterhorn3838 SuperAgent 0.18 -> flexonafft budget-aware v2 0.22 -> prompt edits; limits 8 min / 28 calls / 240 s / 80 turns, temperature 0.2, thinking 4096; box 74: $GATE; purpose: calibrate the box against a known hidden score and the earliest 0.24 on the board; expectation 0.20-0.26"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-pub024 0000 "$MSG" "sub18:" >> "$LOG" 2>&1
rc=$?
echo "$(date -u) submit_at.sh exited $rc" >> "$LOG"
exit "$rc"   # submit_at's status, not echo's ($? inside the command substitution was date's: always 0)
