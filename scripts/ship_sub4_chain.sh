#!/bin/bash
# Wait for ship.sh (tests) to produce kernels/g4agent-sub4, then push it to Kaggle so the VPS can submit it at 00:01 UTC.
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/submit_log.txt; OUT=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/tasks/bq60wh1v8.output
source /Users/carson/Projects/kaggriculture/.venv/bin/activate
until grep -qE "SHIP OK|SHIP REFUSED" "$OUT" 2>/dev/null; do sleep 30; done
if grep -q "SHIP OK" "$OUT"; then kaggle kernels push -p kernels/g4agent-sub4 >> $LOG 2>&1; echo "$(date -u) sub4 kernel pushed" >> $LOG
else echo "$(date -u) sub4 SHIP REFUSED, not pushed (VPS will fail to find sub4; sub3 config stays)" >> $LOG; fi
