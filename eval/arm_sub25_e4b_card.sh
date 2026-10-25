#!/bin/bash
# sub25 driver (24 Oct 2026, GAPS "sub25 pre-registration"): the Small Model bonus line, v12b_e4b (0.06) with the E4B card sampling (temperature 1.0, top_k 64) and nothing else;
# PREPARED, NOT RUN: it submits to Kaggle, so it refuses unless the owner has approved
# this submission (CARSON_APPROVED_SUB25=yes).
#  1. ship.sh submissions/v12b_e4b_card -> g4agent-v12b-e4b-card (full Mac suite + Linux gate + kernel build).
#  2. Wait until nothing is PENDING, push the kernel once (a CPU kernel that zips the bundle), submit that version with tag
#     sub25:. No box gate (no 4xL4 read of E4B exists); the hidden read is the only read.
# Every step is idempotent (ship rebuilds; submit_at skips a tag already on Kaggle).
# Run by hand, after the owner's yes: CARSON_APPROVED_SUB25=yes bash eval/arm_sub25_e4b_card.sh
[ "${CARSON_APPROVED_SUB25:-}" = yes ] || { echo "sub25 not approved: Carson approves each Kaggle submission (CARSON_APPROVED_SUB25=yes)" >&2; exit 2; }
cd /Users/carson/Projects/gemma-swe-agent || exit 1
B=v12b_e4b_card; SLUG=g4agent-v12b-e4b-card; TAG="sub25:"
LOG=eval/arm_sub25_e4b_card.out; SP=${SP:-${TMPDIR:-/tmp}}
K=$PWD/.venv/bin/kaggle
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
push_version() {   # push once, wait for COMPLETE, print the pushed version number
  local slug=$1 out; out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh "$slug" 2>&1); echo "$out" >> "$LOG"
  echo "$out" | grep -q "COMPLETE\|output already present" || return 1
  echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1
}
# ---- 0. the pre-registration and the pinned bundle must be in this checkout (merge feat/v12b-e4b first)
[ -f "submissions/$B/agent.yaml" ] && [ -f tests/test_v12b_e4b_card_bundle.py ] || { say "submissions/$B or its test missing: missing; stop"; exit 1; }
grep -q "^### sub25 pre-registration" docs/GAPS_2026-10-06.md || { say "GAPS has no sub25 pre-registration; stop"; exit 1; }
# ---- 1. package
say "ship $B"
bash scripts/ship.sh "submissions/$B" "$SLUG" submit > "$SP/ship_$B.log" 2>&1
grep -q "SHIP OK: kernels/$SLUG" "$SP/ship_$B.log" || { say "$B ship FAILED (see $SP/ship_$B.log); stop"; exit 1; }
say "$B SHIP OK"
# ---- 2. submit on the first free slot
until nothing_pending; do say "$B shipped; waiting: a submission is PENDING"; sleep 600; done
V=$(push_version "$SLUG") || { say "$B kernel push/run failed; stop"; exit 1; }
MSG="$TAG v12b_e4b_card = v12b_e4b (sub24, 0.06) with the E4B model card sampling (temperature 1.0, top_k 64, top_p 0.95) and nothing else; small-model board top 0.08, cluster at 0.06 (22 Oct); expectation 0.04-0.10"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh "$SLUG" 0000 "$MSG" "$TAG" >> "$LOG" 2>&1
say "$TAG ($B) submit_at exited $?"
say "chain done"
