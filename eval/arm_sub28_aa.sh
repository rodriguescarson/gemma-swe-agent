#!/bin/bash
# sub28 = v12b byte-identical, a hidden repeat (GAPS 'Owner decisions; sub28 pre-registration', 30 Oct). Submits Kaggle kernel
# g4agent-v12b version 1 (the sub20 zip; nothing rebuilt) with tag sub28:. It submits to Kaggle, so it refuses unless the owner
# approved this submission. submit_at.sh waits out a PENDING submission and skips if a sub28: submission already exists.
#   CARSON_APPROVED_SUB28=yes bash eval/arm_sub28_aa.sh
[ "${CARSON_APPROVED_SUB28:-}" = yes ] || { echo "sub28 not approved: Carson approves each Kaggle submission (CARSON_APPROVED_SUB28=yes)" >&2; exit 2; }
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub28_aa.out
say() { echo "$(date -u) $*" >> "$LOG"; }
grep -q "^### Owner decisions; sub28 pre-registration" docs/GAPS_2026-10-06.md || { say "GAPS has no sub28 pre-registration; stop"; exit 1; }
MSG="sub28: v12b again, byte-identical to sub20 (Kaggle kernel g4agent-v12b v1, no seed): a hidden repeat so final pick 1 is chosen on a mean; v12 line reads 0.10-0.17, mean 0.13; expectation 0.12-0.17"
say "submitting g4agent-v12b v1 as sub28 when nothing is PENDING"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-v12b 0000 "$MSG" "sub28:" >> "$LOG" 2>&1
rc=$?
say "sub28 (v12b repeat) submit_at exited $rc"
exit "$rc"   # submit_at's status, not say's
