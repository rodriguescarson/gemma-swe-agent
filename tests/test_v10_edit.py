"""edit.py, the only edit channel (SPEC 4.7): R39-R51.

Every test copies the bundle scripts to a temp dir first (no __pycache__ can appear in the bundle) and runs edit.py as a
subprocess against a throwaway git repo with the _swegemma_baseline tag, exactly as the model would through run_command.
"""
import hashlib, json, os, pathlib, re, shutil, statistics, subprocess, sys, time
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "submissions/v10/skills/swe-tools/scripts"
PY = sys.executable

from v10_support.repo import no_orphans  # noqa: F401,E402  (R120: the orphan-process guard, autouse)

SEP_CHARS = ["\f", "\x0b", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    d = tmp_path_factory.mktemp("scripts")
    for p in SRC.glob("*.py"):
        shutil.copy2(p, d / p.name)
    return d


def git(ws, *args, check=True):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ws, capture_output=True, check=check)


def mkrepo(tmp, files):
    """A git repo with every file committed and tagged _swegemma_baseline. files: {rel: str | bytes}."""
    ws = tmp / "ws"
    ws.mkdir(parents=True)
    for rel, data in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    git(ws, "init", "-q")
    git(ws, "add", "-A")
    git(ws, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "base")
    git(ws, "tag", "-f", "_swegemma_baseline")
    return ws


def env_for(ws, t=None):
    tmp = ws.parent / "sbx_tmp"
    tmp.mkdir(exist_ok=True)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SWE_", "PYTHON", "TEST_TMPDIR"))}
    e.update(SWE_WS=str(ws), SWE_DIR=str(tmp / "swe"), TMPDIR=str(tmp), HOME=str(tmp), SWE_DUAL="0",
             PYTHONDONTWRITEBYTECODE="1", LANG="C.UTF-8")
    if t is not None:
        e["SWE_FAKE_CLOCK"] = str(t)
    return e


def edit(scripts, ws, args, stdin=None, t=None, cwd=None):
    """Run edit.py; stdin None means /dev/null (the Docker case). Returns stdout (str)."""
    r = subprocess.run([PY, str(scripts / "edit.py"), *args], cwd=str(cwd or ws), env=env_for(ws, t),
                       input=stdin.encode("utf-8", "surrogateescape") if isinstance(stdin, str) else stdin,
                       stdin=subprocess.DEVNULL if stdin is None else None, capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0, out + r.stderr.decode()
    assert "Traceback" not in out and "HELPER ERROR" not in out, out + r.stderr.decode()
    return out


def sr(search, replace):
    return "<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n" % (search, replace)


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def c_call(scripts, ws, code, t=None):
    """Run a snippet with the helpers' _swe_common imported as C (the real state API)."""
    prog = "import sys; sys.path.insert(0, %r); import _swe_common as C\n%s" % (str(scripts), code)
    r = subprocess.run([PY, "-c", prog], cwd=str(ws), env=env_for(ws, t), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def record_view(scripts, ws, rel, a, b, t):
    c_call(scripts, ws, "def f(s):\n    s.setdefault('views', {}).setdefault(%r, []).append([%d, %d, %r])\n    return s\n"
                        "C.state_update(f)" % (rel, a, b, float(t)), t=t)


MOD = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n\n\nclass K:\n    def m(self):\n        return 1\n"


@pytest.fixture
def ws(tmp_path):
    return mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": MOD, "tests/test_m.py": "def test_a():\n    pass\n"})


# ------------------------------------------------------------------------------------------------------------ R39
def test_search_replace_basic_and_atomic(scripts, ws):
    f = ws / "pkg/m.py"
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return b + a"))
    assert out.splitlines()[0].startswith("OK (exact): pkg/m.py lines 2-2 replaced (1 old, 1 new)"), out
    assert f.read_text() == MOD.replace("return a + b", "return b + a")
    assert "    2|     return b + a" in out and "NEXT: python3 /tmp/swe/verify.py" in out
    # two blocks, both applied in order, reported once
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return b + a", "    return a + b") + sr("        return 1",
                                                                                          "        return 2"))
    assert out.startswith("OK (exact): pkg/m.py 2 blocks") and f.read_text() == MOD.replace("return 1", "return 2")
    # all-or-nothing: the first block matches, the second does not -> byte-identical file
    before = sha(f)
    out = edit(scripts, ws, ["pkg/m.py"], sr("def add(a, b):", "def add(a, b, c=0):") + sr("    return zzz", "    x"))
    assert out.startswith("NO MATCH (block 2 of 2; no block was applied): pkg/m.py unchanged"), out
    assert sha(f) == before


# ------------------------------------------------------------------------------------------------------------ R40
TIER_CASES = [
    # id, file content, SEARCH, REPLACE, expected tier, expected content
    ("exact", MOD, "def sub(a, b):\n    return a - b", "def sub(a, b):\n    return b - a", "exact",
     MOD.replace("return a - b", "return b - a")),
    ("exact-lost-first-indent", MOD, "return a - b", "return a - b - 0", "exact",
     MOD.replace("return a - b", "return a - b - 0")),
    ("exact-mid-line-fragment", "x = compute(a, b) + 1\n", "compute(a, b)", "compute(a, b, c)", "exact",
     "x = compute(a, b, c) + 1\n"),
    ("rstrip-trailing-space", "def f():\n    return 1   \n", "    return 1", "    return 2", "rstrip",
     "def f():\n    return 2\n"),
    ("rstrip-crlf", "def f():\r\n    x = 1\r\n    return x\r\n", "    x = 1\n    return x", "    x = 2\n    return x",
     "rstrip", "def f():\r\n    x = 2\r\n    return x\r\n"),
    ("unescape-quotes", 'def f():\n    return "a"\n', '    return \\"a\\"', '    return \\"b\\"', "unescape",
     'def f():\n    return "b"\n'),
    ("unescape-newline", "def f():\n    x = 1\n    return x\n", "    x = 1\\n    return x", "    x = 5\\n    return x",
     "unescape", "def f():\n    x = 5\n    return x\n"),
    ("prefix-strip-search", MOD, "    5| def sub(a, b):\n    6|     return a - b", "def sub(a, b):\n    return -b + a",
     "exact", MOD.replace("return a - b", "return -b + a")),
    ("prefix-strip-both", MOD, "   10|     def m(self):\n   11|         return 1",
     "   10|     def m(self):\n   11|         return 11", "exact", MOD.replace("return 1\n", "return 11\n")),
    ("indent-plus", MOD, "def m(self):\n    return 1", "def m(self):\n    return 3", "indent",
     MOD.replace("        return 1\n", "        return 3\n")),
    ("indent-dedent", MOD, "        def sub(a, b):\n            return a - b",
     "        def sub(a, b):\n            return a - b - 1", "indent", MOD.replace("return a - b", "return a - b - 1")),
    ("unescape-indent", 'class C:\n    def f(self):\n        return "q"\n', 'def f(self):\n    return \\"q\\"',
     'def f(self):\n    return \\"r\\"', "unescape+indent", 'class C:\n    def f(self):\n        return "r"\n'),
]


