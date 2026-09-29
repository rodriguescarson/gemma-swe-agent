"""Shared v10 test support (owned by helpers-core; other modules import it and never edit it).

- make_repo(tmp, files, *, baseline=True, exclude_lines=HARNESS_EXCLUDES): a git repo prepared the way the harness does
  it (git exclude lines, the harness pytest.ini and conftest hook, baseline commit, _swegemma_baseline tag).
- copy_helpers(tmp) -> Path: the bundle scripts copied to a temp dir (tests never run helpers inside submissions/).
- helper_env(ws, swe, fake_t=None) -> dict: a sandbox-like env (HOME=TMPDIR=TEST_TMPDIR=swe's parent, SWE_DIR=swe,
  PYTHONPATH=ws, SWE_DUAL=0, host /tmp and /workspace redirected to temp dirs).
- run_helper(scripts, name, args, *, ws, env, stdin=None, timeout=30) -> CompletedProcess (cwd=ws, PWD=ws).
- run_py(scripts, code, ...): run code with `import _swe_common as C` from the copied scripts, in a subprocess.
- run_as_skill(...): run a helper exactly like the ADK skill wrapper (skill_toolset.py:571-706).
- no_orphans: autouse fixture (import it into a test module to activate it) that fails a test when a process whose
  command line contains the test's tmp_path survives 1 s after the test (R120).
"""
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUNDLE = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10")   # G4_BUNDLE: run the v10 suite on a variant arm
SCRIPTS_SRC = BUNDLE / "skills" / "swe-tools" / "scripts"
PY = sys.executable
TAG = "_swegemma_baseline"

# container_setup.py:498-503 (setup_git_exclude)
HARNESS_EXCLUDES = ("__pycache__/", "*.pyc", ".pytest_cache/", "*.egg-info/", "build/", "dist/", ".coverage",
                    ".adk_exec_*.py")
# container_setup.py:872-924 (setup_workspace_test_config), verbatim
HARNESS_PYTEST_INI = ("[pytest]\naddopts = -p no:anyio\nnorecursedirs = .* build dist venv\npython_classes = Test* *Test\n"
                      "python_files = test_*.py *_test.py\nfilterwarnings =\n    ignore::DeprecationWarning\n"
                      "    ignore::UserWarning\n")
HARNESS_CONFTEST_HEADER = "# Hermetic test discovery hook for SWE-gemma\n"

DEFAULT_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def parse_header(x):\n    return x\n\n\ndef other(y):\n    return y + 1\n",
    "tests/test_mod.py": "from pkg.mod import parse_header\n\n\ndef test_p():\n    assert parse_header(1) == 1\n",
}


def _git_env(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="a@b",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="a@b", GIT_TERMINAL_PROMPT="0")
    if extra:
        e.update(extra)
    return e


def git(ws, *args, check=True, env=None, text=True):
    """Run git in ws with no user/system config (no hooks, no signing); returns stdout."""
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                        "-c", "core.hooksPath=" + os.devnull] + [str(a) for a in args], cwd=str(ws),
                       env=_git_env(env), capture_output=True, text=text)
    if check and r.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(map(str, args)), r.stderr))
    return r.stdout


def write_files(ws, files):
    for rel, data in (files or {}).items():
        p = pathlib.Path(ws) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(data)


def harness_test_config(ws):
    """What setup_workspace_test_config writes: pytest.ini unless one with [pytest] exists; the conftest hook header."""
    ws = pathlib.Path(ws)
    ini = ws / "pytest.ini"
    old = ini.read_text(errors="replace") if ini.exists() else ""
    if "# Hermetic test discovery" not in old and "[pytest]" not in old:
        ini.write_text(HARNESS_PYTEST_INI)
    cf = ws / "conftest.py"
    old = cf.read_text(errors="replace") if cf.exists() else ""
    if "# Hermetic test discovery hook for SWE-gemma" not in old and "# Standard test discovery hook for SWE-gemma" not in old:
        clean = old.replace(HARNESS_CONFTEST_HEADER, "").strip()
        cf.write_text(HARNESS_CONFTEST_HEADER + ("\n" + clean if clean else "") + "\n")


def make_repo(tmp, files=None, *, baseline=True, exclude_lines=HARNESS_EXCLUDES, name="ws", commit_time=None,
              harness_config=True):
    """A git repo at tmp/name with `files` ({rel: str | bytes}, default DEFAULT_FILES), prepared like the harness:
    exclude lines appended, pytest.ini and conftest hook written, everything committed and tagged _swegemma_baseline.
    commit_time (epoch seconds) backdates the baseline commit."""
    ws = pathlib.Path(tmp) / name
    ws.mkdir(parents=True, exist_ok=True)
    write_files(ws, DEFAULT_FILES if files is None else files)
    git(ws, "init", "-q")
    if exclude_lines:
        info = ws / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        with open(info / "exclude", "a") as f:
            f.write("".join(x + "\n" for x in exclude_lines))
    if harness_config:
        harness_test_config(ws)
    if baseline:
        env = None
        if commit_time is not None:
            d = "@%d +0000" % int(commit_time)
            env = {"GIT_COMMITTER_DATE": d, "GIT_AUTHOR_DATE": d}
        git(ws, "add", "-A")
        git(ws, "commit", "-qm", "baseline", "--allow-empty", env=env)
        git(ws, "tag", "-f", TAG)
    return ws


