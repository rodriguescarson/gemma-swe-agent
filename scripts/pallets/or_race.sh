#!/usr/bin/env bash
# Pallets transfer race WITHOUT a GPU pod (2026-09-30): the pod's faithful env emulated in Docker exactly as
# scripts/pallets/pod_probe.sh does, the model served by OpenRouter through scripts/or_proxy.py (pinned bf16 provider,
# one proxy and one USD cap per arm so neither arm can starve the other).
#
#   [RACE_OUT=/abs/dir] [MAX_USD_ARM=4] [CONC=2] [IDS_FILE=...] [HARNESS=data/pallets/harness] scripts/pallets/or_race.sh ARM [ARM ...]
#   1..N arms (2026-10-05): arm i gets proxy port 8790+i. HARNESS = the packed task dir (e.g. data/pallets/harness_holdout).
#   DRY_RUN=1 prints the plan (harness, arms, ports) and exits before any proxy or container starts.
#
# Both arms run at the same time (same provider load for both), each with its bundle's own eval_config budgets
# (FAITHFUL), compaction on. The proxies pace every reply to the modelled L4 time of that call (or_proxy --l4-pace), so
# the harness's wall-clock cap and the helper clock (scale 1.0) both see L4 speed whatever the provider's speed.
# PROXY result: screening only (bf16 + OpenRouter's tool parser, not int4 + vLLM's gemma4 parser).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ $# -ge 1 ] || { echo "usage: or_race.sh ARM [ARM ...]"; exit 2; }
ARMS=("$@"); PORTS=(); for i in "${!ARMS[@]}"; do PORTS+=($((8790 + i))); done
HARNESS=${HARNESS:-data/pallets/harness}
OUT="${RACE_OUT:-$PWD/eval/runs/or_pal_$(date -u +%Y%m%dT%H%M%SZ)}"
IDS_FILE=${IDS_FILE:-$HARNESS/ids.txt}
CAP=${MAX_USD_ARM:-4}; CONC=${CONC:-2}
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "harness=$HARNESS"; echo "ids=$IDS_FILE"; echo "out=$OUT cap=$CAP conc=$CONC"
  for i in "${!ARMS[@]}"; do echo "arm ${ARMS[$i]} port ${PORTS[$i]}"; done
  exit 0
fi
[ -f "$HARNESS/tasks.jsonl" ] || { echo "no $HARNESS/tasks.jsonl"; exit 1; }
mkdir -p "$OUT"; cp "$IDS_FILE" "$OUT/ids.txt"
# crusoe/bf16 (the golden-eval pin) answered 0/6 with 429 on 2026-09-30 23:20 IST; parasail/fp8 and deepinfra/fp8 6/6
PROVIDER=${OR_PROVIDER:-parasail/fp8}
PY=${PY:-.venv/bin/python}
# 2026-10-02: a proxy left over from an earlier race answered the readiness check, so one arm ran against the wrong
# proxy (wrong log, wrong cap) while its own proxy died on "Address already in use". Refuse to start on a busy port.
for p in "${PORTS[@]}"; do
  curl -sf "http://127.0.0.1:$p/v1/models" >/dev/null 2>&1 && { echo "port $p is already in use (a stale or_proxy?); kill it first: pgrep -f scripts/or_proxy.py"; exit 1; }
done
PIDS=()
for i in "${!ARMS[@]}"; do
  "$PY" scripts/or_proxy.py --port "${PORTS[$i]}" --max-usd "$CAP" --or-provider "$PROVIDER" --l4-pace \
    --log "$OUT/proxy_${ARMS[$i]}.jsonl" > "$OUT/proxy_${ARMS[$i]}.out" 2>&1 &
  PIDS+=($!)
done
trap 'kill "${PIDS[@]}" 2>/dev/null || true' EXIT
for p in "${PORTS[@]}"; do
  for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$p/v1/models" >/dev/null && break; sleep 1; done
  curl -sf "http://127.0.0.1:$p/v1/models" >/dev/null || { echo "proxy :$p did not start"; exit 1; }