@pytest.mark.parametrize("case", TIER_CASES, ids=[c[0] for c in TIER_CASES])
def test_match_tiers(scripts, tmp_path, case):
    _, content, search, replace, tier, want = case
    ws = mkrepo(tmp_path, {"pkg/f.py": content})
    out = edit(scripts, ws, ["pkg/f.py"], sr(search, replace))
    assert out.startswith("OK (%s): pkg/f.py" % tier), out
    assert (ws / "pkg/f.py").read_bytes() == want.encode(), (ws / "pkg/f.py").read_bytes()


def test_blank_edge_lines_in_search_are_trimmed(scripts, ws):
    out = edit(scripts, ws, ["pkg/m.py"], sr("\n    return a + b\n", "\n    return a + b + 0\n"))
    assert out.startswith("OK ("), out
    assert (ws / "pkg/m.py").read_text() == MOD.replace("return a + b", "return a + b + 0")


# ------------------------------------------------------------------------------------------------------------ R41
def test_nomatch_and_ambiguous(scripts, ws):
    f = ws / "pkg/m.py"
    before = sha(f)
    out = edit(scripts, ws, ["pkg/m.py"], sr("def sub(a, c):\n    return a - c", "def sub(a, c):\n    return c"))
    first = out.splitlines()[0]
    assert first.startswith("NO MATCH: pkg/m.py unchanged. Closest lines (similarity 0.") and first.endswith("are 5-6:")
    assert "    5| def sub(a, b):" in out and "    6|     return a - b" in out
    assert "use: python3 /tmp/swe/edit.py pkg/m.py --lines 5-6 <<'EOF' ... EOF" in out
    assert "first difference: your line 1: def sub(a, c):" in out
    assert sha(f) == before
    # AMBIGUOUS lists every start line
    ws2 = mkrepo(ws.parent / "amb", {"a.py": "x = 1\ny = 2\nx = 1\ny = 2\nz = 0\nx = 1\ny = 2\n"})
    before = sha(ws2 / "a.py")
    out = edit(scripts, ws2, ["a.py"], sr("x = 1\ny = 2", "x = 3\ny = 2"))
    assert out.startswith("AMBIGUOUS: SEARCH matches at lines 1, 3, 6; add context lines or use --lines"), out
    assert sha(ws2 / "a.py") == before
    # nothing similar at all
    out = edit(scripts, ws, ["pkg/m.py"], sr("qqqq wwww", "x"))
    assert out.startswith("NO MATCH: pkg/m.py unchanged. No similar lines found"), out


def test_closest_window_speed_5k_lines(scripts, tmp_path):
    """The closest-window search takes 300 ms or less on a 5k-line file (measured in a subprocess)."""
    code = ("import sys, time; sys.path.insert(0, %r); import edit\n"
            "lines = ['    value_%%d = compute_%%d(alpha, beta_%%d)  # row %%d' %% (i, i %% 97, i %% 13, i) "
            "for i in range(5000)]\n"
            "want = [lines[4200][:-3], lines[4201], 'something else entirely', lines[4203]]\n"
            "ts = []\n"
            "for _ in range(5):\n"
            "    t = time.perf_counter(); r = edit.closest(lines, want); ts.append(time.perf_counter() - t)\n"
            "print(min(ts), max(ts), r)\n" % str(scripts))
    r = subprocess.run([PY, "-c", code], env=env_for(mkrepo(tmp_path, {"a.py": "x\n"})), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    lo, hi, rest = r.stdout.split(" ", 2)
    assert float(hi) <= 0.300, r.stdout
    assert "4201, 4204" in rest, r.stdout          # 1-based window of the four searched lines


# ------------------------------------------------------------------------------------------------------------ R42
def test_line_modes(scripts, ws):
    f = ws / "pkg/m.py"
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return -(b - a)\n")
    assert out.startswith("OK (lines): pkg/m.py lines 5-6 replaced (2 old, 2 new)"), out
    assert f.read_text() == MOD.replace("return a - b", "return -(b - a)")
    # empty text is an ERROR and changes nothing (the Docker /dev/null case)
    before = sha(f)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], None)
    assert out.startswith("ERROR: no text on stdin (to delete lines add --delete)"), out
    assert sha(f) == before
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "")
    assert out.startswith("ERROR: no text on stdin") and sha(f) == before
    # --delete
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "3-4", "--delete"], None)
    assert out.startswith("OK (delete): pkg/m.py lines 3-4 deleted (2 old)"), out
    assert f.read_text() == MOD.replace("return a - b", "return -(b - a)").replace("    return a + b\n\n\n",
                                                                                    "    return a + b\n")
    # --insert-after 0 (top) and N
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import os\n")
    assert out.startswith("OK (insert): pkg/m.py 1 new lines after line 0"), out
    assert f.read_text().startswith("import os\ndef add(a, b):\n")
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", "3"], "    # tail of add\n")
    assert f.read_text().split("\n")[3] == "    # tail of add", f.read_text()
    # --create: parents made, existing file refused
    out = edit(scripts, ws, ["pkg/sub/new.py", "--create"], "VALUE = 1\n")
    assert out.startswith("OK (create): pkg/sub/new.py created (1 lines)") and (ws / "pkg/sub/new.py").read_text() == "VALUE = 1\n"
    out = edit(scripts, ws, ["pkg/sub/new.py", "--create"], "VALUE = 2\n")
    assert out.startswith("REFUSED: pkg/sub/new.py already exists") and (ws / "pkg/sub/new.py").read_text() == "VALUE = 1\n"
    # an empty new module is allowed
    out = edit(scripts, ws, ["pkg/sub/__init__.py", "--create"], None)
    assert out.startswith("OK (create)") and (ws / "pkg/sub/__init__.py").read_bytes() == b""
    # range errors
    assert edit(scripts, ws, ["pkg/m.py", "--lines", "90-95"], "x\n").startswith("ERROR: pkg/m.py has only")
    assert edit(scripts, ws, ["pkg/m.py", "--lines", "6-5"], "x\n").startswith("ERROR: bad range 6-5")
    assert edit(scripts, ws, ["pkg/m.py", "--lines", "abc"], "x\n").startswith("ERROR: --lines wants A-B")
    assert edit(scripts, ws, ["pkg/nope.py", "--lines", "1-1"], "x\n").startswith("ERROR: pkg/nope.py does not exist")


