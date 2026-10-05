#!/usr/bin/env bash
# Free, local emulation of the POD's faithful environment for SWE-Pallets-X tasks (research/pallets.md section 7.2).
#
#   [PROBE_OUT=/abs/dir] [PROBE_CPUS=6] [PROBE_VENV=default|flask-wz2] [PROBE_RUNS="stock fix"] scripts/pallets/pod_probe.sh IDS_FILE
#   PROBE_VENV is passed to pack.py --venv (ids of another venv are dropped by pack); PROBE_RUNS=fix skips the two
#   stock runs (the pre-flight of research/pallets.md 7.3 needs only fix_gold + fix_empty).
#
# In a python:3.12-slim container: /root/buildenv built by pod/buildenv.sh (the sandbox host env the pod uses), the
# newest competition wheels of click/flask/werkzeug/jinja2/itsdangerous installed into the harness python as
# pod/harness_env.sh does (only these: the container is arm64 on a Mac, so the x86_64 compiled wheels and their pure
# partners such as pydantic/pydantic-core cannot be mirrored), the tasks packed by scripts/pallets/pack.py with its own
# pinned wheelhouse (compiled x86_64 pins such as markupsafe/cffi then fall back to buildenv's copies on arm64) at
# /root/h (NOT under /tmp: the subprocess sandbox rewrites /tmp, /workspace, /usr/local/bin and /wheels in commands),
# then four runs of the real harness through scripts/run_eval.py (G4_FAITHFUL_ENV=1, subprocess sandbox, no model):
#   stock_gold  --oracle              stock_empty  --skip-agent-patch        (scripts/run_eval.py)
#   fix_gold    --oracle              fix_empty    --skip-agent-patch        (scripts/pallets/run_eval_pallets.py with
#                                                                             G4_WHEELHOUSE = the pack's own wheels)
# Output: data/pallets/oracle/pod_probe/<run>/ (task_results.jsonl, test_outputs/) and probe.log. No GPU, no model.
#
# 2026-10-06 (heldout1k): PROBE_HARNESS=<repo-relative dir> uses an already packed harness dir (e.g. one written by
# scripts/heldout/pack_heldout.py) instead of running pack.py in the container; PROBE_CONC = the harness --concurrency
# (default 2); PROBE_NO_EDITABLE=1 exports G4_NO_EDITABLE=1 as scripts/pallets/or_race.sh does; DRY_RUN=1 prints the
# plan and exits before anything is deleted or started.
set -euo pipefail
cd "$(dirname "$0")/../.."
IDS_FILE="${1:?usage: pod_probe.sh IDS_FILE}"
OUT="${PROBE_OUT:-$PWD/data/pallets/oracle/pod_probe}"      # PROBE_OUT: absolute dir, for a second probe beside the first
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "out=$OUT"; echo "ids=$IDS_FILE"
  echo "harness=${PROBE_HARNESS:-pack.py --venv ${PROBE_VENV:-default}}"
  echo "runs=${PROBE_RUNS:-stock fix}"; echo "conc=${PROBE_CONC:-2}"; echo "no_editable=${PROBE_NO_EDITABLE:-0}"
  exit 0
fi
if [ -n "${PROBE_HARNESS:-}" ]; then
  [ -f "$PROBE_HARNESS/tasks.jsonl" ] || { echo "no $PROBE_HARNESS/tasks.jsonl"; exit 1; }
fi
rm -rf "$OUT" && mkdir -p "$OUT"
cp "$IDS_FILE" "$OUT/ids.txt"
IMAGE="${PROBE_IMAGE:-python:3.12-slim}"
if [ -z "${PROBE_IMAGE:-}" ] && docker image inspect g4-pallets-linux:local >/dev/null 2>&1; then
  IMAGE=g4-pallets-linux:local
