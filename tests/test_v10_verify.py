"""verify.py and the gate library (SPEC 4.9, 4.11): R52-R69.

Every test copies the bundle scripts to a temp dir first (no __pycache__ can appear in the bundle) and runs the helpers as
subprocesses against throwaway git repos tagged _swegemma_baseline, as the model would through run_command. A few
timing-heavy rules (claim timeouts, the claims budget) are checked in-process with the constants shrunk.
"""
import hashlib, json, os, pathlib, re, shutil, subprocess, sys, textwrap, time
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10") / "skills/swe-tools/scripts"
PY = sys.executable
VBIN = str(pathlib.Path(sys.executable).parent)          # the project venv: python3 with pytest
MODS = ("_swe_common", "_swe_gate", "_swe_ckpt", "_swe_index")

from v10_support.repo import find_orphans, no_orphans  # noqa: F401  (R120: the orphan-process guard, autouse)
from v10_support.compat import V102, later_stage  # noqa: E402,F401  (G4_BUNDLE may be v10.2)

pytestmark = pytest.mark.skipif(not (SRC / "_swe_common.py").exists() or not (SRC / "verify.py").exists(),
                                reason="helpers not built")

HARNESS_INI = ("[pytest]\naddopts = -p no:anyio\nnorecursedirs = .* build dist venv\npython_classes = Test* *Test\n"
               "python_files = test_*.py *_test.py\nfilterwarnings =\n    ignore::DeprecationWarning\n"
               "    ignore::UserWarning\n")
HOOK = "# Hermetic test discovery hook for SWE-gemma\n"
EXCLUDES = "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\nbuild/\ndist/\n.coverage\n.adk_exec_*.py\n"
LINE1_FORMS = [
    r"^REPRO: fails on original \(\d+ of \d+ claims\): claim \d+ .+",
    r"^REPRO: claim \d+ passes on original - it misses the bug; rewrite it once with another input shape\.$",
    r"^REPRO: claim \d+ hangs on original \(expected for hang bugs\)\.$",
    r"^REPRO: claim \d+ is BROKEN \(.+, in the reproduction itself\): fix the reproduction\.$",
    r"^REPRO: none saved\. Pipe one in: python3 /tmp/swe/verify\.py --repro-only <<'EOF' \.\.\. EOF$",
]
BAD_WORDS = re.compile(r"\bundo\b|must fix", re.I)

TEXT_PY = '''\
def pad(s, width):
    return s.ljust(width - 1)


def center(s, width):
    return s.center(width)
'''
TEXT_TESTS = '''\
from pkg.text import pad, center


def test_center():
    assert center("a", 3) == " a "


def test_pad_zero():
    assert pad("", 0) == ""
'''
BASIC = {"pkg/__init__.py": "", "pkg/text.py": TEXT_PY, "tests/test_text.py": TEXT_TESTS}
REPRO_FAIL = ("from pkg.text import pad\n# CLAIM 1: pads to the width\nassert pad('ab', 4) == 'ab  ', repr(pad('ab', 4))\n"
              "# CLAIM 2: exact length\nassert len(pad('x', 3)) == 3\n")


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    d = tmp_path_factory.mktemp("scripts")
    for p in SRC.glob("*.py"):
        shutil.copy2(p, d / p.name)
    return d


def git(ws, *args, check=True):
    return subprocess.run(["git", "-c", "core.quotepath=off", "-c", "user.email=a@b", "-c", "user.name=t", *args],
                          cwd=ws, capture_output=True, check=check)


def write(ws, rel, data):
    p = pathlib.Path(ws) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def mkrepo(tmp, files, harness=True, name="ws"):
    """A git repo with the harness pytest.ini/conftest hook and exclude lines, committed and tagged
    _swegemma_baseline. files: {rel: str | bytes}."""
    ws = pathlib.Path(tmp) / name
    ws.mkdir(parents=True)
    for rel, data in files.items():
        write(ws, rel, data)
    if harness:
        if "pytest.ini" not in files:
            write(ws, "pytest.ini", HARNESS_INI)
        if "conftest.py" not in files:
            write(ws, "conftest.py", HOOK)
    git(ws, "init", "-q")
    with open(ws / ".git/info/exclude", "a") as f:
        f.write(EXCLUDES)
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "base", "--allow-empty")
    git(ws, "tag", "-f", "_swegemma_baseline")
    return ws


def swe(ws):
    return pathlib.Path(ws).parent / "sbx_tmp" / "swe"


def env_for(ws, t=100, **extra):
    tmp = pathlib.Path(ws).parent / "sbx_tmp"
    tmp.mkdir(exist_ok=True)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SWE_", "PYTHON", "TEST_TMPDIR"))}
    later_stage(tmp / "swe")    # v10.2: verify and finalize run in later stages (the locator budget does not apply)
    e.update(SWE_WS=str(ws), SWE_DIR=str(tmp / "swe"), TMPDIR=str(tmp), HOME=str(tmp), SWE_DUAL="0",
             SWE_DOCKER_TMP_FOR_TESTS=str(tmp / "docker_tmp"), PYTHONDONTWRITEBYTECODE="1", LANG="C.UTF-8",
             PYTHONPATH=str(ws), PATH=VBIN + os.pathsep + os.environ.get("PATH", ""))
    if t is not None:
        e["SWE_FAKE_CLOCK"] = str(t)
    e.update({k: str(v) for k, v in extra.items()})
    return e


class Res(object):
    def __init__(self, out, secs):
        self.out, self.secs = out, secs
        self.lines = out.split("\n")
        self.first = self.lines[0] if self.lines else ""

    def line(self, prefix):
        return next((ln for ln in self.lines if ln.startswith(prefix)), None)


def run(scripts, name, ws, args=(), stdin=None, t=100, env=None, timeout=120, py=PY):
    e = env or env_for(ws, t)
    t0 = time.monotonic()
    r = subprocess.run([py, str(scripts / ("%s.py" % name))] + list(args), cwd=str(ws), env=e,
                       input=stdin.encode("utf-8", "surrogateescape") if isinstance(stdin, str) else stdin,
                       stdin=subprocess.DEVNULL if stdin is None else None, capture_output=True, timeout=timeout)
    secs = time.monotonic() - t0
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0, out + r.stderr.decode("utf-8", "replace")
    assert "HELPER ERROR" not in out and "Traceback (most recent" not in out, out
    return Res(out, secs)


def verify(scripts, ws, *args, **kw):
    return run(scripts, "verify", ws, list(args), **kw)


def repro_only(scripts, ws, text, **kw):
    return run(scripts, "verify", ws, ["--repro-only"], stdin=text, **kw)