def test_line_numbers_match_git_and_view_on_separator_chars(scripts, tmp_path):
    """Form feed and other str.splitlines separators never shift numbering (F6): --lines N replaces git's line N."""
    body = "".join("line_%d = %r  # %s\n" % (i, i, c) for i, c in enumerate(SEP_CHARS, 1))
    src = "# header\n" + body + "tail = 1\n"
    ws = mkrepo(tmp_path, {"sep.py": src})
    n_git = len(src.encode().split(b"\n")) - 1
    target = 6                                            # line 6 holds the \x85 comment in git's numbering
    sed = subprocess.run(["sed", "-n", "%dp" % target, "sep.py"], cwd=ws, capture_output=True).stdout
    out = edit(scripts, ws, ["sep.py", "--lines", "%d-%d" % (target, target)], "replaced = True\n")
    assert out.startswith("OK (lines)"), out
    new = (ws / "sep.py").read_bytes().split(b"\n")
    assert new[target - 1] == b"replaced = True" and len(new) - 1 == n_git
    assert sed.rstrip(b"\n") in src.encode().split(b"\n")[target - 1]
    # SEARCH mode on the same file reports the same numbers
    out = edit(scripts, ws, ["sep.py"], sr("tail = 1", "tail = 2"))
    assert "lines %d-%d replaced" % (n_git, n_git) in out.splitlines()[0], out
    if (scripts / "view.py").exists():   # the view.py numbering convention (helpers-locate)
        r = subprocess.run([PY, str(scripts / "view.py"), "sep.py", str(target), str(target)], cwd=ws,
                           env=env_for(ws), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        assert "%5d| replaced = True" % target in r.stdout, r.stdout


# ------------------------------------------------------------------------------------------------------------ R43
def test_syntax_revert(scripts, ws):
    f = ws / "pkg/m.py"
    before = sha(f)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return (a -\n")
    first = out.splitlines()[0]
    assert first.startswith("REVERTED: syntax error at line") and first.endswith("pkg/m.py unchanged."), out
    assert sha(f) == before
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return a +* b"))
    assert out.startswith("REVERTED: syntax error at line 2 (line 1 of your new text)"), out
    assert "your edit would give:" in out and "    2|>    return a +* b" in out and sha(f) == before
    # the compile check leaves no bytecode: none in the workspace or the scripts copy, and nowhere a .pyc of the edited
    # module (core's installer may keep checked-hash .pyc files of its own libraries in $SWE; that is not this check)
    for root in (ws, scripts):
        assert not [p for p in pathlib.Path(root).rglob("*") if p.suffix == ".pyc" or p.name == "__pycache__"], root
    assert not [p for p in (ws.parent / "sbx_tmp").rglob("m.*.pyc")]
    # a file that already did not compile: the edit is applied with a WARNING, never REVERTED
    f.write_text(MOD + "def broken(:\n")
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return a + b + 1"))
    assert out.startswith("WARNING: pkg/m.py does not compile (line 12"), out
    assert "it did not compile before this edit either" in out and "OK (exact)" in out
    assert "return a + b + 1" in f.read_text()


def test_unescape_fallback_when_new_text_does_not_compile(scripts, ws):
    """--lines text with double-JSON escapes that does not compile raw is decoded once when that compiles."""
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "11-11"], '        return \\"one\\"\n')
    assert out.startswith("OK (lines, unescape)"), out
    assert '        return "one"\n' in (ws / "pkg/m.py").read_text()
    # escapes that compile as written are kept (plus a warning)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "11-11"], "        return 'it\\'s'\n")
    assert out.startswith("OK (lines)") and "WARNING" not in out.splitlines()[0]
    assert "return 'it\\'s'" in (ws / "pkg/m.py").read_text()


# ------------------------------------------------------------------------------------------------------------ R44
def test_encoding_fidelity(scripts, tmp_path):
    crlf = "def f():\r\n    a = 1\r\n    b = 2\r\n    return a + b\r\n"
    ws = mkrepo(tmp_path, {"crlf.py": crlf, "bom.py": b"\xef\xbb\xbfx = 1\ny = 2\n", "nonl.py": "x = 1\ny = 2",
                           "lat.py": b"# -*- coding: latin-1 -*-\nname = '\xe9t\xe9'\nz = 0\n",
                           "bad.txt": b"ok\n\xff\xfe raw \x80 bytes\nlast\n",
                           "mixed.py": "a = 1\r\nb = 2\nc = 3\r\nd = 4\r\n"})
    edit(scripts, ws, ["crlf.py"], sr("    b = 2", "    b = 3"))
    assert (ws / "crlf.py").read_bytes() == crlf.replace("b = 2", "b = 3").encode()
    ns = git(ws, "diff", "--numstat", "_swegemma_baseline", "--", "crlf.py").stdout.decode().split()
    assert ns[:2] == ["1", "1"], ns
    edit(scripts, ws, ["crlf.py", "--lines", "2-2"], "    a = 10\n    a2 = 11\n")
    assert (ws / "crlf.py").read_bytes() == b"def f():\r\n    a = 10\r\n    a2 = 11\r\n    b = 3\r\n    return a + b\r\n"
    edit(scripts, ws, ["bom.py"], sr("y = 2", "y = 3"))
    assert (ws / "bom.py").read_bytes() == b"\xef\xbb\xbfx = 1\ny = 3\n"
    edit(scripts, ws, ["nonl.py", "--lines", "1-1"], "x = 5\n")
    assert (ws / "nonl.py").read_bytes() == b"x = 5\ny = 2"
    edit(scripts, ws, ["nonl.py"], sr("x = 5", "x = 6"))
    assert (ws / "nonl.py").read_bytes() == b"x = 6\ny = 2"
    edit(scripts, ws, ["lat.py", "--lines", "3-3"], "z = 1\n")
    assert (ws / "lat.py").read_bytes() == b"# -*- coding: latin-1 -*-\nname = '\xe9t\xe9'\nz = 1\n"
    edit(scripts, ws, ["bad.txt"], sr("last", "LAST"))
    assert (ws / "bad.txt").read_bytes() == b"ok\n\xff\xfe raw \x80 bytes\nLAST\n"
    out = edit(scripts, ws, ["bad.txt", "--lines", "3-3"], "end\n")
    assert (ws / "bad.txt").read_bytes() == b"ok\n\xff\xfe raw \x80 bytes\nend\n" and "\ufffd" in out
    edit(scripts, ws, ["mixed.py", "--lines", "2-2"], "b = 20\n")   # dominant CRLF for new lines, others untouched
    assert (ws / "mixed.py").read_bytes() == b"a = 1\r\nb = 20\r\nc = 3\r\nd = 4\r\n"


# ------------------------------------------------------------------------------------------------------------ R45
REFUSE_CASES = [
    ("tests/test_m.py", "REFUSED: "), ("pkg/test_x.py", "REFUSED: "), ("pkg/x_test.py", "REFUSED: "),
    ("conftest.py", "REFUSED: "), ("pkg/sub/conftest.py", "REFUSED: "), ("pytest.ini", "REFUSED: "),
    ("tox.ini", "REFUSED: "), ("setup.cfg", "REFUSED: "), ("pyproject.toml", "REFUSED: "),
    ("sitecustomize.py", "REFUSED: "), ("x.pth", "REFUSED: "), ("test/helper.py", "REFUSED: "),
    ("testing/helper.py", "REFUSED: "), ("pkg/tests/util.py", "REFUSED: "), (".git/config", "REFUSED: "),
    ("../outside.py", "REFUSED: outside the repository"), ("/etc/hosts", "REFUSED: outside the repository"),
    ("json_dep", "REFUSED: outside the repository"),
]


