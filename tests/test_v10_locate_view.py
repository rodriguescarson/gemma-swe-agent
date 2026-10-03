"""locate.py, grep.py, view.py and the _swe_index library (SPEC 4.3-4.6): R29-R38.

Every test copies the bundle scripts to a temp dir first (no __pycache__ can appear in the bundle) and runs the helpers
as subprocesses against throwaway git repos with the _swegemma_baseline tag, the way the model runs them through
run_command. Library-level checks import _swe_index from that temp copy.
"""
import json, os, pathlib, re, resource, shutil, statistics, subprocess, sys, time, uuid
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10") / "skills/swe-tools/scripts"
PY = sys.executable

try:  # R120: the orphan-process guard is autouse in every v10 module
    from v10_support.repo import no_orphans, list_processes  # noqa: F401
except ImportError:  # pragma: no cover - only while helpers-core's test support is not built yet
    def list_processes():
        out = []
        if os.path.isdir("/proc/self"):
            for d in os.listdir("/proc"):
                try:
                    with open("/proc/%s/cmdline" % d, "rb") as f:
                        out.append((int(d), f.read().replace(b"\0", b" ").decode("utf-8", "replace")))
                except (OSError, ValueError):
                    pass
            return out
        ps = subprocess.run(["ps", "-axww", "-o", "pid=", "-o", "command="], capture_output=True, text=True).stdout
        return [(int(l.split(None, 1)[0]), l.split(None, 1)[1]) for l in ps.splitlines() if len(l.split(None, 1)) == 2]

    @pytest.fixture(autouse=True)
    def no_orphans(tmp_path):
        yield
        end = time.time() + 1.0
        while True:
            left = [c for p, c in list_processes() if str(tmp_path) in c and p != os.getpid()]
            if not left or time.time() > end:
                break
            time.sleep(0.1)
        assert not left, left

pytestmark = pytest.mark.skipif(not (SRC / "_swe_common.py").exists(), reason="helpers-core (_swe_common.py) not built")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.compat import V102, later_stage  # noqa: E402  (G4_BUNDLE may be v10.2)

SEP_CHARS = ["\f", "\x0b", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    d = tmp_path_factory.mktemp("scripts")
    for p in SRC.glob("*.py"):
        shutil.copy2(p, d / p.name)
    return d


@pytest.fixture(scope="module")
def I(scripts):
    """_swe_index imported from the temp copy (never from the bundle)."""
    sys.path.insert(0, str(scripts))
    try:
        sys.modules.pop("_swe_index", None)
        import _swe_index as mod
    finally:
        sys.path.remove(str(scripts))
    return mod


def git(ws, *args, check=True):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ws, capture_output=True, check=check)


def mkrepo(tmp, files, name="ws", symlinks=()):
    """A git repo with every file committed and tagged _swegemma_baseline. files: {rel: str | bytes}."""
    ws = tmp / name
    ws.mkdir(parents=True)
    for rel, data in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    for link, target in symlinks:
        (ws / link).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, ws / link)
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "base")
    git(ws, "tag", "-f", "_swegemma_baseline")
    return ws


def env_for(ws, t=20, swe=None, pythonpath=True, extra=None):
    tmp = pathlib.Path(swe).parent if swe else ws.parent / ("sbx_" + ws.name)
    tmp.mkdir(exist_ok=True)
    later_stage(swe or tmp / "swe")    # v10.2: these contracts hold outside the locator budget (14 calls, t=90s)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SWE_", "PYTHON", "TEST_TMPDIR"))}
    e.update(SWE_WS=str(ws), SWE_DIR=str(swe or tmp / "swe"), TMPDIR=str(tmp), HOME=str(tmp), SWE_DUAL="0",
             PYTHONDONTWRITEBYTECODE="1", LANG="C.UTF-8")
    if pythonpath:
        e["PYTHONPATH"] = str(ws)
    if t is not None:
        e["SWE_FAKE_CLOCK"] = str(t)
    e.update(extra or {})
    return e


class R(object):
    def __init__(self, out, secs, cpu):
        self.out, self.secs, self.cpu = out, secs, cpu
        self.lines = out.split("\n")          # never splitlines(): \x1c, \x85, U+2028 are not line breaks here
        self.first = self.lines[0]


def run(scripts, name, args, ws, env=None, stdin=None, timeout=60, cwd=None):
    """Run a helper; stdin None means /dev/null. Exit code 0, no traceback, no HELPER ERROR. Records wall seconds
    and CPU seconds (user + sys of the helper and every child it waited for)."""
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    a = time.perf_counter()
    r = subprocess.run([PY, str(scripts / (name + ".py")), *args], cwd=str(cwd or ws), env=env or env_for(ws),
                       input=stdin.encode() if isinstance(stdin, str) else stdin,
                       stdin=subprocess.DEVNULL if stdin is None else None, capture_output=True, timeout=timeout)
    secs = time.perf_counter() - a
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0, out + r.stderr.decode()
    assert "Traceback" not in out and "HELPER ERROR" not in out, out + r.stderr.decode()
    return R(out, secs, cpu)


_CAL_SRC = "".join("def f_%d(a, b=1, *c, **d):\n    x = [i * a for i in range(b)]\n    return {k: v for k, v in d.items() "
                   "if k != 'z'}, x\n\nclass K%d:\n    y = 1\n    def m(self):\n        return self.y + %d\n\n" % (i, i, i)
                   for i in range(120))
CAL_REF_S = 0.020          # the calibration workload's best time on this Mac (M-series P-core, 2026-09-28)


def _calibration():
    import ast
    ts = []
    for _ in range(7):
        a = time.perf_counter()
        for _ in range(4):
            ast.parse(_CAL_SRC)
        ts.append(time.perf_counter() - a)
    return statistics.median(ts)


def contention():
    """How much slower than an idle Mac this box runs right now (1.0 when idle): the larger of the 1-minute load
    average per core and a calibration workload timed in this process against its idle reference (the second one
    also sees a VM's or container's CPU limits and a host that the guest load average cannot see)."""
    try:
        load = os.getloadavg()[0] / float(os.cpu_count() or 1)
    except OSError:
        load = 1.0
    return max(1.0, load, _calibration() / CAL_REF_S)


def assert_budget(rs, budget, what):
    """Timing budget on the helper's own CPU time (median over rs), scaled by the current contention so a saturated
    CI box does not turn a correct helper red; on an idle machine the factor is 1 and the spec budget applies as is.
    Wall time gets the same scaling with a further 2x for scheduling noise."""
    rs = rs if isinstance(rs, list) else [rs]
    k = contention()
    cpu = statistics.median(r.cpu for r in rs)
    wall = statistics.median(r.secs for r in rs)
    msg = "%s: cpu %.3f s, wall %.3f s, budget %.3f s x contention %.2f" % (what, cpu, wall, budget, k)
    assert cpu <= budget * k, msg
    assert wall <= budget * k * 2, msg


