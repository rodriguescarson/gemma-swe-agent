"""scripts/run_eval.py plus one line for src-layout repos (research/pallets.md section 7.2). run_eval.py is not edited.

    python scripts/pallets/run_eval_pallets.py [--oracle] eval <swegemma eval args>     (same interface as run_eval.py)

Why: in the faithful pod environment (G4_FAITHFUL_ENV=1) the sandbox venv holds `_host_env.pth` -> /root/buildenv, and
buildenv carries click (typer), Flask, Werkzeug, Jinja2, MarkupSafe and itsdangerous (pytest-httpbin -> httpbin ->
Flask) (pod/buildenv.sh). flit_core's editable install writes `<module>.pth` (flit_core/wheel.py:168 in the
competition's flit_core 3.12.0 wheel), which sorts AFTER `_host_env.pth`, so `import click` finds buildenv's click and
the task's /workspace/src code is never tested. This wrapper adds `__g4_src.pth` = /workspace/src (when the repo has a
src/ dir) to the sandbox venv; it sorts before `_host_env.pth`, exactly like pip's `__editable__.*.pth` finders do.
Flat-layout repos (rich, fastapi) have no src/ dir, so for them that line changes nothing.

G4_WHEELHOUSE=<absolute dir> (optional, e.g. data/pallets/harness/wheels from pack.py): the faithful install reads and
installs from that directory instead of /wheels. Needed because the subprocess sandbox copies a wheels dir to
<sandbox>/wheels/<dir name> (swegemma/sandbox/subprocess.py:197-198), one level too deep, so `/wheels` in commands falls
back to a literal /wheels (subprocess.py:458-479), which on a pod is the competition wheelhouse: a task set's own pinned
wheels (pallets' ephemeral-port-reserve, trio, asgiref, pytest 8.4.2, ...) would never be seen. The directory must NOT
lie under /tmp, /workspace, /usr/local/bin or /wheels: the subprocess sandbox rewrites those four prefixes in every
command to its own per-sandbox dirs (swegemma/sandbox/subprocess.py:436-479), so /tmp/h/wheels becomes
<sandbox>/tmp/h/wheels and the install fails (measured: the first pod_probe run packed to /tmp/h and every task logged
"FileNotFoundError: ... /swegemma_sandbox_<id>/tmp/h/wheels"). On the pod, /root/g4/data/pallets/harness/wheels is safe.
With G4_WHEELHOUSE set, the wrapper also installs <wheelhouse>/_extra-$REPO_PKG.txt (written by pack.py: the task venv's
freeze minus the repo's own package, --no-deps), so the sandbox holds the oracle venv's packages even when the repo does
not declare them where the faithful install looks (sympy before 2023 lists mpmath only in setup.py).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_eval  # noqa: E402

SRC_STEP = (
    'SP=$(python3 -c "import sysconfig;print(sysconfig.get_paths()[\'purelib\'])")\n'
    'if [ -d /workspace/src ]; then echo /workspace/src > "$SP/__g4_src.pth"; fi\n'
)
_orig_setup_script = run_eval.setup_script


EXTRA_STEP = (                    # pack.py's per-repo freeze minus the repo's own package; one pip call, per line on error
    'EX="{wh}/_extra-$REPO_PKG.txt"\n'
    'if [ -n "$REPO_PKG" ] && [ -f "$EX" ]; then\n'
    '  python3 -m pip install -q --no-index --find-links={wh} --no-deps -r "$EX" 2>>/tmp/_pip.err \\\n'
    '   || while read -r r; do python3 -m pip install -q --no-index --find-links={wh} --no-deps "$r" 2>>/tmp/_pip.err '
    '|| true; done < "$EX"\n'
    'fi\n'
)


HTTPBIN_STUB_STEP = (             # after SRC_STEP (uses $SP); src-layout task sandboxes only, see below
    'if [ -d /workspace/src ] && [ ! -e "$SP/pytest_httpbin" ] && python3 -c "import pytest_httpbin" 2>/dev/null; then\n'
    '  mkdir -p "$SP/pytest_httpbin" && : > "$SP/pytest_httpbin/__init__.py"\n'
    '  echo "# g4 stub (scripts/pallets/run_eval_pallets.py): pytest-httpbin disabled" > "$SP/pytest_httpbin/plugin.py"\n'
    'fi\n'
)
# Why the stub (research/pallets.md 7.2): /root/buildenv (pod/buildenv.sh, for the public requests tasks) holds
# pytest-httpbin, whose pytest11 entry point `httpbin = pytest_httpbin.plugin` is auto-loaded in every sandbox pytest run
# and imports httpbin, which builds a Flask app at import time. With __g4_src.pth that app's werkzeug is the TASK's
# /workspace/src/werkzeug, so werkzeug's tests/test_routing.py::test_no_memory_leak_from_Rule_builder counts 57 live
# Rule objects and fails (pod_probe_dev40: werkzeug_23142a3 gold `assert 57 == 0`), for every werkzeug task graded on
# test_routing.py. Kaggle's image has no pytest-httpbin (eval/kaggle/rescore_fair/pip_freeze.txt), so an empty plugin
# module in the sandbox venv (it precedes the _host_env.pth paths on sys.path) makes the pod MORE Kaggle-like.
# G4_PALLETS_HTTPBIN_STUB=0 turns it off.


def setup_script(no_editable=False):
    s = _orig_setup_script(no_editable)
    assert s.endswith(run_eval.SETUP_TAIL), "run_eval.setup_script layout changed; re-check this wrapper"
    wh = os.environ.get("G4_WHEELHOUSE", "").strip()
    extra = ""
    if wh:
        assert os.path.isabs(wh), "G4_WHEELHOUSE must be an absolute path"
        for pre in ("/tmp", "/workspace", "/usr/local/bin", "/wheels"):   # the sandbox rewrites these prefixes
            assert wh != pre and not wh.startswith(pre + "/"), f"G4_WHEELHOUSE must not lie under {pre}: {wh}"
        n = s.count("--find-links=/wheels") + s.count('os.listdir("/wheels")')
        assert n >= 3, "run_eval.setup_script no longer names /wheels as expected; re-check this wrapper"
        s = s.replace("--find-links=/wheels", f"--find-links={wh}").replace('os.listdir("/wheels")', f'os.listdir("{wh}")')
        extra = EXTRA_STEP.format(wh=wh)
    stub = HTTPBIN_STUB_STEP if os.environ.get("G4_PALLETS_HTTPBIN_STUB", "1") != "0" else ""
    return s[: -len(run_eval.SETUP_TAIL)] + extra + SRC_STEP + stub + run_eval.SETUP_TAIL


run_eval.setup_script = setup_script

if __name__ == "__main__":
    sys.exit(run_eval.main())