@pytest.mark.parametrize("case", REFUSE_CASES, ids=[c[0] for c in REFUSE_CASES])
def test_refusals(scripts, ws, case):
    rel, want = case
    if rel == "json_dep":
        import json as _j
        rel = _j.__file__                                # an installed dependency / stdlib path
    p = pathlib.Path(rel) if os.path.isabs(rel) else ws / rel
    before = p.read_bytes() if p.exists() else None
    out = edit(scripts, ws, [rel, "--lines", "1-1"], "x = 1\n")
    assert out.startswith(want), out
    if want == "REFUSED: " and rel != ".git/config":
        assert "graders replace test files; this edit would make grading fail; put checks in a reproduction" in out
    assert (p.read_bytes() if p.exists() else None) == before


def test_refusal_exceptions_allowed(scripts, tmp_path):
    ws = mkrepo(tmp_path, {"pkg/testing/util.py": "a = 1\n", "pkg/ünï/mödule.py": "b = 1\n"})
    assert edit(scripts, ws, ["pkg/testing/util.py", "--lines", "1-1"], "a = 2\n").startswith("OK (lines)")
    out = edit(scripts, ws, ["pkg/ünï/mödule.py"], sr("b = 1", "b = 2"))
    assert out.startswith("OK (exact): pkg/ünï/mödule.py"), out
    assert (ws / "pkg/ünï/mödule.py").read_text() == "b = 2\n"
    # an absolute path inside the workspace is fine; one written for another root keeps the suffix that exists
    assert edit(scripts, ws, [str(ws / "pkg/testing/util.py"), "--lines", "1-1"], "a = 3\n").startswith("OK (lines)")
    out = edit(scripts, ws, ["/nonexistent_root/pkg/testing/util.py", "--lines", "1-1"], "a = 4\n")
    assert out.startswith("OK (lines): pkg/testing/util.py"), out


# ------------------------------------------------------------------------------------------------------------ R46
def test_loop_breaker(scripts, ws):
    f = ws / "pkg/m.py"
    before = sha(f)
    bad = sr("def sub(a, c):\n    return a - c", "def sub(a, c):\n    return c")
    first = edit(scripts, ws, ["pkg/m.py"], bad, t=10)
    assert first.startswith("NO MATCH")
    again = edit(scripts, ws, ["pkg/m.py"], bad, t=20)
    assert again.startswith("ALREADY TRIED: this exact edit failed at t=10s (NO MATCH). Do something different: "
                            "python3 /tmp/swe/view.py pkg/m.py 2 9, then python3 /tmp/swe/edit.py pkg/m.py --lines 5-6."), again
    # three consecutive failures on one file: the numbered region plus the recipe
    third = edit(scripts, ws, ["pkg/m.py"], sr("    return a +* b", "    return 0"), t=30)
    assert "3 failed edits in a row on pkg/m.py" in third, third
    assert "use: python3 /tmp/swe/edit.py pkg/m.py --lines" in third and "| " in third
    assert sha(f) == before
    # a REVERTED edit repeated verbatim is also ALREADY TRIED; a success resets the count
    bad2 = sr("    return a + b", "    return (a")
    assert edit(scripts, ws, ["pkg/m.py"], bad2, t=40).startswith("REVERTED")
    assert edit(scripts, ws, ["pkg/m.py"], bad2, t=50).startswith("ALREADY TRIED: this exact edit failed at t=40s (REVERTED)")
    assert edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return a + b  # ok"), t=60).startswith("OK")
    out = edit(scripts, ws, ["pkg/m.py"], sr("zzz", "yyy"), t=70)
    assert "3 failed edits" not in out


# ------------------------------------------------------------------------------------------------------------ R47
def test_stale_guard(scripts, ws):
    f = ws / "pkg/m.py"
    record_view(scripts, ws, "pkg/m.py", 1, 12, t=50)
    # an edit near the top adds 2 lines (delta +2) after that view
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    s = a + b\n    t = s\n    return t"), t=60)
    assert out.startswith("OK (exact): pkg/m.py lines 2-2 replaced (1 old, 3 new)"), out
    before = sha(f)
    # the old numbers of sub() (5-6) are stale: the same code is now at 7-8
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return b - a\n", t=70)
    assert out.startswith("STALE: lines moved by +2 since your last view of this region; the same code is now at 7-8. "
                          "Re-run with --lines 7-8 or view it again."), out
    assert "    7| def sub(a, b):" in out and sha(f) == before
    # repeating the stale numbers stays STALE
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return b - a\n", t=75)
    assert out.startswith("STALE: lines moved by +2") and sha(f) == before
    # the corrected range is accepted
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "7-8"], "def sub(a, b):\n    return b - a\n", t=80)
    assert out.startswith("OK (lines): pkg/m.py lines 7-8 replaced"), out
    assert "def sub(a, b):\n    return b - a\n" in f.read_text()
    # an edit above the earlier edit is accepted without a new view
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "1-1"], "def add(a, b):  # top\n", t=90)
    assert out.startswith("OK (lines)"), out


def test_stale_guard_after_covering_view_and_insert(scripts, ws):
    record_view(scripts, ws, "pkg/m.py", 1, 12, t=50)
    assert edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import os\nimport re\n", t=60).startswith("OK")
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", "6"], "# note\n", t=70)
    assert out.startswith("STALE: lines moved by +2") and "--insert-after 8" in out, out
    record_view(scripts, ws, "pkg/m.py", 1, 14, t=80)      # a newer covering view: the numbers are current
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "7-8"], "def sub(a, b):\n    return 0\n", t=90)
    assert out.startswith("OK (lines): pkg/m.py lines 7-8 replaced"), out
    assert "def sub(a, b):\n    return 0\n" in (ws / "pkg/m.py").read_text()


def test_stale_guard_trusts_current_numbers_when_the_text_fits_them(scripts, ws):
    """Numbers taken after the edit (grep, verify SIBLINGS) are current: when the new text clearly resembles the lines
    as numbered now, no STALE fires; a post-edit display only vouches for the edited span, not its +-2 context."""
    record_view(scripts, ws, "pkg/m.py", 1, 12, t=50)
    assert edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import os\nimport re\n", t=60).startswith("OK")
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "7-8"], "def sub(a, b):\n    return b - a\n", t=70)
    assert out.startswith("OK (lines): pkg/m.py lines 7-8 replaced"), out
    assert (ws / "pkg/m.py").read_text() == "import os\nimport re\n" + MOD.replace("return a - b", "return b - a")
    # old numbers (the t=50 view) whose text fits the shifted region better are STALE: line 9 is now blank, and the
    # "class K:" the model saw at 9 is at 11
    before = sha(ws / "pkg/m.py")
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "9-9"], "class K(object):\n", t=80)
    assert out.startswith("STALE: lines moved by +2 since your last view of this region; the same code is now at "
                          "11-11."), out
    assert sha(ws / "pkg/m.py") == before


def test_stale_guard_with_real_view_helper(scripts, ws):
    if not (scripts / "view.py").exists():
        pytest.skip("view.py (helpers-locate) not built")
    r = subprocess.run([PY, str(scripts / "view.py"), "pkg/m.py", "1", "12"], cwd=ws, env=env_for(ws, 50),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert "    5| def sub(a, b):" in r.stdout, r.stdout
    edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import os\n", t=60)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return 0\n", t=70)
    assert out.startswith("STALE: lines moved by +1") and "now at 6-7" in out, out


