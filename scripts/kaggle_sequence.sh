#!/usr/bin/env bash
# Kaggle kernel sequence: wait for the gate (today's submission made, nothing PENDING), then push-and-wait each slug in
# order, one GPU kernel at a time, stopping at the first failure (tests/test_kaggle_sequence.py).
#   scripts/kaggle_sequence.sh <slug> [<slug> ...]        (run inside tmux with caffeinate)
# GATE_SH / PUSH_WAIT_SH swap the tested parts (tests); SEQ_LOG defaults to eval/overnight/progress.log.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
GATE=${GATE_SH:-scripts/overnight_gate.sh}; PUSH=${PUSH_WAIT_SH:-scripts/kaggle_push_wait.sh}
LOG=${SEQ_LOG:-eval/overnight/progress.log}; mkdir -p "$(dirname "$LOG")"
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] $*" | tee -a "$LOG"; }
[ $# -ge 1 ] || { echo "usage: $0 <slug> [<slug> ...]"; exit 2; }
step "sequence start: $*"
bash "$GATE" >> "$LOG" 2>&1 || { step "gate never opened; nothing pushed"; exit 1; }
step "gate open"
for slug in "$@"; do
  step "$slug: push_wait"
  if bash "$PUSH" "$slug" >> "$LOG" 2>&1; then step "$slug: COMPLETE"; else step "$slug: FAILED; stopping the sequence"; exit 1; fi
done
step "sequence done"
