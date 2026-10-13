#!/bin/bash
# Submit a bundle on today's slot once the A6000 box's 74-task run has ended and passes the full-population gate
# (scripts/box_p4_gate.py). Runs on the Mac, detached; it never touches the working tree: it reads the box's pushed files
# from origin with `git show`. GAPS "sub15b pre-registration" (2026-10-13).
# Usage: [DRY_RUN=1] [POLL_S=300] arm_box_submit.sh <p4 step name> <submit kernel slug> <kernel version> <deadline ISO UTC> <message prefix> [floor]
#   e.g. arm_box_submit.sh p4_b1024 g4agent-v12-b1024 2 2026-10-13T23:50:00Z "sub15b: v12-b1024 ..." 26
# Ends when: the step's END line is in docs/a6000/P2_LOG.md on origin and the gate decided (PASS -> submit_at.sh fires now;
# FAIL -> logged, no submission), or the deadline passed (logged, no submission). Log: eval/submit_log.txt (same as submit_at.sh).
set -uo pipefail
STEP=$1; KERNEL=$2; VER=$3; DEADLINE=$4; PREFIX=$5; FLOOR=${6:-26}
HERE=$(cd "$(dirname "$0")/.." && pwd); cd "$HERE" || exit 2
LOG=${SUBMIT_LOG:-$HERE/eval/submit_log.txt}; POLL=${POLL_S:-300}; BR=wip/gemma-agent
PY=${PY:-$HERE/.venv/bin/python}; KAGGLE=${KAGGLE_BIN:-$HERE/.venv/bin/kaggle}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
deadline_epoch=$("$PY" -c 'import datetime as d, sys; print(int(d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp()))' "$DEADLINE") || exit 2
log() { echo "$(date -u) [$(hostname -s)] arm_box_submit $STEP: $*" >> "$LOG"; echo "$*"; }
log "armed: kernel $KERNEL v$VER, floor $FLOOR, deadline $DEADLINE, poll ${POLL}s, dry_run=${DRY_RUN:-0}"
while :; do
  if [ "$(date +%s)" -ge "$deadline_epoch" ]; then log "deadline $DEADLINE passed before a decision: no submission"; exit 3; fi
  git fetch -q origin "$BR" 2>/dev/null
  if git show "origin/$BR:docs/a6000/P2_LOG.md" 2>/dev/null | grep -q "step=$STEP | END"; then
    endline=$(git show "origin/$BR:docs/a6000/P2_LOG.md" | grep "step=$STEP | END" | tail -1)
    if git show "origin/$BR:eval/a6000/results/$STEP/results.jsonl" > "$TMP/results.jsonl" 2>/dev/null; then
      verdict=$("$PY" scripts/box_p4_gate.py "$TMP/results.jsonl" --floor "$FLOOR"); rc=$?
      log "END seen ($endline); gate: $verdict"
      if [ $rc -eq 0 ]; then
        msg="$PREFIX; box 74 public: $(echo "$verdict" | cut -d' ' -f2-7)"
        if [ "${DRY_RUN:-0}" = 1 ]; then log "DRY_RUN: would submit $KERNEL v$VER: $msg"; exit 0; fi
        log "PASS -> submitting $KERNEL v$VER now"
        KERNEL_VERSION=$VER SUBMIT_TARGET_EPOCH=0 KAGGLE_BIN=$KAGGLE SUBMIT_LOG=$LOG bash scripts/submit_at.sh "$KERNEL" 0000 "$msg" "${PREFIX%%:*}:"
        exit $?
      fi
      log "FAIL: no submission"; exit 1
    fi
    log "END seen but eval/a6000/results/$STEP/results.jsonl not on origin yet; waiting for the backup push"
  fi
  sleep "$POLL"
done
