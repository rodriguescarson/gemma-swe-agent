#!/bin/bash
# usage: grade_rA.sh PATCHES.json RUN_NAME   (CONC env; always keeps full logs). Same env/args as labels/grader/grade.sh, driver adds -rA.
S=<scratch>/labels
N=<scratch>/assume/nearmiss
R=<repo>
PATCHES=$1; RUN=$2; VENV=$S/venv
mkdir -p $N/runs/$RUN $N/gtmp
cd $R
env -i HOME=$HOME PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin LANG=C.UTF-8 TERM=xterm-color \
  TMPDIR=$N/gtmp G4_FAITHFUL_ENV=0 G4_WS_CACHE=$HOME/.cache/g4/ws PYTHONDONTWRITEBYTECODE=1 G4_REPLAY_LOGS=1 \
  $VENV/bin/python $N/drv.py --patches $PATCHES eval --tasks $R/data/tasks.jsonl \
  --snapshots-dir $N/snapshots_placeholder --results-dir $N/runs/$RUN --submission-dir $N/runs/$RUN \
  --sandbox subprocess --timeout-seconds 300 --concurrency ${CONC:-2} --display quiet \
  > $N/runs/$RUN.out 2>&1
echo "rc=$?"
