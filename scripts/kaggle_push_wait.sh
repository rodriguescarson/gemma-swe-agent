#!/usr/bin/env bash
# Push kernels/<slug>, wait for the run named by the directory's kernel-metadata.json id, fetch its output into
# eval/kaggle/<slug>/ (tests/test_kaggle_push_wait.py). The id and the directory can differ: a kernel rebuilt with
# make_eval_kernel.py --pin original --kernel-id g4-l4-v4 lives under kernels/<new-slug>/ but runs as a new version of
# the old slug, whose first version was created on the Python 3.12 image (the wheelhouse has no cp313 wheels; E2).
#   [KAGGLE_BIN=...] [PUSH_POLL_S=300] [PUSH_SETTLE_S=120] [PUSH_MAX_S=50400] [PUSH_EMPTY_MAX=10] scripts/kaggle_push_wait.sh <slug>
# Exit 0 on COMPLETE (or when output is already present), 1 on ERROR/CANCEL, a failed push, no final status within PUSH_MAX_S
# (default 14 h, above Kaggle's 12 h notebook limit) or PUSH_EMPTY_MAX (default 10) status reads in a row that return nothing
# (CLI or network down; any real status resets the count).
set -uo pipefail
slug=${1:?slug under kernels/}
KAGGLE=${KAGGLE_BIN:-$(command -v kaggle || ls "$HOME"/Library/Python/3.*/bin/kaggle .venv/bin/kaggle "$HOME"/.local/bin/kaggle 2>/dev/null | head -1)}
POLL=${PUSH_POLL_S:-300}; SETTLE=${PUSH_SETTLE_S:-120}; MAX_S=${PUSH_MAX_S:-50400}; EMPTY_MAX=${PUSH_EMPTY_MAX:-10}
out="eval/kaggle/$slug"
if [ -s "$out/results.jsonl" ] || [ -s "$out/lora_probe.json" ]; then echo "$slug: output already present, skip"; exit 0; fi
kid=$(python3 -c "import json; print(json.load(open('kernels/$slug/kernel-metadata.json'))['id'])") || { echo "$slug: no kernel-metadata.json"; exit 1; }
gpu=$(python3 -c "import json; print(bool(json.load(open('kernels/$slug/kernel-metadata.json')).get('enable_gpu')))")
# 2026-10-03: the metadata's machine_shape is ignored by every CLI; only the 2.x CLI's --accelerator selects the machine.
# A push without it ran the 4xL4 probe on 2xT4 (vLLM: "Bfloat16 is only supported on compute capability >= 8.0").
accel=()
if [ "$gpu" = True ]; then
  "$KAGGLE" --version 2>&1 | grep -q "Kaggle CLI 2" || { echo "$slug: GPU kernel needs Kaggle CLI 2.x with --accelerator (have: $("$KAGGLE" --version 2>&1 | head -1)); set KAGGLE_BIN"; exit 1; }
  accel=(--accelerator "${ACCELERATOR:-NvidiaL4}")
fi
echo "$(date -u) $slug: push (runs as $kid${accel:+, ${accel[*]}})"
ack=$("$KAGGLE" kernels push -p "kernels/$slug" ${accel[@]+"${accel[@]}"} 2>&1 | tail -2 | tr '\n' ' ')
echo "$slug: $ack"
echo "$ack" | grep -qi "successfully pushed" || { echo "$slug: push FAILED"; exit 1; }
t0=$(date +%s)
sleep "$SETTLE"
empty=0
while :; do
  st=$("$KAGGLE" kernels status "$kid" 2>&1 | grep -oE 'KernelWorkerStatus\.[A-Z]+' | head -1)
  case "$st" in *COMPLETE|*ERROR|*CANCEL*) break ;; esac
  # A status read that returns nothing is a CLI or network failure, not "still running": without these two exits a dead
  # session looped here until someone noticed (the chains wait on this script).
  if [ -z "$st" ]; then
    empty=$((empty + 1))
    [ "$empty" -ge "$EMPTY_MAX" ] && { echo "$(date -u) $slug: $empty status reads in a row returned nothing; giving up (kernel $kid not checked further)"; exit 1; }
  else empty=0; fi
  [ $(( $(date +%s) - t0 )) -ge "$MAX_S" ] && { echo "$(date -u) $slug: no final status after PUSH_MAX_S=${MAX_S}s (last: ${st:-none}); giving up (kernel $kid not checked further)"; exit 1; }
  sleep "$POLL"
done
echo "$(date -u) $slug: $st"
mkdir -p "$out"; "$KAGGLE" kernels output "$kid" -p "$out" > /dev/null 2>&1 || true
echo "$slug: output $(ls "$out" 2>/dev/null | tr '\n' ' ' | cut -c1-200)"
case "$st" in *COMPLETE) exit 0 ;; *) exit 1 ;; esac
