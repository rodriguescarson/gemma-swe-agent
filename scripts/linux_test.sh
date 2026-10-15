#!/usr/bin/env bash
# Run the suite in a Linux Python 3.12 container (the pod/Kaggle OS). macOS-only passes once hid a stdlib-shadowing bug.
#
# V10_ONLY=1 (SPEC R119): only tests/test_v10_*.py, under the Docker scorer's limits (--cpus 2 --memory 4g,
# docker.py:89) with TMPDIR unset and TEST_TMPDIR=/tmp (docker.py:93), so the v10 helpers are exercised in the
# Docker-backend path layout for real. The harness wheels (harness/wheels) are installed so the real-sandbox and
# mock-LLM flow tests run too (needs network once for their PyPI deps; V10_HARNESS=0 skips it and those tests skip).
# Big read-only inputs (data/, eval/race1, eval/kaggle) are symlinked, not copied. G4_NIGHTLY is forwarded.
# G4_BUNDLE (2026-09-29) is forwarded too, so a make_variant arm runs the v10 suite on Linux
# (G4_BUNDLE=submissions/v10_1_sweep V10_ONLY=1 scripts/linux_test.sh); tests/test_make_variant_v10.py always runs.
# PY (2026-09-30, docs/v10/SPEC_v10_2.md E6/R143) picks the container's Python: 3.12 (default) or 3.13, the scorer's
# (PY=3.13 V10_ONLY=1 G4_BUNDLE=submissions/v10_2 scripts/linux_test.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-3.12}"
case "$PY" in
  3.12|3.13) ;;
  *) echo "linux_test.sh: PY must be 3.12 or 3.13, not $PY" >&2; exit 2 ;;
esac

read -r -d '' STAGE_SCRIPT <<'SH' || true
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
mkdir -p /tmp/g4
(cd /g4 && tar -cf - --exclude=./.venv --exclude=./data --exclude=./eval --exclude=./backups \
   --exclude='*/__pycache__' --exclude='*.pyc' .) | tar -xf - -C /tmp/g4
ln -s /g4/data /tmp/g4/data
mkdir -p /tmp/g4/eval
for d in race1 kaggle golden a6000; do if [ -d "/g4/eval/$d" ]; then ln -s "/g4/eval/$d" "/tmp/g4/eval/$d"; fi; done
cd /tmp/g4 || exit 1
SH
# data/ (40 GB on 2026-10-15) and eval/ are symlinked, never copied: a copy fills the Docker VM and the daemon dies.

if [ "${V10_ONLY:-0}" = 1 ]; then
  read -r -d '' V10_SCRIPT <<'SH' || true
set -uo pipefail
unset TMPDIR
pip -q install pytest >/dev/null 2>&1
if [ "${V10_HARNESS:-1}" = 1 ]; then
  pip -q install harness/wheels/*.whl >/dev/null 2>&1 || echo "WARN harness wheels not installed: sandbox/flow tests will skip"
fi
git config --global user.email a@b; git config --global user.name a
echo "LINUX_V10 TMPDIR=${TMPDIR-unset} TEST_TMPDIR=${TEST_TMPDIR-unset} nproc=$(nproc) G4_NIGHTLY=${G4_NIGHTLY-} G4_BUNDLE=${G4_BUNDLE-} python=$(python -V 2>&1)"
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_v10_*.py tests/test_make_variant_v10.py -rfE > /tmp/v10_pytest.log 2>&1
rc=$?
grep -E "^(FAILED|ERROR) " /tmp/v10_pytest.log | cut -c1-300 | head -60
tail -1 /tmp/v10_pytest.log
exit $rc
SH
  V10_SCRIPT="$STAGE_SCRIPT"$'\n'"$V10_SCRIPT"            # staging first (shared block above), then the v10 steps
  exec docker run --rm --cpus 2 --memory 4g -e TEST_TMPDIR=/tmp -e "G4_NIGHTLY=${G4_NIGHTLY:-}" -e "G4_BUNDLE=${G4_BUNDLE:-}" \
    -e "V10_HARNESS=${V10_HARNESS:-1}" -v "$PWD":/g4:ro -v g4-pip-cache:/root/.cache/pip -w /tmp \
    "python:${PY}-slim" bash -c "$V10_SCRIPT"
fi

# Whole suite. The harness wheels are installed because the v10 tests import swegemma/ADK (without them 150+ tests
# failed with ModuleNotFoundError), and the exit code is pytest's: the old '| tail -5' always exited 0 (integrator,
# 2026-09-28: a run with 152 failures reported success).
read -r -d '' FULL_SCRIPT <<'SH' || true
pip -q install pytest pyarrow >/dev/null 2>&1
pip -q install harness/wheels/*.whl >/dev/null 2>&1 || echo 'WARN harness wheels not installed: harness tests will fail'
git config --global user.email a@b; git config --global user.name a
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests -k 'not shellcheck and not official_compiler' -rfE > /tmp/full.log 2>&1
rc=$?; grep -E '^(FAILED|ERROR) ' /tmp/full.log | cut -c1-300 | head -60; tail -1 /tmp/full.log; exit $rc
SH
FULL_SCRIPT="$STAGE_SCRIPT"$'\n'"$FULL_SCRIPT"                 # staging first, then the whole suite
docker run --rm -v "$PWD":/g4:ro -v g4-pip-cache:/root/.cache/pip -w /tmp "python:${PY}-slim" bash -c "$FULL_SCRIPT"
