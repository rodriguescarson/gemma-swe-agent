#!/bin/bash
# sub19 chain (17 Oct 2026, GAPS "v16a pre-registration"): wait for ship.sh (SHIP_PID, SHIP_LOG) -> SHIP OK -> wait for the
# box's END of p4_v16a on origin (its backup hook pushes eval/a6000/results/p4_v16a/ before the END message) -> gate: VALID
# (74 rows, 0 crash rows, scripts/box_p4_gate.py), malformed replies 0 (scripts/forty_two/screen_read.py), mean seconds <= 345
# (12-hour gate), paired net vs p4_pub024 >= -2 -> push the kernel only when no submission is PENDING (rule: nothing runs on
# Kaggle while scoring; scripts/push_after_scoring.sh) -> wait for the kernel run -> submit_at.sh tag sub19: (it waits out a
# PENDING submission itself). Re-run by hand if dead (every step is idempotent):
#   SHIP_PID=<pid> SHIP_LOG=<log> bash eval/arm_sub19_chain.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub19_chain.out
SHIP=${SHIP_LOG:?SHIP_LOG}
: "${SHIP_PID:?SHIP_PID}"
echo "$(date -u) armed: waiting for ship pid $SHIP_PID ($SHIP)" >> "$LOG"
while kill -0 "$SHIP_PID" 2>/dev/null; do sleep 30; done
if ! grep -q "SHIP OK: kernels/g4agent-v16a" "$SHIP"; then echo "$(date -u) ship.sh did not print SHIP OK; chain stops (see $SHIP)" >> "$LOG"; exit 1; fi
echo "$(date -u) SHIP OK; waiting for the box END of p4_v16a (origin polled every 300 s)" >> "$LOG"
while :; do
  git fetch -q origin wip/gemma-agent 2>/dev/null
  if git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null | grep -q "step=p4_v16a | END done: done=74/74"; then break; fi
  sleep 300
done
echo "$(date -u) box END seen for p4_v16a" >> "$LOG"
for _ in 1 2 3; do git pull -q --rebase --autostash origin wip/gemma-agent && break; sleep 10; done
R=eval/a6000/results/p4_v16a/results.jsonl
GATE=$(.venv/bin/python scripts/box_p4_gate.py "$R" 2>&1 | tail -1)
SCREEN=$(.venv/bin/python scripts/forty_two/screen_read.py eval/a6000/results/p4_v16a 2>&1 | head -1)
NET=$(.venv/bin/python - <<'EOF'
import json
def load(p): return {r["id"]: bool(r["resolved"]) for r in (json.loads(l) for l in open(p) if l.strip())}
a = load("eval/a6000/results/p4_v16a/results.jsonl"); b = load("eval/a6000/results/p4_pub024/results.jsonl")
ids = set(a) & set(b); w = sum(a[i] and not b[i] for i in ids); l = sum(b[i] and not a[i] for i in ids)
print(f"net_vs_pub024 {w - l} wins {w} losses {l} n {len(ids)}")
EOF
)
SECS=$(echo "$GATE" | sed -n 's/.* secs \([0-9]*\).*/\1/p'); MEAN=$(( ${SECS:-99999} / 74 ))
MALF=$(echo "$SCREEN" | sed -n 's/.*malformed \([0-9]*\).*/\1/p'); NETV=$(echo "$NET" | awk '{print $2}')
echo "$(date -u) gate: $GATE | $SCREEN | $NET | mean_secs $MEAN" >> "$LOG"
ok=1
echo "$GATE" | grep -q " crash 0 " || ok=0
echo "$GATE" | grep -q " missing 0 " || ok=0
[ "${MALF:-1}" -eq 0 ] || ok=0
[ "$MEAN" -le 345 ] || ok=0
[ "${NETV:--99}" -ge -2 ] || ok=0
if [ "$ok" -ne 1 ]; then echo "$(date -u) p4_v16a fails the sub19 rule (crash/missing/malformed/mean/net); sub19 NOT submitted" >> "$LOG"; exit 1; fi
echo "$(date -u) sub19 rule PASSED; pushing kernels/g4agent-v16a once nothing is PENDING" >> "$LOG"
# one push only (kaggle_push_wait.sh pushes; push_after_scoring.sh would push a second version): wait out a PENDING
# submission here with submit_at.sh's own test, requiring a real listing (header present) before trusting "no PENDING"
while :; do
  s=$(.venv/bin/kaggle competitions submissions -c gemma-4-developer-agent -v 2>&1)
  if echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; then break; fi
  sleep 600
done
echo "$(date -u) nothing PENDING; pushing kernels/g4agent-v16a" >> "$LOG"
KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/kaggle_push_wait.sh g4agent-v16a >> "$LOG" 2>&1 || { echo "$(date -u) kaggle_push_wait failed; chain stops" >> "$LOG"; exit 1; }
MSG="sub19: v16a = pub024 (sub18, the public LB-0.24 bundle) + L1 only: edit_file/write_file removed, edits through a run_command python heredoc that asserts the old block occurs once and compiles (pub024 wasted 56 of 203 edit calls on malformed edit_file args inside its 28-call budget); limits, sampling, prompt otherwise identical; box 74: $GATE; $SCREEN; $NET; expectation 0.22-0.28"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-v16a 0000 "$MSG" "sub19:" >> "$LOG" 2>&1
echo "$(date -u) submit_at.sh exited $?" >> "$LOG"
