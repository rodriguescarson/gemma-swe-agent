#!/bin/bash
# sub22 + sub23 driver (19 Oct 2026, GAPS "v12b6 and v15b pre-registration; a mean-based runtime gate by the owner's decision").
#  1. ship.sh both bundles (full Mac suite + Linux gate + kernel build): submissions/v12b6 -> g4agent-v12b6, submissions/v15b ->
#     g4agent-v15b.
#  2. For each candidate in order (v12b6, then v15b): wait for the box END of p4_<tag> on origin (or a stop line: skip it), pull,
#     gate it (crash 0, missing 0, solved >= 26, net >= -3 vs p4_v12b; v12b6 also mean seconds <= 280), wait until nothing is
#     PENDING, push its kernel once, submit with the next free tag (sub22:, then sub23:). A candidate that fails its gate is
#     skipped and the next one takes the slot.
# Every step is idempotent (ship rebuilds; submit_at skips a tag already on Kaggle). Re-run by hand: bash eval/arm_sub22_sub23.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub22_sub23.out; SP=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad
K=$PWD/.venv/bin/kaggle
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
push_version() {   # push once, wait for COMPLETE, print the pushed version number
  local slug=$1 out; out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh "$slug" 2>&1); echo "$out" >> "$LOG"
  echo "$out" | grep -q "COMPLETE\|output already present" || return 1
  echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1
}
# ---- 1. package both
BUNDLES=${BUNDLES:-v12b6 v15b}   # 20 Oct: BUNDLES=v15b ships only v15b (v12b6 failed its pre-registered mean gate)
for b in $BUNDLES; do
  say "ship $b"
  bash scripts/ship.sh "submissions/$b" "g4agent-$b" submit > "$SP/ship_$b.log" 2>&1
  grep -q "SHIP OK: kernels/g4agent-$b" "$SP/ship_$b.log" || { say "$b ship FAILED (see $SP/ship_$b.log); stop"; exit 1; }
  say "$b SHIP OK"
done
# ---- 2. gate and submit in order
NEXT=22
for b in $BUNDLES; do
  say "waiting for the box END (or stop) of p4_$b"
  while :; do
    git fetch -q origin wip/gemma-agent 2>/dev/null
    box=$(git show origin/wip/gemma-agent:docs/a6000/channel/box_to_mac.md 2>/dev/null)
    echo "$box" | grep -q "step=p4_$b | END done: done=74/74" && break
    if echo "$box" | grep -qE "p4_$b (STOPPED|CONTAMINATED)|step=p4_$b \| END failed"; then say "box reports p4_$b stopped/failed; $b skipped"; continue 2; fi
    sleep 300
  done
  for _ in 1 2 3; do git pull -q --rebase --autostash origin wip/gemma-agent && break; sleep 10; done
  GATE=$(.venv/bin/python scripts/box_p4_gate.py "eval/a6000/results/p4_$b/results.jsonl" 2>&1 | tail -1)
  STATS=$(B=$b .venv/bin/python - <<'EOF'
import json, os
def load(p): return {r["id"]: r for r in (json.loads(l) for l in open(p) if l.strip())}
a = load(f"eval/a6000/results/p4_{os.environ['B']}/results.jsonl"); b = load("eval/a6000/results/p4_v12b/results.jsonl"); ids = set(a) & set(b)
w = sum(bool(a[i]["resolved"]) and not b[i]["resolved"] for i in ids); l = sum(bool(b[i]["resolved"]) and not a[i]["resolved"] for i in ids)
late = sum(bool(r["resolved"]) and r["secs"] > 300 for r in a.values())
print(f"solved {sum(bool(r['resolved']) for r in a.values())} mean_secs {sum(r['secs'] for r in a.values())/max(1,len(a)):.2f} net_vs_v12b {w-l} wins {w} losses {l} n {len(ids)} solves_after_300s {late}")
EOF
)
  say "p4_$b gate: $GATE | $STATS"
  SOLVED=$(echo "$STATS" | awk '{print $2}'); MEAN=$(echo "$STATS" | awk '{print $4}'); NETV=$(echo "$STATS" | awk '{print $6}')
  ok=1; echo "$GATE" | grep -q " crash 0 " || ok=0; echo "$GATE" | grep -q " missing 0 " || ok=0
  [ "${SOLVED:-0}" -ge 26 ] || ok=0; [ "${NETV:--99}" -ge -3 ] || ok=0
  # the written rule is mean <= 280 s, compared unrounded (20 Oct: the integer comparison would have passed 280.29)
  if [ "$b" = v12b6 ] && awk -v m="${MEAN:-999}" 'BEGIN { exit !(m > 280) }'; then ok=0; fi
  [ "$ok" -eq 1 ] || { say "p4_$b fails its rule (crash/missing/solved<26/net<-3/mean>280 for v12b6); $b skipped"; continue; }
  TAG="sub$NEXT:"
  until nothing_pending; do say "$b rule PASSED; waiting: a submission is PENDING"; sleep 600; done
  V=$(push_version "g4agent-$b") || { say "$b kernel push/run failed; stop"; exit 1; }
  if [ "$b" = v12b6 ]; then
    MSG="$TAG v12b6 = v12b (hidden 0.17) with a 6-minute cap, nothing else (prompt still paces for 5 min); mean-based runtime gate (owner's call): box mean <= 280 s; box 74: $GATE; $STATS; expectation 0.15-0.21"
  else
    MSG="$TAG v15b = v12b (hidden 0.17) + L1 (heredoc edits, edit_file/write_file dropped) + L2 (60 s per command); 5-min cap; box 74: $GATE; $STATS; expectation 0.14-0.20"
  fi
  KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh "g4agent-$b" 0000 "$MSG" "$TAG" >> "$LOG" 2>&1
  say "$TAG ($b) submit_at exited $?"
  NEXT=$((NEXT + 1))
done
say "chain done"
