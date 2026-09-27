#!/usr/bin/env bash
# Race on data/arena_ids.txt (27 contested + 24 feasible never-solved), 2 tasks per GPU, same budget args as the fair runs.
# Arms: v4 as submitted (helpers unreachable), v9_c (= v4 + $TMPDIR helper fix), and the fractional factorial of the
# three levers on top of v9_c: eo, eg, og (+ eog). Arms are interleaved across GPUs so drift hits both sides.
cd /root/g4 || exit 1
stop_pod() {  # every exit path: verified backup, then stop
  sed -i "/^HOLD /d" eval/progress.log
  # shellcheck disable=SC2046
  export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
  bash pod/backup.sh "$1" && runpodctl stop pod "$RUNPOD_POD_ID"
}
ARMS0="v4 v9_eg v9_og"; ARMS1="v9_c v9_eo v9_eog"
until grep -q BOOT_CHAIN_DONE /root/chain.log 2>/dev/null; do sleep 30; done
for _ in $(seq 1 40); do bash pod/health.sh && break; sleep 30; done
echo "HOLD race $(date -u +%FT%TZ)" >> eval/progress.log
# GO gate: the Mac writes GO_RACE after the Kaggle-image helper check passes (NOGO or 100 min without a flag -> stop).
for _ in $(seq 1 200); do [ -f GO_RACE ] && break; sleep 30; done
grep -qx GO GO_RACE 2>/dev/null || { echo "ABORT race no GO ($(cat GO_RACE 2>/dev/null || echo timeout)) $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod raceabort; exit 1; }
[ -s data/kaggle_pins.txt ] && VIRTUAL_ENV=/root/buildenv uv pip install -q -r data/kaggle_pins.txt
bash pod/health.sh || { echo "ABORT race unhealthy $(date -u +%FT%TZ)" >> eval/progress.log; stop_pod raceabort; exit 1; }
/root/buildenv/bin/python -c "import multipart" || { echo "ABORT race buildenv lacks python-multipart" >> eval/progress.log; stop_pod raceabort; exit 1; }
for b in $ARMS0 $ARMS1; do
  LORA_GATE=0 bash pod/preflight.sh submissions/$b > /root/preflight_$b.out 2>&1 || { echo "ABORT race preflight $b" >> eval/progress.log; stop_pod raceabort; exit 1; }
done
for b in v9_c v9_eog; do bash pod/canary.sh submissions/$b || { echo "ABORT race canary $b" >> eval/progress.log; stop_pod raceabort; exit 1; }; done
IDS=$(tr '\n' ' ' < data/arena_ids.txt)
( for b in $ARMS0; do OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/$b r_$b 6 110 220 180 2 $IDS; echo "ARM_DONE $b $(date -u +%FT%TZ)" >> eval/progress.log; done ) &
( for b in $ARMS1; do OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/$b r_$b 6 110 220 180 2 $IDS; echo "ARM_DONE $b $(date -u +%FT%TZ)" >> eval/progress.log; done ) &
wait
# Confirmation (memoized): the arena results are reused; the top two new arms run only the 23 remaining valid tasks.
TOP=$(python3 - <<'PY'
import json, glob, os
sc = {}
for d in glob.glob("eval/runs/r_v9_*"):
    rows = [json.loads(l) for l in open(os.path.join(d, "task_results.jsonl"))]
    sc[d.split("r_")[1]] = (sum(r.get("resolved", False) for r in rows), -sum(r.get("duration_seconds", 0) for r in rows))
print(" ".join(sorted(sc, key=lambda k: sc[k], reverse=True)[:2]))
PY
)
echo "RACE_TOP $TOP $(date -u +%FT%TZ)" >> eval/progress.log
set -- $TOP
REST=$(tr '\n' ' ' < data/rest_ids.txt)
( OPENAI_BASE_URL=http://127.0.0.1:8100/v1 bash pod/run_eval.sh submissions/$1 c_$1 6 110 220 180 2 $REST ) &
( [ -n "$2" ] && OPENAI_BASE_URL=http://127.0.0.1:8101/v1 bash pod/run_eval.sh submissions/$2 c_$2 6 110 220 180 2 $REST ) &
wait
echo "ALL_DONE race $(date -u +%FT%TZ)" >> eval/progress.log
stop_pod race