def commit_all(ws, msg="agent commit"):
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", msg, "--allow-empty")


def cli_scripts(src=SCRIPTS_SRC):
    """Stems of the CLI helpers currently in the bundle (every *.py not starting with '_')."""
    return sorted(p.stem for p in pathlib.Path(src).glob("*.py") if not p.name.startswith("_"))


def copy_helpers(tmp, src=SCRIPTS_SRC):
    """Copy the bundle's scripts (*.py only) into a fresh dir under tmp and return it."""
    tmp = pathlib.Path(tmp)
    d = tmp / "scripts"
    n = 1
    while d.exists():
        n += 1
        d = tmp / ("scripts%d" % n)
    d.mkdir(parents=True)
    for p in pathlib.Path(src).glob("*.py"):
        shutil.copyfile(p, d / p.name)
    return d


def helper_env(ws, swe, fake_t=None, **extra):
    """A sandbox-like environment for running helpers: HOME=TMPDIR=TEST_TMPDIR=<swe's parent>, SWE_DIR=swe,
    PYTHONPATH=ws, SWE_DUAL=0; the host /tmp and /workspace hooks point at temp dirs; SWE_FAKE_CLOCK=fake_t if given."""
    swe = pathlib.Path(swe)
    tmpd = swe.parent
    tmpd.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "USER", "LOGNAME", "SYSTEMROOT", "LD_LIBRARY_PATH")
           if k in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    env.update(HOME=str(tmpd), TMPDIR=str(tmpd), TEST_TMPDIR=str(tmpd), PYTHONNOUSERSITE="1",
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ws), SWE_DIR=str(swe), SWE_DUAL="0",
               SWE_DOCKER_TMP_FOR_TESTS=str(tmpd / "docker_tmp"), SWE_DOCKER_WS_FOR_TESTS=str(tmpd / "no_workspace"),
               GIT_CONFIG_NOSYSTEM="1", PYTHONIOENCODING="utf-8")
    if fake_t is not None:
        env["SWE_FAKE_CLOCK"] = str(fake_t)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _script(scripts, name):
    name = str(name)
    return pathlib.Path(scripts) / (name if name.endswith(".py") else name + ".py")


def run_helper(scripts, name, args=(), *, ws, env, stdin=None, timeout=30):
    """python3 <scripts>/<name>.py ARGS with cwd=ws (and PWD=ws, as bash exports it). stdin=None means /dev/null."""
    e = dict(env)
    e["PWD"] = str(ws)
    kw = {"stdin": subprocess.DEVNULL} if stdin is None else {"input": stdin}
    return subprocess.run([PY, str(_script(scripts, name))] + [str(a) for a in args], cwd=str(ws), env=e,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)


def run_py(scripts, code, *, env=None, cwd=None, stdin=None, timeout=30, pwd=None):
    """Run `code` in a fresh interpreter after `import _swe_common as C` from the copied scripts dir.
    pwd: None sets PWD=cwd (as bash does), False removes PWD, a string sets it."""
    prog = "import sys\nsys.path.insert(0, %r)\nimport _swe_common as C\n" % str(scripts) + code
    e = dict(env if env is not None else os.environ)
    if pwd is False:
        e.pop("PWD", None)
    elif pwd is not None:
        e["PWD"] = str(pwd)
    elif cwd is not None:
        e["PWD"] = str(cwd)
    kw = {"stdin": subprocess.DEVNULL} if stdin is None else ({"stdin": stdin} if not isinstance(stdin, str)
                                                               else {"input": stdin})
    return subprocess.run([PY, "-c", prog], cwd=str(cwd) if cwd else None, env=e, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, **kw)


