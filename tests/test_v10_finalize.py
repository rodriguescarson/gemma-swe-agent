"""Checkpoints and finalize.py (SPEC 4.9.8, 4.10, 4.12): R70-R77.

Every test copies the bundle scripts to a temp dir first (no __pycache__ can appear in the bundle) and runs the helpers as
subprocesses against throwaway git repos tagged _swegemma_baseline; the checkpoint library is also driven in-process.
"""
import hashlib, json, os, pathlib, re, shutil, subprocess, sys, time
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10") / "skills/swe-tools/scripts"
PY = sys.executable
VBIN = str(pathlib.Path(sys.executable).parent)
MODS = ("_swe_common", "_swe_gate", "_swe_ckpt", "_swe_index")

from v10_support.repo import no_orphans  # noqa: F401  (R120: the orphan-process guard, autouse)
from v10_support.compat import V102, later_stage  # noqa: E402,F401  (G4_BUNDLE may be v10.2)

pytestmark = pytest.mark.skipif(not (SRC / "_swe_common.py").exists() or not (SRC / "finalize.py").exists(),
                                reason="helpers not built")

HARNESS_INI = ("[pytest]\naddopts = -p no:anyio\nnorecursedirs = .* build dist venv\npython_classes = Test* *Test\n"
               "python_files = test_*.py *_test.py\n")
HOOK = "# Hermetic test discovery hook for SWE-gemma\n"
EXCLUDES = "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\nbuild/\ndist/\n.coverage\n.adk_exec_*.py\n"
EMPTY_LINE_T = ("NOT READY: EMPTY at t=%ds (%ds left) - no source change. Do not submit an empty patch: it always "
                "fails. Make the plan's FIX (smallest plausible version) now, then run python3 /tmp/swe/finalize.py "
                "again.")       # v10.1: time left and what an empty patch costs (race 2, fastapi_14873)
EMPTY_LINE = EMPTY_LINE_T % (100, 200)
CORE_PY = "def pad(s, width):\n    return s.ljust(width - 1)\n\n\ndef center(s, width):\n    return s.center(width)\n"
CORE_TESTS = ("from pkg.core import pad, center\n\n\ndef test_center():\n    assert center('a', 3) == ' a '\n\n\n"
              "def test_pad_zero():\n    assert pad('', 0) == ''\n")
BASIC = {"pkg/__init__.py": "", "pkg/core.py": CORE_PY, "tests/test_core.py": CORE_TESTS, "setup.cfg": "[x]\n",
         "docs/index.md": "docs\n"}
REPRO = "from pkg.core import pad\n# CLAIM 1: pads\nassert pad('ab', 4) == 'ab  ', repr(pad('ab', 4))\n"
FIX = ("s.ljust(width - 1)", "s.ljust(width)")
HYGIENE_WHY = " (graders replace test and config files, so a patch never carries them; do not redo this)"
WORSE = ("s.ljust(width - 1)", "s.ljust(width - 22)")   # edits change the size: see _RACY_NOTE


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def scripts(tmp_path_factory):
    d = tmp_path_factory.mktemp("scripts")
    for p in SRC.glob("*.py"):
        shutil.copy2(p, d / p.name)
    return d


def git(ws, *args, check=True, stdin=None):
    return subprocess.run(["git", "-c", "core.quotepath=off", "-c", "user.email=a@b", "-c", "user.name=t", *args],
                          cwd=ws, capture_output=True, check=check, input=stdin)


def write(ws, rel, data):
    p = pathlib.Path(ws) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def mkrepo(tmp, files, name="ws"):
    ws = pathlib.Path(tmp) / name
    ws.mkdir(parents=True)
    for rel, data in files.items():
        write(ws, rel, data)
    write(ws, "pytest.ini", HARNESS_INI)
    write(ws, "conftest.py", HOOK)
    git(ws, "init", "-q")
    with open(ws / ".git/info/exclude", "a") as f:
        f.write(EXCLUDES)
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "base")
    git(ws, "tag", "-f", "_swegemma_baseline")
    return ws


def swe(ws):
    return pathlib.Path(ws).parent / "sbx_tmp" / "swe"


def env_for(ws, t=100):
    tmp = pathlib.Path(ws).parent / "sbx_tmp"
    tmp.mkdir(exist_ok=True)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SWE_", "PYTHON", "TEST_TMPDIR"))}
    later_stage(tmp / "swe")    # v10.2: verify and finalize run in later stages (the locator budget does not apply)
    e.update(SWE_WS=str(ws), SWE_DIR=str(tmp / "swe"), TMPDIR=str(tmp), HOME=str(tmp), SWE_DUAL="0",
             SWE_DOCKER_TMP_FOR_TESTS=str(tmp / "docker_tmp"), PYTHONDONTWRITEBYTECODE="1", LANG="C.UTF-8",
             PYTHONPATH=str(ws), PATH=VBIN + os.pathsep + os.environ.get("PATH", ""))
    if t is not None:
        e["SWE_FAKE_CLOCK"] = str(t)
    return e


class Res(object):
    def __init__(self, out, secs):
        self.out, self.secs = out, secs
        self.lines = out.split("\n")
        self.first = self.lines[0] if self.lines else ""

    def line(self, prefix):
        return next((ln for ln in self.lines if ln.startswith(prefix)), None)


def run(scripts, name, ws, args=(), stdin=None, t=100, timeout=120, env=None):
    t0 = time.monotonic()
    r = subprocess.run([PY, str(scripts / ("%s.py" % name))] + list(args), cwd=str(ws), env=env or env_for(ws, t),
                       input=stdin.encode() if isinstance(stdin, str) else stdin,
                       stdin=subprocess.DEVNULL if stdin is None else None, capture_output=True, timeout=timeout)
    secs = time.monotonic() - t0
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0, out + r.stderr.decode("utf-8", "replace")
    assert "HELPER ERROR" not in out and "Traceback (most recent" not in out, out
    return Res(out, secs)


