#!/bin/bash
# Push a Kaggle kernel only when no competition submission is PENDING (rule: nothing runs on Kaggle while scoring).
# Usage: push_after_scoring.sh <kernel_dir>
KDIR=$1; LOG=/Users/carson/Projects/gemma-swe-agent/eval/submit_log.txt
source /Users/carson/Projects/kaggriculture/.venv/bin/activate
echo "$(date -u) waiting for scoring to finish before pushing $KDIR" >> $LOG
while true; do
  s=$(kaggle competitions submissions gemma-4-developer-agent -v 2>&1)
  if echo "$s" | grep -q "ref,fileName" && ! echo "$s" | grep -q "PENDING"; then break; fi
  sleep 600
done
echo "$(date -u) scoring done: $(echo "$s" | sed -n 2p | cut -c1-160)" >> $LOG
kaggle kernels push -p "$KDIR" >> $LOG 2>&1
echo "$(date -u) pushed $KDIR" >> $LOG
