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
# Free-disk guard (2026-10-15: the Docker VM grew 11 GB in 5 min and took the Mac to 0 GB free twice in one afternoon). The
# container needs ~10 GB (pip cache, torch site-packages, the 1.7 GB staged copy, per-test workspace copies). MIN_FREE_GB=0 disables.
MIN_FREE_GB=${MIN_FREE_GB:-12}
free_gb=$(python3 -c 'import shutil; print(shutil.disk_usage(".").free // 2**30)')
if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
  echo "linux_test.sh: only ${free_gb} GB free on this disk (MIN_FREE_GB=${MIN_FREE_GB}); not starting the container" >&2; exit 3
fi
# The task workspaces (~/.cache/g4/ws, 24 GB on 2026-10-15) are bind-mounted from the Mac, never rebuilt inside the VM: the
# full suite had written 12 GB of them by 32% and filled the disk. kpar venvs are platform-specific and stay in the container.
G4_WS="${G4_WS:-$HOME/.cache/g4/ws}"; mkdir -p "$G4_WS"
# The container's full pytest log (tracebacks) is copied to this host folder (default eval/linux_test_out/, gitignored).
LINUX_TEST_OUT="${LINUX_TEST_OUT:-$PWD/eval/linux_test_out}"; mkdir -p "$LINUX_TEST_OUT"
# Read-only inputs bind-mounted at their in-tree paths (real directories, so paths relativise as on the Mac; a symlinked
# data/ made test_committed_split_equals_recomputation record /tmp/g4/data/... instead of data/...).
RO_MOUNTS=(-v "$PWD/data:/tmp/g4/data:ro")
for d in golden kaggle collect; do if [ -d "eval/$d" ]; then RO_MOUNTS+=(-v "$PWD/eval/$d:/tmp/g4/eval/$d:ro"); fi; done
case "$PY" in
  3.12|3.13) ;;
  *) echo "linux_test.sh: PY must be 3.12 or 3.13, not $PY" >&2; exit 2 ;;
esac

read -r -d '' STAGE_SCRIPT <<'SH' || true
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git procps >/dev/null 2>&1   # procps: pgrep/ps for the A6000 + bounded tests
mkdir -p /tmp/g4
(cd /g4 && tar -cf - --exclude=./.venv --exclude=./data --exclude=./eval --exclude=./backups \
   --exclude='*/__pycache__' --exclude='*.pyc' .) | tar -xf - -C /tmp/g4
[ -e /tmp/g4/data ] || ln -s /g4/data /tmp/g4/data
mkdir -p /tmp/g4/eval
(cd /g4/eval && tar -cf - --exclude=./collect --exclude=./golden --exclude=./kaggle \
   --exclude='*/__pycache__' --exclude='*.pyc' .) | tar -xf - -C /tmp/g4/eval
# In Docker the read-only inputs are bind mounts at these paths already (real directories: paths relativise like on the Mac);
# the symlinks are the fallback when this block runs outside Docker (tests/test_linux_test_script.py, test_v10_2_bundle.py).
for d in golden kaggle collect; do if [ -d "/g4/eval/$d" ] && [ ! -e "/tmp/g4/eval/$d" ]; then ln -s "/g4/eval/$d" "/tmp/g4/eval/$d"; fi; done
cd /tmp/g4 || exit 1
SH
# data/ (40 GB on 2026-10-15) is never copied: a copy fills the Docker VM and the daemon dies. eval/ is copied minus its big
# read-only inputs (collect, golden, kaggle): its scripts (eval/locate_recall_heldout.py is imported by a test module) and
# outputs (eval/runs is written by the pace-proxy test) must be present and writable.

if [ "${V10_ONLY:-0}" = 1 ]; then
  read -r -d '' V10_SCRIPT <<'SH' || true
