#!/usr/bin/env bash
# Trajectory collection for the v11 LoRA (docs/v11/PLAN.md P2 without a pod): run ONE bundle over a task list SAMPLES
# times through the Docker pod-emulation (as scripts/pallets/or_race.sh) with the model on OpenRouter through
# scripts/or_proxy.py --capture, so every model call's exact request and reply are kept for train/build_sft.py.
#
#   [SAMPLES=3] [CONC=4] [MAX_USD=25] [PROVIDER=parasail/fp8] [MODEL=google/gemma-4-31b-it] [HARNESS=data/pallets/harness_train] \
#       scripts/collect/collect.sh <bundle> <ids_file> <tag>
#
# Output eval/collect/<tag>/: capture_s<k>.jsonl + s<k>/task_results.jsonl (+ traces) per sample, progress.log.
# Resumable: a sample pass skips task ids already present in its task_results.jsonl. Replies are paced to the modelled
# L4 time (or_proxy --l4-pace), compaction on, budgets from the bundle's eval_config (FAITHFUL), so the collected
# trajectories live under the scorer's own time pressure. Leak guard: the ids file must not intersect
# data/pallets/dev40_ids.txt or data/pallets/holdout_ids.txt (the eval sets); the script refuses otherwise.
set -euo pipefail
cd "$(dirname "$0")/../.."
BUNDLE=${1:?bundle dir under submissions/, e.g. v4h}; IDS_FILE=${2:?ids file}; TAG=${3:?tag}
SAMPLES=${SAMPLES:-3}; CONC=${CONC:-4}; CAP=${MAX_USD:-25}; PROVIDER=${PROVIDER:-parasail/fp8}; MODEL=${MODEL:-google/gemma-4-31b-it}
PORT=${PORT:-8792}; PY=${PY:-.venv/bin/python}; HARNESS=${HARNESS:-data/pallets/harness}   # packed by scripts/pallets/pack.py
OUT="$PWD/eval/collect/$TAG"; mkdir -p "$OUT"
for f in data/pallets/dev40_ids.txt data/pallets/holdout_ids.txt; do
  if [ -f "$f" ] && [ -n "$(grep -Fxf "$f" "$IDS_FILE" || true)" ]; then
    echo "LEAK GUARD: $IDS_FILE intersects $f (an eval set); refusing"; exit 2
  fi
done
# keep only ids the packed harness holds (pack.py drops tasks of another venv, e.g. the 5 flask-wz2 ones)
grep -Fxf "$HARNESS/ids.txt" "$IDS_FILE" > "$OUT/ids.txt" || true
echo "ids: $(wc -l < "$IDS_FILE") requested, $(wc -l < "$OUT/ids.txt") in $HARNESS, dropped: $(grep -vFxf "$HARNESS/ids.txt" "$IDS_FILE" | tr "\n" " ")"
[ -s "$OUT/ids.txt" ] || { echo "no requested id is in $HARNESS/ids.txt"; exit 2; }
curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && { echo "port $PORT busy (stale or_proxy?)"; exit 1; }
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
# 2026-10-02: use the harness in place through the read-only mount. Copying it into the container put 9.6 GB of
# graphs+embeddings into the Docker VM and drove the Mac under 3 GB free within 80 s (watchdog kill).
H="/g4/$HARNESS"
export G4_WHEELHOUSE="$H/wheels" G4_COMPACTION=1 G4_L4_SCALE=1.0 G4_NO_EDITABLE=1 OPENAI_API_KEY=EMPTY
export OPENAI_BASE_URL=http://host.docker.internal:$PORT/v1
budget() {
  python - "$1/eval_config.yaml" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
v = {k: re.search(rf"^\s*{k}\s*:\s*([0-9.]+)", t, re.M).group(1)
     for k in ("max_time_minutes", "max_tool_calls", "max_turns", "timeout_seconds")}
print(f"--max-time-minutes {v['max_time_minutes']} --max-tool-calls {v['max_tool_calls']} "
      f"--max-turns {v['max_turns']} --timeout-seconds {v['timeout_seconds']}")
PY
}
cp -r "/g4/submissions/$BUNDLE" /tmp/bundle; mkdir -p /tmp/sbx /tmp/run; cd /tmp/run
DONE=/out/s$SAMPLE/task_results.jsonl
if [ -f "$DONE" ]; then
  IDS=$(python - "$DONE" /out/ids.txt <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
# a row whose error is a dead proxy (connection refused / APIConnection) is not a result: re-run that task
bad = {r["instance_id"] for r in rows if any(k in str(r.get("error") or "") for k in ("onnection", "refused", "APIConnection"))}
done = {r["instance_id"] for r in rows} - bad
if bad:
    keep = [json.dumps(r) for r in rows if r["instance_id"] not in bad]
    open(sys.argv[1], "w").write("".join(k + "\n" for k in keep))
print(" ".join(i for i in open(sys.argv[2]).read().split() if i not in done))
PY
)
else
  IDS=$(tr '\n' ' ' < /out/ids.txt)