fi
read -r -d '' SCRIPT <<'SH' || true
set -euo pipefail
if ! python -c "import swegemma, uv" 2>/dev/null; then   # python:3.12-slim; g4-pallets-linux:local has all of it
  apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git patch >/dev/null 2>&1
  pip -q install uv >/dev/null 2>&1
  pip -q install /g4/harness/wheels/*.whl >/dev/null 2>&1
fi
export PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
ln -sfn /g4/data/raw/wheels /wheels
# pod/harness_env.sh: newest competition wheels into the harness env, minus the repos under test (pure-python only here)
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
bash /g4/pod/buildenv.sh
python -c "import importlib.metadata as m; print('harness env:', {p: m.version(p) for p in ('click', 'flask', 'werkzeug', 'jinja2', 'itsdangerous')})" || true
/root/buildenv/bin/python -c "import importlib.metadata as m; print('buildenv:', {p: m.version(p) for p in ('click', 'flask', 'werkzeug', 'jinja2', 'markupsafe', 'itsdangerous', 'blinker')})" || true
if [ -n "$PROBE_HARNESS" ]; then
  cp -r "/g4/$PROBE_HARNESS" /root/h
else
  python /g4/scripts/pallets/pack.py --ids /out/ids.txt --venv "$PROBE_VENV" --out /root/h
fi
if [ "$PROBE_NO_EDITABLE" = 1 ]; then export G4_NO_EDITABLE=1; fi
cp -r /g4/submissions/v10 /tmp/bundle
mkdir -p /tmp/sbx /tmp/run && cd /tmp/run
export OPENAI_BASE_URL=http://127.0.0.1:9/v1 OPENAI_API_KEY=EMPTY G4_COMPACTION=0 TMPDIR=/tmp/sbx
IDS=$(tr '\n' ' ' < /out/ids.txt)
common() {
  # shellcheck disable=SC2086
  echo --tasks /root/h/tasks.jsonl --snapshots-dir /root/h/snapshots --submission-dir /tmp/bundle --sandbox subprocess \
    --timeout-seconds 180 --max-time-minutes 5 --concurrency "$PROBE_CONC" --display quiet --task-ids $IDS
}
if [[ " $PROBE_RUNS " == *" stock "* ]]; then
# shellcheck disable=SC2046
python /g4/scripts/run_eval.py --oracle eval $(common) --results-dir /out/stock_gold > /out/stock_gold.out 2>&1 || true
# shellcheck disable=SC2046
python /g4/scripts/run_eval.py eval --skip-agent-patch $(common) --results-dir /out/stock_empty > /out/stock_empty.out 2>&1 || true
fi
export G4_WHEELHOUSE=/root/h/wheels
# shellcheck disable=SC2046
python /g4/scripts/pallets/run_eval_pallets.py --oracle eval $(common) --results-dir /out/fix_gold > /out/fix_gold.out 2>&1 || true
# shellcheck disable=SC2046
python /g4/scripts/pallets/run_eval_pallets.py eval --skip-agent-patch $(common) --results-dir /out/fix_empty > /out/fix_empty.out 2>&1 || true
python - <<'PY'
import json, os
runs = ("stock_gold", "stock_empty", "fix_gold", "fix_empty")
res = {}
for r in runs:
    p = f"/out/{r}/task_results.jsonl"
    res[r] = {json.loads(l)["instance_id"]: json.loads(l)["resolved"] for l in open(p)} if os.path.exists(p) else {}
ids = open("/out/ids.txt").read().split()
print("task".ljust(24) + "".join(r.rjust(13) for r in runs) + "   valid(stock) valid(fix)")
for t in ids:
    row = [res[r].get(t) for r in runs]
    print(t.ljust(24) + "".join(str(v).rjust(13) for v in row) + f"   {bool(row[0]) and row[1] is False!s:>12} {bool(row[2]) and row[3] is False!s:>10}")
for label, g, e in (("stock", "stock_gold", "stock_empty"), ("fix", "fix_gold", "fix_empty")):
    print(label, "valid", sum(1 for t in ids if res[g].get(t) and res[e].get(t) is False), "of", len(ids))
PY
SH
docker run --rm --cpus "${PROBE_CPUS:-6}" --memory "${PROBE_MEM:-12g}" -e PROBE_VENV="${PROBE_VENV:-default}" \
  -e PROBE_HARNESS="${PROBE_HARNESS:-}" -e PROBE_CONC="${PROBE_CONC:-2}" -e PROBE_NO_EDITABLE="${PROBE_NO_EDITABLE:-0}" \
  -e PROBE_RUNS="${PROBE_RUNS:-stock fix}" -v "$PWD":/g4:ro -v "$OUT":/out -v g4-pip-cache:/root/.cache/pip \
  -v "${G4_PALLETS:-$HOME/.cache/g4/pallets}":/root/.cache/g4/pallets:ro \
  -v g4-uv-cache:/root/.cache/uv -w /tmp "$IMAGE" bash -c "$SCRIPT" 2>&1 | tee "$OUT/probe.log"
