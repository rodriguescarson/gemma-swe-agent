#!/usr/bin/env bash
# The SWE-Pallets-X gold oracle on Linux (the pod/Kaggle OS), in python:3.12-slim (research/pallets.md section 4.3).
#
#   scripts/pallets/linux_oracle.sh [oracle.py args ...]     e.g.  --repos click flask werkzeug jinja2 markupsafe itsdangerous -j 4
#
# The repo is mounted read-only at /g4; results go to data/pallets/oracle/linux/ (results_linux.jsonl, logs/). Venvs are
# rebuilt inside the container by build_envs.sh (network once; docker volumes g4-pallets-venvs and g4-pip-cache keep
# them). swegemma comes from harness/wheels (the same wheels scripts/linux_test.sh installs). CPU: --cpus 8 by default
# (LINUX_CPUS), so -j 4 gives each task about 2 cores, the scorer's Docker quota. Image: LINUX_IMAGE, default
# g4-pallets-linux:local when it exists (python:3.12-slim + git, patch, uv, pytest and the harness wheels, made once with
# `docker commit`, research/pallets.md section 10), else python:3.12-slim (then about 10 min of pip installs first).
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT="$PWD/data/pallets/oracle/linux"
mkdir -p "$OUT"
ENVS="${LINUX_ENVS:-click flask flask-wz2 werkzeug jinja2 markupsafe itsdangerous}"
IMAGE="${LINUX_IMAGE:-python:3.12-slim}"
if [ -z "${LINUX_IMAGE:-}" ] && docker image inspect g4-pallets-linux:local >/dev/null 2>&1; then
  IMAGE=g4-pallets-linux:local
fi
read -r -d '' SCRIPT <<'SH' || true
set -euo pipefail
if ! python -c "import swegemma, uv" 2>/dev/null; then   # python:3.12-slim; g4-pallets-linux:local has all of it
  apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git patch >/dev/null 2>&1
  pip -q install uv pytest >/dev/null 2>&1
  pip -q install /g4/harness/wheels/*.whl >/dev/null 2>&1
fi
export G4_PALLETS=/root/.cache/g4/pallets PYTHONDONTWRITEBYTECODE=1
# shellcheck disable=SC2086
bash /g4/scripts/pallets/build_envs.sh $ENVS 2>&1 | grep -E "ok|rror" || true
cd /g4
python /g4/scripts/pallets/oracle.py --out /out/results_linux.jsonl --logs /out/logs "$@"
SH
exec docker run --rm --cpus "${LINUX_CPUS:-8}" --memory 16g -e ENVS="$ENVS" \
  -v "$PWD":/g4:ro -v "$OUT":/out -v g4-pallets-venvs:/root/.cache/g4/pallets -v g4-pip-cache:/root/.cache/pip \
  -v g4-uv-cache:/root/.cache/uv -w /tmp "$IMAGE" bash -c "$SCRIPT" linux_oracle "$@"
