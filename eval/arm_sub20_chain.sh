#!/bin/bash
# sub20 chain (17 Oct 2026, GAPS "sub18 ERRORED on runtime"): wait for ship.sh (SHIP_PID, SHIP_LOG) -> SHIP OK -> wait for the
# box's END of p4_pub024_6m on origin, OR a stop/contamination line for it (then give up: a chain's wait must include the run's
# stop line, lesson of 17 Oct) -> gate: VALID (74 rows, 0 crash, scripts/box_p4_gate.py), mean seconds <= 300 (the 12-hour
# gate: 10 h projected for 120 hidden tasks; the 346 s public pace errored), solved >= 28, paired net vs p4_pub024 >= -3 ->
# one kernel push once nothing is PENDING -> wait for the kernel run -> submit_at.sh tag sub20: (it waits out a PENDING
# submission itself). Re-run by hand if dead (every step is idempotent):  SHIP_PID=<pid> SHIP_LOG=<log> bash eval/arm_sub20_chain.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub20_chain.out
SHIP=${SHIP_LOG:?SHIP_LOG}
: "${SHIP_PID:?SHIP_PID}"
echo "$(date -u) armed: waiting for ship pid $SHIP_PID ($SHIP)" >> "$LOG"
while kill -0 "$SHIP_PID" 2>/dev/null; do sleep 30; done
if ! grep -q "SHIP OK: kernels/g4agent-pub024-6m" "$SHIP"; then echo "$(date -u) ship.sh did not print SHIP OK; chain stops (see $SHIP)" >> "$LOG"; exit 1; fi
echo "$(date -u) SHIP OK; waiting for the box END (or stop) of p4_pub024_6m (origin polled every 300 s)" >> "$LOG"
while :; do
  git fetch -q origin wip/gemma-agent 2>/dev/null
  box=$(git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null)
  if echo "$box" | grep -q "step=p4_pub024_6m | END done: done=74/74"; then break; fi
  if echo "$box" | grep -qE "p4_pub024_6m.*(STOPPED|CONTAMINATED|hard stop reached|END failed)"; then
    echo "$(date -u) the box reports p4_pub024_6m stopped or failed; sub20 NOT submitted" >> "$LOG"; exit 1
  fi
  sleep 300
done
echo "$(date -u) box END seen for p4_pub024_6m" >> "$LOG"
for _ in 1 2 3; do git pull -q --rebase --autostash origin wip/gemma-agent && break; sleep 10; done
R=eval/a6000/results/p4_pub024_6m/results.jsonl
GATE=$(.venv/bin/python scripts/box_p4_gate.py "$R" 2>&1 | tail -1)
STATS=$(.venv/bin/python - <<'EOF'
import json
def load(p): return {r["id"]: r for r in (json.loads(l) for l in open(p) if l.strip())}
a = load("eval/a6000/results/p4_pub024_6m/results.jsonl"); b = load("eval/a6000/results/p4_pub024/results.jsonl")
ids = set(a) & set(b)
w = sum(bool(a[i]["resolved"]) and not b[i]["resolved"] for i in ids); l = sum(bool(b[i]["resolved"]) and not a[i]["resolved"] for i in ids)
solved = sum(bool(r["resolved"]) for r in a.values()); mean = sum(r["secs"] for r in a.values()) / max(1, len(a))
print(f"solved {solved} mean_secs {mean:.0f} net_vs_pub024 {w - l} wins {w} losses {l} n {len(ids)}")
EOF
)
echo "$(date -u) gate: $GATE | $STATS" >> "$LOG"
SOLVED=$(echo "$STATS" | awk '{print $2}'); MEAN=$(echo "$STATS" | awk '{print $4}'); NETV=$(echo "$STATS" | awk '{print $6}')
ok=1
echo "$GATE" | grep -q " crash 0 " || ok=0
echo "$GATE" | grep -q " missing 0 " || ok=0
[ "${MEAN:-9999}" -le 300 ] || ok=0
[ "${SOLVED:-0}" -ge 28 ] || ok=0
[ "${NETV:--99}" -ge -3 ] || ok=0
if [ "$ok" -ne 1 ]; then echo "$(date -u) p4_pub024_6m fails the sub20 rule (crash/missing/mean>300/solved<28/net<-3); sub20 NOT submitted" >> "$LOG"; exit 1; fi
echo "$(date -u) sub20 rule PASSED; pushing kernels/g4agent-pub024-6m once nothing is PENDING" >> "$LOG"
while :; do
  s=$(.venv/bin/kaggle competitions submissions -c gemma-4-developer-agent -v 2>&1)
  if echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; then break; fi
  sleep 600
done
echo "$(date -u) nothing PENDING; pushing kernels/g4agent-pub024-6m" >> "$LOG"
KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/kaggle_push_wait.sh g4agent-pub024-6m >> "$LOG" 2>&1 || { echo "$(date -u) kaggle_push_wait failed; chain stops" >> "$LOG"; exit 1; }
MSG="sub20: pub024_6m = the public LB-0.24 bundle (sub18 of it ERRORED on the 12-h runtime; the author's run scored) with max_time_minutes 8 -> 6 and the prompt's budget sentence saying 6 minutes, nothing else (28 calls, 240 s, 80 turns, temp 0.2, thinking 4096 unchanged); box 74: $GATE; $STATS; 12-h gate: mean <= 300 s = 10 h projected; expectation 0.18-0.24"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-pub024-6m 0000 "$MSG" "sub20:" >> "$LOG" 2>&1
rc=$?
echo "$(date -u) submit_at.sh exited $rc" >> "$LOG"
exit "$rc"   # submit_at's status, not echo's