def ranked(out):
    return re.findall(r"^\s*\d+\.\s+(\S+)", out, re.M)


def state(env):
    with open(os.path.join(env["SWE_DIR"], "state.json")) as f:
        return json.load(f)


def synth_repo(root, n=3000):
    """n small modules in 30 packages (about 1.6 kB each), committed and tagged."""
    words = ["alpha", "beta", "gamma", "delta", "render", "parse", "table", "column", "width", "padding", "style",
             "segment", "console", "buffer", "stream", "token", "cache", "index", "query", "score"]
    root.mkdir(parents=True)
    for i in range(n):
        d = root / "lib" / ("pkg%02d" % (i % 30))
        if not d.exists():
            d.mkdir(parents=True)
            (d / "__init__.py").write_text("")
        w1, w2 = words[i % 20], words[(i * 7) % 20]
        body = ['"""Module %d: %s %s helpers."""' % (i, w1, w2), "import os", "", "CONST_%d = %d" % (i, i), ""]
        for c in range(2):
            body += ["class %s%s%d%d:" % (w1.title(), w2.title(), i, c), '    """A %s of %s."""' % (w1, w2),
                     "    def __init__(self, %s, %s=None):" % (w1, w2), "        self.%s = %s" % (w1, w1), ""]
            for m in range(3):
                body += ["    def get_%s_%s_%d(self, value):" % (w2, w1, m), "        total = 0",
                         "        for item in range(value):", "            total += len(str(item)) * %d" % (m + 1),
                         "        return total + self.%s" % w1, ""]
        for f in range(2):
            body += ["def compute_%s_%d_%d(%s, %s):" % (w1, i, f, w1, w2), "    if not %s:" % w1,
                     "        return %s" % w2, "    return [x for x in %s if x != %s]" % (w1, w2), "", ""]
        (d / ("mod_%04d.py" % i)).write_text("\n".join(body) + "\n")
    (root / "lib" / "pkg00" / "special.py").write_text(
        "class Table:\n    def _get_padding_width(self, column_index):\n        return column_index\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "base")
    git(root, "tag", "-f", "_swegemma_baseline")
    return root


# =============================================================================================================== R29
HOSTILE = {
    "pkg/__init__.py": "",
    "pkg/good.py": ("import functools\n\nCONST = 1\nA, (B, *C) = 1, (2, 3)\n\n"
                    "class Outer:\n    attr = 1\n\n    class Inner:\n        def deep(self):\n            return 1\n\n"
                    "    @functools.lru_cache()\n    def method(self, a, *rest, key=None, **kw):\n        return a\n\n"
                    "async def fetch_thing(x, /, y):\n    def nested():\n        return x\n    return nested\n\n"
                    "if CONST:\n    def conditional_def():\n        return 2\n"),
    "pkg/bad_syntax.py": "def broken(:\n    pass\n",
    "pkg/py2.py": 'print "hello"\n\ndef py2_func():\n    pass\n',
    "pkg/esc.py": "import re\nPAT = re.compile('\\d+')\n\ndef uses_escape():\n    return PAT\n",
    "pkg/bom.py": "\ufeffdef after_bom():\n    return 1\n",
    "pkg/\u00fcn\u00ef/m\u00f6d.py": "def unicode_path_func():\n    return 1\n",
    "site-packages/vendored.py": "def vendored_func():\n    pass\n",
    "vendor/lib.py": "def vendor_func():\n    pass\n",
    ".hidden/secret.py": "def hidden_func():\n    pass\n",
}


def hostile_repo(tmp):
    files = dict(HOSTILE)
    files["pkg/latin1.py"] = b"# comment caf\xe9\ndef latin_func():\n    return '\xe9'\n"
    files["pkg/huge.py"] = "x = 1\n" * 350000                      # about 2.1 MB: skipped
    return mkrepo(tmp, files, symlinks=[("pkg/loop.py", "loop.py"), ("pkg/selfdir", ".")])


def test_index_hostile_tree_and_cache(tmp_path, scripts, I):
    """R29: SyntaxError, py2 print, non-UTF-8, a 2 MB file, a symlink loop, site-packages and unicode paths; the cache
    re-parses only changed files; a forced deadline gives partial and valid output; output identical over 3 runs."""
    ws = hostile_repo(tmp_path)
    cache = str(tmp_path / "swe" / "index_test.marshal")
    os.makedirs(os.path.dirname(cache))
    idx = I.build(str(ws), deadline_s=30, cache_path=cache)
    files = set(idx.files)
    assert "pkg/good.py" in files and "pkg/\u00fcn\u00ef/m\u00f6d.py" in files and "pkg/latin1.py" in files
    assert not files & {"pkg/huge.py", "site-packages/vendored.py", "vendor/lib.py", ".hidden/secret.py", "pkg/loop.py"}
    assert idx.symbols("pkg/bad_syntax.py") == [] and idx.symbols("pkg/py2.py") == []
    names = {s[0]: s for s in idx.symbols("pkg/good.py")}
    assert set(names) >= {"Outer", "Outer.Inner", "Outer.Inner.deep", "Outer.method", "fetch_thing",
                          "fetch_thing.nested", "conditional_def"}
    assert names["fetch_thing"][1] == "async def" and names["Outer"][1] == "class"
    assert names["Outer.method"][4] == ("self", "a", "*rest", "key", "**kw")       # params
    assert names["fetch_thing"][4] == ("x", "y")
    assert names["Outer.method"][2] == 13 and names["Outer.method"][3] == 15      # start includes the decorator
    assert idx.module_assigns("pkg/good.py") >= {"CONST", "A", "B", "C"}
    assert [s[0] for s in idx.symbols("pkg/latin1.py")] == ["latin_func"]
    assert [s[0] for s in idx.symbols("pkg/bom.py")] == ["after_bom"]
    assert [s[0] for s in idx.symbols("pkg/esc.py")] == ["uses_escape"]
    assert idx.enclosing("pkg/good.py", 11)[0] == "Outer.Inner.deep"
    assert idx.enclosing("pkg/good.py", 7)[0] == "Outer" and idx.enclosing("pkg/good.py", 2) is None
    assert idx.span("pkg/good.py", "method") == (13, 15) and idx.span("pkg/good.py", "Outer.Inner") == (9, 11)
    assert [p for p, _ in idx.defs_named("deep")] == ["pkg/good.py"]
    assert idx.class_attrs("pkg/good.py", "Outer") >= {"attr", "Inner", "method"}
    assert not idx.partial and len(idx.parsed) == len(idx.files)
    res = idx.bm25(["unicode", "path", "func"])
    assert res and res[0][1] == "pkg/\u00fcn\u00ef/m\u00f6d.py" and res[0][2][0] == "unicode_path_func"
    # the cache: a second build parses nothing; touching one file re-parses exactly that file
    again = I.build(str(ws), deadline_s=30, cache_path=cache)
    assert again.parsed == [] and again.symbols("pkg/good.py") == idx.symbols("pkg/good.py")
    assert again.bm25(["unicode", "path", "func"]) == res
    time.sleep(0.01)
    (ws / "pkg/good.py").write_text(HOSTILE["pkg/good.py"] + "\ndef added_later():\n    pass\n")
    third = I.build(str(ws), deadline_s=30, cache_path=cache)
    assert third.parsed == ["pkg/good.py"]
    assert third.bm25(["added", "later"])[0][2][0] == "added_later"
    # forced deadline: nothing parsed, the files are still ranked by their path tokens
    part = I.build(str(ws), deadline_s=0, cache_path=str(tmp_path / "swe" / "index_other.marshal"))
    assert part.partial and part.parsed == [] and part.symbols("pkg/good.py") == []
    pr = part.bm25(["good"])
    assert pr and pr[0][1] == "pkg/good.py" and pr[0][2][1] == "module"
    # the CLI: identical output over 3 cold runs (fresh $SWE each time)
    outs = []
    for k in range(3):
        env = env_for(ws, swe=str(tmp_path / ("cold%d" % k) / "swe"))
        outs.append(run(scripts, "locate", ["unicode path func conditional"], ws, env).out)
    assert outs[0] == outs[1] == outs[2]
    assert outs[0].startswith("LOCATE:") and "m\u00f6d.py" in outs[0]
    # grep and view with a unicode path (core.quotepath=off, -z)
    g = run(scripts, "grep", ["unicode_path_func"], ws, env)
    assert "pkg/\u00fcn\u00ef/m\u00f6d.py" in g.out and "(in def unicode_path_func L1-2)" in g.out
    v = run(scripts, "view", ["pkg/\u00fcn\u00ef/m\u00f6d.py", "unicode_path_func"], ws, env)
    assert v.first == "pkg/\u00fcn\u00ef/m\u00f6d.py lines 1-2 of 2 (def unicode_path_func)"


def test_index_walk_fallback_and_partial_cli(tmp_path, scripts, I):
    """R29 (cont.): outside git the index walks the tree (symlink loops are not followed); the locate CLI under a
    1 s parse deadline (fake clock 295) prints a partial but valid ranking."""
    d = tmp_path / "plain"
    (d / "a").mkdir(parents=True)
    (d / "a" / "m.py").write_text("def walk_found():\n    pass\n")
    (d / "node_modules").mkdir()
    (d / "node_modules" / "x.py").write_text("def nm():\n    pass\n")
    os.symlink(str(d), str(d / "a" / "loop"))
    idx = I.build(str(d), deadline_s=10, cache_path=None, use_cache=False)
    assert idx.files == ["a/m.py"] and idx.symbols("a/m.py")[0][0] == "walk_found"
    # 60 files of about 200 kB each take 2 s or more to parse: a 1 s deadline leaves many of them unparsed, and each
    # file is small enough that the deadline overrun stays far below the helper's 4 s watchdog at t=295
    big = {"pkg/__init__.py": ""}
    for i in range(60):
        big["pkg/big_%02d.py" % i] = ("def target_%d():\n    pass\n" % i) + ("value_%d = [1, 2, 3]\n" % i) * 10000
    ws = mkrepo(tmp_path, big, name="bigws")
    r = run(scripts, "locate", ["target big"], ws, env_for(ws, t=295), timeout=60)
    assert r.first.startswith("LOCATE:") and "NOTE: partial index" in r.out, r.out
    assert len(ranked(r.out)) == 8 and len(r.out) <= 1800
    # later calls (more time) keep what was parsed and continue until the index is complete
    counts = [int(r.first.split()[1])]
    for _ in range(6):
        r2 = run(scripts, "locate", ["target big"], ws, env_for(ws, t=100), timeout=120)
        counts.append(int(r2.first.split()[1]))
        if "partial index" not in r2.out:
            break
        assert counts[-1] > counts[-2], counts
    assert "partial index" not in r2.out and r2.first == "LOCATE: 60 symbols in 61 files", (counts, r2.out)


# =============================================================================================================== R30
REPO_A = {
    "rich/__init__.py": "",
    "rich/text.py": ("class Text:\n    def divide(self, offsets):\n        return [offsets]\n\n"
                     "    def split(self, separator):\n        return separator\n\n"
                     "    def wrap(self, width):\n        return width\n\n"
                     "def divide_text(text, offsets):\n    return text\n"),
    "rich/segment.py": "class Segment:\n    def divide(self, cuts):\n        return cuts\n",
    "rich/console.py": "class Console:\n    def print(self, text):\n        return text\n",
    "tests/test_text.py": "from rich.text import Text\n\ndef test_divide():\n    assert Text().divide([1])\n",
    "tests/test_segment.py": "from rich.segment import Segment\n\ndef test_segment_divide():\n    Segment().divide(1)\n",
    "tests/conftest.py": "import pytest\n",
}


def test_locate_output_contract(tmp_path, scripts):
    """R30: LOCATE line, LAYOUT line, at most 6 files x 3 symbols with L ranges, RELATED TESTS, 1,800 chars; the
    positional, --query and --text forms agree; stdin is never read."""
    files = dict(REPO_A)
    for i in range(12):
        files["rich/extra_%02d.py" % i] = "".join("def divide_%d_%d(offsets):\n    return offsets\n" % (i, k)
                                                  for k in range(6))
    ws = mkrepo(tmp_path, files)
    env = env_for(ws)
    r = run(scripts, "locate", ["Text.divide offsets"], ws, env)
    assert re.match(r"^LOCATE: \d+ symbols in \d+ files$", r.first), r.first
    assert r.lines[1].startswith("LAYOUT: packages rich (workspace) | tests tests/ | layout flat"), r.lines[1]
    rk = ranked(r.out)
    assert rk[0] == "rich/text.py" and 1 <= len(rk) <= 8
    groups, cur = {}, None
    for ln in r.lines:
        m = re.match(r"^(\d+)\. (\S+)", ln)
        if m:
            cur = int(m.group(1))
            groups[cur] = []
        elif cur and re.match(r"^\s{5}(def|async def|class) \S+  L\d+-\d+$", ln):
            groups[cur].append(ln)
    assert all(len(v) <= 3 for v in groups.values()) and sum(1 for v in groups.values() if v) <= 6
    assert all(not groups[k] for k in groups if k > 6)
    assert "     def Text.divide  L2-3" in r.out
    rel = [l for l in r.lines if l.startswith("RELATED TESTS:")]
    assert rel and rel[0].split(":", 1)[1].split()[0] == "tests/test_text.py"
    assert "conftest" not in rel[0] and len(rel[0].split(":", 1)[1].split()) <= 3
    assert len(r.out) <= 1800 and r.lines[-2].startswith("[t=")
    # the three query forms give the same ranking; the skill form (--query) and --text too
    body = lambda o: [l for l in o.split("\n") if not l.startswith(("[t=", "NOTE: 3rd"))]
    q = run(scripts, "locate", ["--query", "Text.divide offsets"], ws, env)
    t = run(scripts, "locate", ["--text=Text.divide offsets"], ws, env)
    assert body(q.out) == body(r.out) == body(t.out)
    # never reads stdin: an open pipe that never sends anything does not block
    p = subprocess.Popen([PY, str(scripts / "locate.py"), "Text.divide"], cwd=str(ws), env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    a = time.perf_counter()
    try:
        while p.poll() is None and time.perf_counter() - a < 5:
            time.sleep(0.01)
        secs = time.perf_counter() - a
        out = p.stdout.read().decode()
    finally:
        if p.poll() is None:
            p.kill()
        p.stdin.close()
        p.wait()
    assert secs < 1.0 and out.startswith("LOCATE:"), (secs, out)


def test_locate_edge_cases(tmp_path, scripts):
    """R30 (cont.): usage without a query, a repo without tests or packages, no matches."""
    ws = mkrepo(tmp_path, {"tool.py": "def only_function():\n    return 1\n"})
    env = env_for(ws)
    u = run(scripts, "locate", [], ws, env)
    assert u.first == 'USAGE: python3 /tmp/swe/locate.py "QUERY"'
    r = run(scripts, "locate", ["only function"], ws, env)
    assert "LAYOUT: packages none | tests none | layout flat" in r.out and ranked(r.out) == ["tool.py"]
    assert "RELATED TESTS: none" in r.out
    n = run(scripts, "locate", ["zzzqqq xyzzy"], ws, env)
    assert ranked(n.out) == [] and "no matches" in n.out
    s = run(scripts, "locate", ["the and of to"], ws, env)       # stop words only
    assert ranked(s.out) == [] and s.first.startswith("LOCATE:")
    e = mkrepo(tmp_path, {"README.md": "hi\n"}, name="empty")
    r = run(scripts, "locate", ["anything"], e, env_for(e))
    assert r.first == "LOCATE: 0 symbols in 0 files" and "no matches" in r.out


# =============================================================================================================== R31
def test_locate_ranking_rules(tmp_path, scripts):
    """R31: tests x0.35, docs dirs x0.6 (docs_src below the package for identical identifiers), bigram x1.5,
    deterministic ties; PR boilerplate, URLs, #123, gh-12 and hex tokens produce no terms."""
    same = "def frobnicate_value(widget):\n    return widget.frobnicate_value\n"
    # paths of equal token length, so each multiplier alone decides against the path-order tie-break
    files = {
        "pkg/__init__.py": "",
        "pkg/frob.py": same, "docs/frob.py": same, "examples/frob.py": same, "benchmarks/frob.py": same,
        "my_pkg/frob.py": same, "docs_src/frob.py": same,
        "zzz/frob.py": same, "tests/frob.py": same,
        "aaa/pad.py": "class Table:\n    def get_width_padding(self, column):\n        return column\n",
        "zzz/pad.py": "class Table:\n    def _get_padding_width(self, column):\n        return column\n",
        "tie_a/twin.py": "def twinned_symbol():\n    pass\n",
        "tie_b/twin.py": "def twinned_symbol():\n    pass\n",
        "noise/gh.py": "def deadbeef1234567():\n    pass\n\ndef checklist_marker():\n    pass\n",
        "noise/link.py": "def wikipedia_entry():\n    pass\n",
    }
    ws = mkrepo(tmp_path, files)
    env = env_for(ws)
    rk = ranked(run(scripts, "locate", ["frobnicate_value"], ws, env).out)
    assert len(rk) == 8 and rk[0] == "pkg/frob.py", rk
    for d in ("docs/frob.py", "examples/frob.py", "benchmarks/frob.py"):          # x0.6 beats the path order
        assert rk.index("pkg/frob.py") < rk.index(d) < rk.index("tests/frob.py"), rk
    assert rk.index("my_pkg/frob.py") < rk.index("docs_src/frob.py"), rk            # docs_src below the package
    assert rk.index("zzz/frob.py") < rk.index("tests/frob.py") and rk[-1] == "tests/frob.py", rk   # tests x0.35
    # bigram: the same tokens, but only zzz/pad.py has "padding width" in order (the tie would put aaa first)
    assert ranked(run(scripts, "locate", ["padding width"], ws, env).out)[0] == "zzz/pad.py"
    assert ranked(run(scripts, "locate", ["width padding"], ws, env).out)[0] == "aaa/pad.py"
    # deterministic ties: path order, the same over repeated runs
    ties = [ranked(run(scripts, "locate", ["twinned_symbol"], ws, env).out)[:2] for _ in range(3)]
    assert ties == [["tie_a/twin.py", "tie_b/twin.py"]] * 3
    # boilerplate-only queries produce no terms at all
    junk = ("<!-- frobnicate_value twinned_symbol -->\n## Type of changes\n- [x] checklist_marker done\n"
            "- [ ] padding width\nSee https://en.wikipedia.org/wiki/wikipedia_entry and #123, gh-12, GH-7.\n"
            "At deadbeef1234567 and a1b2c3d4e5f60718293a4b5c6d7e8f9012345678.")
    j = run(scripts, "locate", [junk], ws, env)
    # v10.2 (SPEC_v10_2 5.6): a query with no searchable words is refused before the index is built
    assert ranked(j.out) == [] and ("no searchable words" if V102 else "no matches") in j.out, j.out


# =============================================================================================================== R32
@pytest.fixture(scope="module")
def big_repo(tmp_path_factory):
    return synth_repo(tmp_path_factory.mktemp("big") / "ws", 3000)


def test_locate_perf_cache_deadline(tmp_path, scripts, big_repo):
    """R32: first call 3 s or less on a synthetic 3k-file repo; cached 300 ms or less; a hanging import in the origin
    probe is bounded by 5 s."""
    ws = big_repo
    env = env_for(ws, swe=str(tmp_path / "perf" / "swe"))
    first = run(scripts, "locate", ["special padding width"], ws, env)
    assert_budget(first, 3.0, "locate first call, 3k files")
    assert first.first.startswith("LOCATE:") and "3031 files" in first.first
    assert ranked(first.out)[0] == "lib/pkg00/special.py", first.out
    cached = [run(scripts, "locate", ["special padding width"], ws, env) for _ in range(3)]
    assert_budget(cached, 0.30, "locate cached, 3k files")
    assert cached[0].out.split("\n")[:12] == first.out.split("\n")[:12]
    # origin probe hang: a sitecustomize.py on the probe's PYTHONPATH that never returns
    hw = mkrepo(tmp_path, {"hangpkg/__init__.py": "", "hangpkg/mod.py": "def hang_target():\n    pass\n",
                           "sitecustomize.py": "while True:\n    pass\n"}, name="hangws")
    henv = env_for(hw, pythonpath=False)         # the helper itself must not import the looping sitecustomize
    r = run(scripts, "locate", ["hang target"], hw, henv, timeout=30)
    assert r.secs <= 5.0 + 2.0, r.secs
    assert "hangpkg (origin unknown: import probe timed out)" in r.out, r.out
    assert ranked(r.out)[0] == "hangpkg/mod.py"
    again = run(scripts, "locate", ["hang target"], hw, henv, timeout=30)   # the probe result is cached
    assert again.secs < 2.0 and "import probe timed out" in again.out


# =============================================================================================================== R33
def test_locate_third_call_note(tmp_path, scripts):
    """R33: the third locate call in a task appends the NOTE (and later calls keep it); a new task starts over."""
    ws = mkrepo(tmp_path, REPO_A)
    env = env_for(ws)
    note = "NOTE: 3rd locate call; stop searching and use what you have."
    outs = [run(scripts, "locate", ["divide"], ws, env).out for _ in range(4)]
    assert [note in o for o in outs] == [False, False, True, True]
    assert state(env)["locate_calls"] == 4
    ev = [json.loads(l) for l in open(os.path.join(env["SWE_DIR"], "journal.jsonl"))]
    assert sum(1 for e in ev if e.get("h") == "locate") == 4 and "top rich/text.py" in ev[-1]["msg"]
    other = mkrepo(tmp_path, REPO_A, name="ws2")
    env2 = dict(env, SWE_WS=str(other))
    assert note not in run(scripts, "locate", ["divide"], other, env2, cwd=other).out


# =============================================================================================================== R34
def grep_repo(tmp):
    files = {"pkg/__init__.py": "", "tests/test_hits.py": "def test_x():\n    needle_word = 1\n",
             "pkg/sub/test_inner.py": "needle_word = 2\n", "pkg/testing/util.py": "needle_word = 3\n",
             "pkg/sub/deep/tests/helper.py": "needle_word = 4\n", "conftest.py": "needle_word = 5\n",
             "README.md": "needle_word in docs\n",
             "pkg/long.py": "def long_line():\n    return '%s'  # needle_word\n" % ("x" * 500)}
    for i in range(12):
        src = ["class Klass%d:" % i, "    def meth(self):"]
        src += ["        needle_word = %d  # line %d" % (k, k) for k in range(8)]
        src += ["", "def free_function():", "    return 'needle_word'", ""]
        files["pkg/mod_%02d.py" % i] = "\n".join(src) + "\n"
    return mkrepo(tmp, files)


def test_grep_contract(tmp_path, scripts):
    """R34: 40 hits or fewer, 5 per file, 160-char lines, tests excluded unless --tests, --path, enclosing def
    annotations, the count line, an invalid regex in one line, 1 s or less."""
    ws = grep_repo(tmp_path)
    env = env_for(ws)
    r = run(scripts, "grep", ["needle_word"], ws, env)
    m = re.match(r"^GREP: (\d+) hits in (\d+) files \(shown (\d+)\)$", r.first)
    assert m, r.first
    total, nfiles, shown = map(int, m.groups())
    assert total == 12 * 9 + 3 and nfiles == 15 and shown <= 40       # 12 x (8 + 1) + testing/util + long + README
    hits = [l for l in r.lines if re.match(r"^\s*\d+\| ", l)]
    assert len(hits) == shown and all(len(l) <= 7 + 160 for l in hits)
    per = {}
    cur = None
    for l in r.lines[1:]:
        if re.match(r"^[\w./-]+$", l):
            cur = l
        elif re.match(r"^\s*\d+\| ", l):
            per[cur] = per.get(cur, 0) + 1
    assert per and max(per.values()) <= 5
    assert "  (in def Klass0.meth L2-10)" in r.out
    fr = run(scripts, "grep", ["return 'needle_word'"], ws, env)
    assert fr.first == "GREP: 12 hits in 12 files (shown 12)" and "  (in def free_function L12-13)" in fr.out
    assert not any(k.startswith(("tests/", "pkg/sub/test_inner", "pkg/sub/deep/tests", "conftest")) for k in per)
    assert list(per)[0].startswith("pkg/") and len(r.out) <= 1800 and "more hits not shown" in r.out
    assert_budget(r, 1.0, "grep")
    # the long line is cut to 160 chars
    lg = run(scripts, "grep", ["needle_word", "--path", "pkg/long.py"], ws, env)
    line = [l for l in lg.lines if "|" in l and "return" in l][0]
    assert len(line.split("| ", 1)[1]) <= 160 and line.endswith(" ...")
    # --tests includes (and lists first) the test files; --path limits the search
    t = run(scripts, "grep", ["needle_word", "--tests", "--max", "80"], ws, env)
    assert "tests/test_hits.py" in t.out and "conftest.py" in t.out and t.lines[1].startswith(("conftest", "pkg/sub",
                                                                                             "tests/"))
    p = run(scripts, "grep", ["needle_word", "--path", "pkg/testing"], ws, env)
    assert p.first == "GREP: 1 hits in 1 files (shown 1)" and "pkg/testing/util.py" in p.out
    # --max is clamped to 1..80; python regex syntax works; an invalid regex is one line
    assert "(shown 1)" in run(scripts, "grep", ["needle_word", "--max", "0"], ws, env).first
    assert int(re.search(r"shown (\d+)", run(scripts, "grep", ["needle_word", "--max=500"], ws,
                                                    env).first).group(1)) <= 80
    rx = run(scripts, "grep", [r"needle_\w+ = \d+  # line [7](?:\b)"], ws, env)
    assert rx.first.startswith("GREP: 12 hits in 12 files")
    bad = run(scripts, "grep", ["foo("], ws, env)
    assert bad.first.startswith("GREP: invalid regex:") and len(bad.lines) == 3 and bad.lines[1].startswith("[t=")
    z = run(scripts, "grep", ["zzz_no_such"], ws, env)
    assert z.first == "GREP: 0 hits in 0 files (shown 0)" and "--tests" in z.out
    miss = run(scripts, "grep", ["x", "--path", "nope/dir"], ws, env)
    assert miss.first.startswith("GREP: 0 hits") and "does not exist" in miss.out
    # the skill form (--regex) and the ERE fallback (git without PCRE) give the same hits
    sk = run(scripts, "grep", ["--regex", r"needle_\w+ = \d+  # line 7"], ws, env)
    sp = pathlib.Path(env["SWE_DIR"], "state.json")
    st = json.loads(sp.read_text()) if sp.exists() else {}
    st["grep_pcre"] = False
    sp.write_text(json.dumps(st))
    ere = run(scripts, "grep", [r"needle_\w+ = \d+  # line 7"], ws, env)
    assert sk.first == ere.first == "GREP: 12 hits in 12 files (shown 12)", (sk.first, ere.first)
    ere2 = run(scripts, "grep", [r"(?:free)_\w+\(\)"], ws, env)
    assert ere2.first.startswith("GREP: 12 hits in 12 files"), ere2.out
    assert run(scripts, "grep", [], ws, env).first.startswith("USAGE: python3 /tmp/swe/grep.py")


def test_grep_outside_workspace_path(tmp_path, scripts):
    """--path outside the repository (an installed dependency dir) searches it with git grep --no-index."""
    ws = mkrepo(tmp_path, {"a.py": "x = 1\n"})
    dep = tmp_path / "site" / "deplib"
    dep.mkdir(parents=True)
    (dep / "core.py").write_text("class Dep:\n    def resolve_thing(self):\n        return 'resolve_thing'\n")
    r = run(scripts, "grep", ["resolve_thing", "--path", str(dep)], ws, env_for(ws))
    assert r.first == "GREP: 2 hits in 1 files (shown 2)" and "(in def Dep.resolve_thing L2-3)" in r.out
    # regression: a workspace without git was reported as "invalid regex"; it is searched with --no-index and shown
    # with relative paths, tests still excluded unless --tests
    plain = tmp_path / "plain"
    (plain / "pkg").mkdir(parents=True)
    (plain / "tests").mkdir()
    (plain / "pkg" / "a.py").write_text('def plain_fn():\n    return "marker_x"\n')
    (plain / "tests" / "test_a.py").write_text("marker_x = 1\n")
    g = run(scripts, "grep", ["marker_x"], plain, env_for(plain))
    assert g.first == "GREP: 1 hits in 1 files (shown 1)" and g.lines[1] == "pkg/a.py", g.out
    assert "(in def plain_fn L1-2)" in g.out
    assert run(scripts, "grep", ["marker_x", "--tests"], plain, env_for(plain)).first.startswith("GREP: 2 hits")


# =============================================================================================================== R35
SEP_SRC = ("def before():\n    return 1\n"
           "\f# form feed line\n"
           "x0 = 'a\x0bb'\n"
           "x1 = 'a\x1cb'  # \x1d and \x1e too\n"
           "x2 = 'a\x85b'\n"
           "x3 = 'a\u2028b\u2029c'\n"
           "class Holder:\n"
           "    async def fetch(self):\n"
           "        return 2\n"
           "\n"
           "    class Inner:\n"
           "        def deep(self):\n"
           "            return 3\n"
           "def after():\n    return 4\n")


def test_view_modes_and_numbering(tmp_path, scripts):
    """R35: range, symbol (func, async def, Class, Class.method, nested) and outline modes; the '%5d| ' format;
    numbering equals git blame's on a file with separator chars; views recorded."""
    long_src = "".join("def fn_%03d(a):\n    return a + %d\n\n" % (i, i) for i in range(60))
    ws = mkrepo(tmp_path, {"pkg/sep.py": SEP_SRC, "pkg/long.py": long_src, "pkg/crlf.py": b"a = 1\r\nb = 2\r\n"})
    env = env_for(ws)
    data = (ws / "pkg/sep.py").read_bytes()
    truth = data.split(b"\n")[:-1]
    r = run(scripts, "view", ["pkg/sep.py", "1", str(len(truth))], ws, env)
    assert r.first == "pkg/sep.py lines 1-%d of %d" % (len(truth), len(truth))
    shown = [l for l in r.lines[1:] if re.match(r"^\s*\d+\| ", l)]
    assert len(shown) == len(truth)
    blame = git(ws, "blame", "--line-porcelain", "pkg/sep.py").stdout.split(b"\n")
    bl, final = {}, None
    for ln in blame:
        if ln.startswith(b"\t"):
            bl[final] = ln[1:]
        elif re.match(rb"^[0-9a-f]{40} \d+ \d+", ln):
            final = int(ln.split()[2])
    assert sorted(bl) == list(range(1, len(truth) + 1))
    for k, ln in enumerate(shown, 1):
        assert ln == "%5d| %s" % (k, truth[k - 1].decode()), (k, ln)
        assert bl[k] == truth[k - 1]
    for sep in SEP_CHARS:
        assert sep in r.out
    # symbol modes
    assert len(truth) == 16
    s = run(scripts, "view", ["pkg/sep.py", "Holder.fetch"], ws, env)
    assert s.first == "pkg/sep.py lines 9-10 of 16 (async def Holder.fetch)" and "    9|     async def fetch" in s.out
    assert run(scripts, "view", ["pkg/sep.py", "fetch"], ws, env).first == s.first
    assert run(scripts, "view", ["pkg/sep.py", "Holder.Inner.deep"], ws, env).first.endswith("(def Holder.Inner.deep)")
    assert run(scripts, "view", ["pkg/sep.py", "Inner"], ws, env).first == "pkg/sep.py lines 12-14 of 16 (class Holder.Inner)"
    c = run(scripts, "view", ["pkg/sep.py", "Holder"], ws, env)
    assert c.first == "pkg/sep.py lines 8-14 of 16 (class Holder)"
    f = run(scripts, "view", ["pkg/sep.py", "def after()"], ws, env)
    assert f.first == "pkg/sep.py lines 15-16 of 16 (def after)"
    miss = run(scripts, "view", ["pkg/sep.py", "Holdr"], ws, env)
    assert miss.first.startswith("VIEW: no def or class named Holdr") and "Holder" in miss.first
    # skill form, FILE:A-B form, single START
    sk = run(scripts, "view", ["--file", "pkg/sep.py", "--start", "9", "--end", "10"], ws, env)
    assert sk.first == "pkg/sep.py lines 9-10 of 16"
    assert run(scripts, "view", ["pkg/sep.py:9-10"], ws, env).first == sk.first
    assert run(scripts, "view", ["--file", "pkg/sep.py", "--name", "Holder.fetch"], ws, env).first == s.first
    assert run(scripts, "view", ["pkg/long.py", "170"], ws, env).first == "pkg/long.py lines 170-180 of 180"
    # outline (a .py file over 100 lines with only FILE given); a short file is shown whole
    o = run(scripts, "view", ["pkg/long.py"], ws, env)
    assert o.first == "pkg/long.py: 180 lines, 60 defs/classes (outline)"
    assert "  def fn_000  L1-2" in o.out and "  def fn_059  L178-179" in o.out
    assert run(scripts, "view", ["pkg/sep.py"], ws, env).first == "pkg/sep.py lines 1-16 of 16"
    # CRLF: shown without the \r, numbering unchanged
    cr = run(scripts, "view", ["pkg/crlf.py", "1", "2"], ws, env)
    assert "    1| a = 1\n    2| b = 2\n" in cr.out and "\r" not in cr.out
    # views recorded for edit.py's stale guard
    v = state(env)["views"]
    assert [9, 10] in [x[:2] for x in v["pkg/sep.py"]] and [170, 180] in [x[:2] for x in v["pkg/long.py"]]
    assert all(isinstance(x[2], (int, float)) for x in v["pkg/sep.py"])


# =============================================================================================================== R36
def test_view_bounds(tmp_path, scripts):
    """R36: 100 lines and 4,000 chars or fewer, the clamp message with the next command, the non-UTF-8 note, CRLF
    display, a missing file in one line, 200 ms or less."""
    ws = mkrepo(tmp_path, {"short.txt": "".join("line %d\n" % i for i in range(1, 301)),
                           "wide.txt": "".join(("w%03d " % i) + "y" * 190 + "\n" for i in range(1, 201)),
                           "huge_line.txt": "z" * 5000 + "\n",
                           "latin.py": b"s = 'caf\xe9'\nt = 'ok'\n",
                           "win.txt": b"one\r\ntwo\r\n",
                           "pkg/mod.py": "x = 1\n", "empty.py": "", "nonl.py": "a = 1\nb = 2"})
    env = env_for(ws)
    r = run(scripts, "view", ["short.txt", "1", "300"], ws, env)
    shown = [l for l in r.lines if re.match(r"^\s*\d+\| ", l)]
    assert len(shown) == 100 and r.first == "short.txt lines 1-100 of 300"
    assert "range clamped; next: python3 /tmp/swe/view.py short.txt 101 200" in r.out
    w = run(scripts, "view", ["wide.txt", "1", "100"], ws, env)
    ws_lines = [l for l in w.lines if re.match(r"^\s*\d+\| ", l)]
    last = int(ws_lines[-1].split("|")[0])
    assert len(w.out) <= 4000 and last < 100
    assert "range clamped; next: python3 /tmp/swe/view.py wide.txt %d %d" % (last + 1, last + 100) in w.out
    h = run(scripts, "view", ["huge_line.txt"], ws, env)
    assert len(h.out) <= 4000 and " ... " in h.out
    lat = run(scripts, "view", ["latin.py", "1", "2"], ws, env)
    assert "\ufffd" in lat.out and "[non-UTF-8 bytes shown as U+FFFD]" in lat.out
    win = run(scripts, "view", ["win.txt", "1", "2"], ws, env)
    assert "\r" not in win.out and "    2| two" in win.out
    miss = run(scripts, "view", ["pkg/mdo.py"], ws, env)
    assert len(miss.lines) == 3 and miss.first.startswith("VIEW: no such file: pkg/mdo.py")
    assert "pkg/mod.py" in miss.first
    assert run(scripts, "view", ["pkg"], ws, env).first.startswith("VIEW: pkg is a directory: mod.py")
    assert run(scripts, "view", ["empty.py"], ws, env).first == "empty.py is empty (0 lines)"
    nl = run(scripts, "view", ["nonl.py"], ws, env)             # no final newline: still 2 lines, numbered 1-2
    assert nl.first == "nonl.py lines 1-2 of 2" and "    2| b = 2\n" in nl.out
    beyond = run(scripts, "view", ["short.txt", "400", "420"], ws, env)
    assert beyond.first.startswith("VIEW: short.txt has 300 lines; asked for 400-420")
    assert run(scripts, "view", [], ws, env).first.startswith("USAGE: python3 /tmp/swe/view.py")
    rs = [run(scripts, "view", ["short.txt", "120", "180"], ws, env) for _ in range(3)]
    rs += [run(scripts, "view", ["latin.py", "s"], ws, env)]
    assert_budget(rs, 0.20, "view")


# =============================================================================================================== R37
def test_view_obj_dependency_and_hang(tmp_path, scripts):
    """R37: --obj json.JSONEncoder.default shows origin, signature and numbered source; a repo object shows
    [workspace]; a module that loops at import gives HANG importing within the deadline + 2 s, no survivors."""
    tag = "hangmod_%s" % uuid.uuid4().hex[:8]
    ws = mkrepo(tmp_path, {"mypkg/__init__.py": "", "mypkg/core.py": (
        "import functools\n\nclass Base:\n    def shared(self, a, b=2):\n        return a\n\n"
        "class Child(Base):\n    @property\n    def size(self):\n        return 3\n\n"
        "    @functools.lru_cache()\n    def cached(self, x):\n        return x\n"),
        "mypkg/big.py": "LIMIT = 42\n\nclass BigThing:\n" + "".join(
            "    def method_%02d(self):\n        return %d\n\n" % (i, i) for i in range(40)),
        "%s/__init__.py" % tag: "import time\nwhile True:\n    time.sleep(0.05)\n"})
    env = env_for(ws)
    r = run(scripts, "view", ["--obj", "json.JSONEncoder.default"], ws, env)
    assert r.first == "OBJ json.JSONEncoder.default: function"
    assert re.search(r"^origin: \S+json/encoder\.py \[installed dependency: read-only\]$", r.out, re.M), r.out
    assert "signature: default(self, o)" in r.out and "defined in: json.encoder.JSONEncoder" in r.out
    assert re.search(r"^\s*\d+\|     def default\(self, o\):", r.out, re.M) and len(r.out) <= 4000
    w = run(scripts, "view", ["--obj", "mypkg.core.Child.shared"], ws, env)
    assert "origin: mypkg/core.py [workspace]" in w.out and "defined in: mypkg.core.Base" in w.out
    assert "    4|     def shared(self, a, b=2):" in w.out
    assert [4, 5] in [v[:2] for v in state(env)["views"]["mypkg/core.py"]]
    p = run(scripts, "view", ["--obj", "mypkg.core.Child.size"], ws, env)
    assert p.first.endswith(": property") and "    9|     def size(self):" in p.out
    c = run(scripts, "view", ["--obj", "mypkg.core.Child.cached"], ws, env)
    assert "   13|     def cached(self, x):" in c.out
    m = run(scripts, "view", ["--obj", "mypkg.core"], ws, env)
    assert m.first == "OBJ mypkg.core: module" and "  class Child  L7-14" in m.out
    big = run(scripts, "view", ["--obj", "mypkg.big.BigThing"], ws, env)
    assert "(class BigThing, 120 lines; members below)" in big.out and "members of BigThing (40):" in big.out
    assert "  def BigThing.method_39  L121-122" in big.out and len(big.out) <= 4000
    val = run(scripts, "view", ["--obj", "mypkg.big.LIMIT"], ws, env)
    assert val.first == "OBJ mypkg.big.LIMIT: int" and "value: 42" in val.out
    b = run(scripts, "view", ["--obj", "len"], ws, env)
    assert "no Python source" in b.out
    n = run(scripts, "view", ["--obj", "no_such_mod_xyz.Thing"], ws, env)
    assert n.first.startswith("VIEW: cannot load no_such_mod_xyz.Thing: ModuleNotFoundError")
    assert run(scripts, "view", ["--obj", "not a name!"], ws, env).first.startswith("VIEW: --obj needs a dotted name")
    # hang: fake clock 294 -> the --obj budget is real_budget(15) = 2 s (the helper watchdog stays at 4 s)
    h = run(scripts, "view", ["--obj", tag + ".thing"], ws, env_for(ws, t=294), timeout=30)
    assert h.first.startswith("HANG importing %s" % tag) and h.secs <= 2 + 2, (h.secs, h.out)
    time.sleep(0.5)
    assert not [c for _p, c in list_processes() if tag in c and "pytest" not in c]
    src = (SRC / "_swe_common.py").read_text()
    assert re.search(r"\bVIEW_OBJ = 15\b", src) and re.search(r"\bORIGIN_PROBE = 5\b", src)


# =============================================================================================================== R38
def test_import_origin_warning(tmp_path, scripts):
    """R38: an src layout with an installed same-named copy on PYTHONPATH makes locate print OUTSIDE WORKSPACE (and
    verify report AMBER with that reason); the flat layout prints (workspace) and caches origin for grader_env."""
    ws = mkrepo(tmp_path, {"src/shadowpkg/__init__.py": "", "src/shadowpkg/core.py": "def shadow_fn():\n    return 1\n",
                           "tests/test_core.py": "from shadowpkg.core import shadow_fn\n"})
    site = tmp_path / "site"
    (site / "shadowpkg").mkdir(parents=True)
    (site / "shadowpkg" / "__init__.py").write_text("")
    (site / "shadowpkg" / "core.py").write_text("def shadow_fn():\n    return 0\n")
    env = env_for(ws, extra={"PYTHONPATH": os.pathsep.join([str(ws), str(site)])})
    r = run(scripts, "locate", ["shadow_fn"], ws, env)
    lay = r.lines[1]
    assert lay.startswith("LAYOUT: packages shadowpkg (OUTSIDE WORKSPACE: ") and lay.endswith("| layout src"), lay
    assert str((site / "shadowpkg").resolve()) in lay and "tests import that copy, not your edit" in lay
    assert state(env)["origin"] == {"shadowpkg": None}
    # an editable-style path to ws/src: inside the workspace, origin dir "src" cached for grader_env
    env2 = env_for(ws, swe=str(tmp_path / "s2" / "swe"), extra={"PYTHONPATH": str(ws / "src")})
    r2 = run(scripts, "locate", ["shadow_fn"], ws, env2)
    assert r2.lines[1].startswith("LAYOUT: packages shadowpkg (workspace) | tests tests/ | layout src"), r2.lines[1]
    assert state(env2)["origin"] == {"shadowpkg": "src"}
    # not importable at all (src layout, PYTHONPATH = workspace only)
    env3 = env_for(ws, swe=str(tmp_path / "s3" / "swe"))
    assert "shadowpkg (NOT IMPORTABLE" in run(scripts, "locate", ["shadow_fn"], ws, env3).lines[1]
    flat = mkrepo(tmp_path, {"flatpkg/__init__.py": "", "flatpkg/m.py": "def flat_fn():\n    pass\n"}, name="flat")
    fenv = env_for(flat)
    f = run(scripts, "locate", ["flat_fn"], flat, fenv)
    assert f.lines[1] == "LAYOUT: packages flatpkg (workspace) | tests none | layout flat", f.lines[1]
    assert state(fenv)["origin"] == {"flatpkg": ""}
    if not (SRC / "verify.py").exists():
        pytest.skip("verify.py not built yet (the verify half of R38)")
    (ws / "src/shadowpkg/core.py").write_text("def shadow_fn():\n    return 2\n")
    v = run(scripts, "verify", [], ws, env, timeout=90)
    assert v.first.startswith("VERIFY: AMBER"), v.out
    assert "OUTSIDE WORKSPACE" in v.out, v.out


# ================================================================================================ bundle-level checks
def test_scripts_contract_static():
    """USAGE/FLAGS exported, the verbatim preamble first, no /tmp literal used as a path, stdlib only (the core
    module's R01-R04 also cover these; here for this component's four files)."""
    import ast
    pre = (SRC / "edit.py").read_text().split("import _swe_common as C\n", 1)[0] if (SRC / "edit.py").exists() else None
    for name in ("locate", "grep", "view"):
        src = (SRC / (name + ".py")).read_text()
        tree = ast.parse(src, feature_version=(3, 8))
        assert src.startswith("import os, sys\nsys.dont_write_bytecode = True\n")
        if pre:
            assert src.split("import _swe_common as C\n", 1)[0] == pre
        consts = {n.targets[0].id: n.value for n in tree.body if isinstance(n, ast.Assign)
                  and isinstance(n.targets[0], ast.Name)}
        assert isinstance(ast.literal_eval(consts["USAGE"]), str) and isinstance(ast.literal_eval(consts["FLAGS"]), dict)
    usage = {n: re.search(r'^USAGE = (.*)$', (SRC / (n + ".py")).read_text(), re.M).group(1) for n in ("locate", "grep", "view")}
    assert usage["locate"] == "'python3 /tmp/swe/locate.py \"QUERY\"'"
    assert usage["grep"] == "'python3 /tmp/swe/grep.py \"REGEX\" [PATH ...] [--tests] [--max N]'"
    assert usage["view"] == '"python3 /tmp/swe/view.py FILE [START END | NAME] | --obj DOTTED.NAME"'
    for name in ("locate", "grep", "view", "_swe_index"):
        tree = ast.parse((SRC / (name + ".py")).read_text(), feature_version=(3, 8))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                assert n.value not in ("/tmp", "/workspace") and not n.value.startswith(("/tmp/", "/workspace/")), n.value
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                for m in mods:
                    top = m.split(".")[0]
                    assert top in sys.stdlib_module_names or top.startswith("_swe_"), (name, m)
