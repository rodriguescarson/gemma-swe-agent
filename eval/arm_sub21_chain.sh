#!/bin/bash
# sub21 chain (19 Oct 2026). eval/arm_sub20_sub21.sh stood down at 17:44Z on a STALE stop line: it grepped the whole channel
# file and matched B-191 ("p4_v16 STOPPED: probe rule FAILED"), written before the relaunch (B-192/B-193) that is now running.
# Lesson (same family as 17 Oct): a chain must read only the box's messages AFTER the launch it waits on. SINCE names that
# message; only text after it counts, for the END line and for stop lines alike.
# Rule unchanged (GAPS 'v16 pre-registration'): VALID (74 rows, 0 crash), solved >= 26, paired net vs p4_v12 >= -3 -> wait until
# nothing is PENDING (sub20) -> one push of kernels/g4agent-v16 (built and SHIP OK at 17:44Z) -> submit tag sub21:.
#   SINCE="### B-193" bash eval/arm_sub21_chain.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub21_chain.out
SINCE=${SINCE:?SINCE}
K=$PWD/.venv/bin/kaggle
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
after_since() { git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null | awk -v s="$SINCE" 'index($0, s) == 1 {f = 1} f'; }
grep -q "SHIP OK: kernels/g4agent-v16" /private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/ship_v16.log || { say "no SHIP OK for v16; stop"; exit 1; }
say "armed: waiting for the box END of p4_v16 in messages from '$SINCE' on"
while :; do
  git fetch -q origin wip/gemma-agent 2>/dev/null
  box=$(after_since)
  [ -n "$box" ] || { say "marker '$SINCE' not found on origin; waiting"; sleep 300; continue; }
  echo "$box" | grep -q "step=p4_v16 | END done: done=74/74" && break
  if echo "$box" | grep -qE "p4_v16 (STOPPED|CONTAMINATED)|step=p4_v16 \| END failed"; then say "box reports p4_v16 stopped/failed after '$SINCE'; sub21 NOT submitted"; exit 1; fi
  sleep 300
done
for _ in 1 2 3; do git pull -q --rebase --autostash origin wip/gemma-agent && break; sleep 10; done
GATE=$(.venv/bin/python scripts/box_p4_gate.py eval/a6000/results/p4_v16/results.jsonl 2>&1 | tail -1)
STATS=$(.venv/bin/python - <<'EOF'
import json
def load(p): return {r["id"]: r for r in (json.loads(l) for l in open(p) if l.strip())}
a = load("eval/a6000/results/p4_v16/results.jsonl"); b = load("eval/a6000/results/p4_v12/results.jsonl"); ids = set(a) & set(b)
w = sum(bool(a[i]["resolved"]) and not b[i]["resolved"] for i in ids); l = sum(bool(b[i]["resolved"]) and not a[i]["resolved"] for i in ids)
print(f"solved {sum(bool(r['resolved']) for r in a.values())} mean_secs {sum(r['secs'] for r in a.values())/max(1,len(a)):.0f} net_vs_v12 {w-l} wins {w} losses {l} n {len(ids)}")
EOF
)
say "p4_v16 gate: $GATE | $STATS"
SOLVED=$(echo "$STATS" | awk '{print $2}'); NETV=$(echo "$STATS" | awk '{print $6}')
ok=1; echo "$GATE" | grep -q " crash 0 " || ok=0; echo "$GATE" | grep -q " missing 0 " || ok=0
[ "${SOLVED:-0}" -ge 26 ] || ok=0; [ "${NETV:--99}" -ge -3 ] || ok=0
[ "$ok" -eq 1 ] || { say "p4_v16 fails the sub21 rule (crash/missing/solved<26/net<-3); sub21 NOT submitted"; exit 1; }
until nothing_pending; do say "sub21 rule PASSED; waiting: a submission is PENDING"; sleep 600; done
out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh g4agent-v16 2>&1); echo "$out" >> "$LOG"
echo "$out" | grep -q "COMPLETE\|output already present" || { say "v16 kernel push/run failed; stop"; exit 1; }
V=$(echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1)
MSG="sub21: v16 = v12 (hidden 0.15) + the public LB-0.24 lineage's prompt restated to v12's limits (40 calls, 5 min), nothing else; worst case 10 h; box 74: $GATE; $STATS; expectation 0.14-0.20"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh g4agent-v16 0000 "$MSG" "sub21:" >> "$LOG" 2>&1
say "sub21 submit_at exited $?"