set -uo pipefail
unset TMPDIR
pip -q install pytest >/dev/null 2>&1
if [ "${V10_HARNESS:-1}" = 1 ]; then
  pip -q install harness/wheels/*.whl >/dev/null 2>&1 || echo "WARN harness wheels not installed: sandbox/flow tests will skip"
  pip -q install mcp==1.30.0 litellm==1.102.1 >/dev/null 2>&1 || echo "WARN mcp/litellm pins not installed"   # the Mac venv pins (2026-10-18: a fresh resolution broke litellm's mcp import)
fi
git config --global user.email a@b; git config --global user.name a
echo "LINUX_V10 TMPDIR=${TMPDIR-unset} TEST_TMPDIR=${TEST_TMPDIR-unset} nproc=$(nproc) G4_NIGHTLY=${G4_NIGHTLY-} G4_BUNDLE=${G4_BUNDLE-} python=$(python -V 2>&1)"
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_v10_*.py tests/test_make_variant_v10.py -rfE > /tmp/v10_pytest.log 2>&1
rc=$?
cp /tmp/v10_pytest.log /out/v10_pytest.log 2>/dev/null
grep -E "^(FAILED|ERROR) " /tmp/v10_pytest.log | cut -c1-300 | head -60
tail -1 /tmp/v10_pytest.log
exit $rc
SH
  V10_SCRIPT="$STAGE_SCRIPT"$'\n'"$V10_SCRIPT"            # staging first (shared block above), then the v10 steps
  exec docker run --rm --cpus 2 --memory 4g -e TEST_TMPDIR=/tmp -e "G4_NIGHTLY=${G4_NIGHTLY:-}" -e "G4_BUNDLE=${G4_BUNDLE:-}" \
    -e "V10_HARNESS=${V10_HARNESS:-1}" -v "$PWD":/g4:ro -v g4-pip-cache:/root/.cache/pip -v "$G4_WS":/root/.cache/g4/ws "${RO_MOUNTS[@]}" -v "$LINUX_TEST_OUT":/out -w /tmp \
    "python:${PY}-slim" bash -c "$V10_SCRIPT"
fi

# Whole suite (TESTS="tests/a.py::x tests/b.py" = that subset, same container environment). The harness wheels are installed because the v10 tests import swegemma/ADK (without them 150+ tests
# failed with ModuleNotFoundError), and the exit code is pytest's: the old '| tail -5' always exited 0 (integrator,
# 2026-09-28: a run with 152 failures reported success).
# The steps follow the container command (a heredoc inside the command substitution), not a heredoc above it, so
# the static test that slices from the last container command (tests/test_v10_integration.py) still sees the wheel
# install and the exit line. Shared staging first (STAGE_SCRIPT above), then the whole suite.
docker run --rm -v "$PWD":/g4:ro -v g4-pip-cache:/root/.cache/pip -v "$G4_WS":/root/.cache/g4/ws "${RO_MOUNTS[@]}" -v "$LINUX_TEST_OUT":/out -e "TESTS=${TESTS:-}" -w /tmp "python:${PY}-slim" bash -c "$STAGE_SCRIPT
$(cat <<'SH'
pip -q install pytest pyarrow >/dev/null 2>&1
pip -q install harness/wheels/*.whl >/dev/null 2>&1 || echo 'WARN harness wheels not installed: harness tests will fail'
pip -q install mcp==1.30.0 litellm==1.102.1 >/dev/null 2>&1 || echo 'WARN mcp/litellm pins not installed'   # the Mac venv pins (see the V10 branch)
pip -q install peft==0.21.0 >/dev/null 2>&1 || echo 'WARN peft not installed: train/qlora tests will fail'   # the Mac venv pin
git config --global user.email a@b; git config --global user.name a
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider ${TESTS:-tests} -k 'not shellcheck and not official_compiler' -rfE > /tmp/full.log 2>&1
rc=$?; cp /tmp/full.log /out/full.log 2>/dev/null; grep -E '^(FAILED|ERROR) ' /tmp/full.log | cut -c1-300 | head -60; tail -1 /tmp/full.log; exit $rc
SH
)"