# ------------------------------------------------------------------------------------------------------------ R48
def test_input_normalisation_and_warnings(scripts, ws):
    f = ws / "pkg/m.py"
    variants = ("<<<<<<<SEARCH\n    return a + b\n=========\n    return a + b + 1\n>>>>>>>REPLACE\n"
                "EOF\n`\n")
    out = edit(scripts, ws, ["pkg/m.py"], variants)
    assert out.startswith("OK (exact)"), out
    assert f.read_text() == MOD.replace("return a + b", "return a + b + 1")
    lower = "<<<<<<<< search\n    return a + b + 1\n=====\n    return a + b\n>>>>>>>>> replace\nSWE_EOF\n"
    assert edit(scripts, ws, ["pkg/m.py"], lower).startswith("OK (exact)") and f.read_text() == MOD
    # trailing EOF / backtick junk after --lines text is stripped
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "2-2"], "    return b + a\nEOF\n")
    assert out.startswith("OK (lines): pkg/m.py lines 2-2 replaced (1 old, 1 new)"), out
    assert "EOF" not in f.read_text()
    # NO CHANGE
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return b + a", "    return b + a"))
    assert out.startswith("NO CHANGE: the new text equals the old text."), out
    # \" warning: the new text has \" but neither SEARCH nor the old code does (and it compiles as written)
    out = edit(scripts, ws, ["pkg/m.py"], sr("        return 1", "        return 'a\\\"b'"))
    assert out.startswith("OK (exact)") and 'WARNING: block 1 new text contains \\"' in out, out
    # column-0 warning: an indented line replaced by column-0 text that still compiles
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "11-11"], "VALUE = 1\n")
    assert "WARNING: your new text starts at column 0 but line 11 was indented" in out or out.startswith("REVERTED"), out
    ws2 = mkrepo(ws.parent / "w2", {"a.py": "def f():\n    x = 1\n    return x\ny = 2\n"})
    out = edit(scripts, ws2, ["a.py"], sr("    return x\ny = 2", "    return x\ny = 3"))
    assert "WARNING" not in out
    out = edit(scripts, ws2, ["a.py"], sr("    x = 1\n    return x", "x = 1\nreturn_x = 1"))
    assert "WARNING: block 1 new text starts at column 0 but line 2 was indented" in out or out.startswith("REVERTED"), out
    # markers with --lines: the blocks win, --lines is ignored and said so
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "1-1"], sr("    return b + a", "    return a + b"))
    assert out.startswith("OK (exact): (ignored --lines: your text has SEARCH/REPLACE blocks) pkg/m.py"), out
    # no markers and no mode
    assert edit(scripts, ws, ["pkg/m.py"], "x = 1\n").startswith("ERROR: no <<<<<<< SEARCH")


# ------------------------------------------------------------------------------------------------------------ R49
def test_edit_runs_hygiene(scripts, ws):
    t = ws / "tests/test_m.py"
    original = t.read_bytes()
    subprocess.run(["sed", "-i.bak", "s/pass/assert False/", str(t)], check=True)
    os.remove(str(t) + ".bak")
    assert t.read_bytes() != original
    out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return a + b  # hygiene"))
    assert out.startswith("OK (exact)"), out
    assert "reverted test/config edits: tests/test_m.py" in out
    assert t.read_bytes() == original


