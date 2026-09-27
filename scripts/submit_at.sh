#!/bin/bash
# Timed Kaggle submitter. Runs on the Mac or the VPS.
# Usage: submit_at.sh <kernel-slug> <HHMM UTC> <message> [tag]
# Idempotent across machines: before submitting it asks Kaggle whether a
# submission whose description starts with <tag> already exists.
KERNEL=$1; AT=$2; MSG=$3; TAG=${4:-${MSG%%:*}:}
HERE=$(cd "$(dirname "$0")/.." && pwd)
LOG=${SUBMIT_LOG:-$HERE/eval/submit_log.txt}
KAGGLE=${KAGGLE_BIN:-kaggle}
COMP=gemma-4-developer-agent
mkdir -p "$(dirname "$LOG")"
already() { "$KAGGLE" competitions submissions $COMP -v 2>/dev/null | grep -q ",\"\\?$TAG"; }
echo "$(date -u) [$(hostname -s)] armed $KERNEL for $AT UTC (tag $TAG)" >> "$LOG"
# wait until AT; a sleeping machine that wakes late still fires (same UTC day)
until [ "$(date -u +%H%M)" -ge "$AT" ] 2>/dev/null; do sleep 20; done
for i in 1 2 3; do
  if already; then echo "$(date -u) [$(hostname -s)] $TAG already on Kaggle, skipping" >> "$LOG"; break; fi
  out=$("$KAGGLE" competitions submit $COMP -k "carsonrodrigues/$KERNEL" -v 1 -f submission.zip -m "$MSG" 2>&1 | tr "\n" " ")
  echo "$(date -u) [$(hostname -s)] attempt $i: $out" >> "$LOG"
  echo "$out" | grep -qi "success" && break
  sleep 60
done
"$KAGGLE" competitions submissions $COMP -v 2>&1 | head -2 >> "$LOG"