def skill_wrapper_code(scripts, name, argv, pre_import=("json",)):
    """The self-extracting wrapper the ADK builds for run_skill_script (skill_toolset.py:571-706), for a .py script:
    every skill file inline, written under a TemporaryDirectory, chdir there, sys.argv = ['scripts/x.py', ...],
    runpy.run_path(..., run_name='__main__')."""
    files = {}
    for p in sorted(pathlib.Path(scripts).glob("*.py")):
        files["scripts/" + p.name] = p.read_text(encoding="utf-8")
    fp = "scripts/" + (name if str(name).endswith(".py") else name + ".py")
    lines = ["import os", "import tempfile", "import sys"]
    lines += ["import %s as _%s" % (m, m) for m in pre_import]
    lines += ["import subprocess", "import runpy",
              "_files = %r" % files,
              "def _materialize_and_run():",
              "  _orig_cwd = os.getcwd()",
              "  with tempfile.TemporaryDirectory() as td:",
              "    for rel_path, content in _files.items():",
              "      full_path = os.path.join(td, rel_path)",
              "      os.makedirs(os.path.dirname(full_path), exist_ok=True)",
              "      mode = 'wb' if isinstance(content, bytes) else 'w'",
              "      with open(full_path, mode) as f:",
              "        f.write(content)",
              "    os.chdir(td)",
              "    try:",
              "      sys.argv = %r" % ([fp] + [str(a) for a in argv]),
              "      try:",
              "        runpy.run_path(%r, run_name='__main__')" % fp,
              "      except SystemExit as e:",
              "        if e.code is not None and e.code != 0:",
              "          raise e",
              "    finally:",
              "      os.chdir(_orig_cwd)",
              "_materialize_and_run()"]
    return "\n".join(lines) + "\n"


def skill_args(args=None, positional=None):
    """argv as the wrapper builds it from dict args ('--k', str(v)) and positional_args ('--', ...)."""
    out = []
    for k, v in (args or {}).items():
        out += ["--%s" % k, str(v)]
    if positional:
        out.append("--")
        out += [str(v) for v in positional]
    return out


def run_as_skill(scripts, name, argv=(), *, ws, env, timeout=30, pre_import=("json",), pwd=True):
    """Execute a helper like run_skill_script: the wrapper file .adk_exec_<hex>.py in ws, run as `python3 <path>` with
    cwd=ws (so sys.path[0] is the workspace); PWD=ws unless pwd=False."""
    path = pathlib.Path(ws) / (".adk_exec_%s.py" % uuid.uuid4().hex[:8])
    path.write_text(skill_wrapper_code(scripts, name, argv, pre_import), encoding="utf-8")
    e = dict(env)
    if pwd:
        e["PWD"] = str(ws)
    else:
        e.pop("PWD", None)
    try:
        return subprocess.run([PY, str(path)], cwd=str(ws), env=e, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------------------------------- orphan guard
def list_processes():
    """[(pid, command line)] of every visible process (/proc on Linux, ps elsewhere)."""
    out = []
    if os.path.isdir("/proc/self"):
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % d, "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            except OSError:
                continue
            if cmd:
                out.append((int(d), cmd))
        return out
    r = subprocess.run(["ps", "-axww", "-o", "pid=", "-o", "command="], capture_output=True, text=True,
                       errors="replace")
    for line in r.stdout.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            out.append((int(pid), cmd.strip()))
    return out


MIN_MARKER = 16


def find_orphans(markers, exclude=()):
    """Processes (other than this one and `exclude`) whose command line contains any marker string. Markers shorter
    than MIN_MARKER chars are ignored: a marker must be unique to the test (a tmp path), because callers kill what
    this returns and a short marker like '25.5' can match an unrelated process."""
    ms = [str(m) for m in markers if m and len(str(m)) >= MIN_MARKER]
    if not ms:
        raise ValueError("find_orphans needs markers of %d+ chars (use the test's tmp path)" % MIN_MARKER)
    me = os.getpid()
    skip = set(exclude) | {me}
    return [(pid, cmd) for pid, cmd in list_processes()
            if pid not in skip and any(m in cmd for m in ms) and not cmd.startswith("ps -axww")]


def unique_sleep(tmp):
    """A `sleep` reachable under tmp (a symlink named with a random suffix): processes started through it carry the
    test's tmp path in their command line, so orphan checks can find them without matching anything else."""
    real = shutil.which("sleep") or "/bin/sleep"
    d = pathlib.Path(tmp) / "ubin"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("sleep_%s" % uuid.uuid4().hex[:8])
    os.symlink(real, str(p))
    return str(p)


def kill_processes(procs):
    for pid, _ in procs:
        for fn in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
            try:
                fn()
            except (ProcessLookupError, PermissionError, OSError):
                pass


@pytest.fixture(autouse=True)
def no_orphans(tmp_path):
    """Fail the test when a process whose command line contains its tmp_path is still alive 1 s after it (R120)."""
    yield
    markers = {str(tmp_path), os.path.realpath(str(tmp_path))}
    left = find_orphans(markers)
    end = time.monotonic() + 1.0
    while left and time.monotonic() < end:
        time.sleep(0.1)
        left = find_orphans(markers)
    if left:
        kill_processes(left)
        pytest.fail("orphan processes survived the test by 1 s: %s" % "; ".join("%d %s" % (p, c[:160]) for p, c in left))