# ------------------------------------------------------------------------------------------------------------ R50
def big_module(n=5000):
    rows = ["def fn_%d(x):\n    return x + %d\n" % (i, i) for i in range(n // 2)]
    return "".join(rows)


def test_edit_output_and_perf(scripts, tmp_path):
    ws = mkrepo(tmp_path, {"big.py": big_module(), "long.py": "".join("v%d = %r\n" % (i, "x" * 300) for i in range(200))})
    assert len((ws / "big.py").read_text().split("\n")) >= 5000
    # a big replacement: output bounded, status on line 1, region at most 30 numbered lines
    new = "".join("    y_%d = %d\n" % (i, i) for i in range(60)) + "    return x\n"
    out = edit(scripts, ws, ["big.py", "--lines", "2-2"], new)
    assert out.startswith("OK (lines): big.py lines 2-2 replaced (1 old, 61 new)"), out
    assert len(out) <= 1500, len(out)
    rows = [s for s in out.splitlines() if s[:5].strip().isdigit() and s[5:7] == "| "]
    assert 0 < len(rows) <= 30
    out = edit(scripts, ws, ["long.py", "--lines", "100-110"], "".join("w%d = %r\n" % (i, "y" * 300) for i in range(11)))
    assert out.startswith("OK (lines)") and len(out) <= 1500, len(out)
    out = edit(scripts, ws, ["long.py"], sr("v5 = 'nothing'", "v5 = 1"))
    assert out.startswith("NO MATCH") and len(out) <= 1500, len(out)
    # p95 of 20 successful edits on the 5k-line file: 150 ms or less, end to end (process start to exit). Runs the
    # installed copy (python3 /tmp/swe/edit.py in production, where bootstrap has nothing to copy); best p95 of up to 3
    # rounds of 20. Asserted whenever the machine is not saturated (load average at or below the core count); on a
    # saturated machine (other suites running) no wall or CPU figure is meaningful (Apple Silicon moves work to
    # efficiency cores), so only a 1 s regression guard is asserted and the figure is reported as a warning.
    installed = ws.parent / "sbx_tmp/swe/edit.py"
    assert installed.exists()
    best, k = None, 0
    for _ in range(3):
        walls = []
        for _ in range(20):
            n = 100 + k
            k += 1
            t0 = time.perf_counter()
            o = edit(installed.parent, ws, ["big.py"], sr("    return x + %d" % n, "    return x + %d  # e" % n))
            walls.append(time.perf_counter() - t0)
            assert o.startswith("OK (exact)"), o
        p95 = statistics.quantiles(walls, n=20)[-1]
        best = p95 if best is None else min(best, p95)
        if best <= 0.150:
            break
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    if load <= (os.cpu_count() or 1):
        assert best <= 0.150, (best, walls)
    else:
        assert best <= 1.0, (best, walls)          # regression guard only: a quadratic matcher takes seconds here
        if best > 0.150:
            import warnings
            warnings.warn("edit.py p95 %.0f ms not asserted against 150 ms: machine saturated (load %.1f > %d cores)"
                          % (best * 1000, load, os.cpu_count() or 1))


def test_edit_core_logic_budget_5k_lines(scripts, tmp_path):
    """Timing of edit.py's own work on a 5k-line file, in process (best of 7): locate a SEARCH block, apply it,
    compile the result in memory and build the numbered region, 60 ms or less (a full compile() of the 5k-line module
    is most of it); NO MATCH's closest-window search 300 ms or less. On a saturated machine (load average above the
    core count) the bounds are 5x, which still fails any quadratic matcher."""
    code = ("import sys, time; sys.path.insert(0, %r); import edit\n"
            "src = ''.join('def fn_%%d(x):\\n    return x + %%d\\n' %% (i, i) for i in range(2500))\n"
            "lines, fnl = edit.split_text(src)\n"
            "def one():\n"
            "    h = edit.find_block(lines, fnl, ['    return x + 2400'], ['    return x + 2400  # e'])\n"
            "    out, f2, A, B, A2, B2 = edit.apply_hit(lines, fnl, h, False)\n"
            "    assert edit.compile_error(edit.encode(edit.join_text(out, f2), False), 'big.py') is None\n"
            "    edit.region(out, [(A2, B2)], 1000, 'big.py')\n"
            "def miss():\n"
            "    return edit.no_match.__code__ and edit.closest(lines, ['def fn_2400(y):', '    return y + 2400'])\n"
            "def best(f):\n"
            "    ts = []\n"
            "    for _ in range(7):\n"
            "        t = time.perf_counter(); f(); ts.append(time.perf_counter() - t)\n"
            "    return min(ts)\n"
            "print(best(one), best(miss), miss())\n" % str(scripts))
    ws = mkrepo(tmp_path, {"a.py": "x = 1\n"})
    r = subprocess.run([PY, "-c", code], cwd=str(ws), env=env_for(ws), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    t_one, t_miss, rest = r.stdout.split(" ", 2)
    assert "4801, 4802" in rest, r.stdout
    saturated = hasattr(os, "getloadavg") and os.getloadavg()[0] > (os.cpu_count() or 1)
    k = 5.0 if saturated else 1.0      # a saturated machine runs this on efficiency cores; still catches O(n^2)
    assert float(t_one) <= 0.060 * k, r.stdout
    assert float(t_miss) <= 0.300 * k, r.stdout


# ------------------------------------------------------------------------------------------------------------ R51
def test_skill_arg_form(scripts, tmp_path):
    a = mkrepo(tmp_path / "a", {"pkg/m.py": MOD})
    b = mkrepo(tmp_path / "b", {"pkg/m.py": MOD})
    text = "def sub(a, b):\n    return a - b - 0\n"
    edit(scripts, a, ["pkg/m.py", "--lines", "5-6"], text)
    out = edit(scripts, b, ["--file", "pkg/m.py", "--lines", "5-6", "--text", text.rstrip("\n")], None)
    assert out.startswith("OK (lines)"), out
    assert (a / "pkg/m.py").read_bytes() == (b / "pkg/m.py").read_bytes()
    # SEARCH/REPLACE through --text, and the wrapper's runpy form (cwd = a temp dir, argv with a bare --)
    c = mkrepo(tmp_path / "c", {"pkg/m.py": MOD})
    td = tmp_path / "wrapper"
    (td / "scripts").mkdir(parents=True)
    for p in scripts.glob("*.py"):
        shutil.copy2(p, td / "scripts" / p.name)
    argv = ["scripts/edit.py", "--file", "pkg/m.py", "--text", sr("        return 1", "        return 7"), "--"]
    code = "import runpy, sys; sys.argv = %r; runpy.run_path('scripts/edit.py', run_name='__main__')" % (argv,)
    r = subprocess.run([PY, "-c", code], cwd=str(td), env=dict(env_for(c), PWD=str(c)), capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert r.stdout.startswith("OK (exact): pkg/m.py"), r.stdout + r.stderr
    assert (c / "pkg/m.py").read_text() == MOD.replace("return 1", "return 7")
    # --insert-after and --delete in the key-value form
    out = edit(scripts, c, ["--file", "pkg/m.py", "--insert-after", "0", "--text", "import os"], None)
    assert out.startswith("OK (insert)") and (c / "pkg/m.py").read_text().startswith("import os\n")
    out = edit(scripts, c, ["--file", "pkg/m.py", "--lines", "1-1", "--delete", "True"], None)
    assert out.startswith("OK (delete)") and (c / "pkg/m.py").read_text() == MOD.replace("return 1", "return 7")


# ----------------------------------------------------------------------------------------------------- journal/state
def test_journal_and_state_records(scripts, ws):
    edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    s = a + b\n    return s"), t=42)
    swe = ws.parent / "sbx_tmp/swe"
    ev = [json.loads(s) for s in (swe / "journal.jsonl").read_text().splitlines() if '"edit"' in s]
    assert ev[-1]["ok"] is True and ev[-1]["file"] == "pkg/m.py" and ev[-1]["start"] == 2 and ev[-1]["end"] == 2
    assert ev[-1]["delta"] == 1 and ev[-1]["mode"] == "search"
    st = json.loads((swe / "state.json").read_text())
    assert {"file": "pkg/m.py", "start": 2, "end": 2, "delta": 1, "t": 42.0}.items() <= st["edits"][-1].items()
    assert any(v[0] <= 2 <= v[1] for v in st["views"]["pkg/m.py"])


def test_blank_last_search_line_never_joins_lines(scripts, tmp_path):
    """Regression: a SEARCH ending in a blank line that the file does not have (or a REPLACE without it) must never
    consume the newline and join two lines."""
    ws = mkrepo(tmp_path, {"a.py": "def f():\n    return 1\nx = 2\n", "b.py": "def g():\n    return 1\n\ny = 2\n"})
    out = edit(scripts, ws, ["a.py"], "<<<<<<< SEARCH\n    return 1\n\n=======\n    return 3\n>>>>>>> REPLACE\n")
    assert out.startswith("OK ("), out
    assert (ws / "a.py").read_text() == "def f():\n    return 3\nx = 2\n"
    # the blank line exists in the file: SEARCH has 2 lines, REPLACE 1, so the blank line goes with it
    out = edit(scripts, ws, ["b.py"], "<<<<<<< SEARCH\n    return 1\n\n=======\n    return 4\n>>>>>>> REPLACE\n")
    assert out.startswith("OK (exact)"), out
    assert (ws / "b.py").read_text() == "def g():\n    return 4\ny = 2\n"


def test_tolerant_forms(scripts, tmp_path):
    """Forms a weak model produces: a block without >>>>>>> REPLACE, ``` fences around the bodies, an RST underline
    (=======) inside a docstring, cwd in a subdirectory, --lines A B, --start/--end, non-ASCII text, empty SEARCH."""
    doc = 'def f():\n    """Title\n    =======\n\n    Body.\n    """\n    return 1\n'
    ws = mkrepo(tmp_path, {"pkg/m.py": MOD, "pkg/d.py": doc, "pkg/u.py": 'S = "café"\n'})
    f = ws / "pkg/m.py"
    out = edit(scripts, ws, ["pkg/m.py"], "<<<<<<< SEARCH\n    return a + b\n=======\n    return a + b + 5\n")
    assert out.startswith("OK (exact)") and "return a + b + 5" in f.read_text(), out
    fenced = ("<<<<<<< SEARCH\n```python\n    return a + b + 5\n```\n=======\n```python\n    return a + b\n```\n"
              ">>>>>>> REPLACE\n")
    out = edit(scripts, ws, ["pkg/m.py"], fenced)
    assert out.startswith("OK (exact)") and f.read_text() == MOD, out
    # the underline sits in both halves: the symmetric ======= split is the divider
    rst = ('<<<<<<< SEARCH\n    """Title\n    =======\n\n    Body.\n=======\n    """Title\n    =======\n\n    More body.\n'
           '>>>>>>> REPLACE\n')
    out = edit(scripts, ws, ["pkg/d.py"], rst)
    assert out.startswith("OK ("), out
    assert (ws / "pkg/d.py").read_text() == doc.replace("    Body.", "    More body.")
    # cwd in a subdirectory, FILE relative to it
    out = edit(scripts, ws, ["m.py", "--lines", "2", "2"], "    return b + a\n", cwd=ws / "pkg")
    assert out.startswith("OK (lines): pkg/m.py lines 2-2 replaced"), out
    out = edit(scripts, ws, ["pkg/m.py", "--start", "2", "--end", "2"], "    return a + b\n")
    assert out.startswith("OK (lines): pkg/m.py lines 2-2") and f.read_text() == MOD, out
    out = edit(scripts, ws, ["pkg/u.py"], sr('S = "café"', 'S = "café ☕"'))
    assert out.startswith("OK (exact)") and (ws / "pkg/u.py").read_text() == 'S = "café ☕"\n', out
    out = edit(scripts, ws, ["pkg/m.py"], sr("", "x = 1"))
    assert out.startswith("ERROR: block 1 has an empty SEARCH"), out
    out = edit(scripts, ws, ["pkg/brand_new.py"], sr("", "VALUE = 3"))
    assert out.startswith("OK (create): pkg/brand_new.py created (1 lines)"), out
    assert (ws / "pkg/brand_new.py").read_text() == "VALUE = 3\n"
    assert edit(scripts, ws, ["pkg/m.py", "--insert-after", "x"], "a\n").startswith("ERROR: --insert-after wants")
    assert edit(scripts, ws, ["pkg/m.py", "--delete"], None).startswith("ERROR: --delete needs --lines")
    assert edit(scripts, ws, ["pkg/m.py", "--lines", "1-1", "--create"], "x\n").startswith("ERROR: use only one of")
    assert edit(scripts, ws, [], None).startswith("USAGE: python3 /tmp/swe/edit.py FILE")
    assert edit(scripts, ws, ["pkg/m.py", "--bogus", "1"], None).startswith("USAGE ERROR: unknown option --bogus")


def test_write_failure_is_one_line(scripts, tmp_path):
    ws = mkrepo(tmp_path, {"pkg/m.py": MOD, "pkg/blocker": "not a dir\n"})
    out = edit(scripts, ws, ["pkg/blocker/new.py", "--create"], "x = 1\n")
    assert out.startswith("ERROR: could not create the directory of pkg/blocker/new.py") or \
        out.startswith("ERROR"), out
    ro = ws / "pkg/m.py"
    ro.chmod(0o444)
    try:
        if os.access(str(ro), os.W_OK):
            pytest.skip("running as a user that can write read-only files")
        out = edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    return 0"))
        assert out.startswith("ERROR: could not write pkg/m.py"), out
        assert ro.read_text() == MOD
    finally:
        ro.chmod(0o644)


def test_stale_by_content_without_any_view(scripts, ws):
    """Numbers from locate/grep/the plan (no view recorded) that predate a line-shifting edit: STALE only when the new
    text clearly fits the shifted range; fresh numbers taken after the edit are accepted."""
    f = ws / "pkg/m.py"
    assert edit(scripts, ws, ["pkg/m.py"], sr("    return a + b", "    s = a + b\n    return s"), t=60).startswith("OK")
    before = sha(f)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "5-6"], "def sub(a, b):\n    return b - a\n", t=70)
    assert out.startswith("STALE: lines moved by +1") and "now at 6-7" in out and sha(f) == before, out
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "6-7"], "def sub(a, b):\n    return b - a\n", t=80)
    assert out.startswith("OK (lines): pkg/m.py lines 6-7 replaced"), out
    # a rewrite unlike either region is taken at face value (no evidence either way)
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "11-12"], "    def m(self):\n        return 42\n", t=90)
    assert out.startswith("OK (lines)"), out


