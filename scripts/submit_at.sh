#!/bin/bash
# Timed Kaggle submitter. Runs on the Mac or the VPS.
# Usage: [KERNEL_VERSION=N] submit_at.sh <kernel-slug> <HHMM UTC> <message> [tag]   (N = the notebook version whose
# submission.zip is submitted; 2026-09-29: g4agent-v10 v1 is v10.0, v2 is v10.1, so the version must be explicit)
# Idempotent across machines: before submitting it asks Kaggle whether a
# submission whose description starts with <tag> already exists.
KERNEL=$1; AT=$2; MSG=$3; TAG=${4:-${MSG%%:*}:}
HERE=$(cd "$(dirname "$0")/.." && pwd)
LOG=${SUBMIT_LOG:-$HERE/eval/submit_log.txt}
KAGGLE=${KAGGLE_BIN:-kaggle}
COMP=gemma-4-developer-agent
mkdir -p "$(dirname "$LOG")"
# 2026-10-02: sub8 never went out because the detached shell had no `kaggle` on PATH (the VPS keeps it in
# g4submit/venv/bin); the script then retried a failing listing for the whole slot. Resolve the binary at ARM time and
# refuse loudly if it is missing, so a bad PATH is caught the moment the job is armed, not at 00:01 UTC.
if [ -z "${KAGGLE_BIN:-}" ] && ! command -v "$KAGGLE" >/dev/null 2>&1; then   # an explicit KAGGLE_BIN is never second-guessed
  for c in "$(dirname "$0")/venv/bin/kaggle" "$HERE/.venv/bin/kaggle" "$HOME/.local/bin/kaggle"; do
    [ -x "$c" ] && { KAGGLE=$c; break; }
  done
fi
command -v "$KAGGLE" >/dev/null 2>&1 || { echo "$(date -u) [$(hostname -s)] ABORT: kaggle binary not found (KAGGLE_BIN=$KAGGLE); not armed" >> "$LOG"; echo "kaggle binary not found" >&2; exit 2; }
# 0 = a submission with TAG exists, 1 = listing succeeded and it does not, 2 = listing failed (unknown: never submit on it)
already() { local out; out=$("$KAGGLE" competitions submissions $COMP -v 2>/dev/null) || return 2
  echo "$out" | grep -q "^ref," || return 2
  echo "$out" | grep -q ",\"\?$TAG" && return 0 || return 1; }
echo "$(date -u) [$(hostname -s)] armed $KERNEL v${KERNEL_VERSION:-1} for $AT UTC (tag $TAG)" >> "$LOG"
# Target = the NEXT occurrence of AT (UTC) after arming, as an absolute epoch; a late wake still fires, an afternoon
# arming never fires early (2026-09-27: an HHMM ">=" check fired at 16:12 for a 00:01 target).
TARGET=${SUBMIT_TARGET_EPOCH:-$(python3 -c 'import datetime as d, sys
n = d.datetime.now(d.timezone.utc); a = sys.argv[1]
t = n.replace(hour=int(a[:2]), minute=int(a[2:]), second=0, microsecond=0)
print(int((t if t > n else t + d.timedelta(days=1)).timestamp()))' "$AT")}
echo "$(date -u) [$(hostname -s)] target epoch $TARGET ($(python3 -c "import datetime as d,sys; print(d.datetime.fromtimestamp(int(sys.argv[1]), d.timezone.utc))" "$TARGET"))" >> "$LOG"
until [ "$(date -u +%s)" -ge "$TARGET" ]; do sleep 20; done
# GPU-overlap guard (2026-09-29: queued L4 eval kernels started 10 h late and overlapped sub5's scoring). Before
# submitting, wait while any of our own GPU eval kernels (slug prefix g4-l4- or g4-eval) is QUEUED or RUNNING, up to
# the end of the UTC day (a later submission the same day still uses the day's slot). SKIP_GPU_GUARD=1 disables it.
if [ "${SKIP_GPU_GUARD:-0}" != 1 ]; then
  DAY_END=$(( TARGET - (TARGET % 86400) + 86400 - 600 ))
  while :; do
    busy=$("$KAGGLE" kernels list --mine --page-size 50 2>/dev/null | awk 'NR>2{print $1}' | grep -E '/g4-(l4-|eval)' | while read -r k; do
      "$KAGGLE" kernels status "$k" 2>/dev/null | grep -qE 'QUEUED|RUNNING' && echo "$k"; done | tr '\n' ' ')
    [ -z "$busy" ] && break
    [ "$(date -u +%s)" -ge "$DAY_END" ] && { echo "$(date -u) [$(hostname -s)] GPU kernels still busy ($busy) at day end; submitting anyway" >> "$LOG"; break; }
    echo "$(date -u) [$(hostname -s)] waiting: own GPU kernels busy: $busy" >> "$LOG"; sleep 600
  done
fi
for i in 1 2 3 4 5 6; do
  already; st=$?
  if [ $st -eq 0 ]; then echo "$(date -u) [$(hostname -s)] $TAG already on Kaggle, skipping" >> "$LOG"; break; fi
  if [ $st -eq 2 ]; then echo "$(date -u) [$(hostname -s)] listing failed (network?), not submitting blind; retry $i" >> "$LOG"; sleep 120; continue; fi
  out=$("$KAGGLE" competitions submit $COMP -k "carsonrodrigues/$KERNEL" -v "${KERNEL_VERSION:-1}" -f submission.zip -m "$MSG" 2>&1 | tr "\n" " ")
  echo "$(date -u) [$(hostname -s)] attempt $i: $out" >> "$LOG"
  echo "$out" | grep -qi "success" && break
  sleep 60
done
"$KAGGLE" competitions submissions $COMP -v 2>&1 | head -2 >> "$LOG"
