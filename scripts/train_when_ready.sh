#!/usr/bin/env bash
# Launch the Adaption LoRA run (train/adaption_train.py --launch) exactly once, when the stitched rows validate:
# report ok, rows >= MIN_ROWS, report written after SINCE_EPOCH (never a stale report from an earlier stitch).
# Carson's go for Adaption: 2026-10-02 ("gonahead ... before submitting to adaption also": full population first;
# the 159 training tasks pre-flighted 159/159 on 10-03). tests/test_train_when_ready.py.
#   [REPORT=eval/collect/rows_stitched_report.json] [ROWS=data/v11/rows_stitched.jsonl] [MIN_ROWS=10000]
#   [SINCE_EPOCH=<chain start>] [READY_POLL_S=600] [READY_MAX_POLLS=0] [TRAINER=...] [MARKER=eval/overnight/adaption_launched] scripts/train_when_ready.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPORT=${REPORT:-eval/collect/rows_stitched_report.json}; ROWS=${ROWS:-data/v11/rows_stitched.jsonl}; MIN_ROWS=${MIN_ROWS:-10000}
TRAINER=${TRAINER:-".venv/bin/python train/adaption_train.py"}; MARKER=${MARKER:-eval/overnight/adaption_launched}
SINCE=${SINCE_EPOCH:-$(date -u +%s)}; POLL=${READY_POLL_S:-600}; MAX=${READY_MAX_POLLS:-0}
LOG=${SEQ_LOG:-eval/overnight/progress.log}; mkdir -p "$(dirname "$LOG")" "$(dirname "$MARKER")"
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] train_when_ready: $*" | tee -a "$LOG"; }
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
[ -f "$MARKER" ] && { step "already launched ($MARKER exists); nothing to do"; exit 0; }
n=0
while :; do
  n=$((n + 1)); why=""
  if [ ! -f "$REPORT" ]; then why="no report"
  elif [ "$(mtime "$REPORT")" -lt "$SINCE" ]; then why="stale report ($(date -u -r "$(mtime "$REPORT")" 2>/dev/null || echo "mtime $(mtime "$REPORT")") < since $SINCE)"
  else
    verdict=$(python3 -c "import json,sys; r=json.load(open(sys.argv[1])); print('READY' if r.get('ok') and int(r.get('rows') or 0) >= int(sys.argv[2]) else f\"not ready: ok={r.get('ok')} rows={r.get('rows')}\")" "$REPORT" "$MIN_ROWS")
    [ "$verdict" = READY ] || why="$verdict"
  fi
  if [ -z "$why" ]; then
    step "rows validated ($REPORT); launching Adaption v11a"
    # shellcheck disable=SC2086
    out=$($TRAINER "$ROWS" --name v11a --launch 2>&1); st=$?
    echo "$out" | tail -5 | tee -a "$LOG"
    if [ $st -eq 0 ] && echo "$out" | grep -q LAUNCHED; then echo "$out" | grep LAUNCHED | head -1 > "$MARKER"; step "LAUNCHED; marker $MARKER"; exit 0; fi
    step "launch FAILED (exit $st)"; exit 1
  fi
  step "$why (poll $n)"
  if [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ]; then exit 1; fi
  sleep "$POLL"
done