# -------------------------------------------------------------- review round 1: REPLACE decoding in the unescape tier
QUOTED = 'import re\n\n\ndef f(parts):\n    x = "abc"\n    return x\n'


def _journal(ws):
    p = ws.parent / "sbx_tmp" / "swe" / "journal.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


@pytest.mark.parametrize("case", [
    # (id, SEARCH as the model sends it, REPLACE as the model sends it, the line written, rdec)
    ("native-newline-escape-kept", '    x = \\"abc\\"', '    x = \\"abc\\" + "\\n".join(parts)',
     '    x = "abc" + "\\n".join(parts)', "quotes"),
    ("native-regex-kept-verbatim", '    x = \\"abc\\"', '    x = re.sub(r"\\\\s+", " ", "abc")',
     '    x = re.sub(r"\\\\s+", " ", "abc")', "raw"),
    ("artefact-quotes-decoded", '    x = \\"abc\\"', '    x = \\"abd\\"', '    x = "abd"', "quotes"),
    ("native-escaped-quotes-compile-fallback", '    x = \\"abc\\"', '    x = "say \\"hi\\""',
     '    x = "say \\"hi\\""', "raw"),
], ids=lambda c: c[0])
def test_unescape_tier_decodes_replace_only_for_its_own_artefacts(scripts, tmp_path, case):
    """Review round 1: when SEARCH matched only after decoding, the same decode was applied to REPLACE, so natively
    written escapes changed: "\\n".join became a real newline (REVERTED) and r"\\\\s+" silently became r"\\s+" (OK).
    REPLACE is now decoded only for artefacts it carries itself, and the compile check picks among the forms."""
    _, search, replace, want, rdec = case
    ws = mkrepo(tmp_path, {"pkg/f.py": QUOTED})
    out = edit(scripts, ws, ["pkg/f.py"], sr(search, replace))
    assert out.startswith("OK (unescape): pkg/f.py lines 5-5 replaced"), out
    assert (ws / "pkg/f.py").read_text() == QUOTED.replace('    x = "abc"', want), (ws / "pkg/f.py").read_text()
    ev = [e for e in _journal(ws) if e.get("h") == "edit" and e.get("ok")][-1]
    assert ev["rdec"] == [rdec], ev
    if case[0].endswith("compile-fallback"):
        assert "NOTE: SEARCH matched after decoding escapes; your new text compiled only as you wrote it." in out, out


def test_unescape_one_json_level_search(scripts, tmp_path):
    """Review round 1: a SEARCH copied one JSON level deep for a line with real escapes ("Hello, \\"%s\\"") decoded
    \\\\\\" to a bare quote and never matched (NO MATCH at 0.92); the one-level decode now matches it."""
    src = 'def greet(name):\n    msg = "Hello, \\"%s\\"" % name\n    return msg\n'
    ws = mkrepo(tmp_path, {"pkg/g.py": src})
    search = '    msg = \\"Hello, \\\\\\"%s\\\\\\"\\" % name'
    out = edit(scripts, ws, ["pkg/g.py"], sr(search, "    msg = \"Hello, '%s'\" % name"))
    assert out.startswith("OK (unescape): pkg/g.py lines 2-2 replaced"), out
    assert (ws / "pkg/g.py").read_text() == src.replace('"Hello, \\"%s\\""', "\"Hello, '%s'\"")


