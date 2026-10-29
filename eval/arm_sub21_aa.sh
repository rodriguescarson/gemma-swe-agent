#!/bin/bash
# sub21 = v12 byte-identical, a hidden A/A (GAPS 'v16 result; sub21 = v12 again as a hidden A/A', 19 Oct). Waits for the v16 chain
# (OLD_PID) to stand down, then submits Kaggle kernel g4agent-v12 version 1 (the sub14 zip; nothing rebuilt) with tag sub21:.
# submit_at.sh waits out a PENDING submission (sub20) and skips if a sub21: submission already exists.
#   OLD_PID=<pid> bash eval/arm_sub21_aa.sh
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub21_aa.out
say() { echo "$(date -u) $*" >> "$LOG"; }
say "armed: waiting for the v16 chain ${OLD_PID:-none} to exit"
while [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; do sleep 30; done
if grep -q "sub21 submit_at exited 0$" eval/arm_sub21_chain.out 2>/dev/null; then say "the v16 chain submitted sub21 itself; A/A not used"; exit 0; fi
say "v16 chain gone without submitting ($(tail -1 eval/arm_sub21_chain.out | cut -c1-160)); submitting v12 again as sub21 when nothing is PENDING"
MSG="sub21: v12 again, byte-identical to sub14 (Kaggle kernel g4agent-v12 v1): a hidden A/A, so every single-draw hidden comparison (v12 0.15, v13 0.13, b1024 0.10, v0-think 0.10) gets a measured noise floor; v16 (the public prompt at 5 min) failed its box rule at 22/74; expectation 0.12-0.17"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-v12 0000 "$MSG" "sub21:" >> "$LOG" 2>&1
rc=$?
say "sub21 (v12 A/A) submit_at exited $rc"
exit "$rc"   # submit_at's status, not say's
