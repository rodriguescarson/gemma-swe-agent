#!/usr/bin/env bash
# No-model pre-flight of a packed Pallets harness (the check chain_pallets.sh did for dev40, now for any id list):
# a task is VALID iff the gold patch resolves it AND the empty patch does not. Runs the real harness in the Docker
# pod-emulation against the harness in place (no copy into the container). Writes <out>/valid_ids.txt,
# <out>/invalid.txt (id + reason) and <out>/report.txt.
#
#   [CONC=4] [HARNESS=data/pallets/harness_train] scripts/collect/preflight.sh <ids_file> <tag>
set -euo pipefail
cd "$(dirname "$0")/../.."
IDS_FILE=${1:?ids file}; TAG=${2:?tag}
CONC=${CONC:-4}; HARNESS=${HARNESS:-data/pallets/harness_train}
OUT="$PWD/eval/preflight/$TAG"; mkdir -p "$OUT"
grep -Fxf "$HARNESS/ids.txt" "$IDS_FILE" > "$OUT/ids.txt" || true
[ -s "$OUT/ids.txt" ] || { echo "no requested id is in $HARNESS/ids.txt"; exit 2; }
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
bash /g4/pod/buildenv.sh > /out/buildenv.log 2>&1
H="/g4/$HARNESS"
export G4_WHEELHOUSE="$H/wheels" G4_COMPACTION=0 G4_NO_EDITABLE=1 OPENAI_API_KEY=EMPTY OPENAI_BASE_URL=http://127.0.0.1:9/v1
cp -r /g4/submissions/v4 /tmp/bundle; mkdir -p /tmp/sbx /tmp/run; cd /tmp/run
IDS=$(tr '\n' ' ' < /out/ids.txt)
for m in oracle skip-agent-patch; do
  pre=""; post=""; [ "$m" = oracle ] && pre=--oracle || post=--skip-agent-patch
  echo "START $m $(date -u +%FT%TZ)" >> /out/progress.log
  # shellcheck disable=SC2086
  TMPDIR=/tmp/sbx python /g4/scripts/pallets/run_eval_pallets.py $pre eval $post --tasks "$H/tasks.jsonl" --snapshots-dir "$H/snapshots" \
    --submission-dir /tmp/bundle --results-dir "/out/$m" --sandbox subprocess --timeout-seconds 180 --max-time-minutes 5 \
    --concurrency $CONC --display quiet --task-ids $IDS > "/out/$m.out" 2>&1 || true
  echo "DONE $m rows=$(wc -l < "/out/$m/task_results.jsonl" 2>/dev/null || echo 0) $(date -u +%FT%TZ)" >> /out/progress.log
done
python - <<'PY'
import json
def res(d):
    try: return {json.loads(l)["instance_id"]: json.loads(l) for l in open(f"/out/{d}/task_results.jsonl") if l.strip()}
    except FileNotFoundError: return {}
g, e = res("oracle"), res("skip-agent-patch")
ids = open("/out/ids.txt").read().split()
valid, invalid = [], []
for t in ids:
    gr, er = g.get(t), e.get(t)
    if gr is None or er is None: invalid.append((t, "no row: gold=%s empty=%s" % (gr is not None, er is not None))); continue
    if str(gr.get("resolved")) != "True": invalid.append((t, "gold does not resolve: " + str(gr.get("error") or gr.get("test_exit_code"))[:80])); continue
    if str(er.get("resolved")) == "True": invalid.append((t, "empty patch resolves (tests do not fail on the original)")); continue
    valid.append(t)
open("/out/valid_ids.txt", "w").write("".join(t + "\n" for t in valid))
open("/out/invalid.txt", "w").write("".join(f"{t}\t{why}\n" for t, why in invalid))
import collections
by = collections.Counter(t.split("_")[0] for t in valid); tot = collections.Counter(t.split("_")[0] for t in ids)
rep = [f"preflight: {len(valid)}/{len(ids)} valid"] + [f"  {k}: {by[k]}/{tot[k]}" for k in sorted(tot)] + [f"  invalid reasons: {collections.Counter(w.split(':')[0] for _, w in invalid)}"]
open("/out/report.txt", "w").write("\n".join(rep) + "\n"); print("\n".join(rep))
PY
echo "ALL_DONE preflight $(date -u +%FT%TZ)" >> /out/progress.log
SH
docker run --rm --cpus "${RACE_CPUS:-6}" --memory "${RACE_MEM:-10g}" -e CONC="$CONC" -e HARNESS="$HARNESS" \
  -v "$PWD":/g4:ro -v "$OUT":/out -v g4-pip-cache:/root/.cache/pip -v g4-uv-cache:/root/.cache/uv -w /tmp "$IMAGE" bash -c "$SCRIPT" > "$OUT/preflight.log" 2>&1 || true
cat "$OUT/report.txt" 2>/dev/null || tail -5 "$OUT/preflight.log"
