#!/bin/bash
# Mac side of the race gate: wait for the Kaggle rescore kernel, read its helper check, derive version pins from the
# Kaggle image, copy them to the pod, then write GO or NOGO into /root/g4/GO_RACE (the pod chain waits for that flag).
cd /Users/carson/Projects/gemma-swe-agent || exit 1
LOG=eval/submit_log.txt; O=eval/kaggle/rescore_fair; K=carsonrodrigues/g4-rescore-fair
source /Users/carson/Projects/kaggriculture/.venv/bin/activate
echo "$(date -u) go_race: waiting for $K" >> $LOG
until kaggle kernels status $K 2>&1 | grep -qE 'KernelWorkerStatus\.(COMPLETE|ERROR|CANCEL)'; do sleep 120; done
mkdir -p $O && kaggle kernels output $K -p $O >/dev/null 2>&1
VERDICT=NOGO
grep -q "HELPER_CHECK PASS" $O/helper_check.txt 2>/dev/null && VERDICT=GO
: > data/kaggle_pins.txt
[ -f $O/pip_freeze.txt ] && grep -iE "^(pygments|python-multipart)==" $O/pip_freeze.txt > data/kaggle_pins.txt
echo "$(date -u) go_race: helper check -> $VERDICT; pins: $(tr '\n' ' ' < data/kaggle_pins.txt)" >> $LOG
scp -q data/kaggle_pins.txt h100:/root/g4/data/kaggle_pins.txt && scp -q pod/run_eval.sh h100:/root/g4/pod/run_eval.sh &&
  ssh h100 "echo $VERDICT > /root/g4/GO_RACE" && echo "$(date -u) go_race: wrote $VERDICT to pod" >> $LOG