fi
[ -z "$IDS" ] && { echo "SAMPLE_DONE s$SAMPLE (nothing left) $(date -u +%FT%TZ)" >> /out/progress.log; exit 0; }
echo "SAMPLE_START s$SAMPLE $(echo $IDS | wc -w) tasks $(date -u +%FT%TZ) $(budget /tmp/bundle)" >> /out/progress.log
# shellcheck disable=SC2046,SC2086
TMPDIR=/tmp/sbx python /g4/scripts/pallets/run_eval_pallets.py eval --tasks "$H/tasks.jsonl" --snapshots-dir "$H/snapshots" \
  --submission-dir /tmp/bundle --results-dir /out/s$SAMPLE --sandbox subprocess $(budget /tmp/bundle) --concurrency $CONC \
  --display quiet --task-ids $IDS > /out/s$SAMPLE.out 2>&1 || true
echo "SAMPLE_DONE s$SAMPLE rows=$(wc -l < $DONE 2>/dev/null || echo 0) $(date -u +%FT%TZ)" >> /out/progress.log
SH
for k in $(seq 1 "$SAMPLES"); do
  # E7: never start a pass into a full disk; E1: never start a pass on a key that is over its limit (one probe call)
  bash scripts/collect/disk_guard.sh | tee -a "$OUT/progress.log" || exit 3
  "$PY" scripts/or_proxy.py --probe --or-provider "$PROVIDER" --model "$MODEL" 2>&1 | tee -a "$OUT/progress.log" || { echo "PROBE FAILED: not starting s$k" | tee -a "$OUT/progress.log"; exit 4; }
  "$PY" scripts/or_proxy.py --port "$PORT" --max-usd "$CAP" --or-provider "$PROVIDER" --model "$MODEL" --l4-pace \
    --log "$OUT/proxy_s$k.jsonl" --capture "$OUT/capture_s$k.jsonl" > "$OUT/proxy_s$k.out" 2>&1 &
  P=$!
  for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null && break; sleep 1; done
  docker run --rm --cpus "${RACE_CPUS:-6}" --memory "${RACE_MEM:-10g}" -e BUNDLE="$BUNDLE" -e CONC="$CONC" -e PORT="$PORT" -e SAMPLE="$k" -e HARNESS="$HARNESS" \
    --add-host host.docker.internal:host-gateway -v "$PWD":/g4:ro -v "$OUT":/out -v g4-pip-cache:/root/.cache/pip \
    -v g4-uv-cache:/root/.cache/uv -w /tmp "$IMAGE" bash -c "$SCRIPT" >> "$OUT/collect.log" 2>&1 || true
  kill "$P" 2>/dev/null || true; wait "$P" 2>/dev/null || true
done
echo "ALL_DONE $TAG $(date -u +%FT%TZ)" >> "$OUT/progress.log"
for k in $(seq 1 "$SAMPLES"); do
  echo "s$k: rows $(wc -l < "$OUT/s$k/task_results.jsonl" 2>/dev/null || echo 0), solved $(grep -c '"resolved": true' "$OUT/s$k/task_results.jsonl" 2>/dev/null || echo 0), captured calls $(wc -l < "$OUT/capture_s$k.jsonl" 2>/dev/null || echo 0)"
done