def verify_span(scripts, ws, t):
    """verify.span() at fake clock t, in a child (importing verify.py here would run its preamble on pytest's
    sys.path)."""
    code = "import sys; sys.path.insert(0, %r)\nimport verify as V, _swe_gate as G\nprint(repr(V.span(G)))" % str(scripts)
    r = subprocess.run([PY, "-c", code], cwd=str(ws), env=env_for(ws, t), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return float(r.stdout.strip().splitlines()[-1])


def edit_file(ws, rel, old, new):
    p = pathlib.Path(ws) / rel
    s = p.read_text()
    assert old in s, (rel, old)
    p.write_text(s.replace(old, new, 1))


def porcelain(ws):
    return git(ws, "status", "--porcelain", "--untracked-files=all").stdout.decode()


@pytest.fixture
def lib(scripts, monkeypatch):
    """lib(ws, t=100, **consts) -> (C, G, K): fresh in-process imports of the copied helper libraries with the task
    env of `ws`; constants in consts (e.g. CLAIM_TIMEOUT=1) are patched on _swe_common."""
    def load(ws, t=100, **consts):
        for k in list(os.environ):
            if k.startswith(("SWE_", "TEST_TMPDIR", "PYTHONPATH")):
                monkeypatch.delenv(k)
        for k, v in env_for(ws, t).items():
            monkeypatch.setenv(k, v)
        monkeypatch.chdir(ws)
        for m in MODS:
            sys.modules.pop(m, None)
        monkeypatch.syspath_prepend(str(scripts))
        import _swe_common as C
        import _swe_gate as G
        import _swe_ckpt as K
        for k, v in consts.items():
            monkeypatch.setattr(C, k, v)
        return C, G, K
    yield load
    for m in MODS:
        sys.modules.pop(m, None)


# --------------------------------------------------------------------------------------------------------- R52 repro
def test_repro_only_states(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    forms = [re.compile(x) for x in LINE1_FORMS]

    def check(res, want):
        hits = [i for i, rx in enumerate(forms) if rx.match(res.first)]
        assert hits == [want], res.out
    # 5: nothing saved, stdin an open pipe nobody writes to: returns within 1.2 s
    e = env_for(ws)
    t0 = time.monotonic()
    p = subprocess.Popen([PY, str(scripts / "verify.py"), "--repro-only"], cwd=str(ws), env=e, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, _ = p.communicate(timeout=10)
    finally:
        if p.stdin:
            p.stdin.close()
    secs = time.monotonic() - t0
    check(Res(out.decode(), secs), 4)
    assert secs <= 1.2 + 0.3, secs          # 1.0 s select guard + interpreter start; 0.3 s slack for a loaded runner
    # 1: fails on original; the repro is saved verbatim
    r = repro_only(scripts, ws, REPRO_FAIL + "EOF\n")
    check(r, 0)
    assert r.first.startswith("REPRO: fails on original (2 of 2 claims): claim 1 AssertionError: 'ab '"), r.out
    assert (swe(ws) / "repro.py").read_text() == REPRO_FAIL
    assert len(r.out) <= 1200
    # 2: a claim that passes on original
    r = repro_only(scripts, ws, REPRO_FAIL.replace("assert len(pad('x', 3)) == 3", "assert pad('ab', 1) == 'ab'"))
    check(r, 1)
    assert r.first.startswith("REPRO: claim 2 passes"), r.out
    # 4: BROKEN (NameError of a name another section defines) with the prelude hint
    r = repro_only(scripts, ws, "from pkg.text import pad\n# CLAIM 1: uses v\nassert v == 3\n"
                                "# CLAIM 2: defines v\nv = len(pad('ab', 4))\nassert v == 4\n")
    check(r, 3)
    assert "NameError" in r.first and "put shared code before the first # CLAIM line" in r.out, r.out
    # a whole-file syntax error is reported before anything runs
    r = repro_only(scripts, ws, "# CLAIM 1: x\nif True\n    pass\n")
    assert r.first.startswith("REPRO INVALID: syntax error line 2"), r.out
    # the --text form (skill args) equals stdin
    r = run(scripts, "verify", ws, ["--repro-only", "--text", REPRO_FAIL])
    check(r, 0)


def test_repro_only_hang_form(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    t0 = time.monotonic()
    r = repro_only(scripts, ws, "import time\n# CLAIM 1: loops forever\ntime.sleep(60)\n")
    assert re.match(LINE1_FORMS[2], r.first), r.out
    assert r.first == "REPRO: claim 1 hangs on original (expected for hang bugs)."
    assert time.monotonic() - t0 < 10 + 4                    # CLAIM_TIMEOUT plus start-up


def test_repro_only_with_source_change_saves_quick_checkpoint(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    repro_only(scripts, ws, REPRO_FAIL)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r = repro_only(scripts, ws, "")
    assert r.first == "REPRO: 2/2 claims fixed", r.out
    assert re.search(r"^CHECKPOINT: #1 saved \(quick\)", r.out, re.M), r.out
    st = json.loads((swe(ws) / "state.json").read_text())
    assert st["ckpts"][0]["quick"] is True and len(st["ckpts"][0]["score"]) == 5


# ---------------------------------------------------------------------------------------------- R53 claim scheduling
INSTR_CLAIM = textwrap.dedent('''\
    # CLAIM {n}: instrumented
    s = time.time()
    time.sleep(0.4)
    open(os.path.join(os.environ["SWE_TEST_INSTR"], "{n}.json"), "w").write(json.dumps([s, time.time()]))
    assert False
''')


def test_claim_sections_concurrency_budget(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    prelude, cl, new, msgs = G.claims.parse("import os\n# NEW: a, C.b, f(p=)\n# MESSAGE: \"bad value given\"\n"
                                           "# CLAIM 1: one\nassert 1\n#CLAIM 2:two\nassert 2\n")
    assert prelude.startswith("import os") and [c.idx for c in cl] == [1, 2] and cl[1].title == "two"
    assert cl[0].text.startswith(prelude) and "assert 2" not in cl[0].text
    assert new == ["a", "C.b", "f(p=)"] and msgs == ["bad value given"]
    _, cl, _, _ = G.claims.parse("x = 1\nassert x == 2\n")
    assert len(cl) == 1 and cl[0].text == "x = 1\nassert x == 2\n"
    _, cl, _, _ = G.claims.parse("".join("# CLAIM %d: c\nassert %d\n" % (i, i) for i in range(1, 9)))
    assert len(cl) == 6 == G.MAX_CLAIMS
    # at most MAX_PAR claim processes at once (instrumented: each records its own interval)
    instr = tmp_path / "instr"
    instr.mkdir()
    text = "import json, os, time\n" + "".join(INSTR_CLAIM.format(n=i) for i in range(1, 7))
    r = run(scripts, "verify", ws, ["--repro-only"], stdin=text, env=env_for(ws, SWE_TEST_INSTR=instr))
    assert r.first.startswith("REPRO: fails on original (6 of 6 claims)"), r.out
    spans = [json.loads((instr / ("%d.json" % i)).read_text()) for i in range(1, 7)]
    events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    assert peak <= 2, spans
    # CLAIM_TIMEOUT per claim and CLAIMS_TOTAL overall (shrunk in-process): 4 claims HANG, the rest are UNKNOWN
    C, G, K = lib(ws, CLAIM_TIMEOUT=1, CLAIMS_TOTAL=2.6)
    text = "import time\n" + "".join("# CLAIM %d: sleeps\ntime.sleep(30)\n" % i for i in range(1, 7))
    t0 = time.monotonic()
    res = G.claims.run(str(ws), "orig", G.sha1(text), text=text)
    secs = time.monotonic() - t0
    st = [res[i]["status"] for i in range(1, 7)]
    assert st[:4] == ["HANG"] * 4 and st[4:] == ["UNKNOWN"] * 2, res
    assert secs < 2.6 + 1.5, secs


# ------------------------------------------------------------------------------------------------- R54 claim classes
M_PY = '''\
def f(x):
    return x + 1


def g(x):
    return x * 2


def h():
    return 1
'''


def test_claim_matrix(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": M_PY})
    edit_file(ws, "pkg/m.py", "return x + 1", "return x + 21")         # f fixed (edits change the file size:
    edit_file(ws, "pkg/m.py", "return x * 2", "return x * 30")         # g broken  see test_v10_finalize._RACY_NOTE)
    write(ws, "pkg/newsub.py", "def thing():\n    return 1\n")
    C, G, K = lib(ws, CLAIM_TIMEOUT=1.5)
    a = ("from pkg.m import f, g, h\n"
         "# CLAIM 1: fixed\nassert f(1) == 22\n"
         "# CLAIM 2: still fails\nassert f(1) == 99\n"
         "# CLAIM 3: still hangs\nwhile True:\n    pass\n"
         "# CLAIM 4: broke\nassert g(2) == 4\n"
         "# CLAIM 5: invalid\nassert h() == 1\n"
         "# CLAIM 6: broken syntax\nif True\n    pass\n")
    G.save_repro(a)
    R = G.evaluate(quick=True, run_tests=False, advice=False, repro_only=True)
    s = R["repro"]["summary"]
    assert [s["classes"][i] for i in range(1, 7)] == ["FIXED", "STILL FAILS", "STILL HANGS", "BROKE", "INVALID",
                                                      "BROKEN"], R["repro"]
    assert s["text"] == "1/3 claims fixed" and s["valid"] == [1, 2, 3]
    assert "SyntaxError" in R["repro"]["orig"][6]["broken"]
    assert R["score"][3] == 0                                           # a claim hangs now
    b = ("from pkg.m import f\n"
         "# CLAIM 1: a name only another section defines\nassert helper_value == 22\n"
         "# CLAIM 2: defines it\nhelper_value = f(1)\nassert helper_value == 22\n"
         "# CLAIM 3: a module that does not exist anywhere\nimport nonexistent_mod_zz_qq\n"
         "# CLAIM 4: a new submodule of an existing package\nfrom pkg.newsub import thing\nassert thing() == 1\n")
    G.save_repro(b)
    R = G.evaluate(quick=True, run_tests=False, advice=False, repro_only=True)
    s = R["repro"]["summary"]
    orig = R["repro"]["orig"]
    assert [s["classes"][i] for i in range(1, 5)] == ["BROKEN", "FIXED", "BROKEN", "FIXED"], R["repro"]
    assert orig[1]["hint"] == "put shared code before the first # CLAIM line"
    assert "No module named 'pkg.newsub'" in orig[4]["sig"] and not orig[4]["broken"]
    assert s["text"] == "2/2 claims fixed"
    assert G.classify({"status": "FAIL"}, {"status": "UNKNOWN"}) == "UNKNOWN"


# ------------------------------------------------------------------------------------ R55 base tree and original cache
def test_base_tree_and_orig_cache(scripts, tmp_path):
    ws = mkrepo(tmp_path, {".gitignore": "pkg/_speedups.py\n", "pkg/__init__.py": "",
                           "pkg/fast.py": "from pkg._speedups import factor\n\n\ndef speed(x):\n    return x * factor\n"})
    write(ws, "pkg/_speedups.py", "factor = 2\n")                     # a built artefact: untracked and git-ignored
    log = tmp_path / "claims.log"
    repro = ("import os\nfrom pkg.fast import speed\n# CLAIM 1: speed\n"
             "open(os.environ['SWE_TEST_LOG'], 'a').write(os.getcwd() + '\\n')\n"
             "open('made_by_claim.txt', 'w').write('x')\n"
             "assert speed(2) == 5, speed(2)\n")
    env = env_for(ws, SWE_TEST_LOG=log)
    run(scripts, "verify", ws, ["--repro-only"], stdin=repro, env=env)
    edit_file(ws, "pkg/fast.py", "return x * factor", "return x * factor + 1")
    before = porcelain(ws)
    r1 = run(scripts, "verify", ws, env=env)
    assert r1.line("REPRO:") == "REPRO: 1/1 claims fixed", r1.out
    edit_file(ws, "pkg/fast.py", "return x * factor + 1", "return 1 + x * factor")
    r2 = run(scripts, "verify", ws, env=env)
    assert r2.line("REPRO:") == "REPRO: 1/1 claims fixed", r2.out
    base = swe(ws) / "base"
    assert (base / "pkg/_speedups.py").read_text() == "factor = 2\n"
    assert (base / "pkg/fast.py").read_text().endswith("return x * factor\n")
    cwds = log.read_text().split()
    # the first --repro-only ran on the workspace (no change yet); both verifies reuse that original result
    assert cwds.count(str(base)) == 0 and len(cwds) == 3, cwds
    assert porcelain(ws) == before
    assert not (ws / "made_by_claim.txt").exists() and not (base / "made_by_claim.txt").exists()
    st = json.loads((swe(ws) / "state.json").read_text())
    assert st["base"]["ok"] is True and st["repro"]["orig"]["1"]["status"] == "FAIL"
    # a new repro sha re-runs the original side, now in the base tree (the workspace has a change)
    r3 = run(scripts, "verify", ws, ["--repro-only"], stdin=repro.replace("== 5", "== 5 + 0"), env=env)
    assert r3.first == "REPRO: 1/1 claims fixed", r3.out
    cwds = log.read_text().split()
    assert cwds.count(str(base)) == 1, cwds


# ----------------------------------------------------------------------------------------------- R56 import check
def test_import_check(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, dict(BASIC, **{"pkg/old.py": "X = 1\n"}))
    write(ws, "pkg/text.py", TEXT_PY + "\n\ndef broken(:\n    pass\n")
    r = verify(scripts, ws)
    assert r.first == "VERIFY: RED - import error", r.out
    assert re.search(r"^IMPORT: RED .*SyntaxError.*\(pkg/text\.py:9\)", r.out, re.M), r.out
    assert "NEXT: fix the error at pkg/text.py:9 with python3 /tmp/swe/edit.py" in r.out
    assert not list(ws.rglob("*.pyc")) and not list(ws.rglob("__pycache__"))
    write(ws, "pkg/text.py", TEXT_PY + "\nundefined_zz\n")
    r = verify(scripts, ws)
    assert r.first == "VERIFY: RED - import error", r.out
    assert "IMPORT: RED pkg.text: NameError: name 'undefined_zz' is not defined (pkg/text.py:8)" in r.out, r.out
    # deleted modules are skipped; a good change imports fine
    write(ws, "pkg/text.py", TEXT_PY.replace("width - 1", "width"))
    (ws / "pkg/old.py").unlink()
    r = verify(scripts, ws)
    assert r.line("IMPORT:") == "IMPORT: ok (pkg from workspace)", r.out
    C, G, K = lib(ws)
    write(ws, "src/spk/__init__.py", "")
    write(ws, "src/spk/sub/__init__.py", "")
    write(ws, "src/spk/sub/mod.py", "")
    write(ws, "loose/mod.py", "")
    assert G.module_name("src/spk/sub/mod.py") == "spk.sub.mod"
    assert G.module_name("src/spk/sub/__init__.py") == "spk.sub"
    assert G.module_name("pkg/text.py") == "pkg.text" and G.module_name("pkg/__main__.py") is None
    assert G.module_name("loose/mod.py") is None and G.module_name("setup.py") is None
    assert G.compile_check(["pkg/text.py"]) is None


# ------------------------------------------------------------------------------------------------- R57 discovery
def test_discovery_rules(scripts, tmp_path, lib):
    files = {
        "pkg/__init__.py": "", "pkg/text.py": "def divide(a):\n    return a\n\n\ndef keep():\n    return 0\n",
        "tests/test_text.py": "from pkg.text import divide\n\ndef test_x():\n    assert divide(1) == 1\n",
        "tests/test_users.py": "from pkg import text\n\ndef test_y():\n    assert text.divide(2) == 2\n",
        "tests/test_mentions.py": "# divide\ndef test_z():\n    pass\n",
        "tests/test_stem_only.py": "# text\ndef test_w():\n    pass\n",
        "tests/test_unrelated.py": "def test_u():\n    pass\n",
        "tests/render.py": "# divide text\n", "tests/_card_render.py": "# divide text\n",
        "tests/conftest.py": "# divide text\n", "tools/test_tool.py": "# divide text\n",
        "tests/test_huge.py": "# divide text\n" + "#" * 310000 + "\n",
    }
    ws = mkrepo(tmp_path, files)
    edit_file(ws, "pkg/text.py", "return a\n", "return a + 0\n")
    r = verify(scripts, ws, "--list-tests")
    assert r.first == "TESTS: tests/test_text.py tests/test_users.py tests/test_mentions.py", r.out
    r = verify(scripts, ws, "--list-tests", "--tests", "tests/test_stem_only.py::test_w, tests/nope.py")
    assert r.first == "TESTS: tests/test_stem_only.py::test_w tests/test_text.py tests/test_users.py", r.out
    C, G, K = lib(ws)
    for p in ("tests/render.py", "tests/_card_render.py", "tests/conftest.py", "tools/test_tool.py"):
        assert not G.is_candidate(p)
    assert G.is_candidate("tests/test_a.py") and G.is_candidate("pkg/sub/x_test.py")
    # no related test at all
    edit_file(ws, "pkg/text.py", "def keep():\n    return 0", "def keep():\n    return 1")
    assert G.discover(["pkg/zzz_none.py"], (), {}, None) == []


# ---------------------------------------------------------------------------------------- R58 grader flags and env
def test_grader_flags_and_env(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    log = tmp_path / "py.log"
    real = shutil.which("python3", path=VBIN) or PY
    (fake / "python3").write_text('#!/bin/sh\nprintf "ARGV %%s || SAFE=%%s NOUSER=%%s\\n" "$*" "$PYTHONSAFEPATH" '
                                  '"$PYTHONNOUSERSITE" >> "%s"\nexec "%s" "$@"\n' % (log, real))
    (fake / "python3").chmod(0o755)
    env = env_for(ws)
    env["PATH"] = str(fake) + os.pathsep + env["PATH"]
    r = run(scripts, "verify", ws, env=env)
    assert r.line("TESTS:").startswith("TESTS: tests/test_text.py | original 2 passed | now 2 passed"), r.out
    lines = [ln for ln in log.read_text().split("\n") if ln]
    runs = [ln for ln in lines if ln.startswith("ARGV -s -m pytest ")]
    assert len(runs) == 2, lines                                         # ORIGINAL and CURRENT
    for a in runs:
        for flag in ("-p no:cacheprovider", "-p no:anyio", "-o timeout=0", "-o python_classes=Test* *Test",
                     "--junitxml="):
            assert flag in a, a
        assert "addopts" not in a
        assert a.endswith(" || SAFE=1 NOUSER=1"), a
    text = log.read_text()
    assert "pytest.main" not in text and "import pytest" not in text and "addopts" not in text


# ---------------------------------------------------------------------------------------- R59 PYTHONPATH mapping
def test_pythonpath_mapping(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, {"src/spk/__init__.py": "VALUE = 1\n", "src/spk/core.py": "def f():\n    return 1\n"})
    C, G, K = lib(ws)
    base = str(tmp_path / "base_tree")
    os.makedirs(base + "/src")
    os.environ["PYTHONPATH"] = os.pathsep.join([str(ws), str(ws / "src"), "/opt/elsewhere"])
    e = C.grader_env(base, "orig")
    assert e["PYTHONPATH"].split(os.pathsep) == [base, base + "/src", "/opt/elsewhere"]
    assert e["PYTHONSAFEPATH"] == "1" and e["PYTHONNOUSERSITE"] == "1" and e["TMPDIR"].endswith("rt_orig")
    os.environ["PYTHONPATH"] = ""
    assert C.grader_env(base, "orig")["PYTHONPATH"] == base
    # the import probe maps the src layout into state.origin, and grader_env then prepends tree/src
    os.environ["PYTHONPATH"] = str(ws / "src")
    edit_file(ws, "src/spk/core.py", "return 1", "return 22")
    res = G.import_check(["src/spk/core.py"])
    assert res["ok"] is True and res["origins"]["spk"].startswith(str(ws / "src"))
    assert C.state_load()["origin"]["spk"] == "src"
    os.environ["PYTHONPATH"] = ""
    assert C.grader_env(base, "orig")["PYTHONPATH"].split(os.pathsep) == [base + "/src", base]


def test_import_origin_outside_workspace_is_amber(scripts, tmp_path):
    ws = mkrepo(tmp_path, {"src/spk/__init__.py": "", "src/spk/core.py": "def f():\n    return 1\n"})
    other = tmp_path / "installed"
    write(other, "spk/__init__.py", "")
    write(other, "spk/core.py", "def f():\n    return 1\n")
    edit_file(ws, "src/spk/core.py", "return 1", "return 22")
    env = env_for(ws, PYTHONPATH=other)
    r = run(scripts, "verify", ws, env=env)
    assert r.first.startswith("VERIFY: AMBER - spk is imported from outside the workspace"), r.out
    assert "OUTSIDE WORKSPACE" in r.line("IMPORT:"), r.out


# ------------------------------------------------------------------------------------- R60 outcomes and UNKNOWN rules
JUNIT = '''<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="1" failures="1"
skipped="1" tests="5">
<testcase classname="tests.test_x.TestA" name="test_p[a b-\u00e9]" />
<testcase classname="tests.test_x.TestA.TestInner" name="test_q" ><failure message="AssertionError: 1 != 2&#10;more">x
</failure></testcase>
<testcase classname="tests.test_x" name="test_r"><error message="failed on setup">E</error></testcase>
<testcase classname="tests.test_x" name="test_s"><skipped message="skip" /></testcase>
<testcase classname="" name="tests.test_bad"><error message="collection failure">trace
E   ModuleNotFoundError: No module named 'zz'</error></testcase>
</testsuite></testsuites>'''


def test_test_outcomes_and_unknown(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    j = tmp_path / "j.xml"
    j.write_text(JUNIT, encoding="utf-8")
    outcomes, msgs, coll = G.parse_junit(str(j), ["tests/test_x.py", "tests/test_bad.py"])
    assert outcomes == {"tests/test_x.py::TestA::test_p[a b-\u00e9]": "passed",
                        "tests/test_x.py::TestA::TestInner::test_q": "failed",
                        "tests/test_x.py::test_r": "error", "tests/test_x.py::test_s": "skipped"}
    assert msgs["tests/test_x.py::TestA::TestInner::test_q"] == "AssertionError: 1 != 2"
    assert coll == {"tests/test_bad.py": "ModuleNotFoundError: No module named 'zz'"}

    def side(status="ok", outcomes=None, coll=None, why=""):
        return {"status": status, "why": why, "outcomes": outcomes or {}, "msgs": {}, "coll": coll or {}, "secs": 1}
    o = side(outcomes={"a": "passed", "b": "passed", "c": "failed", "d": "passed"})
    c = side(outcomes={"a": "failed", "b": "error", "c": "failed", "d": "passed"})
    assert G.compare_tests(o, c)["regressions"] == ["a", "b"]
    only_now = G.compare_tests(side(outcomes={"a": "passed"}), side(outcomes={"a": "passed"}, coll={"t.py": "E"}))
    assert only_now["collects"] == 0 and only_now["status"] == "ok"
    both = G.compare_tests(side(coll={"t.py": "E"}), side(coll={"t.py": "E"}))
    assert both["status"] == "unknown" and both["collects"] == 1
    assert G.compare_tests(side("timeout"), side("timeout"))["status"] == "unknown"
    hang = G.compare_tests(side(outcomes={"a": "passed"}), side("timeout"))
    assert hang["hang_now"] is True
    nojunit = str(tmp_path / "missing.xml")
    for rc, out, why in ((2, "", "pytest exit 2"), (4, "", "pytest exit 4"), (5, "", "pytest exit 5"),
                         (1, "pytest is disabled in this environment", G.DISABLED_TEXT)):
        j.write_text('<testsuites><testsuite tests="0"></testsuite></testsuites>')
        r = G.side_result(rc, out, str(j), [], 1.0, True)
        assert r["status"] == "unknown" and why in r["why"], (rc, r)
    assert G.side_result(0, "", nojunit, [], 1.0, True)["status"] == "unknown"
    j.write_text('<testsuites><testsuite tests="0"></testsuite></testsuites>')
    assert G.side_result(0, "", str(j), [], 1.0, True)["why"] == "0 tests ran"
    assert G.side_result(None, "", str(j), [], 40.0, True)["status"] == "timeout"
    assert G.side_result(None, "", str(j), [], 3.0, False)["status"] == "unknown"


def test_deflake_and_collection_rules_cli(scripts, tmp_path):
    flaky = textwrap.dedent('''\
        import os
        from pkg.text import center


        def test_flaky():
            if os.getcwd() == os.environ["SWE_TEST_WS"]:
                p = os.path.join(os.environ["SWE_TEST_DIR"], "n")
                n = int(open(p).read()) if os.path.exists(p) else 0
                open(p, "w").write(str(n + 1))
                assert n >= 1, "fails only on the first CURRENT run"


        def test_center():
            assert center("a", 3) == " a "
    ''')
    ws = mkrepo(tmp_path, dict(BASIC, **{"tests/test_flaky_text.py": flaky,
                                         "tests/test_text_plugin.py": "import zz_missing_plugin_mod\n\n"
                                                                      "def test_p():\n    pass\n"}))
    d = tmp_path / "flaky"
    d.mkdir()
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    env = env_for(ws, SWE_TEST_WS=ws, SWE_TEST_DIR=d)
    r = run(scripts, "verify", ws, ["--tests", "tests/test_flaky_text.py", "tests/test_text_plugin.py",
                                    "tests/test_text.py"], env=env)
    assert not r.first.startswith("VERIFY: RED"), r.out
    assert "1 flaky (passed on rerun)" in r.out and "REGRESSIONS" not in r.out, r.out
    assert "collection error on both sides: tests/test_text_plugin.py" in r.out, r.out
    # a collection error on CURRENT only is RED
    write(ws, "pkg/text.py", "def pad(s, width):\n    return s\n")
    r = run(scripts, "verify", ws, ["--tests", "tests/test_text.py"], env=env)
    assert r.first == "VERIFY: RED - regressions", r.out
    assert "COLLECTION ERRORS" in r.out and "cannot import name 'center'" in r.out, r.out


# ------------------------------------------------ R60 review round 2: pytest's rootdir below the workspace (rich tasks)
# pytest names JUnit classnames after node ids relative to ITS rootdir, the directory of the nearest ini file. All 45
# rich snapshots ship tests/pytest.ini, so tests/test_markup.py reports as classname "test_markup", not
# "tests.test_markup"; ids built from that could not be re-run (pytest: file not found) and de-flaking did nothing.
JUNIT_NESTED = '''<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="8">
<testcase classname="test_x" name="test_a" />
<testcase classname="test_x.TestA" name="test_b"><failure message="boom&#10;more">x</failure></testcase>
<testcase classname="unit.test_x" name="test_c" />
<testcase classname="unit.test_x.TestB.TestInner" name="test_d[p-1]" />
<testcase classname="test_x_extra" name="test_e" />
<testcase classname="" name="test_bad"><error message="collection failure">trace
E   ImportError: cannot import name 'zz'</error></testcase>
<testcase classname="" name="unit.test_bad2"><error message="collection failure">trace
E   ModuleNotFoundError: No module named 'yy'</error></testcase>
</testsuite></testsuites>'''


def test_parse_junit_rootdir_below_workspace(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    j = tmp_path / "j.xml"
    j.write_text(JUNIT_NESTED, encoding="utf-8")
    # the deeper file comes first on purpose: the most specific suffix (fewest leading parts dropped) wins
    files = ["tests/unit/test_x.py", "tests/test_x.py", "tests/test_bad.py", "tests/unit/test_bad2.py"]
    t0 = time.monotonic()
    outcomes, msgs, coll = G.parse_junit(str(j), files)
    assert time.monotonic() - t0 < 0.5
    assert outcomes == {"tests/test_x.py::test_a": "passed", "tests/test_x.py::TestA::test_b": "failed",
                        "tests/unit/test_x.py::test_c": "passed",
                        "tests/unit/test_x.py::TestB::TestInner::test_d[p-1]": "passed",
                        "test_x_extra::test_e": "passed"}, outcomes      # no file of that name: kept as reported
    assert msgs == {"tests/test_x.py::TestA::test_b": "boom"}
    assert coll == {"tests/test_bad.py": "ImportError: cannot import name 'zz'",
                    "tests/unit/test_bad2.py": "ModuleNotFoundError: No module named 'yy'"}, coll
    # the re-run passes node ids as its files; they map back to the same ids
    assert G.parse_junit(str(j), ["tests/test_x.py::test_a", "tests/test_x.py::TestA::test_b"])[0] == {
        "tests/test_x.py::test_a": "passed", "tests/test_x.py::TestA::test_b": "failed",
        "unit.test_x::test_c": "passed", "unit.test_x.TestB.TestInner::test_d[p-1]": "passed",
        "test_x_extra::test_e": "passed"}
    # control: root-relative classnames (rootdir = the workspace) map exactly as before
    root_rel = JUNIT_NESTED.replace('classname="test_x', 'classname="tests.test_x').replace(
        'classname="unit.', 'classname="tests.unit.')
    j.write_text(root_rel, encoding="utf-8")
    assert G.parse_junit(str(j), files)[0] == {
        "tests/test_x.py::test_a": "passed", "tests/test_x.py::TestA::test_b": "failed",
        "tests/unit/test_x.py::test_c": "passed", "tests/unit/test_x.py::TestB::TestInner::test_d[p-1]": "passed",
        "tests.test_x_extra::test_e": "passed"}
    assert G.display_id("test_x.TestA", "t", ["tests/test_x.py"]) == "tests/test_x.py::TestA::t"
    assert G.display_id("xtest_x", "t", ["tests/test_x.py"]) == "xtest_x::t"          # a dot boundary is required


def test_rerun_with_nested_pytest_ini(scripts, tmp_path):
    """The de-flake rerun works when tests/pytest.ini moves pytest's rootdir (review round 2): a test that fails only
    on the first CURRENT run is reported flaky, and a real regression is named by its runnable path."""
    flaky = textwrap.dedent('''\
        import os
        from pkg.text import center


        def test_flaky():
            if os.getcwd() == os.environ["SWE_TEST_WS"]:
                p = os.path.join(os.environ["SWE_TEST_DIR"], "n")
                n = int(open(p).read()) if os.path.exists(p) else 0
                open(p, "w").write(str(n + 1))
                assert n >= 1, "fails only on the first CURRENT run"
    ''')
    ws = mkrepo(tmp_path, dict(BASIC, **{"tests/pytest.ini": "[pytest]\njunit_family=legacy\n",
                                         "tests/test_flaky_text.py": flaky}))
    d = tmp_path / "flaky"
    d.mkdir()
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    env = env_for(ws, SWE_TEST_WS=ws, SWE_TEST_DIR=d)
    r = run(scripts, "verify", ws, ["--tests", "tests/test_flaky_text.py", "tests/test_text.py"], env=env)
    assert "1 flaky (passed on rerun)" in r.out and "REGRESSIONS" not in r.out, r.out
    assert not r.first.startswith("VERIFY: RED"), r.out
    assert (d / "n").read_text() == "2", "the rerun must actually run the test"
    # a real regression under the nested ini: named by a path pytest can run, and the rerun collected it
    write(ws, "pkg/text.py", "def pad(s, width):\n    return 'x'\n\n\ndef center(s, width):\n    return s.center(width)\n")
    r = run(scripts, "verify", ws, ["--tests", "tests/test_text.py"], env=env)
    assert r.first == "VERIFY: RED - regressions", r.out
    assert re.search(r"^  tests/test_text\.py::test_pad_zero  ", r.out, re.M), r.out
    rerun = (swe(ws) / "j_rerun.xml").read_text()
    assert rerun.count("<testcase ") == 1 and 'name="test_pad_zero"' in rerun, rerun


# --------------------------------------------------------------------------------------------- R61 masked pytest
def _container_setup():
    """The installed harness's container_setup.py, found without importing swegemma (it pulls in litellm)."""
    import importlib.util
    spec = importlib.util.find_spec("swegemma")
    locs = list(spec.submodule_search_locations or []) if spec else []
    p = pathlib.Path(locs[0]) / "harness" / "container_setup.py" if locs else None
    return p if p and p.exists() else None


def _shim_script():
    src = _container_setup().read_text()
    body = src[src.index("def disable_test_runners_in_sandbox"):]
    script = body[body.index("script = r'''") + len("script = r'''"):]
    script = script[:script.index("'''")]
    # verbatim pytest part; the unittest part is cut (it would rewrite the host interpreter's stdlib)
    return script[:script.index("unittest_discovery_msg")]


@pytest.fixture(scope="module")
def masked_venv(tmp_path_factory):
    if _container_setup() is None:
        pytest.skip("swegemma harness not installed")
    d = tmp_path_factory.mktemp("masked") / "venv"
    base_py = os.path.join(sys.base_prefix, "bin", "python3")
    subprocess.run([base_py, "-m", "venv", "--without-pip", str(d)], check=True, capture_output=True, timeout=120)
    site = next((d / "lib").glob("python3*/site-packages"))
    real_site = pathlib.Path(__import__("_pytest").__file__).resolve().parents[1]
    main_py = real_site / "pytest" / "__main__.py"
    before = hashlib.sha256(main_py.read_bytes()).hexdigest()
    shutil.copytree(real_site / "pytest", site / "pytest")          # the shim rewrites this copy only
    for n in ("_pytest", "pluggy", "iniconfig", "packaging", "pygments", "py.py"):
        if (real_site / n).exists():
            os.symlink(real_site / n, site / n)
    bindir = d / "bin"
    script = _shim_script().replace("/usr/local/bin/", str(bindir) + "/")
    r = subprocess.run([str(bindir / "python3"), "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert hashlib.sha256(main_py.read_bytes()).hexdigest() == before, "the real pytest must stay untouched"
    assert "pytest is disabled in this environment" in (site / "pytest/__main__.py").read_text()
    return bindir


def test_masked_pytest(scripts, tmp_path, masked_venv):
    ws = mkrepo(tmp_path, BASIC)
    env = env_for(ws)
    env["PATH"] = str(masked_venv) + os.pathsep + env["PATH"]
    run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO_FAIL, env=env)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r = subprocess.run([str(masked_venv / "python3"), "-X", "importtime", str(scripts / "verify.py")], cwd=str(ws),
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    out = r.stdout
    assert "TESTS: unavailable (pytest is disabled in this environment" in out, out
    assert "REPRO: 2/2 claims fixed" in out, out
    assert out.startswith("VERIFY: AMBER - tests unavailable"), out
    imported = [ln.rsplit("|", 1)[-1].strip() for ln in r.stderr.splitlines() if ln.startswith("import time:")]
    assert imported and not any(m.split(".")[0] in ("pytest", "_pytest") for m in imported), imported


# ------------------------------------------------------------------------------------------ R62 verdicts and wording
def _R(ne=True, imp=None, valid=(), fixed=0, classes=None, cur=None, tests=None, quick=False, repro=True):
    summ = {"valid": list(valid), "fixed": fixed, "broke": 0, "classes": classes or {},
            "text": "%d/%d claims fixed" % (fixed, len(valid))}
    R = {"nonempty": ne, "import": imp or {"ok": True, "origins": {"pkg": "/ws/pkg/__init__.py"}, "outside": {}},
         "tests": tests, "quick": quick, "repro": {"summary": summ, "cur": cur or {}} if repro else None}
    return R


def test_verdict_table_and_wording(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    ok_tests = {"status": "ok", "regressions": [], "collects": 1, "hang_now": False}
    table = [
        (_R(ne=False), "VERIFY: NO SOURCE CHANGE - make the plan's change with python3 /tmp/swe/edit.py first."),
        (_R(imp={"ok": False, "module": "pkg.m", "line": "NameError", "where": "pkg/m.py:3"}),
         "VERIFY: RED - import error"),
        (_R(valid=[1, 2], fixed=1, classes={1: "FIXED", 2: "STILL FAILS"}, cur={2: {"sig": "AssertionError"}},
            tests=ok_tests), "VERIFY: RED - 1/2 claims fixed"),
        (_R(valid=[1], fixed=0, classes={1: "STILL HANGS"}, cur={1: {"status": "HANG"}}),
         "VERIFY: RED - 0/1 claims fixed"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED", 2: "BROKE"}, cur={2: {"sig": "AssertionError"}}),
         "VERIFY: RED - 1/1 claims fixed"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests=dict(ok_tests, regressions=["t::a"])),
         "VERIFY: RED - regressions"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests=dict(ok_tests, collects=0, coll_now={"t.py": "E"})),
         "VERIFY: RED - regressions"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests={"status": "ok", "hang_now": True, "regressions": []}),
         "VERIFY: RED - regressions"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests=ok_tests), "VERIFY: GREEN"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests={"status": "none"}), "VERIFY: GREEN"),
        (_R(repro=False, tests=ok_tests), "VERIFY: AMBER - no reproduction saved"),
        (_R(classes={1: "INVALID"}, tests=ok_tests), "VERIFY: AMBER - the reproduction passes on original"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests={"status": "unknown", "why": "pytest exit 4"}),
         "VERIFY: AMBER - tests unknown (pytest exit 4)"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests={"status": "skipped"}),
         "VERIFY: AMBER - tests skipped (quick mode)"),
        (_R(valid=[1], fixed=1, classes={1: "FIXED"}, tests=ok_tests,
            imp={"ok": True, "outside": {"pkg": "/site/pkg"}}),
         "VERIFY: AMBER - pkg is imported from outside the workspace (/site/pkg)"),
    ]
    for R, want in table:
        first, nxt, word = G.verdict(R)
        assert first == want, (want, first)
        assert nxt.startswith("NEXT:") or nxt == G.REGRESSION_NOTE
        assert not BAD_WORDS.search(nxt)
    assert G.verdict(table[5][0])[1] == G.REGRESSION_NOTE
    assert "OLD behaviour" in G.REGRESSION_NOTE and not BAD_WORDS.search(G.REGRESSION_NOTE)
    # CLI: GREEN without any related test file; RED regressions wording; UNKNOWN on an internal error
    ws2 = mkrepo(tmp_path / "b", {"pkg/__init__.py": "", "pkg/text.py": TEXT_PY})
    repro_only(scripts, ws2, REPRO_FAIL)
    edit_file(ws2, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r = verify(scripts, ws2)
    assert r.first == "VERIFY: GREEN" and r.line("TESTS:") == "TESTS: none related", r.out
    assert r.line("NEXT:") == ("NEXT: ready. Fixer: reply with your notes. Verifier: run "
                               "python3 /tmp/swe/finalize.py."), r.out
    edit_file(ws, "pkg/text.py", "return s.center(width)", "return s.center(width + 2)")
    r = verify(scripts, ws)
    assert r.first == "VERIFY: RED - regressions", r.out
    assert "tests/test_text.py::test_center" in r.out and "NEXT: If a test asserts the OLD behaviour" in r.out
    assert not BAD_WORDS.search(r.out)
    broken = tmp_path / "broken_scripts"
    shutil.copytree(scripts, broken)
    with open(broken / "_swe_gate.py", "a") as f:
        f.write("\n\ndef evaluate(*a, **k):\n    raise RuntimeError('boom')\n")
    edit_file(ws, "pkg/text.py", "width + 2", "width + 4")
    r = run(broken, "verify", ws)
    assert r.first == "VERIFY: UNKNOWN - internal error (RuntimeError: boom)", r.out


def test_no_source_change_is_fast(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    with open(ws / "tests/test_text.py", "a") as f:
        f.write("# a test-only edit is reverted and does not count\n")
    r = verify(scripts, ws)
    assert r.first == "VERIFY: NO SOURCE CHANGE - make the plan's change with python3 /tmp/swe/edit.py first.", r.out
    assert "HYGIENE: reverted tests/test_text.py" in r.out, r.out
    assert (ws / "tests/test_text.py").read_text() == TEXT_TESTS
    r2 = verify(scripts, ws)
    assert r2.first == r.first
    assert min(r.secs, r2.secs) < 1.0, (r.secs, r2.secs)      # best of two: a busy CI host adds noise


def test_skill_arg_forms(tmp_path):
    """run_skill_script passes args as --key value (booleans as True, lists as str(list)); cwd is the wrapper dir."""
    from v10_support import repo as RP
    ws = RP.make_repo(tmp_path, BASIC)
    scripts = RP.copy_helpers(tmp_path)
    env = RP.helper_env(ws, tmp_path / "sbx" / "swe", fake_t=100)
    later_stage(tmp_path / "sbx" / "swe")                 # v10.2: t=100 is a later stage (no locator budget)
    env["PATH"] = VBIN + os.pathsep + env["PATH"]

    def out(r):
        return r.stdout if hasattr(r, "stdout") else str(r)
    r = out(RP.run_as_skill(scripts, "verify", ["--repro-only", "True", "--text", REPRO_FAIL], ws=ws, env=env))
    assert r.startswith("REPRO: fails on original (2 of 2 claims)"), r
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r = out(RP.run_as_skill(scripts, "verify", ["--tests", "['tests/test_text.py']"], ws=ws, env=env, timeout=60))
    assert r.startswith("VERIFY: GREEN") and "TESTS: tests/test_text.py |" in r, r
    r = out(RP.run_as_skill(scripts, "finalize", [], ws=ws, env=env))
    assert r.startswith("READY: 1 files changed (+1 -1): pkg/text.py."), r


# --------------------------------------------------------------------------------------------------------- R63 memo
def test_memo(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r1 = verify(scripts, ws)
    r2 = verify(scripts, ws)
    assert r2.first == "SAME AS LAST RUN (t=100s): " + r1.first, r2.out
    nxt = r1.line("NEXT:")
    assert r2.line("NEXT:") == nxt and "STOP" not in r2.out
    r3 = verify(scripts, ws)
    assert "STOP re-running verify; decide now." in r3.out
    assert r3.first == r2.first and r3.line("NEXT:") == nxt
    assert min(r2.secs, r3.secs) <= 0.3 + 0.1, (r2.secs, r3.secs)   # 300 ms (+ interpreter start), best of two
    edit_file(ws, "pkg/text.py", "s.ljust(width)", "s.ljust(width) ")
    r4 = verify(scripts, ws)
    assert not r4.first.startswith("SAME AS LAST RUN"), r4.out


# ------------------------------------------------------------------------------------- R64 original tests are cached
def test_second_run_cached_speed(scripts, tmp_path):
    counted = TEXT_TESTS.replace("from pkg.text import pad, center\n",
                                 "import os\nfrom pkg.text import pad, center\n"
                                 "open(os.environ['SWE_TEST_LOG'], 'a').write(os.getcwd() + '\\n')\n")
    ws = mkrepo(tmp_path, dict(BASIC, **{"tests/test_text.py": counted}))
    log = tmp_path / "runs.log"
    env = env_for(ws, SWE_TEST_LOG=log)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r1 = run(scripts, "verify", ws, env=env)
    edit_file(ws, "pkg/text.py", "s.ljust(width)", "s.ljust(width + 0)")
    r2 = run(scripts, "verify", ws, env=env)
    cwds = log.read_text().split()
    base = str(swe(ws) / "base")
    assert cwds.count(base) == 1 and cwds.count(str(ws)) == 2, cwds
    assert r1.line("TESTS:") and r2.line("TESTS:").startswith("TESTS: tests/test_text.py | original 2 passed")
    assert r1.secs <= 8 and r2.secs <= 8, (r1.secs, r2.secs)          # verify p90 budget on local tasks
    # the cache keeps the 4 most recent file sets only (state.json is read by every helper call)
    st = json.loads((swe(ws) / "state.json").read_text())
    for k in range(6):
        st["orig_tests"]["old%d" % k] = {"status": "ok", "why": "", "outcomes": {}, "coll": {}, "secs": 1, "at": k}
    (swe(ws) / "state.json").write_text(json.dumps(st))
    edit_file(ws, "pkg/text.py", "s.ljust(width + 0)", "s.ljust(width + 11)")
    run(scripts, "verify", ws, ["--tests", "tests/test_text.py::test_center"], env=env)
    kept = json.loads((swe(ws) / "state.json").read_text())["orig_tests"]
    assert len(kept) == 4 and {"old4", "old5"} < set(kept) and "old3" not in kept, sorted(kept)


# --------------------------------------------------------------------------------- R65 quick mode and session clamp
def test_quick_mode_and_session_clamp(scripts, tmp_path, lib):
    """R65 (end-game plan, review round 1): quick mode from T_QUICK (235), or earlier when clock + 1.2 x last test
    secs + QUICK_PAD (15) passes T_VERIFY_END (262); past T_VERIFY_END a verify gets PHASE_MIN (3 s)."""
    ws = mkrepo(tmp_path, BASIC)
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    r = verify(scripts, ws, t=235)
    assert r.line("TESTS:") == "TESTS: skipped (quick mode)", r.out
    C, G, K = lib(ws, t=220)
    assert (C.T_QUICK, C.T_VERIFY_END, C.T_EVAL_END, C.QUICK_PAD) == (235, 262, C.T_NO_EVAL - 3, 15)
    C.state_update(lambda s: s.__setitem__("last_test_secs", 25.0))
    edit_file(ws, "pkg/text.py", "s.ljust(width)", "s.ljust(width + 0)")
    r = verify(scripts, ws, t=220)                                     # 220 + 1.2 x 25 + 15 > 262
    assert r.line("TESTS:") == "TESTS: skipped (quick mode)", r.out
    C.state_update(lambda s: s.__setitem__("last_test_secs", 20.0))
    edit_file(ws, "pkg/text.py", "s.ljust(width + 0)", "s.ljust(int(width) + 0)")
    r = verify(scripts, ws, t=220)                                     # 220 + 1.2 x 20 + 15 = 259
    assert r.line("TESTS:").startswith("TESTS: tests/test_text.py |"), r.out
    for t, want in ((100, 60.0), (250, 46.0), (290, 6.0), (299, 1.0)):
        C, G, K = lib(ws, t=t)
        assert C.real_budget(C.VERIFY_TOTAL) == want
    # the verify span: VERIFY_TOTAL, ended by T_VERIFY_END, never below PHASE_MIN while the helper budget allows it
    for t, want in ((100, 60.0), (220, 42.0), (240, 22.0), (259, 3.0), (262, 3.0), (290, 3.0)):
        assert verify_span(scripts, ws, t) == want, t
    # near the end a hanging claim is cut at PHASE_MIN: 3 s, plus 2 s
    repro_only(scripts, ws, "import time\n# CLAIM 1: hangs\ntime.sleep(60)\n", t=100)
    t0 = time.monotonic()
    r = verify(scripts, ws, t=290)
    assert time.monotonic() - t0 <= 3 + 2, r.out
    assert r.first.startswith("VERIFY:"), r.out


# ------------------------------------------------------------------------ review round 1: the end-game clock (R65)
SLOW_TESTS = ("import time\nfrom pkg.text import pad, center\n\n\ndef test_slow_a():\n    time.sleep(22)\n"
              "    assert center('a', 3) == ' a '\n\n\ndef test_slow_b():\n    time.sleep(22)\n    assert pad('', 0) == ''\n")
# every claim pays a 6 s prelude: 3 claims per side, both sides uncached -> 18 s of claims at MAX_PAR 2
SLOW_REPRO = "import time\nfrom pkg.text import pad\ntime.sleep(6)\n" + "".join(
    "# CLAIM %d: pads to the width\nassert pad('ab', 4) == 'ab  ', repr(pad('ab', 4))\n" % i for i in (1, 2, 3))


def _slow_case(scripts, tmp_path, t, name):
    ws = mkrepo(tmp_path / name, dict(BASIC, **{"tests/test_text.py": SLOW_TESTS}))
    edit_file(ws, "pkg/text.py", "s.ljust(width - 1)", "s.ljust(width)")
    swe(ws).mkdir(parents=True, exist_ok=True)
    (swe(ws) / "repro.py").write_text(SLOW_REPRO)
    return ws


def test_verify_ends_by_the_end_game_line(scripts, tmp_path):
    """Review round 1: a full verify started at 225-262 s could run to about 294 s, past T_NO_EVAL (275) and
    T_NO_RESTORE (285), so finalize could neither evaluate nor restore. Every verify now ends by T_VERIFY_END (262),
    PHASE_MIN (3 s) at the latest, whatever the tests (two 22 s tests, 44 s per side) and claims (18 s) would need."""
    from concurrent.futures import ThreadPoolExecutor
    clocks = (225, 240, 249, 262)
    cases = {t: _slow_case(scripts, tmp_path, t, "c%d" % t) for t in clocks}

    def go(t):
        return t, verify(scripts, cases[t], t=t, timeout=180)
    # at most one case per CPU: 4 concurrent slow cases on the 2-CPU Linux gate contend and overrun the deadline, a test
    # artifact (the scorer runs one task at a time); the deadline itself is still asserted per case below
    with ThreadPoolExecutor(max(1, min(len(clocks), (os.cpu_count() or 2) // 2))) as ex:
        got = dict(ex.map(go, clocks))
    for t in clocks:
        r = got[t]
        if t + r.secs > 265:
            # 2026-09-30: the t=262 case has no margin (3 s budget, 3.006 s and 3.10 s measured at load 22 on v10.1 and
            # v10.2 alike, passing on reruns), so an overrunning case runs once more on a fresh copy and the faster run
            # is asserted, as the repo's other timing budgets assert minima
            again = verify(scripts, _slow_case(scripts, tmp_path, t, "c%d_again" % t), t=t, timeout=180)
            r = again if again.secs < r.secs else r
        assert r.first.startswith("VERIFY:"), (t, r.out)
        assert t + r.secs <= 265, (t, round(r.secs, 2), r.out)
        if t >= 235:
            assert r.line("TESTS:") == "TESTS: skipped (quick mode)", (t, r.out)
    assert got[225].line("TESTS:").startswith("TESTS: tests/test_text.py |"), got[225].out   # full mode: 225+0+15


def test_quick_evaluations_end_by_t_eval_end(scripts, tmp_path):
    """Review round 1: verify --repro-only and finalize's quick evaluation stop at T_EVAL_END (T_NO_EVAL - 3 = 272),
    so finalize can still restore before T_NO_RESTORE; with under MIN_EVAL (2 s) left, finalize does not evaluate."""
    ws = _slow_case(scripts, tmp_path, 268, "r")
    r = run(scripts, "verify", ws, ["--repro-only"], t=268)
    assert r.first.startswith("REPRO:") and 268 + r.secs <= 275, (r.secs, r.out)
    ws2 = _slow_case(scripts, tmp_path, 268, "f")
    r = run(scripts, "finalize", ws2, t=268)
    assert r.first.startswith("READY:") and 268 + r.secs <= 275, (r.secs, r.out)
    ws3 = _slow_case(scripts, tmp_path, 271, "g")
    r = run(scripts, "finalize", ws3, t=271)
    assert r.first.startswith("READY:") and r.secs <= 2.0, (r.secs, r.out)
    st = json.loads((swe(ws3) / "state.json").read_text())
    assert not st.get("ckpts"), st.get("ckpts")                         # no evaluation, so nothing was scored


# ------------------------------------------------------------------------------------------------------ R66 SIBLINGS
TWIN_PY = '''\
from os import path as _p


def alpha(items):
    total = sum(len(part) for part in items.split(","))
    return total


def beta(items):
    total = sum(len(part) for part in items.split(","))
    return total


class A:
    def render_row(self, x):
        return x.strip()


class B:
    def render_row(self, x):
        return x.strip()
'''


def test_siblings(scripts, tmp_path):
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/twin.py": TWIN_PY,
                           "tests/test_twin.py": "def test_t():\n    total = sum(len(part) for part in items.split(','))\n"})
    edit_file(ws, "pkg/twin.py", 'def alpha(items):\n    total = sum(len(part) for part in items.split(","))\n'
                                 '    return total',
              'def alpha(items):\n    parts = items.split(",")\n    return sum(len(p) for p in parts)')
    edit_file(ws, "pkg/twin.py", "class A:\n    def render_row(self, x):\n        return x.strip()",
              "class A:\n    def render_row(self, x):\n        return x.strip(' ')")
    edit_file(ws, "pkg/twin.py", "from os import path as _p\n", "import os.path as _p\n")   # import lines never count
    r = verify(scripts, ws)
    sib = r.out[r.out.index("SIBLINGS"):].split("\n")[1:]
    sib = [ln for ln in sib if ln.startswith("  ")]
    assert any(re.match(r"  pkg/twin\.py:10  total = sum\(len\(part\) for part in items\.split", ln) for ln in sib), r.out
    assert not any("import" in ln for ln in sib), r.out
    assert any("B.render_row" in ln for ln in sib), r.out
    assert not any(ln.startswith("  tests/") for ln in sib), r.out
    assert not any(":2  " in ln for ln in sib), r.out                 # never a line inside the changed hunk
    # moved lines inside a changed hunk are not siblings; at most 6 lines
    many = TWIN_PY + "".join('\n\ndef twin_%d(items):\n    total = sum(len(part) for part in items.split(","))\n'
                             '    return total\n' % i for i in range(12))
    ws2 = mkrepo(tmp_path / "b", {"pkg/__init__.py": "", "pkg/twin.py": many})
    edit_file(ws2, "pkg/twin.py", 'def alpha(items):\n    total = sum(len(part) for part in items.split(","))\n'
                                  '    return total',
              'def alpha(items):\n    if items:\n        total = sum(len(part) for part in items.split(","))\n'
              '        return total\n    return 0')
    r = verify(scripts, ws2)
    sib = [ln for ln in r.out[r.out.index("SIBLINGS"):].split("\n")[1:] if ln.startswith("  pkg/")]
    assert 1 <= len(sib) <= 6, r.out
    assert not any(re.match(r"  pkg/twin\.py:[67]  ", ln) for ln in sib), r.out   # alpha's own new lines


# ----------------------------------------------------------------------------------------------------- R67 SPEC GAPS
GAPS_PY = '''\
class Console:
    def __init__(self):
        self.width = 80

    def print(self, text, end="\\n"):
        return text


class Pager:
    def print(self, text, end="\\n"):
        return text


class Buffer:
    def print(self, text, **kwargs):
        return text


def render(text):
    raise ValueError("unsupported separator value given")
'''


def test_spec_gaps(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/console.py": GAPS_PY})
    C, G, K = lib(ws)
    sigs = {1: "ImportError: cannot import name 'Theme' from 'pkg.console' (x.py)",
            2: "AttributeError: module 'pkg.console' has no attribute 'measure'",
            3: "AttributeError: 'Console' object has no attribute 'height'",
            4: "AttributeError: type object 'Pager' has no attribute 'lines'",
            5: "TypeError: Console.print() got an unexpected keyword argument 'sep'",
            6: "AttributeError: module 'json' has no attribute 'zz'"}
    orig = {i: {"status": "FAIL", "sig": s, "broken": None} for i, s in sigs.items()}
    new = G.new_from_sigs(orig)
    assert new == ["Theme@pkg.console", "measure@pkg.console", "Console.height", "Pager.lines", "print(sep=)",
                   "zz@json"]
    idx = G._load_index(5)
    gaps = G.spec_gaps(new, [], idx)
    assert len(gaps) <= 4
    assert "  new name Theme is not defined in the source yet" in gaps
    assert "  new name measure is not defined in the source yet" in gaps
    assert any(g.startswith("  height is missing in class Console") for g in gaps)
    assert any(g.startswith("  lines is missing in class Pager") for g in gaps)
    assert not any("zz" in g for g in gaps)                              # a dependency's name is not a gap
    gaps = G.spec_gaps(["print(sep=)", "Console.width"], [], idx)
    assert gaps == ["  new parameter sep= missing in pkg/console.py Console.print (L5)",
                    "  new parameter sep= missing in pkg/console.py Pager.print (L10)"], gaps  # Buffer has **kwargs
    gaps = G.spec_gaps([], ["unsupported separator value given: {sep!r}", "some other message text",
                            "unsupported separator value given"], idx)
    assert gaps == ['  message "some other message text" is not in the source yet'], gaps
    # headers flow through the CLI into the SPEC GAPS section
    edit_file(ws, "pkg/console.py", "return text\n\n\nclass Pager", "return text + ''\n\n\nclass Pager")
    repro_only(scripts, ws, "# NEW: Console.height\n# MESSAGE: \"brand new message text\"\n"
                            "from pkg.console import Console\n# CLAIM 1: h\nassert Console().height == 3\n")
    r = verify(scripts, ws)
    gap = r.out[r.out.index("SPEC GAPS:"):].split("\n")[1:3]
    assert gap[0].startswith("  height is missing in class Console"), r.out
    assert gap[1] == '  message "brand new message text" is not in the source yet', r.out


# ------------------------------------------------------------------------------------------------ R68 hangs bounded
def test_verify_hang_bounded(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    repro_only(scripts, ws, "from pkg.text import pad\n# CLAIM 1: endless\nwhile True:\n    pass\n", t=100)
    write(ws, "pkg/text.py", TEXT_PY + "\nwhile True:\n    pass\n")
    t0 = time.monotonic()
    r = verify(scripts, ws, t=250)                        # span = min(44.5, 262 - 250) = 12 s; import check 10 s
    secs = time.monotonic() - t0
    assert secs <= 12 + 2 + 1, (secs, r.out)             # deadline + 2 s (+1 s interpreter start on a busy host)
    assert r.first == "VERIFY: RED - import error" and "HANG" in r.line("IMPORT:"), r.out
    # past T_VERIFY_END the run is cut at PHASE_MIN (3 s): too short to call the import a hang, never RED for it
    write(ws, "pkg/text.py", TEXT_PY + "\nwhile True:\n    pass  # another diff: no memo hit\n")
    t0 = time.monotonic()
    r = verify(scripts, ws, t=286)
    assert time.monotonic() - t0 <= 3 + 2 + 1, r.out
    assert r.first.startswith("VERIFY:") and "HANG" not in (r.line("IMPORT:") or ""), r.out
    time.sleep(0.3)
    assert find_orphans({str(tmp_path), os.path.realpath(str(tmp_path))}) == []


# ------------------------------------------------------------------------------------------------ R69 output bounds
def test_verify_output_bounds(scripts, tmp_path):
    tests = "from pkg.text import center\n\n" + "".join(
        "\ndef test_many_%02d():\n    assert center('a', 3) == ' a ', 'x' * 20000\n" % i for i in range(50))
    ws = mkrepo(tmp_path, dict(BASIC, **{"tests/test_text.py": tests}))
    repro_only(scripts, ws, "from pkg.text import pad\n# CLAIM 1: " + "y" * 3000 + "\nassert pad('ab', 4) == 'ab  ', "
                            "'z' * 20000\n")
    edit_file(ws, "pkg/text.py", "return s.center(width)", "return s.center(width + 2)")
    r = verify(scripts, ws)
    assert len(r.out.rstrip("\n")) <= 2000, len(r.out)
    assert r.first.startswith("VERIFY: RED"), r.out
    assert r.line("NEXT:") is not None, r.out
    assert r.line("REPRO:") == "REPRO: 0/1 claims fixed", r.out
