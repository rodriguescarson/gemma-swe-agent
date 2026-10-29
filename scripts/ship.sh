#!/usr/bin/env bash
# The only supported path from a bundle to a Kaggle notebook: full test suite first, then build. Refuses on any failure.
# Usage: [ALLOW_ALL_TASKS=1] scripts/ship.sh <bundle_dir> <slug> [eval|submit] [make_eval_kernel args...]
set -euo pipefail
cd "$(dirname "$0")/.."
B=$1; SLUG=$2; MODE=${3:-submit}; shift 3 2>/dev/null || shift $#
find submissions -name "__pycache__" -prune -exec rm -rf {} +
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests || { echo "SHIP REFUSED: tests failed"; exit 1; }
# The Linux gate's own exit status counts, not only the log text: under set -e a bare `| tee` died silently (no refusal line,
# nothing for the log reader to find), and a shared /tmp/linux_test.out let two concurrent ships read each other's result.
LT=$(mktemp "${TMPDIR:-/tmp}/linux_test.XXXXXX")
lt_rc=0; bash scripts/linux_test.sh 2>&1 | tee "$LT" || lt_rc=${PIPESTATUS[0]}
if [ "$lt_rc" -ne 0 ] || ! grep -qE "[0-9]+ passed" "$LT" || grep -qE "[0-9]+ failed" "$LT"; then
  echo "SHIP REFUSED: Linux tests failed (linux_test.sh exit $lt_rc; log $LT)"; exit 1
fi
rm -f "$LT"
if [ "$MODE" = eval ]; then
  EK=$(python3 scripts/make_eval_kernel.py "$B" "$SLUG" "$@") || { ek_rc=$?; echo "$EK"; exit "$ek_rc"; }
  echo "$EK"
  # make_eval_kernel.py without --ids (or with an empty ids file) builds a kernel for EVERY task in tasks.jsonl and says "all tasks":
  # a GPU run of hours that nobody asked for. Refuse it, and take the metadata away so kaggle_push_wait.sh cannot push it anyway.
  if echo "$EK" | grep -q " files all tasks " && [ "${ALLOW_ALL_TASKS:-0}" != 1 ]; then
    rm -f "kernels/$SLUG/kernel-metadata.json"
    echo "SHIP REFUSED: the eval kernel covers ALL tasks (no --ids, or an empty ids file); pass --ids <file>, or set ALLOW_ALL_TASKS=1 if every task is meant"; exit 1
  fi
else python3 scripts/make_kernel.py "$B" "$SLUG"; fi
echo "SHIP OK: kernels/$SLUG"
