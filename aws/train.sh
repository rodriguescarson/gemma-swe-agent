#!/usr/bin/env bash
# The train role's face of scripts/a6000/train.sh (g6e.2xlarge, L40S 48 GB: the A6000 recipe's memory class). Same
# subcommands and recipe; the pod-layout paths from aws/bootstrap.sh are set here, and probe/full run in the FOREGROUND:
# the A6000 launcher backgrounds the trainer and returns, which on EC2 would end the job and stop the machine mid-run.
#
#   bash aws/train.sh full <name> [args...]    # e.g. aws/launch.py train --hours 10 --job 'bash aws/train.sh full d1'
#   bash aws/train.sh probe <name>             # the 1-hour feasibility probe
#   bash aws/train.sh env|dequant|stitch|recipe|status ...   # passed straight to scripts/a6000/train.sh
#
# Inputs: <repo>/runs/train_<name>/{seqs,holdout}.jsonl (stage them with aws/stage.py put; bootstrap's G4_KEEP=runs
# syncs the run dir, checkpoints included, to S3 every few minutes, and a relaunch of the same run resumes from them).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
A6000="$ROOT/scripts/a6000/train.sh"
export TRAIN_VENV=${TRAIN_VENV:-/root/tvenv} MODEL_DIR=${MODEL_DIR:-/root/models/g4} BF16_DIR=${BF16_DIR:-/root/models/g4-bf16}
cmd=${1:-}
case "$cmd" in
  probe|full)
    NAME=${2:?name}
    [ "$HOME/g4" -ef "$ROOT" ] || { echo "train.sh writes \$HOME/g4/runs; on the box \$HOME/g4 must be this repo ($ROOT)"; exit 2; }
    bash "$A6000" "$@"
    D="$ROOT/runs/train_$NAME/run"; R="$D/summary.json"
    [ "$cmd" = probe ] && { D="$ROOT/runs/train_$NAME/probe"; R="$D/probe_report.json"; }
    PID=$(cat "$D/PID")
    while kill -0 "$PID" 2>/dev/null; do sleep 30; done
    [ -s "$R" ] || { echo "TRAIN_FAILED $cmd $NAME: no $R"; tail -30 "$D/train.out" || true; exit 1; }
    echo "TRAIN_DONE $cmd $NAME"; cat "$R" ;;
  *) exec bash "$A6000" "$@" ;;
esac