done
IMAGE=python:3.12-slim
docker image inspect g4-pallets-linux:local >/dev/null 2>&1 && IMAGE=g4-pallets-linux:local
read -r -d '' SCRIPT <<'SH' || true
set -euo pipefail
if ! python -c "import swegemma, uv" 2>/dev/null; then
  apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git patch >/dev/null 2>&1
  pip -q install uv >/dev/null 2>&1
  pip -q install /g4/harness/wheels/*.whl >/dev/null 2>&1
fi
export PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
ln -sfn /g4/data/raw/wheels /wheels
python - <<'PY' > /tmp/newest.txt
import os
from packaging.version import Version
best = {}
for f in os.listdir("/wheels"):
    if not f.endswith("-none-any.whl"):
        continue
    name, ver = f.split("-")[0].lower().replace("_", "-"), f.split("-")[1]
    try:
        v = Version(ver)
    except Exception:
        continue
    if name not in best or v > best[name][0]:
        best[name] = (v, f)
for n, (v, f) in sorted(best.items()):
    if n in ("click", "flask", "werkzeug", "jinja2", "itsdangerous"):
        print("/wheels/" + f)
PY
# shellcheck disable=SC2046
uv pip install -q --system --no-deps $(cat /tmp/newest.txt)
bash /g4/pod/buildenv.sh > /out/buildenv.log 2>&1
cp -r "/g4/$HARNESS" /root/h
export G4_WHEELHOUSE=/root/h/wheels G4_COMPACTION=1 G4_L4_SCALE=1.0 G4_NO_EDITABLE=1 OPENAI_API_KEY=EMPTY
IDS=$(tr '\n' ' ' < /out/ids.txt)
budget() {  # the bundle's eval_config limits, as run_eval.sh FAITHFUL=1 reads them
  python - "$1/eval_config.yaml" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
v = {k: re.search(rf"^\s*{k}\s*:\s*([0-9.]+)", t, re.M).group(1)
     for k in ("max_time_minutes", "max_tool_calls", "max_turns", "timeout_seconds")}
print(f"--max-time-minutes {v['max_time_minutes']} --max-tool-calls {v['max_tool_calls']} "
      f"--max-turns {v['max_turns']} --timeout-seconds {v['timeout_seconds']}")
PY
}
arm() {  # <bundle> <port>
  mkdir -p /tmp/sbx_$1 /tmp/run_$1 && cp -r /g4/submissions/$1 /tmp/bundle_$1 && cd /tmp/run_$1
  echo "START $1 $(date -u +%FT%TZ) $(budget /tmp/bundle_$1)" >> /out/progress.log
  # shellcheck disable=SC2046,SC2086
  TMPDIR=/tmp/sbx_$1 OPENAI_BASE_URL=http://host.docker.internal:$2/v1 python /g4/scripts/pallets/run_eval_pallets.py eval \
    --tasks /root/h/tasks.jsonl --snapshots-dir /root/h/snapshots --submission-dir /tmp/bundle_$1 \
    --results-dir /out/pl_$1 --sandbox subprocess $(budget /tmp/bundle_$1) --concurrency $CONC --display quiet \
    --task-ids $IDS > /out/pl_$1.out 2>&1 || true
  echo "ARM_DONE $1 $(date -u +%FT%TZ) rows=$(wc -l < /out/pl_$1/task_results.jsonl 2>/dev/null || echo 0)" >> /out/progress.log
}
read -r -a A <<< "$ARMS"; read -r -a P <<< "$PORTS"
for i in "${!A[@]}"; do arm "${A[$i]}" "${P[$i]}" & done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> /out/progress.log
SH
docker run --rm --cpus "${RACE_CPUS:-6}" --memory "${RACE_MEM:-10g}" -e ARMS="${ARMS[*]}" -e PORTS="${PORTS[*]}" \
  -e HARNESS="$HARNESS" \
  -e CONC="$CONC" --add-host host.docker.internal:host-gateway \
  -v "$PWD":/g4:ro -v "$OUT":/out -v g4-pip-cache:/root/.cache/pip -v g4-uv-cache:/root/.cache/uv \
  -w /tmp "$IMAGE" bash -c "$SCRIPT" > "$OUT/race.log" 2>&1
if [ "${#ARMS[@]}" -ge 2 ]; then
  "$PY" scripts/pallets/or_race_summary.py "$OUT" "${ARMS[0]}" "${ARMS[1]}" | tee "$OUT/summary.txt"
fi
