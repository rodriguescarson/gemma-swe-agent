#!/usr/bin/env bash
# Stitch every collection pass (all samples, success-only, per-pass verdicts) into data/v11/rows_stitched.jsonl and
# validate it against the eval sets and the 10,000-row floor. Idempotent; run after coverage.sh / resample.sh.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
LOG=eval/collect/coverage.log
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] $*" | tee -a "$LOG"; }
PAIRS=$(.venv/bin/python scripts/collect/pairs.py)
step "stitch: $(echo "$PAIRS" | grep -o -- '--pair' | wc -l | tr -d ' ') pairs"
# shellcheck disable=SC2086
.venv/bin/python train/build_sft.py $PAIRS --tasks data/pallets/harness_train/tasks.jsonl --out data/v11/rows_stitched.jsonl \
  --exclude-ids data/pallets/dev40_ids.txt --exclude-ids data/pallets/holdout_ids.txt > eval/collect/stitch.out 2>&1
.venv/bin/python train/validate_rows.py data/v11/rows_stitched.jsonl --exclude-ids data/pallets/dev40_ids.txt --exclude-ids data/pallets/holdout_ids.txt \
  --min-rows 10000 --report eval/collect/rows_stitched_report.json > eval/collect/validate_stitched.out 2>&1
st=$?
summary=$(python3 - <<'PY' 2>/dev/null
import json
r = json.load(open("eval/collect/rows_stitched_report.json"))
print(" ".join(f"{k}={r.get(k)}" for k in ("rows", "tasks", "rows_per_task", "continuation_rows", "problems")), "first:", r.get("first_problems", [])[:2])
PY
)
step "stitched: validate exit $st; $summary"
exit $st
