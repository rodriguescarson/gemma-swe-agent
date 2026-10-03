#!/usr/bin/env bash
# Wait for <slug>: COMPLETE|FAILED in the sequence log, then restart kaggle_sequence.sh with a new slug list under the
# session-cap retry wrapper (run in tmux: no tool time limit). scripts/seq_restart_after.sh <slug> <new slugs...>
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
slug=${1:?slug to wait for}; shift
until grep -qE "$slug: (COMPLETE|FAILED)" eval/overnight/progress.log; do sleep 60; done
sleep 90
tmux kill-session -t kseq 2>/dev/null; pkill -f "[k]aggle_sequence.sh" 2>/dev/null; sleep 2
tmux new -d -s kseq "KAGGLE_BIN=$PWD/.venv/bin/kaggle PUSH_WAIT_SH=scripts/kaggle_push_retry.sh caffeinate -i bash scripts/kaggle_sequence.sh $* >> eval/overnight/kseq.out 2>&1"
echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] sequence restarted after $slug with: $*" >> eval/overnight/progress.log
