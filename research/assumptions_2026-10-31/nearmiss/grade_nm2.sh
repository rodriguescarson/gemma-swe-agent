#!/bin/bash
# copy of labels/grader/grade.sh writing under the nearmiss scratch dir
O=<scratch>/assume/nearmiss/gr
R=<repo>
PATCHES=$1; RUN=$2; VENV=${3:-<scratch>/assume/nearmiss/venv_rA}
mkdir -p $O/runs/$RUN $O/tmp $O/snapshots_placeholder
cd $R
env -i HOME=$HOME PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin LANG=C.UTF-8 TERM=xterm-color \
  TMPDIR=$O/tmp G4_FAITHFUL_ENV=0 G4_WS_CACHE=$HOME/.cache/g4/ws PYTHONDONTWRITEBYTECODE=1 \
  ${EXTRA_ENV} \
  $VENV/bin/python $R/scripts/run_eval.py --patches $PATCHES eval --tasks ${TASKS:-$R/data/tasks.jsonl} \
  --snapshots-dir $O/snapshots_placeholder --results-dir $O/runs/$RUN --submission-dir $O/runs/$RUN \
  --sandbox subprocess --timeout-seconds 300 --concurrency ${CONC:-1} --display quiet \
  > $O/runs/$RUN.out 2>&1
echo "rc=$?"
