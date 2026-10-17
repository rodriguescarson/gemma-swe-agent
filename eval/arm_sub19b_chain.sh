#!/bin/bash
# sub19 fallback (17 Oct 2026, GAPS "sub19 fallback pre-registration"): when the v16a chain (eval/arm_sub19_chain.sh) ends
# WITHOUT submitting (its gate fails), submit the pub024 kernel again (g4agent-pub024 v1, already on Kaggle, byte-identical to
# sub18) as sub19 = a hidden A/A read of the 0.24 bundle. submit_at.sh waits out a PENDING submission itself and is idempotent
# by tag. Skips itself if the v16a chain took the slot. Kill this process to veto before sub18 scores (~20:00 IST 17 Oct).
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/arm_sub19b_chain.out; L19=eval/arm_sub19_chain.out
echo "$(date -u) armed: waiting for the v16a chain to finish ($L19)" >> "$LOG"
until grep -q "submit_at.sh exited\|NOT submitted\|chain stops" "$L19" 2>/dev/null; do sleep 300; done
if grep -q "sub19 rule PASSED" "$L19"; then echo "$(date -u) the v16a chain took the slot (rule PASSED); fallback not used" >> "$LOG"; exit 0; fi
G=$(grep "gate:" "$L19" | tail -1 | cut -c1-320)
echo "$(date -u) v16a not submitted; fallback = pub024 again (hidden A/A). v16a gate line: $G" >> "$LOG"
MSG="sub19: pub024 again, byte-identical to sub18 (hidden A/A: the same bundle twice measures the hidden noise floor under the 0.10/0.13/0.15/0.24 comparisons; the v16a candidate failed its pre-registered 12-h gate on the box: $G); expectation 0.20-0.28"
KERNEL_VERSION=1 SUBMIT_TARGET_EPOCH=0 PENDING_DEADLINE_EPOCH=0 KAGGLE_BIN=$PWD/.venv/bin/kaggle bash scripts/submit_at.sh g4agent-pub024 0000 "$MSG" "sub19:" >> "$LOG" 2>&1
echo "$(date -u) submit_at.sh exited $?" >> "$LOG"
