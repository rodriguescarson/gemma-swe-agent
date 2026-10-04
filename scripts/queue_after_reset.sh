#!/usr/bin/env bash
# Push the given L4 kernels one after another, each through kaggle_push_retry.sh (waits out the 2-session cap and the
# weekly GPU quota, retry every RETRY_S), then hand each to l4_result_summary.sh. One at a time keeps the order the
# pre-registration states. scripts/queue_after_reset.sh <slug> [<slug> ...]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export KAGGLE_BIN=${KAGGLE_BIN:-$PWD/.venv/bin/kaggle} RETRY_S=${RETRY_S:-900}
for slug in "$@"; do
  echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] queue: $slug" >> eval/overnight/progress.log
  bash scripts/kaggle_push_retry.sh "$slug" >> "eval/overnight/${slug}.out" 2>&1
  SUMMARY_SETTLE_S=60 bash scripts/l4_result_summary.sh "$slug" "eval/overnight/${slug}.out"
done
echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] queue done: $*" >> eval/overnight/progress.log
