#!/bin/bash
# Timed Kaggle submitter. Runs on the Mac or the VPS.
# Usage: submit_at.sh <kernel-slug> <HHMM UTC> <message> [tag]
# Idempotent across machines: before submitting it asks Kaggle whether a
# submission whose description starts with <tag> already exists.
KERNEL=$1; AT=$2; MSG=$3; TAG=${4:-${MSG%%:*}:}
HERE=$(cd "$(dirname "$0")/.." && pwd)
LOG=${SUBMIT_LOG:-$HERE/eval/submit_log.txt}
KAGGLE=${KAGGLE_BIN:-kaggle}
COMP=gemma-4-developer-agent
mkdir -p "$(dirname "$LOG")"
already() { "$KAGGLE" competitions submissions $COMP -v 2>/dev/null | grep -q ",\"\\?$TAG"; }
echo "$(date -u) [$(hostname -s)] armed $KERNEL for $AT UTC (tag $TAG)" >> "$LOG"
# Target = the NEXT occurrence of AT (UTC) after arming, as an absolute epoch; a late wake still fires, an afternoon
# arming never fires early (2026-09-27: an HHMM ">=" check fired at 16:12 for a 00:01 target).
TARGET=${SUBMIT_TARGET_EPOCH:-$(python3 -c 'import datetime as d, sys
n = d.datetime.now(d.timezone.utc); a = sys.argv[1]
t = n.replace(hour=int(a[:2]), minute=int(a[2:]), second=0, microsecond=0)
print(int((t if t > n else t + d.timedelta(days=1)).timestamp()))' "$AT")}
echo "$(date -u) [$(hostname -s)] target epoch $TARGET ($(python3 -c "import datetime as d,sys; print(d.datetime.fromtimestamp(int(sys.argv[1]), d.timezone.utc))" "$TARGET"))" >> "$LOG"
until [ "$(date -u +%s)" -ge "$TARGET" ]; do sleep 20; done
for i in 1 2 3; do
  if already; then echo "$(date -u) [$(hostname -s)] $TAG already on Kaggle, skipping" >> "$LOG"; break; fi
  out=$("$KAGGLE" competitions submit $COMP -k "carsonrodrigues/$KERNEL" -v 1 -f submission.zip -m "$MSG" 2>&1 | tr "\n" " ")
  echo "$(date -u) [$(hostname -s)] attempt $i: $out" >> "$LOG"
  echo "$out" | grep -qi "success" && break
  sleep 60
done
"$KAGGLE" competitions submissions $COMP -v 2>&1 | head -2 >> "$LOG"
