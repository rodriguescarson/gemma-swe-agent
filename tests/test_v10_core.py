"""helpers-core (SPEC 4.0-4.2, 4.14, 4.16): the shared contract of every helper and the pinned _swe_common API.

R01-R24, R28 and R120. Every test copies the bundle scripts to a temp dir first and runs them there as subprocesses
(no __pycache__ can appear in the bundle); _swe_common is imported in-process only for pure functions.
R03, R09 and R28 are parametrised over every CLI script present, so they grow as the other components land.
"""
import ast, importlib.util, json, os, pathlib, pty, re, shutil, subprocess, sys, textwrap, time
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.compat import VERSION, VERSION_RE, later_stage  # noqa: E402  (G4_BUNDLE may be v10.2)
from v10_support.repo import (no_orphans, make_repo, copy_helpers, helper_env, run_helper, run_py, run_as_skill,  # noqa: F401,E402
                              skill_args, cli_scripts, git, commit_all, find_orphans, kill_processes, unique_sleep,
                              SCRIPTS_SRC,
                              DEFAULT_FILES, PY, ROOT, TAG)

pytestmark = pytest.mark.skipif(not (SCRIPTS_SRC / "_swe_common.py").exists(), reason="_swe_common.py not built")

CLI = cli_scripts()
ALL_PY = sorted(SCRIPTS_SRC.glob("*.py"))
TOOL_NAMES = ("submit_patch", "read_file", "edit_file", "write_file", "get_status", "get_code_neighbors",
              "search_similar_code", "get_code_subgraph")

PREAMBLE = '''import os, sys
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
_STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
           and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
    del sys.modules[_n]
import _swe_common as C
'''

# How each known helper is called for a "normal" run: (argv, skill dict args, first-line regex).
EDIT_TEXT = "def other(y):\n    return y + 2\n"
CALLS = {
    "install": ([], {}, r"^swe-tools %s ready in /tmp/swe \(\d+ helpers\)" % VERSION_RE),
    "status": ([], {}, r"^STATUS \[t=\d+s\] helpers %s" % VERSION_RE),
    "run": (["--timeout", "5", "echo hi"], {"cmd": "echo hi", "timeout": 5}, r"^exit=0$"),
    "locate": (["parse_header"], {"query": "parse_header"}, r"^LOCATE:"),
    "grep": (["parse_header"], {"regex": "parse_header"}, r"^GREP:"),
    "view": (["pkg/mod.py", "1", "2"], {"file": "pkg/mod.py", "start": 1, "end": 2}, r"pkg/mod\.py"),
    "edit": (["pkg/mod.py", "--lines", "5-6", "--text", EDIT_TEXT],
             {"file": "pkg/mod.py", "lines": "5-6", "text": EDIT_TEXT}, r"^OK\b"),
    "verify": (["--list-tests"], {"list-tests": True}, r"^TESTS"),
    "finalize": ([], {}, r"^(NOT READY|READY)"),
}
REQUIRES_ARG = {"locate", "grep", "view", "edit", "run"}


# ------------------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
def scripts(tmp_path):
    return copy_helpers(tmp_path)


@pytest.fixture
def ws(tmp_path):
    return make_repo(tmp_path)


@pytest.fixture
def swe(tmp_path):
    return tmp_path / "sbx" / "swe"


@pytest.fixture
def env(ws, swe):
    return helper_env(ws, swe)


