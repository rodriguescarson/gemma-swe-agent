#!/usr/bin/env bash
# Push the given L4 kernels one after another, each through kaggle_push_retry.sh (waits out the 2-session cap and the
# weekly GPU quota, retry every RETRY_S), then hand each to l4_result_summary.sh. One at a time keeps the order the
# pre-registration states. scripts/queue_after_reset.sh <slug> [<slug> ...]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export KAGGLE_BIN=${KAGGLE_BIN:-$PWD/.venv/bin/kaggle} RETRY_S=${RETRY_S:-900}
L=${QUEUE_LOG_DIR:-eval/overnight}; PUSH_RETRY_SH=${PUSH_RETRY_SH:-scripts/kaggle_push_retry.sh}
SUMMARY_SH=${SUMMARY_SH:-scripts/l4_result_summary.sh}
for slug in "$@"; do
  echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] queue: $slug" >> "$L/progress.log"
  if ! bash "$PUSH_RETRY_SH" "$slug" >> "$L/${slug}.out" 2>&1; then
    # no run started: l4_result_summary would wait forever for it (2026-10-06, 9 h on v5h2). Next slug.
    echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] PUSH_FAILED $slug (see $L/${slug}.out)" >> "$L/progress.log"
    continue
  fi
  SUMMARY_SETTLE_S=60 bash "$SUMMARY_SH" "$slug" "$L/${slug}.out"
done
echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] queue done: $*" >> "$L/progress.log"
