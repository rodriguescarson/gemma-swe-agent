#!/bin/bash
# sub20 + sub21 driver (18 Oct 2026, GAPS "sub19 also RUNTIME; ... sub20 = v12b; v16 pre-registration"). Sequential:
#  1. ship.sh submissions/v12b g4agent-v12b -> SHIP OK -> one kernel push (nothing PENDING now) -> submit tag sub20: at once.
#  2. ship.sh submissions/v16 g4agent-v16 (suites + kernel build only).
#  3. wait for the box END of p4_v16 on origin, or a stop line (then stand down) -> gate: VALID (74 rows, 0 crash), solved >= 26,
#     paired net vs p4_v12 >= -3 -> wait until nothing is PENDING (sub20 scoring) -> one kernel push -> submit tag sub21:.
# Every step is idempotent (ship rebuilds; submit_at skips a tag already on Kaggle). Re-run by hand: bash eval/arm_sub20_sub21.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub20_sub21.out; SP=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad
K=$PWD/.venv/bin/kaggle
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
push_version() {   # push once, wait for COMPLETE, print the pushed version number
  local slug=$1 out; out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh "$slug" 2>&1); echo "$out" >> "$LOG"
  echo "$out" | grep -q "COMPLETE\|output already present" || return 1
  echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1
}
# ---- 1. sub20 = v12b
say "ship v12b"
bash scripts/ship.sh submissions/v12b g4agent-v12b submit > "$SP/ship_v12b.log" 2>&1
grep -q "SHIP OK: kernels/g4agent-v12b" "$SP/ship_v12b.log" || { say "v12b ship FAILED (see $SP/ship_v12b.log); stop"; exit 1; }
until nothing_pending; do say "waiting: a submission is PENDING"; sleep 600; done
V=$(push_version g4agent-v12b) || { say "v12b kernel push/run failed; stop"; exit 1; }
say "v12b kernel version ${V:-1} COMPLETE; submitting sub20"
MSG="sub20: v12b = v12 (hidden 0.15) + pub024 sampling only (temperature 0.2, top_p 0.95, no top_k, no seed); 5-min cap (worst case 120 x 5 min = 10 h; both 8-min pub024 draws errored on runtime); box 74: 28/74 (v12 27), net +1, mean 247 s, 0 crash/errored; expectation 0.13-0.17"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh g4agent-v12b 0000 "$MSG" "sub20:" >> "$LOG" 2>&1
rc=$?; RC=$rc
say "sub20 submit_at exited $rc"
# ---- 2. package v16
say "ship v16"
bash scripts/ship.sh submissions/v16 g4agent-v16 submit > "$SP/ship_v16.log" 2>&1
grep -q "SHIP OK: kernels/g4agent-v16" "$SP/ship_v16.log" || { say "v16 ship FAILED (see $SP/ship_v16.log); stop"; exit 1; }
say "v16 SHIP OK; waiting for the box END (or stop) of p4_v16"
# ---- 3. sub21 = v16, gated on the box read
while :; do
  git fetch -q origin wip/gemma-agent 2>/dev/null
  box=$(git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null)
  echo "$box" | grep -q "step=p4_v16 | END done: done=74/74" && break
  if echo "$box" | grep -qE "p4_v16 (STOPPED|CONTAMINATED)|step=p4_v16 \| END failed"; then say "box reports p4_v16 stopped/failed; sub21 NOT submitted"; exit 1; fi
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
V=$(push_version g4agent-v16) || { say "v16 kernel push/run failed; stop"; exit 1; }
MSG="sub21: v16 = v12 (hidden 0.15) + the public LB-0.24 lineage's prompt restated to v12's limits (40 calls, 5 min), nothing else; worst case 10 h; box 74: $GATE; $STATS; expectation 0.14-0.20"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh g4agent-v16 0000 "$MSG" "sub21:" >> "$LOG" 2>&1
rc=$?; [ "$RC" -ne 0 ] || RC=$rc
say "sub21 submit_at exited $rc"
exit "$RC"   # the first non-zero submit_at status, else 0 (a chain that gave up used to exit 0)