_RACY_NOTE = """Edits in these tests change the file size. git trusts (size, mtime) at one-second granularity unless an entry is
"racily clean"; an earlier _swe_common.diff_bytes() copied .git/index with a fresh mtime, which hid same-size edits made
in the same second (fixed in core by keeping the index's timestamps). Size-changing edits keep the tests independent."""


def finalize(scripts, ws, t=100):
    r = run(scripts, "finalize", ws, t=t)
    assert len(r.out.rstrip("\n")) <= 1400, r.out      # CAPS["finalize"] (1,000 -> 1,400 in v10.1: EDIT TARGET)
    return r


def edit(ws, rel, pair):
    p = pathlib.Path(ws) / rel
    s = p.read_text()
    assert pair[0] in s, (rel, pair)
    p.write_text(s.replace(pair[0], pair[1], 1))


def tree_hash(ws):
    """sha256 over every file outside .git (path, mode bit, bytes)."""
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(ws).rglob("*")):
        if ".git" in p.relative_to(ws).parts or not p.is_file():
            continue
        h.update(str(p.relative_to(ws)).encode() + b"\0" + str(os.access(p, os.X_OK)).encode() + b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def submit_diff(ws):
    """What submit_patch sends, computed on a throwaway index."""
    idx = pathlib.Path(ws).parent / "probe_idx"
    shutil.copy(pathlib.Path(ws) / ".git/index", idx)
    env = dict(os.environ, GIT_INDEX_FILE=str(idx))
    subprocess.run(["git", "add", "-N", "."], cwd=ws, env=env, capture_output=True)
    return subprocess.run(["git", "diff", "--binary", "_swegemma_baseline"], cwd=ws, env=env,
                          capture_output=True).stdout


def state(ws):
    return json.loads((swe(ws) / "state.json").read_text())


@pytest.fixture
def lib(scripts, monkeypatch):
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


# ------------------------------------------------------------------------------------------------- R70 score order
def test_checkpoint_score_order(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    S = G.make_score
    ladder = [
        ("empty", S(False, True, 1, True, 0, 0, 0, False)),
        ("import error", S(True, False, 1, True, 0, 0, 0, False)),
        ("collection error", S(True, True, 0, True, 0, 0, 0, False)),
        ("hang", S(True, True, 1, False, 0, 0, 0, False)),
        ("claims still failing", S(True, True, 1, True, 0, 0, 0, True)),
        ("regressions", S(True, True, 1, True, 1, 0, 2, True)),
        ("pass", S(True, True, 1, True, 1, 0, 0, True)),
    ]
    for (na, a), (nb, b) in zip(ladder, ladder[1:]):
        assert tuple(a) < tuple(b), (na, a, nb, b)
    assert tuple(S(True, True, 1, True, 1, 0, 1, True)) > tuple(S(True, True, 1, True, 0, 0, 0, True))
    assert S(True, True, 1, True, 3, 1, 0, False)[4] == 0              # no valid claims: fixed - broke = 0
    assert S(True, True, 1, True, 3, 1, 0, True)[4] == 2
    assert len(S(True, True, 1, True, 1, 0, 0, True, quick=True)) == 5
    # comparisons only within the same key; quick entries compare as 5-tuples
    write(ws, "pkg/a.py", "A = 1\n")
    ida = K.save(submit_diff(ws), [1, 1, 1, 1, 1, 0], "keyA", "GREEN", False, rkey="r1")
    write(ws, "pkg/a.py", "A = 2\n")
    idb = K.save(submit_diff(ws), [1, 1, 1, 1, 2, -5], "keyB", "RED", False, rkey="r1")
    write(ws, "pkg/a.py", "A = 3\n")
    idc = K.save(submit_diff(ws), [1, 1, 1, 1, 1], "r1", "AMBER", True, rkey="r1")
    assert K.best("keyA")["id"] == ida and K.best("keyB")["id"] == idb and K.best("nope") is None
    assert K.best(None)["id"] == idb                                     # any key: the highest score
    full = {"score": [1, 1, 1, 1, 1, -3], "quick": False}
    quick = {"score": [1, 1, 1, 1, 1], "quick": True}
    assert not K.better(full, quick) and not K.better(quick, full)       # equal as 5-tuples
    assert K.better({"score": [1, 1, 1, 1, 1, 0]}, {"score": [1, 1, 1, 1, 1, -1]})
    cur = {"sha": "x", "score": [1, 1, 1, 1, 0], "quick": True, "key": "r1", "rkey": "r1"}
    assert K.best_against(cur)["id"] == idb                              # quick vs any same-repro entry, 5-tuples
    cur = {"sha": "y", "score": [1, 1, 1, 1, 1, 0], "quick": False, "key": "keyA", "rkey": "r1"}
    assert K.best_against(cur)["id"] == idb                              # 2 fixed beats 1 fixed as 5-tuples
    assert K.best_against({"sha": "z", "score": [1, 1, 1, 1, 9], "quick": True, "rkey": "r1"}) is None
    assert idc and K.entry_for_sha(hashlib.sha1(submit_diff(ws)).hexdigest())["id"] == idc
    assert K.save(b"", [1], "k", "X", False) is None                     # empty trees are never stored


# ------------------------------------------------------------------------------------- R71 transactional restore
def test_restore_transactional(scripts, tmp_path, lib):
    ws = mkrepo(tmp_path, dict(BASIC, **{"pkg/c.py": "C = 1\n", "data.bin": bytes(range(256)) * 4}))
    C, G, K = lib(ws)
    edit(ws, "pkg/core.py", FIX)
    x1_hash, x1_sha = tree_hash(ws), C.diff_sha()
    id1 = K.save(C.diff_bytes(), [1, 1, 1, 1, 1, 0], "k", "GREEN", False)
    # X2: another source edit, a new module, a deleted file, a binary change, a mode change
    edit(ws, "pkg/core.py", ("s.center(width)", "s.center(width + 1)"))
    write(ws, "pkg/new.py", "N = 1\n")
    (ws / "pkg/c.py").unlink()
    write(ws, "data.bin", bytes(range(255, -1, -1)) * 5)
    os.chmod(ws / "pkg/__init__.py", 0o755)
    x2_hash, x2_sha = tree_hash(ws), C.diff_sha()
    ok, msg = K.restore(K.entry_for_sha(x1_sha))
    assert ok, msg
    assert C.diff_sha() == x1_sha and tree_hash(ws) == x1_hash
    saved = K.entry_for_sha(x2_sha)
    assert saved is not None and saved["verdict"] == "SAVED" and saved["score"] is None
    # an injected git apply failure rolls back to the tree as it was, byte for byte
    (swe(ws) / "ckpt" / ("%d.diff" % saved["id"])).write_bytes(b"this is not a patch\n")
    ok, msg = K.restore(saved)
    assert not ok and msg.startswith("RESTORE FAILED: git apply failed"), msg
    assert "the current tree was kept" in msg
    assert C.diff_sha() == x1_sha and tree_hash(ws) == x1_hash
    # refused at t >= 285
    C2, G2, K2 = lib(ws, t=285)
    good = submit_diff(ws)
    ok, msg = K2.restore({"id": id1, "sha": "0" * 40})
    assert not ok and msg.startswith("RESTORE REFUSED"), msg
    assert submit_diff(ws) == good
    assert not any(n.startswith("_") or not n.endswith(".diff") for n in os.listdir(swe(ws) / "ckpt"))


# -------------------------------------------------------------------------------------------- R72 hygiene matrix
def test_finalize_hygiene_matrix(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    edit(ws, "pkg/core.py", FIX)
    with open(ws / "tests/test_core.py", "a") as f:
        f.write("\n# tampered\n")
    with open(ws / "setup.cfg", "a") as f:
        f.write("[y]\n")
    scratch = ["repro.py", "reproduce_issue.py", "scratch.txt", "debug_out.txt", "tmp_x.py", "temp.json", "try1.py",
               "demo.py", "test_repro.py", "check_test.py", "repro/run.py", "pkg/out.log", "pkg/core.py.orig",
               "pkg/core.py.rej", "pkg/x.bak", "pkg/.x.swp", "docs/notes.log"]
    for p in scratch:
        write(ws, p, "x\n")
    write(ws, "pkg/big.dat", b"\0" * (1024 * 1024 + 10))
    vendored = ["vendored/site-packages/foo/__init__.py", "libs/requests-2.0.dist-info/METADATA",
                "third/pytest_copy/_pytest/x.py", "pkg/_vendor_x/setup.py", "pkg/_vendor_x/mod.py"]
    for p in vendored:
        write(ws, p, "x = 1\n")
    write(ws, "pkg/newmod.py", "def helper():\n    return 1\n")
    write(ws, "pkg/sub/new_sub.py", "def helper2():\n    return 2\n")
    write(ws, "pkg/mod\u00fcl\u00e9.py", "def helper3():\n    return 3\n")      # a unicode path (git quotes it)
    r = finalize(scripts, ws)
    assert r.first.startswith("READY: 4 files changed (+7 -1): "), r.out
    assert r.first.endswith("pkg/core.py pkg/mod\u00fcl\u00e9.py pkg/newmod.py pkg/sub/new_sub.py. Next step: submit the "
                            "patch."), r.out
    assert "reverted test/config edits:" in r.out and "CLEANED: removed" in r.out, r.out
    for p in scratch + vendored + ["pkg/big.dat"]:
        assert not (ws / p).exists(), p
    for d in ("vendored", "libs", "third", "pkg/_vendor_x", "repro"):
        assert not (ws / d).exists(), d
    assert (ws / "pkg/newmod.py").exists() and (ws / "pkg/sub/new_sub.py").exists()
    assert (ws / "pkg/mod\u00fcl\u00e9.py").exists()
    assert (ws / "tests/test_core.py").read_text() == CORE_TESTS and (ws / "setup.cfg").read_text() == "[x]\n"
    st = git(ws, "status", "--porcelain", "--untracked-files=all").stdout.decode().split("\n")
    assert sorted(x for x in st if x) == [" M pkg/core.py", "?? pkg/mod\u00fcl\u00e9.py", "?? pkg/newmod.py",
                                          "?? pkg/sub/new_sub.py"], st
    assert (ws / "docs/index.md").exists()


# ------------------------------------------------------------------------------------------- R73 NOT READY and NOTE
def test_finalize_not_ready_and_notes(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    r = finalize(scripts, ws)
    assert r.first == EMPTY_LINE, r.out
    with open(ws / "tests/test_core.py", "a") as f:
        f.write("\n# only a test edit\n")
    r = finalize(scripts, ws)
    assert r.first == EMPTY_LINE and "reverted test/config edits: tests/test_core.py" in r.out, r.out
    write(ws, "pkg/core.py", CORE_PY + "\n\ndef broken(:\n    pass\n")        # a raw sed-style edit
    r = finalize(scripts, ws)
    assert re.match(r"^NOT READY: SYNTAX ERROR pkg/core\.py:9: SyntaxError: .+\. Fix it with python3 /tmp/swe/edit\.py, "
                    r"then run python3 /tmp/swe/finalize\.py again\.$", r.first), r.out
    assert state(ws)["final_done"] is False
    # a large patch (26 new files, about 300 kB) is READY with an advisory NOTE, never NOT READY
    write(ws, "pkg/core.py", CORE_PY)
    write(ws, "pkg/gen/__init__.py", "")
    for i in range(25):
        write(ws, "pkg/gen/mod_%02d.py" % i, "".join("V%d_%d = %r\n" % (i, j, "v" * 100) for j in range(110)))
    r = finalize(scripts, ws)
    assert r.first.startswith("READY: 26 files changed"), r.out
    note = r.line("NOTE: large patch")
    assert note and re.match(r"NOTE: large patch \(26 files, \d+ kB\); fine if the issue needs it\.", note), r.out
    assert int(re.search(r"(\d+) kB", note).group(1)) >= 290


# ------------------------------------------------------------------------------------------------ R74 restore rules
def test_finalize_restore_rules(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO)
    edit(ws, "pkg/core.py", FIX)
    r = run(scripts, "verify", ws)
    assert r.first == "VERIFY: GREEN", r.out
    good = submit_diff(ws)
    # a strictly better same-repro checkpoint replaces a worse, unevaluated current tree (quick evaluation first)
    write(ws, "pkg/core.py", CORE_PY)
    edit(ws, "pkg/core.py", WORSE)
    r = finalize(scripts, ws, t=200)
    assert re.search(r"^RESTORED: checkpoint #1 \(GREEN, t=100s\) replaced the current tree \(RED, t=200s\)\.$",
                     r.out, re.M), r.out
    assert r.first.startswith("READY: 1 files changed"), r.out
    assert submit_diff(ws) == good
    # ties keep the current tree: a different diff that scores the same stays
    edit(ws, "pkg/core.py", ("s.ljust(width)", "s.ljust(int(width))"))
    tie = submit_diff(ws)
    r = finalize(scripts, ws, t=210)
    assert "RESTORED" not in r.out and submit_diff(ws) == tie, r.out
    # an empty tree with a stored checkpoint is restored (best of any key)
    write(ws, "pkg/core.py", CORE_PY)
    r = finalize(scripts, ws, t=220)
    assert re.search(r"^RESTORED: checkpoint #\d+ \(\w+, t=\d+s\) \(the tree had no source change\)$", r.out, re.M), r.out
    assert r.first.startswith("READY:"), r.out
    assert submit_diff(ws) in (good, tie)
    # at t >= 275 an unevaluated current tree is kept as it is (no quick evaluation, no restore)
    write(ws, "pkg/core.py", CORE_PY)
    edit(ws, "pkg/core.py", ("s.ljust(width - 1)", "s.ljust(width - 333)"))
    worse = submit_diff(ws)
    r = finalize(scripts, ws, t=280)
    assert "RESTORED" not in r.out and submit_diff(ws) == worse, r.out
    sha = hashlib.sha1(worse).hexdigest()
    assert not any(e["sha"] == sha for e in state(ws)["ckpts"])


# ------------------------------------------------------------------------------ R75 round trip and the FINAL banner
def test_finalize_diff_roundtrip_and_final_flag(scripts, tmp_path):
    astral = "# \U0001F600 \U0001D54F é\nGREETING = '\U0001F44B'\n"
    ws = mkrepo(tmp_path, dict(BASIC, **{"pkg/emoji.py": astral}))
    write(ws, "pkg/emoji.py", astral.replace("'\U0001F44B'", "'\U0001F44B\U0001F30D'"))
    r = finalize(scripts, ws, t=120)
    assert r.first.startswith("READY: 1 files changed (+1 -1): pkg/emoji.py"), r.out
    assert "FINAL: the patch was finalized at t=120s" in r.out, r.out
    diff = submit_diff(ws)
    st = state(ws)
    assert st["final_done"] is True and st["final_sha"] == hashlib.sha1(diff).hexdigest() and st["final_t"] == 120.0
    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "-q", str(ws), str(fresh))
    git(fresh, "checkout", "-q", "_swegemma_baseline")
    text = diff.decode("utf-8").encode("utf-8")                        # the harness transmits UTF-8 text
    assert git(fresh, "apply", "--check", "-", stdin=text, check=False).returncode == 0
    s1 = run(scripts, "status", ws, t=130)
    assert "FINAL: the patch was finalized at t=120s" in s1.out, s1.out
    write(ws, "pkg/emoji.py", astral.replace("'\U0001F44B'", "'\U0001F44B!'"))
    s2 = run(scripts, "status", ws, t=140)
    assert "FINAL:" not in s2.out, s2.out
    # bytes that do not survive UTF-8 transmission are caught before submission
    cookie = b"# -*- coding: latin-1 -*-\n# caf\xe9\n"
    ws2 = mkrepo(tmp_path / "b", {"pkg/__init__.py": "", "pkg/latin.py": cookie + b"X = 1\n"})
    write(ws2, "pkg/latin.py", cookie + b"X = 22\n")
    r = finalize(scripts, ws2)
    assert r.first.startswith("NOT READY: patch does not apply cleanly: "), r.out
    assert "non-UTF-8" in r.first and state(ws2)["final_done"] is False


# ---------------------------------------------------------------------------------------------- R76 late guard
def test_late_auto_restore(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO)
    edit(ws, "pkg/core.py", FIX)
    assert run(scripts, "verify", ws).first == "VERIFY: GREEN"
    good = submit_diff(ws)
    write(ws, "pkg/core.py", CORE_PY)                                   # the tree lost its change
    r = run(scripts, "status", ws, t=250)
    assert "RESTORED" not in r.out and submit_diff(ws) == b"", r.out   # below 255: nothing happens
    r = run(scripts, "status", ws, t=260)
    assert r.first == "RESTORED checkpoint #1: the tree had no source change at t=260s.", r.out
    assert submit_diff(ws) == good
    # when the patch was already finalized, the guard stays quiet
    write(ws, "pkg/core.py", CORE_PY)
    st = state(ws)
    st["final_done"], st["final_sha"] = True, hashlib.sha1(b"").hexdigest()
    (swe(ws) / "state.json").write_text(json.dumps(st))
    r = run(scripts, "status", ws, t=265)
    assert "RESTORED" not in r.out and submit_diff(ws) == b"", r.out
    # any helper's output carries the prefix (verify here)
    st["final_done"] = False
    (swe(ws) / "state.json").write_text(json.dumps(st))
    r = run(scripts, "verify", ws, t=266)
    assert r.first.startswith("RESTORED checkpoint #"), r.out
    assert submit_diff(ws) == good


# ------------------------------------------------------- review round 2: a restore never brings back tests or scratch
TEST_EDIT = "\n\ndef test_pad_two():\n    assert pad('ab', 4) == 'ab  '\n"
SCRATCH = "from pkg.core import pad\nprint(repr(pad('ab', 4)))\n"


def _dirty_checkpoint(ws, scripts):
    """The fix plus a test-file edit and a root scratch file, saved as checkpoint #1 by verify --repro-only (which stores
    the raw tree: no hygiene, no scratch cleanup). -> the clean diff (the fix alone) the patch must end up as."""
    edit(ws, "pkg/core.py", FIX)
    clean = submit_diff(ws)
    with open(ws / "tests/test_core.py", "a") as f:
        f.write(TEST_EDIT)
    write(ws, "reproduce_bug.py", SCRATCH)
    r = run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO)
    assert "CHECKPOINT: #1 saved (quick)" in r.out, r.out
    ck = (swe(ws) / "ckpt" / "1.diff").read_bytes()
    assert b"tests/test_core.py" in ck and b"reproduce_bug.py" in ck and b"pkg/core.py" in ck, ck
    return clean


def _status_porcelain(ws):
    return git(ws, "status", "--porcelain", "--untracked-files=all").stdout.decode()


def test_restore_never_brings_back_tests_or_scratch(scripts, tmp_path):
    """Review round 2: hygiene and scratch cleanup ran BEFORE finalize's restore and never after it, and checkpoints
    hold the raw tree, so finalize printed READY for a patch with a test-file edit (the hidden test_patch then fails to
    apply: a 0) and the scratch file it had just deleted. The late guard's auto-restore had the same hole. Both restore
    through _swe_ckpt.restore(), which now tidies the restored tree and reports what it undid."""
    # finalize: a worse current tree loses to the dirty checkpoint #1
    ws = mkrepo(tmp_path / "a", BASIC)
    clean = _dirty_checkpoint(ws, scripts)
    git(ws, "checkout", "_swegemma_baseline", "--", "tests/test_core.py", "pkg/core.py")
    edit(ws, "pkg/core.py", WORSE)
    r = finalize(scripts, ws, t=240)
    assert re.search(r"^RESTORED: checkpoint #1 \(\w+, t=100s\) replaced the current tree \(RED, t=240s\)\.$",
                     r.out, re.M), r.out
    assert r.first == "READY: 1 files changed (+1 -1): pkg/core.py. Next step: submit the patch.", r.out
    after = r.out[r.out.index("RESTORED: checkpoint #1"):]
    assert "reverted test/config edits: tests/test_core.py" in after, r.out
    assert "CLEANED: removed reproduce_bug.py" in after, r.out
    assert submit_diff(ws) == clean
    assert _status_porcelain(ws) == " M pkg/core.py\n", _status_porcelain(ws)
    assert state(ws)["final_sha"] == hashlib.sha1(clean).hexdigest()
    # finalize with an EMPTY tree restores the best checkpoint (any key): the same tidy applies
    ws = mkrepo(tmp_path / "b", BASIC)
    clean = _dirty_checkpoint(ws, scripts)
    git(ws, "checkout", "_swegemma_baseline", "--", "tests/test_core.py", "pkg/core.py")
    r = finalize(scripts, ws, t=200)
    assert re.search(r"^RESTORED: checkpoint #1 \(\w+, t=100s\) \(the tree had no source change\)$", r.out, re.M), r.out
    assert r.first.startswith("READY: 1 files changed (+1 -1): pkg/core.py."), r.out
    assert "reverted test/config edits: tests/test_core.py" in r.out, r.out
    assert submit_diff(ws) == clean and _status_porcelain(ws) == " M pkg/core.py\n"
    # the late guard in any helper (t >= 255, empty tree, not final): same checkpoint, same tidy, one prefix line
    ws = mkrepo(tmp_path / "c", BASIC)
    clean = _dirty_checkpoint(ws, scripts)
    git(ws, "checkout", "_swegemma_baseline", "--", "tests/test_core.py", "pkg/core.py")
    os.unlink(ws / "reproduce_bug.py")
    r = run(scripts, "status", ws, t=260)
    assert r.first.startswith("RESTORED checkpoint #1: the tree had no source change at t=260s."), r.out
    assert "reverted test/config edits: tests/test_core.py" in r.first and "removed reproduce_bug.py" in r.first, r.out
    assert submit_diff(ws) == clean and _status_porcelain(ws) == " M pkg/core.py\n"


def test_restore_tidy_unit(scripts, tmp_path, lib):
    """_swe_ckpt.restore() checks the tree against the checkpoint sha BEFORE tidying (the transaction stays exact), then
    reverts protected paths and deletes scratch; a clean checkpoint gives the old one-line message; tidy() on a clean
    tree does nothing and costs little."""
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    edit(ws, "pkg/core.py", FIX)
    clean = submit_diff(ws)
    id_clean = K.save(C.diff_bytes(), [1, 1, 1, 1, 1], "r", "AMBER", True, rkey="r")
    with open(ws / "setup.cfg", "a") as f:
        f.write("[y]\n")
    write(ws, "scratch_check.py", SCRATCH)
    write(ws, "pkg/new_mod.py", "X = 1\n")                              # a new module inside a package: kept
    dirty = C.diff_bytes()
    id_dirty = K.save(dirty, [1, 1, 1, 1, 1], "r", "AMBER", True, rkey="r")
    git(ws, "checkout", "_swegemma_baseline", "--", "setup.cfg", "pkg/core.py")
    for p in ("scratch_check.py", "pkg/new_mod.py"):
        os.unlink(ws / p)
    ok, msg = K.restore(K.entry_for_sha(hashlib.sha1(dirty).hexdigest()))
    lines = msg.split("\n")
    assert ok and lines[0] == "restored checkpoint #%d" % id_dirty, msg
    assert lines[1:] == ["reverted test/config edits: setup.cfg" + HYGIENE_WHY, "CLEANED: removed scratch_check.py"], msg
    assert _status_porcelain(ws) == " M pkg/core.py\n?? pkg/new_mod.py\n", _status_porcelain(ws)
    ok, msg = K.restore(K.entry_for_sha(hashlib.sha1(clean).hexdigest()))
    assert ok and msg == "restored checkpoint #%d" % id_clean, msg
    assert submit_diff(ws) == clean
    t0 = time.monotonic()
    assert K.tidy() == []
    assert time.monotonic() - t0 < 1.0


# ------------------------------------------------------------------------------------------------ R77 timing
def test_finalize_timing(scripts, tmp_path):
    ws = mkrepo(tmp_path, BASIC)
    run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO)
    edit(ws, "pkg/core.py", FIX)
    run(scripts, "verify", ws)                                           # the current tree now has a score
    r = finalize(scripts, ws)
    assert r.first.startswith("READY:") and r.secs <= 1.5, (r.secs, r.out)
    edit(ws, "pkg/core.py", ("s.ljust(width)", "s.ljust(width + 0)"))  # unevaluated: quick evaluation runs
    r = finalize(scripts, ws)
    assert r.first.startswith("READY:") and r.secs <= 15, (r.secs, r.out)
    assert state(ws)["ckpts"][-1]["quick"] is True


# ------------------------------------------------------------------ review round 1: root-level scratch and shadows
def test_root_scratch_is_not_a_source_change(scripts, tmp_path):
    """Review round 1: an untracked root-level check_fix.py (no scratch prefix) counted as a new module, so a tree whose
    real fix had been reverted looked changed: verify said AMBER/ready, finalize shipped check_fix.py alone and never
    restored the real-fix checkpoint, and the late guard could not fire. Root .py files are now scratch unless the
    repository already has root-level modules or a changed tracked file imports them."""
    ws = mkrepo(tmp_path, BASIC)
    run(scripts, "verify", ws, ["--repro-only"], stdin=REPRO)
    edit(ws, "pkg/core.py", FIX)
    assert run(scripts, "verify", ws).first == "VERIFY: GREEN"
    good = submit_diff(ws)
    write(ws, "pkg/core.py", CORE_PY)                                   # the real fix is gone
    write(ws, "check_fix.py", "from pkg.core import pad\nprint(pad('ab', 4))\n")
    r = run(scripts, "verify", ws, t=150)
    assert r.first == "VERIFY: NO SOURCE CHANGE - make the plan's change with python3 /tmp/swe/edit.py first.", r.out
    assert "NEXT: ready" not in r.out and len(state(ws)["ckpts"]) == 1, r.out
    r = run(scripts, "status", ws, t=260)                               # the late guard sees an empty tree
    assert r.first.startswith("RESTORED checkpoint #1: the tree had no source change"), r.out
    assert (ws / "pkg/core.py").read_text() == CORE_PY.replace(*FIX)
    assert not (ws / "check_fix.py").exists()                           # a restore resets untracked files too
    write(ws, "pkg/core.py", CORE_PY)
    write(ws, "check_fix.py", "from pkg.core import pad\nprint(pad('ab', 4))\n")
    r = finalize(scripts, ws, t=200)
    assert "CLEANED: removed check_fix.py" in r.out, r.out
    assert re.search(r"^RESTORED: checkpoint #1 \(GREEN, t=100s\) \(the tree had no source change\)$", r.out, re.M), r.out
    assert r.first.startswith("READY: 1 files changed (+1 -1): pkg/core.py."), r.out
    assert submit_diff(ws) == good and not (ws / "check_fix.py").exists()
    # with no checkpoint at all, scratch alone is EMPTY (never READY with check_fix.py as the patch)
    ws2 = mkrepo(tmp_path / "b", BASIC)
    write(ws2, "verify_box_order.py", "print(1)\n")
    write(ws2, "simple_repro.py", "print(2)\n")
    r = finalize(scripts, ws2)
    assert r.first == EMPTY_LINE, r.out
    assert not (ws2 / "verify_box_order.py").exists() and not (ws2 / "simple_repro.py").exists()


def test_root_shadow_modules_are_removed(scripts, tmp_path):
    """Review round 1 (fastapi_14448 shape): root py.py and typing_extensions.py shipped in the patch; under the
    grader's PYTHONPATH=<workspace> they shadow the installed modules and every test fails to import. Untracked root
    files and dirs whose name resolves outside the workspace (installed or stdlib) are deleted; a genuinely new module
    stays. The installed side is a site dir on PYTHONPATH, so the test does not depend on the venv's packages."""
    site = tmp_path / "site"
    write(site, "typing_extensions.py", "X = 1\n")
    write(site, "py.py", "Y = 1\n")
    write(site, "fakedep_pkg/__init__.py", "Z = 1\n")
    ws = mkrepo(tmp_path, BASIC)
    edit(ws, "pkg/core.py", FIX)
    for p in ("typing_extensions.py", "py.py", "json.py", "fakedep_pkg/__init__.py", "fakedep_pkg/core.py",
              "verify_box_order.py", "_pytest/python.py"):
        write(ws, p, "BROKEN = True\n")
    write(ws, "pkg/newmod.py", "def helper():\n    return 1\n")
    env = env_for(ws, 100)
    env["PYTHONPATH"] = os.pathsep.join([str(ws), str(site)])
    r = run(scripts, "finalize", ws, env=env)
    assert r.first.startswith("READY: 2 files changed") and r.first.endswith(
        "pkg/core.py pkg/newmod.py. Next step: submit the patch."), r.out
    for p in ("typing_extensions.py", "py.py", "json.py", "fakedep_pkg", "verify_box_order.py", "_pytest"):
        assert not (ws / p).exists(), (p, r.out)
    assert (ws / "pkg/newmod.py").exists()
    # the patch as the grader applies it imports the installed copy again
    code = "import typing_extensions, py; print(typing_extensions.__file__, py.__file__)"
    out = subprocess.run([PY, "-c", code], cwd=str(ws), env=env, capture_output=True, text=True).stdout
    assert str(site) in out and str(ws) not in out.replace(str(site), ""), out


def test_root_module_rules(scripts, tmp_path, lib):
    """C.root_module_kept: a root .py is a module when the baseline has root-level modules (other than setup.py,
    conftest.py, noxfile.py and similar scripts) or a changed tracked file imports it; never a stdlib or scratch name,
    and never the name of a tracked root entry."""
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    write(ws, "helpers2.py", "def h():\n    return 1\n")
    assert C.changes()["source"] == [] and "helpers2.py" in C.changes()["untracked"]
    write(ws, "pkg/core.py", CORE_PY + "\nfrom helpers2 import h  # noqa\n")
    assert C.changes()["source"] == ["helpers2.py", "pkg/core.py"]
    for name, tracked, want in (("helpers2.py", ["pkg/core.py"], True), ("helpers2.py", [], False),
                                ("json.py", ["pkg/core.py"], False), ("check_fix.py", ["pkg/core.py"], False),
                                ("repro_x.py", ["pkg/core.py"], False), ("pkg.py", ["pkg/core.py"], False),
                                ("pkg/sub/new.py", [], True), ("notes.txt", [], False)):
        C._reset()
        assert C.root_module_kept(name, tracked) is want, (name, tracked)
    for line, want in (("import helpers2", True), ("import os, helpers2 as h", True), ("from helpers2.x import y", True),
                       ("    from helpers2 import h", True), ("import helpers22", False), ("# helpers2", False)):
        write(ws, "pkg/core.py", CORE_PY + "\n" + line + "\n")
        C._reset()
        assert C.imports_module("helpers2", ["pkg/core.py"]) is want, line
    # a repository that already has root-level modules keeps new root modules (setup.py alone does not count)
    ws2 = mkrepo(tmp_path / "b", {"setup.py": "", "noxfile.py": "", "pkg/__init__.py": ""})
    C, G, K = lib(ws2)
    assert C.root_module_kept("extra.py", []) is False
    ws3 = mkrepo(tmp_path / "c", {"mylib.py": "A = 1\n", "setup.py": ""})
    C, G, K = lib(ws3)
    assert C.root_module_kept("extra.py", []) is True and C.root_module_kept("mylib2.py", []) is True
    write(ws3, "extra.py", "B = 2\n")
    assert C.changes()["source"] == ["extra.py"]


# ------------------------------------------------------------ review round 1: incomplete evaluations never restore
OPT_FILES = {"pkg/__init__.py": "", "pkg/mod.py": "def f():\n    return 1\n",
             "pkg/opt.py": "import missing_optional_dep_zz\n", "pkg/zz.py": "Z = 1\n"}
OPT_REPRO = "from pkg.mod import f\n# CLAIM 1: f gives 2\nassert f() == 2, f()\n"


def test_preexisting_import_failure_is_compared_with_the_original(scripts, tmp_path):
    """Review round 1: with the original claims cached and no tests, evaluate() never built the base tree, so an
    import that already failed at baseline read as RED: --repro-only said 'claim 1 UNKNOWN: not run (import error)'
    and finalize restored an older checkpoint over later edits. import_check now builds the base on demand."""
    ws = mkrepo(tmp_path, OPT_FILES)
    assert run(scripts, "verify", ws, ["--repro-only"], stdin=OPT_REPRO).first.startswith("REPRO: fails on original")
    write(ws, "pkg/mod.py", "def f():\n    return 2\n")
    write(ws, "pkg/opt.py", "import missing_optional_dep_zz  # touched\n")
    r = run(scripts, "verify", ws, ["--repro-only"], stdin=None, t=110)
    assert r.first == "REPRO: 1/1 claims fixed" and "IMPORT: RED" not in r.out and "UNKNOWN" not in r.out, r.out
    assert not (swe(ws) / "base").exists() or state(ws)["base"]["ok"]
    r = run(scripts, "verify", ws, t=120)
    assert r.first == "VERIFY: AMBER - import fails on original too" and r.line("REPRO:") == "REPRO: 1/1 claims fixed", r.out
    assert r.line("IMPORT:").startswith("IMPORT: pkg.opt fails on original too"), r.out
    write(ws, "pkg/mod.py", "def f():\n    return 2\n\n\ndef g():\n    return 3\n")   # a later, unscored edit
    r = finalize(scripts, ws, t=200)
    assert "RESTORED" not in r.out and r.first.startswith("READY:"), r.out
    assert "def g():" in (ws / "pkg/mod.py").read_text()
    cur = state(ws)["ckpts"][-1]
    assert cur["incomplete"] is False and cur["imp_def"] is True and cur["classes"] == {"1": "FIXED"}, cur
    # a real failure in a module imported after the pre-existing one is still RED (it was masked before)
    write(ws, "pkg/zz.py", "Z = 1\nundefined_name_zz\n")
    r = run(scripts, "verify", ws, t=130)
    assert r.first == "VERIFY: RED - import error", r.out
    assert "IMPORT: RED pkg.zz: NameError: name 'undefined_name_zz' is not defined (pkg/zz.py:2)" in r.out, r.out


def slow_claims(flag):
    """6 claims whose shared prelude sleeps 4.5 s while `flag` exists: 3 batches at MAX_PAR 2 = 13.5 s, more than
    finalize's 12 s quick evaluation (FINALIZE_QUICK) but within verify's 25 s (CLAIMS_TOTAL)."""
    return ("import os, time\nfrom pkg.core import pad\ntime.sleep(4.5 if os.path.exists(%r) else 0)\n" % str(flag) +
            "".join("# CLAIM %d: pads\nassert pad('ab', 4) == 'ab  ', repr(pad('ab', 4))\n" % i for i in range(1, 7)))


def test_finalize_never_restores_over_an_incomplete_evaluation(scripts, tmp_path):
    """Review round 1 (scratch repo r3/repo3): finalize's 12 s quick evaluation left slow claims UNKNOWN, scored them
    as not fixed, and restored an older fully verified checkpoint over the fixer's later edits. UNKNOWN is now neutral:
    an incomplete current score loses only to definite evidence (a claim that STILL FAILS, or a definite import
    failure). The claims are slow only while a flag file exists, so the repro and the verify stay fast."""
    ws = mkrepo(tmp_path, BASIC)
    flag = tmp_path / "slow.flag"
    assert run(scripts, "verify", ws, ["--repro-only"], stdin=slow_claims(flag)).first.startswith(
        "REPRO: fails on original")
    edit(ws, "pkg/core.py", FIX)
    r = run(scripts, "verify", ws, t=120)
    assert r.line("REPRO:") == "REPRO: 6/6 claims fixed", r.out
    with open(ws / "pkg/core.py", "a") as f:
        f.write("\n\ndef g():\n    return 3\n")                     # a sibling fix / repair, not scored yet
    flag.write_text("slow")
    r = finalize(scripts, ws, t=200)                                  # 12 s for 13.5 s of claims
    assert "RESTORED" not in r.out and r.first.startswith("READY:"), r.out
    assert "def g():" in (ws / "pkg/core.py").read_text()
    cur = state(ws)["ckpts"][-1]
    assert cur["quick"] is True and cur["incomplete"] is True and "UNKNOWN" in cur["classes"].values(), cur
    # definite evidence still restores: the tree breaks the fix and every claim finishes and STILL FAILS
    flag.unlink()
    edit(ws, "pkg/core.py", ("s.ljust(width)", "s.ljust(width - 7)"))
    r = finalize(scripts, ws, t=210)
    assert re.search(r"^RESTORED: checkpoint #\d+ \(\w+, t=\d+s\) replaced the current tree", r.out, re.M), r.out
    assert (ws / "pkg/core.py").read_text() == CORE_PY.replace(*FIX)     # #1: the complete 6/6 evaluation wins


def test_best_against_incomplete_rules(scripts, tmp_path, lib):
    """Unit: K.best_against with the stored evidence (classes, imp_def, incomplete)."""
    ws = mkrepo(tmp_path, BASIC)
    C, G, K = lib(ws)
    write(ws, "pkg/a.py", "A = 1\n")
    good = K.save(submit_diff(ws), [1, 1, 1, 1, 2], "r", "GREEN", True, rkey="r",
                  meta={"classes": {"1": "FIXED", "2": "FIXED"}, "imp_def": True, "incomplete": False})
    assert K.entries()[0]["classes"] == {"1": "FIXED", "2": "FIXED"} and K.entries()[0]["incomplete"] is False

    def cur(score, classes, imp_def=True, incomplete=True):
        return {"sha": "x", "score": score, "quick": True, "key": "r", "rkey": "r", "classes": classes,
                "imp_def": imp_def, "incomplete": incomplete}
    assert K.best_against(cur([1, 1, 1, 1, 1], {"1": "FIXED", "2": "UNKNOWN"})) is None
    assert K.best_against(cur([1, 1, 1, 1, 0], {"1": "UNKNOWN", "2": "UNKNOWN"})) is None
    assert K.best_against(cur([1, 1, 1, 1, 1], {"1": "FIXED", "2": "STILL FAILS"}))["id"] == good
    assert K.best_against(cur([1, 1, 1, 1, 0], {"1": "STILL HANGS", "2": "UNKNOWN"}))["id"] == good
    assert K.best_against(cur([1, 0, 1, 1, 0], {"1": "UNKNOWN", "2": "UNKNOWN"}, imp_def=True))["id"] == good
    assert K.best_against(cur([1, 0, 1, 1, 0], {"1": "UNKNOWN", "2": "UNKNOWN"}, imp_def=False)) is None
    assert K.best_against(cur([1, 1, 1, 1, 1], {"1": "FIXED", "2": "STILL FAILS"}, incomplete=False))["id"] == good
    assert K.best_against(cur([1, 1, 1, 1, 1], {}, incomplete=False))["id"] == good    # complete: plain ranking
    # evidence(): what makes a score incomplete
    ev = G.evidence({"ok": True}, {"classes": {1: "FIXED", 2: "UNKNOWN"}})
    assert ev == {"classes": {"1": "FIXED", "2": "UNKNOWN"}, "imp_def": True, "incomplete": True}
    assert G.evidence({"ok": None}, {"classes": {}})["incomplete"] is True
    assert G.evidence({"ok": False, "syntax": True}, {"classes": {}}) == {"classes": {}, "imp_def": True,
                                                                          "incomplete": False}
    assert G.evidence({"ok": False, "base_checked": False}, {"classes": {}})["incomplete"] is True
    assert G.evidence({"ok": True}, {"classes": {1: "FIXED", 2: "BROKEN", 3: "INVALID"}})["incomplete"] is False
