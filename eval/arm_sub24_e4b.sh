#!/bin/bash
# sub24 driver (23 Oct 2026, GAPS "v12b_e4b pre-registration"): the Small Model Development bonus candidate, v12b with the
# model 31B -> E4B and nothing else. PREPARED, NOT RUN: it submits to Kaggle, so it refuses unless the owner has approved
# this submission (CARSON_APPROVED_SUB24=yes) and the branch feat/v12b-e4b is merged into the checkout it runs in.
#  1. ship.sh submissions/v12b_e4b -> g4agent-v12b-e4b (full Mac suite + Linux gate + kernel build).
#  2. Wait until nothing is PENDING, push the kernel once (a CPU kernel that zips the bundle), submit that version with tag
#     sub24:. No box gate: the A6000 box is closed and no 4xL4 read of E4B exists, so the hidden read is the first read.
# Every step is idempotent (ship rebuilds; submit_at skips a tag already on Kaggle).
# Run by hand, after the owner's yes: CARSON_APPROVED_SUB24=yes bash eval/arm_sub24_e4b.sh
[ "${CARSON_APPROVED_SUB24:-}" = yes ] || { echo "sub24 not approved: Carson approves each Kaggle submission (CARSON_APPROVED_SUB24=yes)" >&2; exit 2; }
cd /Users/carson/Projects/gemma-swe-agent || exit 1
B=v12b_e4b; SLUG=g4agent-v12b-e4b; TAG="sub24:"
LOG=eval/arm_sub24_e4b.out; SP=${SP:-${TMPDIR:-/tmp}}
K=$PWD/.venv/bin/kaggle
say() { echo "$(date -u) $*" >> "$LOG"; }
nothing_pending() { local s; s=$("$K" competitions submissions -c gemma-4-developer-agent -v 2>&1); echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -qiE ',(SubmissionStatus\.)?PENDING(,|$)'; }
push_version() {   # push once, wait for COMPLETE, print the pushed version number
  local slug=$1 out; out=$(KAGGLE_BIN=$K bash scripts/kaggle_push_wait.sh "$slug" 2>&1); echo "$out" >> "$LOG"
  echo "$out" | grep -q "COMPLETE\|output already present" || return 1
  echo "$out" | sed -n 's/.*Kernel version \([0-9]*\) successfully pushed.*/\1/p' | tail -1
}
# ---- 0. the pre-registration and the pinned bundle must be in this checkout (merge feat/v12b-e4b first)
[ -f "submissions/$B/agent.yaml" ] && [ -f tests/test_v12b_e4b_bundle.py ] || { say "submissions/$B or its test missing: merge feat/v12b-e4b; stop"; exit 1; }
grep -q "^### v12b_e4b pre-registration" docs/GAPS_2026-10-06.md || { say "GAPS has no v12b_e4b pre-registration; stop"; exit 1; }
# ---- 1. package
say "ship $B"
bash scripts/ship.sh "submissions/$B" "$SLUG" submit > "$SP/ship_$B.log" 2>&1
grep -q "SHIP OK: kernels/$SLUG" "$SP/ship_$B.log" || { say "$B ship FAILED (see $SP/ship_$B.log); stop"; exit 1; }
say "$B SHIP OK"
# ---- 2. submit on the first free slot
until nothing_pending; do say "$B shipped; waiting: a submission is PENDING"; sleep 600; done
V=$(push_version "$SLUG") || { say "$B kernel push/run failed; stop"; exit 1; }
MSG="$TAG v12b_e4b = v12b (hidden 0.17) with the model 31B -> gemma-4-e4b-it-qat-w4a16-ct, nothing else (prompt, sampling, thinking 4096, 5-min cap unchanged); Small Model bonus entry, counts only as a selected final; no local read (box closed); small-model top 0.06 on 21 Oct; expectation 0.03-0.09"
KERNEL_VERSION=${V:-1} SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$K bash scripts/submit_at.sh "$SLUG" 0000 "$MSG" "$TAG" >> "$LOG" 2>&1
rc=$?
say "$TAG ($B) submit_at exited $rc"
say "chain done"
exit "$rc"   # submit_at's status: 0 only when the tag is on Kaggle (a chain that gave up used to exit 0)