def test_replace_choice_rules_unit(scripts, tmp_path):
    """replace_choices: the forms and their order for each kind of evidence."""
    code = ("import edit as E\n"
            "print(E.replace_choices('a\\\\nb', E.unescape('a\\\\nb'), 'x\\\\ny', E.unescape, 'a\\nb'))\n"
            "print(E.replace_choices('\\\\\"q\\\\\"', '\"q\"', '\\\\\"r\\\\\" + \"\\\\n\"', E.unescape, '\"q\"'))\n"
            "print(E.replace_choices('\\\\\"q\\\\\"', '\"q\"', 'r\"\\\\\\\\s\"', E.unescape, '\"q\"'))\n"
            "print(E.json1('\\\\\"Hello, \\\\\\\\\\\\\"%s\\\\\\\\\\\\\"\\\\\" \\\\u00e9'))\n"
            "print(E.unquote('\\\\\\\\\\\\\"a\\\\\" \\\\\\'b\\\\\\' \\\\n'))\n")
    r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (str(scripts), code)], capture_output=True,
                       text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == repr([("x\ny", "full"), ("x\\ny", "quotes")]), lines[0]
    assert lines[1] == repr([('"r" + "\\n"', "quotes"), ('"r" + "\n"', "full"), ('\\"r\\" + "\\n"', "raw")]), lines[1]
    assert lines[2] == repr([('r"\\\\s"', "raw"), ('r"\\s"', "full")]), lines[2]
    assert lines[3] == '"Hello, \\"%s\\"" é', lines[3]
    assert lines[4] == "\"a\" 'b' \\n", lines[4]


# ------------------------------------------------------------------- review round 1: numbers from grep are current
FNS = "".join("def f%d(x):\n    return x + %d\n\n" % (i, i) for i in range(12))   # f10: lines 31-32


def helper(scripts, ws, name, args, t):
    r = subprocess.run([PY, str(scripts / ("%s.py" % name)), *args], cwd=str(ws), env=env_for(ws, t),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Traceback" not in r.stdout, r.stdout + r.stderr
    return r.stdout


def hit_line(out, text):
    """The line number of the grep hit row (NNNN| text) whose text ends with `text`."""
    return int(next(ln for ln in out.splitlines() if re.match(r"^\s*\d+\| ", ln) and ln.rstrip().endswith(text))
               .split("|")[0])


def views(scripts, ws, rel):
    return json.loads(c_call(scripts, ws, "import json; print(json.dumps(C.state_load().get('views', {}).get(%r, [])))"
                             % rel))


def test_grep_numbers_are_not_stale(scripts, tmp_path):
    """Review round 1 (scratch repo r3/repo5): view 1-60, add 3 imports at the top, grep the target line (current
    number 37-ish), then --lines N-N with an unlike rewrite: the STALE guard trusted only the old view, redirected to
    N+3 (f11's body) and the retry replaced the wrong function. grep.py now records the hits it printed as views."""
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": FNS})
    helper(scripts, ws, "view", ["pkg/m.py", "1", "60"], t=50)
    out = edit(scripts, ws, ["pkg/m.py"], sr("def f0(x):", "import os\nimport re\nimport sys\ndef f0(x):"), t=60)
    assert out.startswith("OK (exact)"), out
    g = helper(scripts, ws, "grep", ["return x \\+ 10$"], t=70)
    n = hit_line(g, "return x + 10")
    assert n == 35                          # f10's return, current numbering; old 35 + 3 = 38 holds f11's return
    assert (ws / "pkg/m.py").read_text().split("\n")[n - 1] == "    return x + 10"
    out = edit(scripts, ws, ["pkg/m.py", "--lines", "%d-%d" % (n, n)], "    raise ValueError('ten')\n", t=80)
    assert out.startswith("OK (lines): pkg/m.py lines %d-%d replaced" % (n, n)), out
    assert [n, n, 70.0, "d"] in views(scripts, ws, "pkg/m.py")
    text = (ws / "pkg/m.py").read_text()
    assert "def f10(x):\n    raise ValueError('ten')\n" in text and "    return x + 11\n" in text, text
    # --insert-after at a grep line taken after the edit: inserted there, not redirected
    g = helper(scripts, ws, "grep", ["^def f11"], t=90)
    k = hit_line(g, "def f11(x):")
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", str(k)], "    '''Eleven.'''\n", t=100)
    assert out.startswith("OK (insert): pkg/m.py 1 new lines after line %d" % k), out
    assert "def f11(x):\n    '''Eleven.'''\n    return x + 11\n" in (ws / "pkg/m.py").read_text()


def test_insert_after_is_redirected_only_on_a_real_view(scripts, tmp_path):
    """--insert-after has no new text to break a tie: an old grep hit (derived view) is not enough to redirect it; an
    old view.py range is."""
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": FNS})
    g = helper(scripts, ws, "grep", ["^def f5"], t=50)
    k = hit_line(g, "def f5(x):")
    assert edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import os\n", t=60).startswith("OK")
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", str(k)], "# note\n", t=70)
    assert out.startswith("OK (insert)"), out                              # weak evidence: taken at face value
    helper(scripts, ws, "view", ["pkg/m.py", "1", "40"], t=80)
    assert edit(scripts, ws, ["pkg/m.py", "--insert-after", "0"], "import re\n", t=90).startswith("OK")
    out = edit(scripts, ws, ["pkg/m.py", "--insert-after", "20"], "# note 2\n", t=100)
    assert out.startswith("STALE: lines moved by +1") and "--insert-after 21" in out, out


def test_locate_and_verify_record_printed_numbers(scripts, tmp_path):
    """locate.py's printed symbol numbers (the two ends of each Lstart-end) and verify.py's SIBLINGS / IMPORT
    file:line are recorded as (derived) views."""
    ws = mkrepo(tmp_path, {"pkg/__init__.py": "", "pkg/m.py": FNS})
    helper(scripts, ws, "locate", ["f10"], t=30)
    got = views(scripts, ws, "pkg/m.py")
    assert [31, 31, 30.0, "d"] in got and [32, 32, 30.0, "d"] in got, got      # f10's printed L31-32, not a range
    code = ("import verify as V\nprint(V.printed_views(['IMPORT: RED pkg.m: NameError: x (pkg/m.py:12)', "
            "'SIBLINGS (same code elsewhere, unchanged; fix them too if they have the same defect):', "
            "'  pkg/a.py:40  for x in y:', '  pkg/b.py:7  def f (same name as your changed g)', 'SPEC GAPS:', "
            "'  pkg/c.py:9  nope']))")
    r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (str(scripts), code)], cwd=str(ws),
                       env=env_for(ws, 40), capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().splitlines()[-1] == repr([("pkg/m.py", "12", "12"), ("pkg/a.py", "40", "40"),
                                                      ("pkg/b.py", "7", "7")]), r.stdout + r.stderr