def base_env(**kw):
    """os.environ without the variables the helpers resolve paths from."""
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("SWE_", "PYTHON")) and k not in ("TMPDIR", "TEST_TMPDIR", "TMP", "TEMP", "PWD")}
    e.update(PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1")
    e.update({k: str(v) for k, v in kw.items()})
    return e


def py_json(scripts, code, **kw):
    r = run_py(scripts, code, **kw)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def load_common(scripts, name):
    spec = importlib.util.spec_from_file_location(name, str(scripts / "_swe_common.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def C(scripts, ws, swe, monkeypatch):
    """_swe_common imported in-process (pure functions only), bound to the test repo."""
    monkeypatch.setenv("SWE_WS", str(ws))
    monkeypatch.setenv("SWE_DIR", str(swe))
    monkeypatch.setenv("SWE_DUAL", "0")
    mod = load_common(scripts, "_swe_common_t%d" % os.getpid())
    mod._reset()
    return mod


def first_line(out):
    return out.splitlines()[0] if out.splitlines() else ""


# ----------------------------------------------------------------------------------------------------------------- R01
def _imports(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            yield n.module.split(".")[0]


def test_stdlib_only_py38_no_network():
    stdlib = set(sys.stdlib_module_names)
    siblings = {p.stem for p in ALL_PY}
    assert ALL_PY, "no helper scripts found"
    for p in ALL_PY:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(p), feature_version=(3, 8))
        for m in _imports(tree):
            assert m in stdlib or m in siblings, "%s imports non-stdlib module %s" % (p.name, m)
            assert m not in {"socket", "urllib", "http", "ssl", "ftplib"}, "%s imports network module %s" % (p.name, m)
        assert p.stem not in stdlib | {"pytest", "_pytest", "py"}, "%s shadows a module" % p.name


@pytest.mark.skipif(not os.path.exists("/usr/bin/python3"), reason="no system python3")
def test_scripts_compile_and_run_on_the_oldest_python_here(tmp_path, ws):
    """Runtime check of the py3.8 rule on an older interpreter (macOS: 3.9): compile every script, run core CLIs."""
    old = "/usr/bin/python3"
    ver = subprocess.run([old, "-c", "import sys; print(sys.version_info[:2] < (3, 12))"], capture_output=True,
                         text=True).stdout.strip()
    if ver != "True":
        pytest.skip("system python3 is not older than 3.12")
    scripts = copy_helpers(tmp_path)
    for p in sorted(scripts.glob("*.py")):
        r = subprocess.run([old, "-c", "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')", str(p)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (p.name, r.stderr)
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    for name, args, rx in (("install", [], r"^swe-tools v10"), ("run", ["echo hi"], r"^exit=0"),
                           ("status", [], r"^STATUS")):
        r = subprocess.run([old, str(scripts / (name + ".py"))] + args, cwd=str(ws), env=dict(env, PWD=str(ws)),
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        assert r.returncode == 0 and re.search(rx, r.stdout) and "HELPER ERROR" not in r.stdout, r.stdout + r.stderr
    assert not list(scripts.rglob("__pycache__"))


# ----------------------------------------------------------------------------------------------------------------- R02
def test_preamble_identical_and_first():
    spec = (ROOT / "docs/v10/SPEC.md")
    if spec.exists():                     # the constant here is the spec's text (section 4.0.1), dedented
        m = re.search(r"```python\n(   import os, sys\n.*?)   ```", spec.read_text(), re.S)
        assert m and textwrap.dedent(m.group(1)) == PREAMBLE
    assert CLI, "no CLI scripts"
    for name in CLI:
        src = (SCRIPTS_SRC / (name + ".py")).read_text(encoding="utf-8")
        body = src
        while body.startswith("#"):
            body = body.split("\n", 1)[1]
        assert body.startswith(PREAMBLE), "%s.py does not start with the verbatim preamble" % name
        tree = ast.parse(src)
        first = tree.body[:2]
        assert isinstance(first[1], ast.Assign) and ast.unparse(first[1]) == "sys.dont_write_bytecode = True"


# ----------------------------------------------------------------------------------------------------------------- R03
def shadow_source(name, marker, transparent):
    """A workspace module shadowing a stdlib one. It records (module, argv[0], whether _swe_common was loaded yet) on
    import; the transparent kind then replaces itself with the real stdlib module (interpreter start-up may import it
    before the preamble runs: site and .pth files), the opaque kind is empty."""
    rec = ("import sys as _s\n"
           "with open(%r, 'a') as _f:\n"
           "    _f.write('%%s\\t%%s\\t%%s\\n' %% (__name__, (getattr(_s, 'argv', None) or ['<startup>'])[0],\n"
           "                                   '_swe_common' in _s.modules))\n" % str(marker))
    if not transparent:
        return rec + "SHADOW = True\n"
    return rec + textwrap.dedent('''\
        import os as _o
        _here = _o.path.realpath(_o.path.dirname(_o.path.abspath(__file__)))
        _saved = _s.path[:]
        _s.path[:] = [p for p in _s.path if _o.path.realpath(p or ".") != _here]
        del _s.modules[__name__]
        try:
            _real = __import__(__name__)
        finally:
            _s.path[:] = _saved
        _s.modules[__name__] = _real
        globals().update({k: v for k, v in _real.__dict__.items() if not k.startswith("__")})
        ''')


SHADOWS = ("json", "types", "select", "signal", "tempfile")


@pytest.mark.parametrize("mode", ["pythonpath", "skill_wrapper"])
@pytest.mark.parametrize("helper", CLI)
def test_stdlib_shadow_immunity(helper, mode, tmp_path):
    marker = tmp_path / "shadow_hits.txt"
    files = dict(DEFAULT_FILES)
    for n in SHADOWS:
        files[n + ".py"] = shadow_source(n, marker, transparent=not (mode == "skill_wrapper" and n == "json"))
    ws = make_repo(tmp_path, files)
    scripts = copy_helpers(tmp_path)
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    argv, sargs, rx = CALLS.get(helper, ([], {}, None))
    if mode == "pythonpath":
        r = run_helper(scripts, helper, argv, ws=ws, env=env, timeout=60)
    else:
        r = run_as_skill(scripts, helper, skill_args(sargs), ws=ws, env=env, timeout=60)
    out = r.stdout
    assert r.returncode == 0, out + r.stderr
    assert "HELPER ERROR" not in out and "Traceback" not in out + r.stderr, out + r.stderr
    if rx:
        assert re.search(rx, first_line(out)), out
    hits = marker.read_text().splitlines() if marker.exists() else []
    # imports once _swe_common is loading/loaded (after the preamble) are the helper's own; start-up ones are not
    bad = [h for h in hits if h.endswith("\tTrue")]
    assert not bad, "the helper itself imported a workspace shadow module: %s" % bad


# ----------------------------------------------------------------------------------------------------------------- R04
PATH_LIT = re.compile(r"(?<![\w.-])/(tmp|workspace)(?![\w.-])")
PATH_WHITELIST = {"DOCKER_TMP", "DOCKER_WS", "DISPLAY_SWE", "SANDBOX_REWRITES"}


def _docstring_ids(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                ids.add(id(b.value))
    return ids


def path_literal_violations(src):
    tree = ast.parse(src)
    skip = _docstring_ids(tree)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id in PATH_WHITELIST for t in targets):
                skip |= {id(x) for x in ast.walk(n.value)}
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)) and id(n) not in skip:
            s = n.value.decode("latin-1") if isinstance(n.value, bytes) else n.value
            for m in PATH_LIT.finditer(s):
                if not (m.group(1) == "tmp" and s[m.end():m.end() + 4] == "/swe"):
                    bad.append((getattr(n, "lineno", 0), s[:80]))
    return bad


def test_no_path_literals():
    assert path_literal_violations('x = "/tmp/a"\n') and path_literal_violations('x = ["/workspace"]\n')
    assert not path_literal_violations('DOCKER_TMP = "/tmp"\nx = "see /tmp/swe/last.log"\ny = "/tmpfoo"\n')
    for p in ALL_PY:
        bad = path_literal_violations(p.read_text(encoding="utf-8"))
        assert not bad, "%s uses /tmp or /workspace path literals: %s" % (p.name, bad)


# ----------------------------------------------------------------------------------------------------------------- R05
DESTRUCTIVE = [re.compile(x) for x in (r"\breset\b.*--hard", r"\bstash\b", r"\bcheckout\s+(--\s+)?\.(\s|$)",
                                       r"\bcheckout\b.*\s--\s+\.(\s|$)", r"\bclean\s+(-\w+\s+)*-\w*f\w*(\s+-\w+)*\s*$")]


def destructive_git(src):
    tree = ast.parse(src)
    texts = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            texts.append(n.value)
        elif isinstance(n, (ast.List, ast.Tuple)) and any(isinstance(e, ast.Constant) for e in n.elts):
            texts.append(" ".join(e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else "<x>"
                                  for e in n.elts))
    return [t for t in texts if any(r.search(t) for r in DESTRUCTIVE)]


def test_no_destructive_git(tmp_path, scripts, ws, env):
    for bad in ('x = ["git", "reset", "--hard"]', 'x = "git stash"', 'x = ["checkout", "--", "."]',
                'x = "git clean -fd"', 'x = ["git", "checkout", "."]'):
        assert destructive_git(bad), bad
    assert not destructive_git('x = ["checkout", b, "--", p]\ny = ["clean", "-f", "--", p]')
    for p in ALL_PY:
        found = destructive_git(p.read_text(encoding="utf-8"))
        assert not found, "%s: destructive git %s" % (p.name, found)
    # dynamic: every checkout <baseline> -- names exactly one path (a fake git logs every call)
    calls = git_log_calls(tmp_path, scripts, ws, env, _dirty_protected)
    checkouts = [c for c in calls if "checkout" in c]
    assert len(checkouts) >= 3
    for c in checkouts:
        assert c[c.index("--") + 1:] and len(c[c.index("--") + 1:]) == 1, c


def fake_git(tmp_path):
    real = shutil.which("git")
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    log = tmp_path / "git_calls.log"
    (d / "git").write_text('#!/bin/bash\n{ for a in "$@"; do printf \'%%s\\x1f\' "$a"; done; printf \'\\n\'; } >> %s\n'
                           'exec %s "$@"\n' % (log, real))
    (d / "git").chmod(0o755)
    return d, log


def git_log_calls(tmp_path, scripts, ws, env, prepare, code="print(json.dumps(C.hygiene_revert()))"):
    prepare(ws)
    d, log = fake_git(tmp_path)
    e = dict(env, PATH="%s:%s" % (d, env["PATH"]))
    r = run_py(scripts, "import json\n" + code, env=e, cwd=ws)
    assert r.returncode == 0, r.stdout + r.stderr
    return [ln.split("\x1f")[:-1] for ln in log.read_text().splitlines()]


def _dirty_protected(ws):
    (ws / "tests/test_mod.py").write_text("def test_p():\n    assert False\n")
    (ws / "pytest.ini").write_text("[pytest]\naddopts = -x\n")
    (ws / "conftest.py").unlink()
    (ws / "pkg/mod.py").write_text("def parse_header(x):\n    return x * 2\n")


# ----------------------------------------------------------------------------------------------------------------- R06
SWE_CASES = ["swe_dir_env", "test_tmpdir", "tmpdir_only", "tempfile_fallback", "docker_like", "subprocess_sandbox",
             "installed"]


@pytest.mark.parametrize("case", SWE_CASES)
def test_swe_dir_resolution(case, tmp_path, scripts, ws):
    t = tmp_path
    for d in ("a", "b", "c", "d", "root/tmp", "elsewhere", "swegemma_sandbox_abc/tmp", "dockertmp"):
        (t / d).mkdir(parents=True, exist_ok=True)
    kw = {"SWE_DOCKER_TMP_FOR_TESTS": t / "dockertmp", "SWE_WS": ws}
    want, targets = None, None
    if case == "swe_dir_env":
        kw.update(SWE_DIR=t / "a/swe", TEST_TMPDIR=t / "b", TMPDIR=t / "c")
        want, targets = t / "a/swe", [t / "a/swe"]
    elif case == "test_tmpdir":
        kw.update(TEST_TMPDIR=t / "b", TMPDIR=t / "c")
        want, targets = t / "b/swe", [t / "b/swe"]
    elif case == "tmpdir_only":
        kw.update(TMPDIR=t / "c")
        want, targets = t / "c/swe", [t / "c/swe", t / "dockertmp/swe"]
    elif case == "tempfile_fallback":
        kw.update(TMP=t / "d")                 # tempfile.gettempdir() honours TMP when TMPDIR is unset
        want, targets = t / "d/swe", [t / "d/swe", t / "dockertmp/swe"]
    elif case == "docker_like":
        kw.update(TEST_TMPDIR=t / "root/tmp", TMPDIR=t / "elsewhere")
        want, targets = t / "root/tmp/swe", [t / "root/tmp/swe"]
    elif case == "subprocess_sandbox":
        s = t / "swegemma_sandbox_abc/tmp"
        kw.update(TEST_TMPDIR=s, TMPDIR=s)
        want, targets = s / "swe", [s / "swe"]
    elif case == "installed":
        (scripts / "VERSION").write_text("v10.1\n")
        kw.update(SWE_DIR=t / "a/swe", TMPDIR=t / "c")
        want, targets = scripts, [t / "a/swe"]
    got = py_json(scripts, "import json; print(json.dumps([C.swe_dir(), C.install_targets(), C.in_rewriting_sandbox()]))",
                  env=base_env(**kw), cwd=ws)
    assert os.path.realpath(got[0]) == os.path.realpath(want)
    assert [os.path.realpath(x) for x in got[1]] == [os.path.realpath(x) for x in targets]
    assert got[2] == (case == "subprocess_sandbox")


# ----------------------------------------------------------------------------------------------------------------- R07

def _start_cost(n=3):
    """Median wall time of a bare interpreter start on this machine now. Wall-clock budgets below scale with it, so a
    loaded host (a parallel test run, other jobs) does not fail them while an unloaded one keeps the original bound."""
    t = []
    for _ in range(n):
        t0 = time.monotonic()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        t.append(time.monotonic() - t0)
    return sorted(t)[n // 2]

def test_install_contract(tmp_path, scripts, ws, swe, env):
    t0 = time.monotonic()
    r = run_helper(scripts, "install", [], ws=ws, env=env)
    wall = time.monotonic() - t0
    out = r.stdout
    assert r.returncode == 0 and r.stderr == ""
    assert re.match(r"^swe-tools %s ready in /tmp/swe \((\d+) helpers\)\. Next: python3 /tmp/swe/locate\.py " % VERSION_RE,
                    out)
    assert int(re.search(r"\((\d+) helpers\)", out).group(1)) == len(CLI)
    assert len(out.rstrip("\n")) <= 400 and out.rstrip("\n").splitlines()[-1].startswith("[t=")
    for p in scripts.glob("*.py"):
        dst = swe / p.name
        assert dst.read_bytes() == p.read_bytes(), p.name
        assert (dst.stat().st_mode & 0o777) == 0o644
    assert (swe / "VERSION").read_text().strip() == VERSION
    assert float((swe / "t0").read_text()) > 0
    libs = sorted(p.stem for p in scripts.glob("_*.py"))              # libraries precompiled in $SWE, never the bundle
    assert sorted(p.name.split(".")[0] for p in (swe / "__pycache__").glob("*.pyc")) == libs
    assert not list(scripts.rglob("__pycache__")) and not list(SCRIPTS_SRC.rglob("__pycache__"))
    assert not [p for p in swe.iterdir() if ".tmp." in p.name]
    assert not list(ws.glob("*.py")) or set(p.name for p in ws.glob("*.py")) == {"conftest.py"}
    assert git(ws, "status", "--porcelain") == ""                       # never touches the workspace
    base = _start_cost()
    assert wall <= 0.3 + max(0.2, 3 * base), (wall, base)              # 300 ms budget (+ interpreter start slack)
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in swe.iterdir() if p.is_file()}
    time.sleep(0.02)
    r2 = run_helper(scripts, "install", [], ws=ws, env=env)
    assert r2.returncode == 0 and "ready in /tmp/swe" in r2.stdout
    for p in swe.iterdir():
        if p.name in before and p.name not in ("state.json", "journal.jsonl", "last.log", "state.lock"):
            assert (p.stat().st_mtime_ns, p.read_bytes()) == before[p.name], "rewrote %s" % p.name
    # a malformed call (stray arguments) still installs
    r3 = run_helper(scripts, "install", ["--whatever", "x"], ws=ws, env=env)
    assert r3.returncode == 0 and "ready in /tmp/swe" in r3.stdout


def test_install_timing_budget(tmp_path, scripts, ws, env):
    run_helper(scripts, "install", [], ws=ws, env=env)
    walls = []
    for _ in range(5):
        t0 = time.monotonic()
        r = run_helper(scripts, "install", [], ws=ws, env=env)
        walls.append(time.monotonic() - t0)
        assert r.returncode == 0
    base = _start_cost()
    assert sorted(walls)[2] <= 0.3 + 2 * base, (walls, base)


# ----------------------------------------------------------------------------------------------------------------- R08
@pytest.mark.parametrize("case", ["dual", "test_tmpdir_set", "rewriting_sandbox", "swe_dual_0", "swe_dir_set",
                                  "docker_tmp_missing"])
def test_install_dual_target(case, tmp_path, scripts, ws):
    t = tmp_path
    dock = t / "dockertmp"
    dock.mkdir()
    kw = {"TMPDIR": t / "c", "SWE_DOCKER_TMP_FOR_TESTS": dock, "HOME": t / "c"}
    (t / "c").mkdir()
    prim = t / "c/swe"
    if case == "test_tmpdir_set":
        (t / "b").mkdir()
        kw["TEST_TMPDIR"] = t / "b"
        prim = t / "b/swe"
    elif case == "rewriting_sandbox":
        s = t / "swegemma_sandbox_q1/tmp"
        s.mkdir(parents=True)
        kw.update(TMPDIR=s, TEST_TMPDIR=s)
        prim = s / "swe"
    elif case == "swe_dual_0":
        kw["SWE_DUAL"] = "0"
    elif case == "swe_dir_set":
        kw["SWE_DIR"] = t / "a/swe"
        prim = t / "a/swe"
    elif case == "docker_tmp_missing":
        kw["SWE_DOCKER_TMP_FOR_TESTS"] = t / "nope"
    e = base_env(**kw)
    r = subprocess.run([PY, str(scripts / "install.py")], cwd=str(ws), env=dict(e, PWD=str(ws)), capture_output=True,
                       text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0 and "ready in /tmp/swe" in r.stdout, r.stdout + r.stderr
    names = sorted(p.name for p in scripts.glob("*.py"))
    assert sorted(p.name for p in prim.glob("*.py")) == names and (prim / "VERSION").exists()
    dual_written = (dock / "swe").exists()
    assert dual_written == (case == "dual"), case
    if dual_written:
        assert sorted(p.name for p in (dock / "swe").glob("*.py")) == names
        assert (dock / "swe/VERSION").read_text().strip() == VERSION and (dock / "swe/t0").exists()


# ----------------------------------------------------------------------------------------------------------------- R09
@pytest.mark.parametrize("helper", CLI)
def test_bootstrap_from_skill_dir(helper, tmp_path, scripts, ws, swe, env):
    e = dict(env)
    e.pop("SWE_DIR")                                   # swe_dir() must come from TEST_TMPDIR, like the real sandbox
    argv, sargs, rx = CALLS.get(helper, ([], {}, None))
    r = run_as_skill(scripts, helper, skill_args(sargs), ws=ws, env=e, timeout=60)
    assert r.returncode == 0 and "HELPER ERROR" not in r.stdout and "Traceback" not in r.stdout + r.stderr, \
        r.stdout + r.stderr
    if rx:
        assert re.search(rx, first_line(r.stdout)), r.stdout
    for p in scripts.glob("*.py"):
        assert (swe / p.name).read_bytes() == p.read_bytes(), "bootstrap did not install %s" % p.name
    assert (swe / "VERSION").read_text().startswith("v10")
    assert not list(ws.glob(".adk_exec_*")) and r.stderr == ""


def test_bootstrap_finds_ws_without_pwd(tmp_path, scripts, ws, swe, env):
    """The skill wrapper keeps sys.path[0] = workspace (SWE_PATH0) even when PWD is not exported."""
    e = dict(env)
    e.pop("SWE_DIR")
    mod = ws / "pkg/mod.py"
    mod.write_text(mod.read_text().replace("    return x\n", "    return x + 1\n", 1))
    r = run_as_skill(scripts, "status", [], ws=ws, env=e, pwd=False)
    assert r.returncode == 0 and "DIFF: pkg/mod.py +1 -1" in r.stdout, r.stdout + r.stderr


# ----------------------------------------------------------------------------------------------------------------- R10
WS_CASES = ["cwd", "cwd_subdir", "pwd", "swe_path0", "decoy_only", "swe_ws", "base_worktree_skipped",
            "no_walk_out_of_tmpdir"]


@pytest.mark.parametrize("case", WS_CASES)
def test_ws_resolution_with_decoy(case, tmp_path, scripts):
    t = tmp_path
    ws = make_repo(t, name="ws")
    decoy = make_repo(t, name="decoy")                  # stands in for a /workspace that is not the task repo
    tmpd = t / "sbx"
    other = tmpd / "tmpq12"                              # like the skill wrapper's TemporaryDirectory
    other.mkdir(parents=True)
    kw = {"TMPDIR": tmpd, "TEST_TMPDIR": tmpd, "SWE_DIR": tmpd / "swe", "SWE_DOCKER_WS_FOR_TESTS": decoy}
    cwd, pwd, want = other, False, ws
    if case == "cwd":
        cwd = ws
    elif case == "cwd_subdir":
        cwd = ws / "pkg"
    elif case == "pwd":
        pwd = str(ws)
    elif case == "swe_path0":
        kw["SWE_PATH0"] = ws
    elif case == "decoy_only":
        want = decoy
    elif case == "swe_ws":
        ws2 = make_repo(t, name="ws2")
        kw["SWE_WS"] = ws2
        cwd, want = ws, ws2
    elif case == "base_worktree_skipped":
        base = tmpd / "swe" / "base"
        git(ws, "worktree", "add", "--detach", "-f", str(base), TAG)
        cwd, pwd = base, str(ws)
    elif case == "no_walk_out_of_tmpdir":
        inner = decoy / "tmpd"                          # TMPDIR inside another repo must not make that repo the ws
        (inner / "tmpabc").mkdir(parents=True)
        kw.update(TMPDIR=inner, TEST_TMPDIR=inner, SWE_DIR=inner / "swe")
        cwd, pwd = inner / "tmpabc", str(ws)
    got = py_json(scripts, "import json; print(json.dumps(C.ws()))", env=base_env(**kw), cwd=cwd, pwd=pwd)
    assert os.path.realpath(got) == os.path.realpath(want), case


# ----------------------------------------------------------------------------------------------------------------- R11
def test_baseline_after_agent_commit(tmp_path, scripts, ws, env):
    tag = git(ws, "rev-parse", TAG).strip()
    mod = ws / "pkg/mod.py"
    mod.write_text(mod.read_text().replace("    return x\n", "    return x * 3\n", 1))
    commit_all(ws, "agent commit")                                       # HEAD moves, the tag does not
    assert git(ws, "rev-parse", "HEAD").strip() != tag
    got = py_json(scripts, "import json; ch = C.changes(); d = C.diff_bytes()\n"
                           "print(json.dumps([C.baseline(), ch['source'], d.decode()]))", env=env, cwd=ws)
    assert got[0] == tag and got[1] == ["pkg/mod.py"] and "+    return x * 3" in got[2]
    if (scripts / "verify.py").exists():
        r = run_helper(scripts, "verify", [], ws=ws, env=env, timeout=90)
        assert "NO SOURCE CHANGE" not in first_line(r.stdout), r.stdout
    if (scripts / "finalize.py").exists():
        r = run_helper(scripts, "finalize", [], ws=ws, env=env, timeout=60)
        assert "EMPTY" not in r.stdout and "READY" in r.stdout, r.stdout
    r = run_helper(scripts, "status", [], ws=ws, env=env)
    assert "DIFF: pkg/mod.py +1 -1" in r.stdout


def test_baseline_without_tag_is_head_at_first_call(tmp_path, scripts):
    ws = make_repo(tmp_path, name="notag")
    git(ws, "tag", "-d", TAG)
    head = git(ws, "rev-parse", "HEAD").strip()
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    assert py_json(scripts, "import json; print(json.dumps(C.baseline()))", env=env, cwd=ws) == head
    (ws / "pkg/mod.py").write_text("x = 1\n")
    commit_all(ws)
    got = py_json(scripts, "import json; print(json.dumps([C.baseline(), C.changes()['source']]))", env=env, cwd=ws)
    assert got == [head, ["pkg/mod.py"]]


# ----------------------------------------------------------------------------------------------------------------- R12
CLOCK_CASES = ["commit_now", "old_commit_tag_mtime", "old_commit_old_tag_t0", "fake_clock", "scale_1_7",
               "scale_clamped_high", "scale_clamped_low", "packed_repo_git_fallback"]


@pytest.mark.parametrize("case", CLOCK_CASES)
def test_clock_sources_and_scale(case, tmp_path, scripts):
    now = time.time()
    old = case not in ("commit_now", "fake_clock", "packed_repo_git_fallback")
    ws = make_repo(tmp_path, commit_time=now - 2000 if old else None)
    swe = tmp_path / "sbx" / "swe"
    env = helper_env(ws, swe)
    swe.mkdir(parents=True)
    tagf = ws / ".git/refs/tags" / TAG
    if old:
        os.utime(tagf, (now - 100, now - 100))
    want, tol = 0.0, 3.0
    if case == "old_commit_tag_mtime":
        want = 100
    elif case == "old_commit_old_tag_t0":
        os.utime(tagf, (now - 2000, now - 2000))
        (swe / "t0").write_text(repr(now - 50))
        want = 50
    elif case == "fake_clock":
        env["SWE_FAKE_CLOCK"] = "123.5"
        want, tol = 123.5, 0.0
    elif case == "scale_1_7":
        (swe / "clock_scale").write_text("1.7")
        want, tol = 170, 5
    elif case == "scale_clamped_high":
        (swe / "clock_scale").write_text("10")
        want, tol = 500, 15
    elif case == "scale_clamped_low":
        (swe / "clock_scale").write_text("0.01")
        want, tol = 20, 2
    elif case == "packed_repo_git_fallback":
        git(ws, "gc", "-q", "--prune=now")                  # no loose commit object, packed tag: git log fallback
        assert not tagf.exists()
    got = py_json(scripts, "import json; print(json.dumps(C.clock()))", env=env, cwd=ws)
    assert abs(got - want) <= tol, (case, got, want)
    if case != "fake_clock":
        assert (swe / "t0").exists()                        # written once by any helper


# ----------------------------------------------------------------------------------------------------------------- R13
@pytest.mark.parametrize("clock,scale,d,want", [
    (0, None, 60, 60.0), (250, None, 60, 46.0), (290, None, 60, 6.0), (299, None, 60, 1.0), (400, None, 60, 1.0),
    (0, 1.7, 200, 300 / 1.7 - 4), (200, 2.0, 60, 46.0), (100, 0.5, 60, 60.0), (280, 0.5, 60, 36.0)])
def test_real_budget_clamp(clock, scale, d, want, tmp_path, scripts, ws, swe):
    env = helper_env(ws, swe, fake_t=clock)
    swe.mkdir(parents=True, exist_ok=True)
    if scale is not None:
        (swe / "clock_scale").write_text(str(scale))
    got = py_json(scripts, "import json; print(json.dumps(C.real_budget(%r)))" % d, env=env, cwd=ws)
    assert abs(got - want) < 1e-6
    assert abs(got - min(d, max(1, (300 - clock) / (scale or 1.0) - 4))) < 1e-6


# ----------------------------------------------------------------------------------------------------------------- R14
def test_sh_killpg_reap_and_cap(tmp_path, scripts, ws, env):
    S = unique_sleep(tmp_path)
    code = textwrap.dedent('''\
        import json, time
        S = %r
        res = {}
        t = time.monotonic(); rc, out = C.sh("%%s 30 & bash -c '%%s 20' & echo started; %%s 25" %% (S, S, S), 1)
        res["timeout"] = [rc, out, time.monotonic() - t]
        t = time.monotonic(); rc, out = C.sh("%%s 31 & echo hi" %% S, 10)
        res["bg"] = [rc, out, time.monotonic() - t]
        t = time.monotonic(); rc, out = C.sh("cat; echo done", 5)
        res["stdin"] = [rc, out, time.monotonic() - t]
        rc, out = C.sh([sys.executable, "-c", "import os; print(os.getsid(0) == os.getpid())"], 5)
        res["session"] = [rc, out]
        rc, out = C.sh([sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000000); print('END')"], 30)
        res["cap"] = [rc, len(out), out[-60:]]
        res["missing"] = list(C.sh(["/nonexistent/binary/x"], 5))
        rc, out = C.sh("exit 7", 5)
        res["rc"] = rc
        print(json.dumps(res))
        ''' % S)
    t0 = time.monotonic()
    res = py_json(scripts, code, env=env, cwd=ws, timeout=60)
    rc, out, secs = res["timeout"]
    assert rc is None and "started" in out and secs < 1 + 2, res["timeout"]
    rc, out, secs = res["bg"]
    assert rc == 0 and out.strip() == "hi" and secs < 1.5, res["bg"]
    rc, out, secs = res["stdin"]
    assert rc == 0 and out.strip() == "done" and secs < 1.5
    assert res["session"] == [0, "True\n"]
    rc, n, tail = res["cap"]
    assert rc == 0 and n <= (4 << 20) + 64 and tail.endswith("[output cut at 4 MB]")
    assert res["missing"][0] == 127 and "cannot run" in res["missing"][1]
    assert res["rc"] == 7
    time.sleep(0.5)
    left = find_orphans([S])
    kill_processes(left)
    assert not left, left
    assert time.monotonic() - t0 < 30


def test_sh_many_concurrency_and_deadline(tmp_path, scripts, ws, env):
    run = tmp_path / "running"
    run.mkdir()
    counts = tmp_path / "counts"
    job = "touch %s/$$; ls %s | wc -l >> %s; sleep 0.3; rm %s/$$; echo job" % (run, run, counts, run)
    code = textwrap.dedent('''\
        import json, time
        t = time.monotonic()
        res = C.sh_many([%r] * 5, 10)
        wall = time.monotonic() - t
        late = C.sh_many([("sleep 0.6", 5)] * 5, 0.5)
        print(json.dumps([res, wall, late]))
        ''' % job)
    res, wall, late = py_json(scripts, code, env=env, cwd=ws)
    assert [r[0] for r in res] == [0] * 5 and all("job" in r[1] for r in res)
    assert max(int(x) for x in counts.read_text().split()) <= 2          # MAX_PAR
    assert 0.85 <= wall < 3.0, wall                                       # ceil(5/2) * 0.3 s
    assert sum(1 for r in late if r[0] is None) >= 3                      # deadline bounds unfinished and unstarted jobs


# ----------------------------------------------------------------------------------------------------------------- R15
READ = ("import json, time\nt = time.monotonic(); s = C.read_stdin(); dt = time.monotonic() - t\n"
        "print(json.dumps([s, dt]))\n")


def _read_stdin_with(scripts, env, **popen_kw):
    prog = "import sys\nsys.path.insert(0, %r)\nimport _swe_common as C\n" % str(scripts) + READ
    return subprocess.run([PY, "-c", prog], env=env, capture_output=True, text=True, timeout=30, **popen_kw)


def test_read_stdin_never_blocks(tmp_path, scripts, ws, env):
    # TTY
    master, slave = pty.openpty()
    try:
        r = _read_stdin_with(scripts, env, stdin=slave)
    finally:
        os.close(master)
        os.close(slave)
    s, dt = json.loads(r.stdout)
    assert s == "" and dt < 0.2, r.stdout + r.stderr
    # /dev/null
    s, dt = json.loads(_read_stdin_with(scripts, env, stdin=subprocess.DEVNULL).stdout)
    assert s == "" and dt < 0.05
    # an inherited pipe nobody writes to or closes
    prog = "import sys\nsys.path.insert(0, %r)\nimport _swe_common as C\n" % str(scripts) + READ
    p = subprocess.Popen([PY, "-c", prog], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        out = p.stdout.read()
        p.wait(10)
    finally:
        p.stdin.close()
    s, dt = json.loads(out)
    assert s == "" and dt <= 1.2, dt
    # closed stdin
    r = subprocess.run(["bash", "-c", '"$0" -c "$1" <&-', PY, prog], env=env, capture_output=True, text=True)
    assert json.loads(r.stdout)[0] == ""
    # 1 MB heredoc read completely
    big = "".join("line %06d %s\n" % (i, "x" * 40) for i in range(20000))
    assert len(big) > 1 << 20
    s, dt = json.loads(_read_stdin_with(scripts, env, input=big).stdout)
    assert s == big
    # a real bash heredoc, and the heredoc junk the model leaves behind
    r = subprocess.run(["bash", "-c", '"$0" -c "$1" <<\'EOF\'\nprint("/tmp/x")\n\n  y = 1\nEOF\n', PY, prog],
                       env=env, capture_output=True, text=True)
    assert json.loads(r.stdout)[0] == 'print("/tmp/x")\n\n  y = 1\n'
    for raw, want in [("a\nb\nEOF\n", "a\nb\n"), ("a\nSWE_EOF\n", "a\n"), ("a\nEOF.\n", "a\n"), ("a\n```\n", "a\n"),
                      ("a\nEOF\n```\n\n", "a\n"), ("a\r\nb\r\n", "a\nb\n"), ("EOF here\nx\n", "EOF here\nx\n"),
                      ("x\n\nEOF\n", "x\n\n"), ("x", "x"), ("EOF\n", ""), ("a\n`\n", "a\n"), ("a\nEOF'\n", "a\n")]:
        s, _ = json.loads(_read_stdin_with(scripts, env, input=raw).stdout)
        assert s == want, (raw, s)


# ----------------------------------------------------------------------------------------------------------------- R16
F = {"file": "str", "start": "int", "end": "int", "lines": "range", "create": "bool", "tests": "list",
     "text": "str", "timeout": "int", "repro-only": "bool", "query": "str"}


def test_parse_args_forms(C):
    P = C.parse_args
    pos = P(["a.py", "10", "20"], F, ["file", "start", "end"], usage="U")
    key = P(["--file", "a.py", "--start", "10", "--end", "20"], F, ["file", "start", "end"], usage="U")
    eq = P(["--file=a.py", "--start=10", "--end=20"], F, ["file", "start", "end"], usage="U")
    mixed = P(["a.py", "--start", "10", "20"], F, ["file", "start", "end"], usage="U")
    wrapper = P(["--file", "a.py", "--", "10", "20"], F, ["file", "start", "end"], usage="U")
    for r in (pos, key, eq, mixed, wrapper):
        assert (r["file"], r["start"], r["end"]) == ("a.py", 10, 20) and r["_"] == []
    # booleans: bare, valued (the wrapper passes str(True)), inline
    for argv, want in ([["--create"], True], [["--create", "True"], True], [["--create", "1"], True],
                       [["--create", "yes"], True], [["--create", "false"], False], [["--create=no"], False],
                       [["--create", "0"], False], [[], False]):
        assert P(argv, F, usage="U")["create"] is want, argv
    r = P(["--create", "x.py"], F, ["file"], usage="U")
    assert r["create"] is True and r["file"] == "x.py"
    # lists
    assert P(["--tests", "a.py", "b.py", "--create"], F, usage="U")["tests"] == ["a.py", "b.py"]
    assert P(["--tests", "a.py, b.py"], F, usage="U")["tests"] == ["a.py", "b.py"]
    assert P(["--tests", "['a.py', 'b.py']"], F, usage="U")["tests"] == ["a.py", "b.py"]
    assert P(["--tests", "t.py::test_x[a b]", "c.py"], F, usage="U")["tests"] == ["t.py::test_x[a b]", "c.py"]
    assert P([], F, usage="U")["tests"] == []
    # --text keeps newlines and quotes; ranges
    assert P(["--text", 'x = "a"\ny = 1\n'], F, usage="U")["text"] == 'x = "a"\ny = 1\n'
    for v, want in (("120-135", (120, 135)), ("120:135", (120, 135)), ("L120-L135", (120, 135)), ("7", (7, 7)),
                    ("3..9", (3, 9))):
        r = P(["--lines", v], F, usage="U")["lines"]
        assert tuple(r) == want and str(r) == "%d-%d" % want
    r = P(["--lines", "abc"], F, usage="U")
    assert r["lines"] == "abc" and r["_bad"] == {"lines": "abc"}
    # ints: tolerant forms, invalid -> None + note
    assert P(["--timeout", "20s"], F, usage="U")["timeout"] == 20
    assert P(["--timeout", "20.0"], F, usage="U")["timeout"] == 20
    r = P(["--timeout", "abc"], F, usage="U")
    assert r["timeout"] is None and "timeout" in r["_bad"] and r["_notes"]
    # key spellings
    r = P(["--repro_only"], F, usage="U")
    assert r["repro-only"] is True and r["repro_only"] is True and r.repro_only is True and "repro_only" in r
    # unknown flags and missing values
    with pytest.raises(C.UsageError) as ei:
        P(["--bogus", "1"], F, usage="python3 /tmp/swe/x.py")
    assert str(ei.value) == "USAGE ERROR: unknown option --bogus. Usage: python3 /tmp/swe/x.py"
    assert P(["--bogus", "a.py"], F, ["file"], usage="U", strict=False)["_unknown"] == ["--bogus"]
    with pytest.raises(C.UsageError):
        P(["--timeout"], F, usage="U")
    # run.py style: the first word ends option parsing; greedy positional
    r = P(["--timeout", "5", "python3", "-m", "pytest", "--tb=short"], F, (), usage="U", interspersed=False)
    assert r["timeout"] == 5 and r["_"] == ["python3", "-m", "pytest", "--tb=short"]
    assert P(["foo", "bar", "baz"], F, ["query*"], usage="U")["query"] == "foo bar baz"
    assert P(["--query", "x y"], F, ["query*"], usage="U")["query"] == "x y"
    # the wrapper's dict-args form equals the positional form
    sk = P(skill_args({"file": "a.py", "start": 1, "end": 2}), F, ["file", "start", "end"], usage="U")
    assert (sk["file"], sk["start"], sk["end"]) == ("a.py", 1, 2)
    # a positional that is not an int stays a string (view.py FILE NAME)
    r = P(["a.py", "Foo.bar"], F, ["file", "start", "end"], usage="U")
    assert r["start"] == "Foo.bar" and r["end"] is None


def test_unknown_flag_is_one_line_usage_error_exit_0(scripts, ws, env):
    r = run_helper(scripts, "run", ["--bogus", "x"], ws=ws, env=env)
    lines = r.stdout.strip().splitlines()
    assert r.returncode == 0 and r.stderr == ""
    assert lines[0] == 'USAGE ERROR: unknown option --bogus. Usage: python3 /tmp/swe/run.py [--timeout N] "COMMAND"'
    assert lines[-1].startswith("[t=") and len(lines) <= 3


# ----------------------------------------------------------------------------------------------------------------- R17
def test_cap_and_last_log(C, swe):
    assert C.cap("\x1b[31mred\x1b[0m plain \x1b]0;title\x07x", 100) == "red plain x"
    assert C.cap("a\r\nb", 100) == "a\nb"
    assert C.cap("progress 10%\rprogress 100%\nnext", 100) == "progress 100%\nnext"
    long_line = "A" * 250 + "M" * 500 + "Z" * 250
    got = C.cap(long_line, 1000)
    assert got == "A" * 200 + " ... " + "Z" * 100 and len(got) == 305
    assert C.cap("short\ntext", 50) == "short\ntext"
    lines = ["line %d" % i for i in range(1000)]
    lines[500] = "==== 3 failed, 10 passed in 1.23s ===="
    text = "\n".join(lines)
    got = C.cap(text, 500)
    assert len(got) <= 500
    assert got.startswith("line 0\n") and got.endswith("line 999")
    assert "lines cut; full output: /tmp/swe/last.log] ..." in got
    assert "==== 3 failed, 10 passed in 1.23s ====" in got
    m = re.search(r"\.\.\. \[(\d+) lines cut", got)
    assert int(m.group(1)) + len(got.split("\n")) - 1 == 1000       # every line is either shown or counted
    assert (swe / "last.log").read_text() == text                  # the full text
    # emit: the whole output stays within the cap, footer included, and last.log holds everything
    C._reset()
    out = C.emit("status", "HEAD LINE", text, 700, tail=["NOTE: keep me"])
    assert len(out) <= 699 and out.startswith("HEAD LINE\n") and "NOTE: keep me\n[t=" in out
    assert out.splitlines()[-1].startswith("[t=")
    log = (swe / "last.log").read_text()
    assert "line 999" in log and "line 1" in log and "HEAD LINE" in log


# ----------------------------------------------------------------------------------------------------------------- R18
FOOTER_CASES = [
    # (name, fake t, tree setup, want hint prefix or "")
    ("early", 10, None, ""),
    ("locator", 80, None, "LOCATOR: 75s used."),
    # v10.1: once the journal shows a later stage (an edit that was undone, a finalize, a full verify), an empty tree
    # hears EDIT NOW, not "Other stages: ignore this line" (race 2: fastapi_15280, fastapi_14873)
    ("locator_over_edit_now", 80, "journal_ok_edit", "EDIT NOW: no source file changed at t=80s;"),
    ("locator_over_finalize", 80, "journal_finalize", "EDIT NOW:"),
    ("locator_over_full_verify", 80, "journal_verify", "EDIT NOW:"),
    ("locator_repro_only_is_locator", 80, "journal_repro_only", "LOCATOR: 75s used."),
    ("locator_src_changed", 80, "src", ""),
    ("edit_now", 160, None, "EDIT NOW: no source file changed at t=160s; an empty patch always fails."),
    ("edit_now_despite_ok_edit", 160, "journal_ok_edit", "EDIT NOW:"),
    ("edit_now_protected_only", 160, "protected", "EDIT NOW:"),
    ("edit_now_scratch_only", 160, "scratch", "EDIT NOW:"),
    ("no_edit_now_new_module", 160, "new_module", ""),
    ("no_edit_now_src", 160, "src", ""),
    # v10.1: an empty tree is never told to end its stage (race 2: fastapi_14851 step 38, fastapi_14306 step 54)
    ("finish_empty", 215, None, "EDIT NOW: no source file changed at t=215s;"),
    ("finish_src", 215, "src", "FINISH: t>=210s."),
    ("time_empty", 255, None, "EDIT NOW: no source file changed at t=255s;"),
    ("time", 255, "src", "TIME: t>=250s."),
    ("final", 100, "final", "FINAL: the patch was finalized at t=131s;"),
    ("final_beats_time", 260, "final", "FINAL:"),
    ("final_then_changed", 255, "final_changed", "TIME:"),
]


@pytest.mark.parametrize("name,t,setup,want", FOOTER_CASES, ids=[c[0] for c in FOOTER_CASES])
def test_footer_hints_matrix(name, t, setup, want, tmp_path, scripts, ws, swe):
    env = helper_env(ws, swe, fake_t=t)
    code = ""
    if setup in ("src", "final", "final_changed"):
        (ws / "pkg/mod.py").write_text("def parse_header(x):\n    return x * 2\n")
    if setup == "protected":
        (ws / "tests/test_mod.py").write_text("def test_p():\n    pass\n")
    if setup == "scratch":
        (ws / "repro.py").write_text("print(1)\n")
    if setup == "new_module":
        (ws / "pkg/new.py").write_text("X = 1\n")
    if setup == "journal_ok_edit":
        code += "C.journal({'h': 'edit', 'ok': True, 'file': 'pkg/mod.py'})\n"
    if setup == "journal_finalize":
        code += "C.journal({'h': 'finalize', 'first': 'NOT READY: EMPTY'})\n"
    if setup == "journal_verify":
        code += "C.journal({'h': 'verify', 'first': 'VERIFY: NO SOURCE CHANGE'})\n"
    if setup == "journal_repro_only":
        code += "C.journal({'h': 'verify', 'mode': 'repro-only', 'first': 'REPRO: fails on original'})\n"
    if setup in ("final", "final_changed"):
        code += "C.state_update(lambda s: s.update(final_done=True, final_sha=C.diff_sha(), final_t=131.0))\n"
    if setup == "final_changed":
        code += "open('pkg/mod.py', 'a').write('y = 2\\n')\n"
    code += "import json; print(json.dumps(C.footer()))\n"
    got = py_json(scripts, code, env=env, cwd=ws)
    lines = got.split("\n")
    assert lines[-1] == "[t=%ds]" % t
    hint = lines[0] if len(lines) == 2 else ""
    assert len(lines) <= 2
    assert hint.startswith(want) if want else hint == "", (name, got)
    if hint.startswith("EDIT NOW"):          # from T_TIME on it also names the finalize command
        assert ("python3 /tmp/swe/finalize.py" in hint) == (t >= 250), (name, hint)
    for tool in TOOL_NAMES:
        assert tool not in got


def test_footer_hint_texts(C):
    assert C.TIME_HINT == ("TIME: t>=250s. End your stage now; reply in one line, under 30 words (verifier: run "
                           "python3 /tmp/swe/finalize.py next).")
    assert C.FINISH_HINT == ("FINISH: t>=210s. Stop exploring; keep the edit you have and end your stage with a short "
                             "reply.")
    assert C.EDIT_NOW_HINT % 160 == ("EDIT NOW: no source file changed at t=160s; an empty patch always fails. "
                                     "Locator: reply with your plan now. Other stages: make the smallest plausible "
                                     "version of the plan's change now.")
    assert C.EDIT_NOW_LATE == " Then run python3 /tmp/swe/finalize.py once."
    assert C.LOCATOR_HINT == ("LOCATOR: 75s used. Locator: stop and reply with your plan now. Other stages: ignore "
                              "this line.")
    assert C.FINAL_HINT % 5 == ("FINAL: the patch was finalized at t=5s; nothing more to change. The stage that can "
                                "submit should submit now; any other stage should reply done.")
    for h in (C.TIME_HINT, C.FINISH_HINT, C.EDIT_NOW_HINT, C.EDIT_NOW_LATE, C.LOCATOR_HINT, C.FINAL_HINT):
        assert not any(tool in h for tool in TOOL_NAMES)
    assert (C.T_LOCATOR, C.T_EDIT_NOW, C.T_FINISH, C.T_TIME, C.T_SAFE) == (75, 150, 210, 250, 255)


# ----------------------------------------------------------------------------------------------------------------- R19
def test_state_atomic_lock_reset(tmp_path, scripts, ws, swe, env):
    run_helper(scripts, "install", [], ws=ws, env=env)
    inc = ("import sys\nsys.path.insert(0, %r)\nimport _swe_common as C\n"
           "for _ in range(5):\n    C.state_update(lambda s: s.__setitem__('n', s.get('n', 0) + 1))\n" % str(scripts))
    reader = ("import sys, json, os, time\np = %r\nbad = 0\nend = time.time() + 1.5\n"
              "while time.time() < end:\n    try:\n        json.loads(open(p).read())\n"
              "    except FileNotFoundError:\n        pass\n    except ValueError:\n        bad += 1\nprint(bad)\n"
              % str(swe / "state.json"))
    e = dict(env, PWD=str(ws))
    rd = subprocess.Popen([PY, "-c", reader], cwd=str(ws), env=e, stdout=subprocess.PIPE, text=True)
    procs = [subprocess.Popen([PY, "-c", inc], cwd=str(ws), env=e) for _ in range(20)]
    for p in procs:
        assert p.wait(60) == 0
    assert rd.communicate(10)[0].strip() == "0"                       # readers never see a partial file
    st = json.loads((swe / "state.json").read_text())
    assert st["n"] == 100                                              # 20 writers x 5 updates, none lost
    assert st["ws"] == os.path.realpath(ws) and st["baseline"] == git(ws, "rev-parse", TAG).strip()
    assert not [p for p in swe.iterdir() if ".tmp." in p.name]
    # a state from another task (ws or baseline differs) is reset with its caches, repro and checkpoints
    for mismatch in ("ws", "baseline"):
        st = json.loads((swe / "state.json").read_text())
        st[mismatch] = "/elsewhere/ws" if mismatch == "ws" else "0" * 40
        st["final_done"] = True
        (swe / "state.json").write_text(json.dumps(st))
        for d in ("ckpt", "claims", "base"):
            (swe / d).mkdir(exist_ok=True)
            (swe / d / "x").write_text("x")
        for f in ("repro.py", "index_abc123.marshal", "journal.jsonl", "idx"):
            (swe / f).write_text("x")
        got = py_json(scripts, "import json; s = C.state_load(); print(json.dumps([s['final_done'], s.get('n'), s['ws']]))",
                      env=env, cwd=ws)
        assert got == [False, None, os.path.realpath(ws)], mismatch
        for f in ("ckpt", "claims", "base", "repro.py", "index_abc123.marshal", "journal.jsonl", "idx"):
            assert not (swe / f).exists(), (mismatch, f)
        assert (swe / "VERSION").exists() and (swe / "_swe_common.py").exists()   # installed helpers stay
    # the matching state is kept as is
    py_json(scripts, "C.state_update(lambda s: s.update(n=7)); print(1)", env=env, cwd=ws)
    assert py_json(scripts, "import json; print(json.dumps(C.state_load()['n']))", env=env, cwd=ws) == 7


def test_state_defaults_and_journal(C, swe):
    st = C.state_load()
    for k in ("ckpts", "edits", "views", "repeats", "origin", "memo", "repro", "orig_tests", "base"):
        assert k in st and isinstance(st[k], (list, dict))
    assert st["final_done"] is False and st["locate_calls"] == 0
    assert C.jtail(8) == []
    C.journal({"h": "edit", "ok": True, "file": "pkg/mod.py", "tier": "exact", "start": 40, "end": 44, "delta": 3,
               "t": 95.2})
    C.journal({"h": "verify", "msg": "RED 1/2 claims fixed", "t": 101})
    C.journal({"h": "locate", "files": 6, "top": "rich/text.py", "t": 12})
    tail = C.jtail(8)
    assert tail[0] == "t=95s edit pkg/mod.py OK (exact) lines 40-44 (+3)"
    assert tail[1] == "t=101s verify: RED 1/2 claims fixed"
    assert tail[2] == "t=12s locate: 6 files (top rich/text.py)"                  # the SPEC 4.13 example
    for i in range(20):
        C.journal({"h": "run", "msg": "run echo %d: exit=0" % i})
    assert len(C.jtail(8)) == 8 and C.jtail(8)[-1].endswith("run echo 19: exit=0")
    notes = [C.repeat_note("run", "k") for _ in range(4)]
    assert notes[:2] == ["", ""] and notes[2] == notes[3] == C.REPEAT_NOTES["run"]


# ----------------------------------------------------------------------------------------------------------------- R20
PROTECTED_CASES = [
    ("pkg/mod.py", None), ("pkg/testing/util.py", None), ("src/pkg/test.py", None), ("pkg/tests.py", None),
    ("pkg/test_utils/helpers.py", None), ("setup.py", None), ("README.md", None), ("docs/conf.py", None),
    ("tests", None), ("pkg/contest.py", None),
    ("tests/test_x.py", "test file"), ("test_repro.py", "test file"), ("pkg/foo_test.py", "test file"),
    ("docs/test_example.py", "test file"), ("tests/helpers.py", "test directory"), ("test/data.json", "test directory"),
    ("testing/util.py", "test directory"), ("pkg/tests/x.py", "test directory"),
    ("src/pkg/test/fixtures.py", "test directory"),
    ("conftest.py", "test configuration file"), ("a/b/conftest.py", "test configuration file"),
    ("pytest.ini", "test configuration file"), (".pytest.ini", "test configuration file"),
    ("tox.ini", "test configuration file"), ("setup.cfg", "packaging/test configuration file"),
    ("pyproject.toml", "packaging/test configuration file"), ("sitecustomize.py", "interpreter startup file"),
    ("pkg/usercustomize.py", "interpreter startup file"), ("_swegemma_stubs.py", "harness file"),
    ("site/x.pth", "interpreter startup file"), (".git/config", "git internals"),
    ("../x.py", "outside the repository"), ("pkg/../../x.py", "outside the repository"),
    ("/etc/passwd", "outside the repository"), ("", "outside the repository"),
    ("ABS:pkg/mod.py", None), ("ABS:tests/test_mod.py", "test file"), ("ABS:", "outside the repository"),
    ("link/passwd", "outside the repository"),
]


@pytest.mark.parametrize("path,want", PROTECTED_CASES, ids=[c[0] or "<empty>" for c in PROTECTED_CASES])
def test_is_protected(path, want, C, ws):
    (ws / "link").symlink_to("/etc") if not (ws / "link").exists() else None
    if path.startswith("ABS:"):
        path = str(ws / path[4:]) if path[4:] else str(ws)
    assert C.is_protected(path) == want


# ----------------------------------------------------------------------------------------------------------------- R21
def test_changes_and_diff_bytes_match_submit(tmp_path, scripts):
    files = dict(DEFAULT_FILES)
    files.update({"pkg/old.py": "OLD = 1\n", "pkg/ren_a.py": "R = 1\n" * 5, "pkg/ünï.py": "U = 1\n",
                  "bin.dat": bytes(range(256)) * 4, "script.sh": "#!/bin/sh\necho hi\n"})
    ws = make_repo(tmp_path, files)
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    (ws / "pkg/mod.py").write_text("def parse_header(x):\n    return x * 2\n")
    (ws / "pkg/old.py").unlink()
    (ws / "pkg/ren_a.py").rename(ws / "pkg/ren_b.py")
    (ws / "pkg/ünï.py").write_text("U = 2\n")
    (ws / "bin.dat").write_bytes(bytes(reversed(range(256))) * 4)
    (ws / "script.sh").chmod(0o755)
    (ws / "pkg/new.py").write_text("NEW = 1\n")
    (ws / "repro.py").write_text("print('scratch')\n")
    (ws / "tests/test_mod.py").write_text("def test_p():\n    pass\n")
    (ws / "tests/test_new.py").write_text("def test_n():\n    pass\n")
    idx = ws / ".git/index"
    before = (idx.stat().st_mtime_ns, idx.read_bytes())
    got = py_json(scripts, "import json, base64\nch = C.changes()\nd = C.diff_bytes()\n"
                           "print(json.dumps([ch, base64.b64encode(d).decode(), C.diff_sha()]))", env=env, cwd=ws)
    ch, d64, sha = got
    import base64, hashlib
    assert (idx.stat().st_mtime_ns, idx.read_bytes()) == before              # the real index is never written
    assert ch["source"] == sorted(["bin.dat", "pkg/mod.py", "pkg/new.py", "pkg/ren_b.py", "pkg/ünï.py", "script.sh"])
    assert ch["deleted"] == ["pkg/old.py", "pkg/ren_a.py"]
    assert ch["protected"] == ["tests/test_mod.py", "tests/test_new.py"]
    assert ch["untracked"] == ["pkg/new.py", "pkg/ren_b.py", "repro.py"]
    assert ch["status"]["pkg/mod.py"] == "M" and ch["status"]["repro.py"] == "?"
    mine = base64.b64decode(d64)
    copy = tmp_path / "copy"
    shutil.copytree(ws, copy, symlinks=True)
    git(copy, "add", "-N", ".")
    harness = subprocess.run(["git", "diff", "--binary", TAG], cwd=str(copy), capture_output=True,
                             env=dict(env, GIT_CONFIG_NOSYSTEM="1")).stdout
    assert mine == harness and len(mine) > 500
    assert b"GIT binary patch" in mine and b"old mode 100644\nnew mode 100755" in mine and b"new file mode" in mine
    assert sha == hashlib.sha1(mine).hexdigest()


def test_same_size_edit_in_the_baseline_second_is_seen(tmp_path, scripts):
    """Regression (found 2026-09-28): the temp index was a copy with a fresh mtime, which hid a same-size edit made in
    the same second as the index write (git's racily-clean check compares against the index file's mtime). A
    one-character fix right after the baseline then vanished from diff_bytes()/numstat()."""
    ws = make_repo(tmp_path, {"pkg/__init__.py": "", "pkg/other.py": "A = 1\n"})
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    f, idx = ws / "pkg/other.py", ws / ".git/index"
    f.write_text("A = 2\n")                                           # same size
    st = idx.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))                  # the same instant as the index write
    git(ws, "diff", "--shortstat")                                    # a porcelain command refreshes the real index
    for _ in range(2):
        got = py_json(scripts, "import json\nprint(json.dumps([C.diff_bytes().decode(), C.numstat(), "
                               "C.changes()['source']]))", env=env, cwd=ws)
        assert "-A = 1\n+A = 2" in got[0] and got[1] == [["pkg/other.py", 1, 1]] and got[2] == ["pkg/other.py"], got
    r = run_helper(scripts, "status", [], ws=ws, env=env)
    assert "DIFF: pkg/other.py +1 -1" in r.stdout, r.stdout


# ----------------------------------------------------------------------------------------------------------------- R22
def test_hygiene_revert(tmp_path, scripts):
    files = dict(DEFAULT_FILES)
    files.update({"tests/helpers.py": "H = 1\n", "tests/test_a.py": "def test_a():\n    pass\n"})
    ws = make_repo(tmp_path, files)
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    base = {p: (ws / p).read_bytes() for p in ("tests/test_mod.py", "conftest.py", "pytest.ini", "tests/helpers.py")}
    assert not (ws / "sitecustomize.py").exists()
    (ws / "tests/test_mod.py").write_text("def test_p():\n    assert False\n")
    (ws / "tests/helpers.py").write_text("H = 2\n")
    (ws / "conftest.py").unlink()
    (ws / "pytest.ini").write_text("[pytest]\naddopts = -x\n")
    (ws / "tests/test_new.py").write_text("x = 1\n")
    (ws / "test_repro.py").write_text("x = 1\n")
    (ws / "tests/test_added.py").write_text("x = 1\n")
    git(ws, "add", "tests/test_added.py")
    (ws / "pkg/mod.py").write_text("def parse_header(x):\n    return x * 2\n")
    (ws / "pkg/new.py").write_text("N = 1\n")
    d, log = fake_git(tmp_path)
    e = dict(env, PATH="%s:%s" % (d, env["PATH"]))
    got = py_json(scripts, "import json; r = C.hygiene_revert(); print(json.dumps([r, C.hygiene_note(r), "
                           "C.hygiene_revert()]))", env=e, cwd=ws)
    done, note, again = got
    assert sorted(done) == sorted(["conftest.py", "pytest.ini", "test_repro.py", "tests/helpers.py",
                                   "tests/test_added.py", "tests/test_mod.py", "tests/test_new.py"])
    assert again == []
    assert note.startswith("reverted test/config edits: ") and "\n" not in note
    for p, b in base.items():
        assert (ws / p).read_bytes() == b, p
    for p in ("tests/test_new.py", "test_repro.py", "tests/test_added.py"):
        assert not (ws / p).exists(), p
    assert "x * 2" in (ws / "pkg/mod.py").read_text() and (ws / "pkg/new.py").exists()
    st = git(ws, "status", "--porcelain")
    assert st.split("\n")[0].strip().endswith("pkg/mod.py") and "tests/" not in st and "conftest" not in st
    calls = [ln.split("\x1f")[:-1] for ln in log.read_text().splitlines()]
    checkouts = [c for c in calls if "checkout" in c]
    assert len(checkouts) == 4 and all(len(c[c.index("--") + 1:]) == 1 for c in checkouts)
    assert not any("sitecustomize.py" in " ".join(c) for c in calls)


# ----------------------------------------------------------------------------------------------------------------- R23
def test_unrewrite_unit(tmp_path, scripts, ws):
    root = tmp_path / "swegemma_sandbox_ab12cd_x7"
    (root / "tmp").mkdir(parents=True)
    r = str(root)
    text = ("open('%s/tmp/x')\nP = '%s/workspace/y'\n#!%s/venv/bin/python3\nW = '%s/wheels/a.whl'\n"
            "keep = '%s/tmpfoo'\nplain = '/usr/lib'\n" % (r, r, r, r, r))
    want = ("open('/tmp/x')\nP = '/workspace/y'\n#!/usr/local/bin/python3\nW = '/wheels/a.whl'\n"
            "keep = '%s/tmpfoo'\nplain = '/usr/lib'\n" % r)
    code = "import json, sys; print(json.dumps(C.unrewrite(sys.stdin.read())))"
    got = py_json(scripts, code, env=base_env(TEST_TMPDIR=root / "tmp", TMPDIR=root / "tmp", SWE_WS=ws), cwd=ws,
                  stdin=text)
    assert got == want
    other = tmp_path / "plain" / "tmp"
    other.mkdir(parents=True)
    got = py_json(scripts, code, env=base_env(TEST_TMPDIR=other, TMPDIR=other, SWE_WS=ws), cwd=ws, stdin=text)
    assert got == text
    got = py_json(scripts, code, env=base_env(TMPDIR=root / "tmp", SWE_WS=ws), cwd=ws, stdin=text)
    assert got == want                                    # TMPDIR alone identifies the sandbox too


# ----------------------------------------------------------------------------------------------------------------- R24
def probe_script(scripts, body):
    p = scripts / "probe.py"
    p.write_text(PREAMBLE + "\n" + textwrap.dedent(body) + "\nif __name__ == '__main__':\n    C.safe_main('probe', main)\n")
    return p


@pytest.mark.parametrize("kind", ["exception", "long_message", "system_exit", "keyboard_interrupt", "usage_error",
                                  "stderr_write", "child_killed", "watchdog", "sh_clamped"])
def test_safe_main_exit0(kind, tmp_path, scripts, ws, env):
    body = {
        "exception": "def main():\n    print('partial')\n    raise ValueError('boom')\n",
        "long_message": "def main():\n    raise RuntimeError('boom\\n' * 200)\n",
        "system_exit": "def main():\n    raise SystemExit(3)\n",
        "keyboard_interrupt": "def main():\n    raise KeyboardInterrupt()\n",
        "usage_error": "def main():\n    C.parse_args(['--nope'], {}, usage='python3 /tmp/swe/probe.py')\n",
        "stderr_write": "def main():\n    sys.stderr.write('to stderr\\n')\n    print('ok')\n",
        "child_killed": ("import threading\ndef main():\n"
                         "    threading.Thread(target=C.sh, args=('%s 40; echo x', 60), daemon=True).start()\n"
                         % unique_sleep(tmp_path) +
                         "    import time; time.sleep(0.5)\n    raise ValueError('boom')\n"),
        "watchdog": "def main():\n    import time\n    time.sleep(30)\n",
        "sh_clamped": ("def main():\n    import time\n    t = time.monotonic()\n    rc, _ = C.sh('%s 30', 60)\n"
                       "    print('rc=%%s secs=%%.1f' %% (rc, time.monotonic() - t))\n" % unique_sleep(tmp_path)),
    }[kind]
    probe_script(scripts, body)
    if kind in ("watchdog", "sh_clamped"):     # near the cap: helper stopped at max(4, real_budget) s; sh at real_budget
        env = dict(env, SWE_FAKE_CLOCK="299")
    t0 = time.monotonic()
    r = run_helper(scripts, "probe", [], ws=ws, env=env)
    wall = time.monotonic() - t0
    assert r.returncode == 0 and r.stderr == "" and "Traceback" not in r.stdout, r.stdout + r.stderr
    out = r.stdout
    if kind == "watchdog":
        assert 3.5 <= wall <= 7 and out.startswith("HELPER ERROR probe: HelperTimeout: stopped after 4s"), (wall, out)
    if kind == "sh_clamped":
        m = re.match(r"rc=None secs=(\d+\.\d)", out)
        assert m and float(m.group(1)) <= 2.0, out                  # 60 s asked, real_budget(60) = 1 s at t=299
        time.sleep(0.3)
        left = find_orphans([str(tmp_path / "ubin")])
        kill_processes(left)
        assert not left
    if kind in ("exception", "long_message", "keyboard_interrupt", "child_killed"):
        err = [ln for ln in out.splitlines() if ln.startswith("HELPER ERROR probe: ")]
        assert len(err) == 1 and len(err[0]) <= 300, out
        typ = {"exception": "ValueError: boom", "long_message": "RuntimeError: boom boom",
               "keyboard_interrupt": "KeyboardInterrupt", "child_killed": "ValueError: boom"}[kind]
        assert err[0].startswith("HELPER ERROR probe: " + typ), err
        assert re.search(r"\(probe\.py:\d+\)$", err[0])
    if kind == "exception":
        assert out.startswith("partial\n")
    if kind == "system_exit":
        assert out == ""
    if kind == "usage_error":
        assert out.startswith("USAGE ERROR: unknown option --nope. Usage: python3 /tmp/swe/probe.py\n")
    if kind == "stderr_write":
        assert "to stderr" in out and "ok" in out
    if kind == "child_killed":
        time.sleep(0.3)
        left = find_orphans([str(tmp_path / "ubin")])
        kill_processes(left)
        assert not left


# ------------------------------------------------------------------------------------------ R76 (the core side of it)
FAKE_CKPT = """import json, os
import _swe_common as C
def auto_restore_if_empty():
    open(os.path.join(C.swe_dir(), "ckpt_calls"), "a").write("x")
    with open(os.path.join(C.ws(), "pkg", "mod.py"), "a") as f:
        f.write("RESTORED_LINE = 1\\n")
    return True, "RESTORED checkpoint #3: the tree had no source change at t=%ds." % int(C.clock())
"""


@pytest.mark.parametrize("case", ["fires", "early", "final", "src_changed", "no_ckpt", "ckpt_module_missing"])
def test_late_guard_hook(case, tmp_path, scripts, ws, swe):
    """emit() -> late_guard(): at t >= 255 with no source change, not final and a non-empty checkpoint, the lazily
    imported _swe_ckpt.auto_restore_if_empty() runs and its RESTORED line prefixes the output."""
    (scripts / "_swe_ckpt.py").write_text(FAKE_CKPT)
    if case == "ckpt_module_missing":
        (scripts / "_swe_ckpt.py").unlink()
    env = helper_env(ws, swe, fake_t=100 if case == "early" else 260)
    run_helper(scripts, "install", [], ws=ws, env=env)
    later_stage(swe)                                     # v10.2: a late stage has ended the locator phase
    if case == "ckpt_module_missing":
        (swe / "_swe_ckpt.py").unlink(missing_ok=True)
    (swe / "ckpt").mkdir(exist_ok=True)
    if case != "no_ckpt":
        (swe / "ckpt/1.diff").write_text("diff --git a/x b/x\n")
    if case == "src_changed":
        (ws / "pkg/new.py").write_text("X = 1\n")
    if case == "final":
        run_py(swe, "C.state_update(lambda s: s.update(final_done=True, final_sha='0' * 40, final_t=200.0))",
               env=env, cwd=ws)
    r = run_helper(swe, "run", ["echo hi"], ws=ws, env=env)
    assert r.returncode == 0 and "HELPER ERROR" not in r.stdout, r.stdout
    fired = (swe / "ckpt_calls").exists()
    assert fired == (case == "fires"), (case, r.stdout)
    if fired:
        assert r.stdout.startswith("RESTORED checkpoint #3: the tree had no source change at t=260s.\nexit=0\n")
        assert "RESTORED_LINE" in (ws / "pkg/mod.py").read_text()
        assert "TIME: t>=250s." in r.stdout                 # footer computed after the restore
    else:
        assert r.stdout.startswith("exit=0\n")


def test_install_restart_shows_final_banner(tmp_path, scripts, ws, swe, env):
    mod = ws / "pkg/mod.py"
    mod.write_text(mod.read_text() + "X = 1\n")
    assert run_py(scripts, "C.state_update(lambda s: s.update(final_done=True, final_sha=C.diff_sha(), "
                           "final_t=201.0))", env=env, cwd=ws).returncode == 0
    r = run_helper(scripts, "install", [], ws=ws, env=env)
    assert "FINAL: the patch was finalized at t=201s;" in r.stdout and len(r.stdout.rstrip("\n")) <= 400


def test_nested_tmp_index_and_state_locks(tmp_path, scripts, ws, env):
    code = ("import json\nwith C.tmp_index() as e:\n    a = C.diff_sha()\n"
            "    C.state_update(lambda s: C.state_update(lambda t: t.update(n=1)))\n"
            "print(json.dumps([a == C.diff_sha(), C.state_load()['n']]))")
    r = run_py(scripts, code, env=env, cwd=ws, timeout=20)
    assert r.returncode == 0 and json.loads(r.stdout) == [True, 1], r.stdout + r.stderr


# ----------------------------------------------------------------------------------------------------------------- R28
def helper_meta(scripts, name):
    code = ("import json, runpy, sys\ng = runpy.run_path(sys.argv[1], run_name='probe')\n"
            "print(json.dumps([g.get('USAGE'), g.get('FLAGS')]))")
    r = subprocess.run([PY, "-c", code, str(scripts / (name + ".py"))], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("helper", CLI)
def test_usage_flags_exported(helper, tmp_path, scripts, ws, env):
    usage, flags = helper_meta(scripts, helper)
    assert isinstance(usage, str) and usage.startswith("python3 /tmp/swe/%s.py" % helper), usage
    assert isinstance(flags, dict) and all(isinstance(k, str) and k == k.lower() and "_" not in k for k in flags)
    assert set(flags.values()) <= {"str", "int", "bool", "range", "list", "float"}, flags
    r = run_helper(scripts, helper, [], ws=ws, env=env, timeout=60)
    assert r.returncode == 0 and "HELPER ERROR" not in r.stdout and "Traceback" not in r.stdout + r.stderr, r.stdout
    if helper in REQUIRES_ARG:
        assert usage in r.stdout, r.stdout
    assert r.stdout.strip().splitlines()[-1].startswith("[t=")


# ---------------------------------------------------------------------------------------------------------------- R120
def test_no_orphans_fixture_detects(tmp_path):
    leak = subprocess.Popen(["bash", "-c", "sleep 30; : %s" % tmp_path], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        found = find_orphans({str(tmp_path)})
        assert any(pid == leak.pid for pid, _ in found), found
    finally:
        kill_processes([(leak.pid, "")])
        leak.wait(5)
    assert not find_orphans({str(tmp_path)})
    # autouse in every v10 test module (imported from v10_support.repo)
    mods = sorted((ROOT / "tests").glob("test_v10_*.py"))
    assert mods
    for m in mods:
        assert re.search(r"from v10_support\.repo import [^\n]*\bno_orphans\b", m.read_text()), m.name
    src = (ROOT / "tests/v10_support/repo.py").read_text()
    assert re.search(r"@pytest\.fixture\(autouse=True\)\ndef no_orphans\(tmp_path\):", src)


# ------------------------------------------------- review round 1: token-aware output caps and the context meter (R95)
BOX = "".join("│ %-6s │ %5d │ ─────── │ ┼ │\n" % ("cell", i) for i in range(400))   # a rendered rich table


def test_est_tokens_and_token_cap(C, monkeypatch):
    """emit caps by estimated tokens as well as chars: box drawing (0.36-0.63 chars/token measured) cannot spend 3x a
    helper's budget any more; ASCII output is unaffected."""
    monkeypatch.setenv("SWE_FAKE_CLOCK", "40")
    assert C.est_tokens("") == 0.0 and C.est_tokens("abc") == 1.0 and C.est_tokens("│") == 2.7
    assert C.CAP_TOKENS == {k: v // 3 for k, v in C.CAPS.items()} and C.CAPS["view"] == 2800
    char_only = C.cap_text(BOX, C.CAPS["run"] - 40)
    assert C.est_tokens(char_only) > 2 * C.CAP_TOKENS["run"]          # what the char cap alone let through
    out = C.emit("run", "RUN: exit 0 (0.1 s)", BOX, C.CAPS["run"])
    assert C.est_tokens(out) <= C.CAP_TOKENS["run"] and len(out) <= C.CAPS["run"] - 1, (C.est_tokens(out), len(out))
    assert out.startswith("RUN: exit 0 (0.1 s)\n") and out.splitlines()[-1] == "[t=40s]" and "│" in out
    ascii_body = "\n".join("line %04d " % i + "x" * 60 for i in range(400))
    out2 = C.emit("run", "RUN: exit 0 (0.1 s)", ascii_body, C.CAPS["run"])
    assert len(out2) >= C.CAPS["run"] - 120 and C.est_tokens(out2) <= C.CAP_TOKENS["run"]
    # a non-ASCII head and tail are cut too, the footer always survives
    out3 = C.emit("finalize", "Ä" * 900, "", C.CAPS["finalize"], tail=["ö" * 300])
    assert C.est_tokens(out3) <= C.CAP_TOKENS["finalize"] and out3.endswith("[t=40s]"), out3[-60:]


def test_context_meter_rules(C):
    """ctx_next: calls add up; status.py restarts the count (verifier step 1, recovery after compaction); the first
    edit.py after the locator starts the fixer's count with its trailing views (at most 3); the setup stage's
    install.py is not counted."""
    ctx = C.ctx_next({}, "install", 150)
    assert ctx["n"] == 0.0 and ctx["phase"] == "locator"
    for name, est in (("locate", 450), ("view", 900), ("grep", 300), ("verify", 400), ("view", 800), ("view", 700)):
        ctx = C.ctx_next(ctx, name, est)
    assert ctx["n"] == 3550.0 and ctx["phase"] == "locator"
    ctx = C.ctx_next(ctx, "edit", 600)
    assert ctx["n"] == 800 + 700 + 600 and ctx["phase"] == "fixer"
    ctx = C.ctx_next(ctx, "verify", 500)
    assert ctx["n"] == 2600.0
    ctx = C.ctx_next(ctx, "status", 700)
    assert ctx["n"] == 700.0 and ctx["phase"] == "verifier"
    ctx = C.ctx_next(ctx, "edit", 600)
    assert ctx["n"] == 1300.0 and ctx["phase"] == "verifier" and len(ctx["tail"]) == 8
    assert C.ctx_next({"n": "junk", "tail": "junk"}, "view", 10)["n"] == 10.0
    # the hint: below FINISH and TIME, above EDIT NOW and LOCATOR; it names no tool
    assert C.hint(100, True, None, C.CONTEXT_TOKENS) == C.CONTEXT_HINT
    # v10.1: an empty tree at t >= T_EDIT_NOW hears EDIT NOW even with a full context (the edit matters more)
    assert C.hint(160, False, None, C.CONTEXT_TOKENS) == C.EDIT_NOW_HINT % 160
    assert C.hint(100, True, None, C.CONTEXT_TOKENS - 1) == ""
    assert C.hint(215, True, None, 99999) == C.FINISH_HINT and C.hint(255, True, None, 99999) == C.TIME_HINT
    assert not any(tool in C.CONTEXT_HINT for tool in TOOL_NAMES)
    assert "python3 /tmp/swe/finalize.py" in C.CONTEXT_HINT


def test_context_meter_through_real_helpers(scripts, ws, swe):
    """The meter as the helpers keep it: views of a 100-line file push a stage over CONTEXT_TOKENS and the footer says
    CONTEXT; status.py starts a new count."""
    body = "".join("def fn_%03d(value):\n    return value + %d  # %s\n" % (i, i, "c" * 40) for i in range(60))
    (ws / "pkg/big.py").write_text(body)
    env = helper_env(ws, swe, fake_t=100)
    later_stage(swe)                                     # v10.2: a fixer (the locator's 14-call close aside)
    seen = []
    for i in range(12):
        r = run_helper(scripts, "view", ["pkg/big.py", str(1 + i), str(100 + i)], ws=ws, env=env)
        seen.append("CONTEXT:" in r.stdout)
        if seen[-1]:
            break
    st = json.loads((swe / "state.json").read_text())
    assert seen[-1] and not any(seen[:-1]) and 3 <= len(seen) <= 8, (seen, st["ctx"])
    assert st["ctx"]["n"] >= C_CONTEXT_TOKENS(scripts), st["ctx"]
    lines = r.stdout.splitlines()
    assert lines[-2].startswith("CONTEXT: this stage's context is nearly full.") and lines[-1] == "[t=100s]", r.stdout
    r = run_helper(scripts, "status", [], ws=ws, env=env)
    assert "CONTEXT:" not in r.stdout
    assert json.loads((swe / "state.json").read_text())["ctx"]["n"] < 1500


def C_CONTEXT_TOKENS(scripts):
    return py_json(scripts, "import json, _swe_common as C; print(json.dumps(C.CONTEXT_TOKENS))")
