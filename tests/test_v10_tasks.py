"""R97-R107: per-task offline tests of the v10 helpers on the real Kaggle-valid tasks (docs/v10/SPEC.md section 8).

Tiers: CI (this Mac, no network) and NIGHTLY (G4_NIGHTLY=1). Nothing touches a GPU, Kaggle or a pod.
- Tasks without a local snapshot skip with the exact (free, network, Carson's go) fetch command; nothing is fetched.
- Repo tests run in the parity venvs of scripts/build_kpar.sh (outside the repo); a missing venv skips with the build
  command.
- Per-task results are computed once per session per kind (tests/v10_support/tasks.py:results, ThreadPoolExecutor with
  G4_J workers, default 4) and written to eval/offline/v10_<kind>.json; parametrised tests read them and aggregate tests
  assert the SPEC's bars, scaled from the 40 local tasks to however many are local (need()).
- Helper-dependent tests skip until the bundle's helper exists (other components build them in parallel).
"""
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
from v10_support import tasks as T  # noqa: E402

from v10_support.repo import no_orphans  # noqa: F401,E402  (R120: autouse orphan guard)

ROOT = T.ROOT
nightly = pytest.mark.skipif(not T.NIGHTLY, reason="nightly tier: set G4_NIGHTLY=1")
ALL = pytest.mark.parametrize("tid", T.TASK_IDS)


def _xfail_known(ids, reason, strict=False):
    return [pytest.param(t, marks=pytest.mark.xfail(reason=reason, strict=strict)) if t in ids else t
            for t in T.TASK_IDS]


def _first_local(repo="rich"):
    for tid in T.TASK_IDS:
        if T.has_snapshot(tid) and T.repo_key(tid) == repo:
            return tid
    pytest.skip(f"no local {repo} snapshot")


# =============================================================================================== unit: tasks.py
PATCH_EDGE = (
    "diff --git a/pkg/new.py b/pkg/new.py\n"
    "new file mode 100644\n"
    "index 0000000..1111111\n"
    "--- /dev/null\n"
    "+++ b/pkg/new.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+x = 1\n"
    "+y = 2\n"
    "--- a/pkg/mod.py\n"
    "+++ b/pkg/mod.py\n"
    "@@ -1,4 +1,4 @@ def f():\n"
    " a = 1\n"
    "\n"                                                 # blank context line whose leading space was stripped
    "--- removed line that looks like a header\n"
    "+-- added line that looks like a header\n"
    " b = '\x0cform feed '\n"
    "@@ -10,2 +10,2 @@\n"
    " c = 1\r\n"
    "-d = 2\n"
    "\\ No newline at end of file\n"
    "+d = 3\n"
    "\\ No newline at end of file\n"
    "--- a/pkg/gone.py\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    "-z = 0\n"
    "--- a/pkg/also_new.py\n"
    "+++ b/pkg/also_new.py\n"
    "@@ -0,0 +1 @@\n"
    "+w = 1\n"
)


def test_parse_patch_edge_cases():
    fps = T.parse_patch(PATCH_EDGE)
    assert [f.path for f in fps] == ["pkg/new.py", "pkg/mod.py", "pkg/gone.py", "pkg/also_new.py"]
    new, mod, gone, also = fps
    assert new.new_file and not mod.new_file and gone.deleted and also.new_file   # @@ -0,0 with "--- a/" (gold style)
    assert new.hunks[0].new_lines == ["x = 1\n", "y = 2\n"] and new.hunks[0].old_lines == []
    h1, h2 = mod.hunks
    assert (h1.old_start, h1.old_len, h1.new_start, h1.new_len) == (1, 4, 1, 4)
    assert h1.old_lines == ["a = 1\n", "\n", "-- removed line that looks like a header\n", "b = '\x0cform feed '\n"]
    assert h1.new_lines[2] == "-- added line that looks like a header\n"
    assert h2.old_lines == ["c = 1\r\n", "d = 2"] and h2.new_lines == ["c = 1\r\n", "d = 3"]
    cut = T.parse_patch("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b")          # stored without its final newline
    assert cut[0].hunks[0].new_lines == ["b\n"] and T.render_patch(cut).endswith("+b")
    assert all(h.counts_ok for f in fps for h in f.hunks)
    assert T.render_patch(fps) == PATCH_EDGE                                          # lossless
    assert T.render_patch(T.parse_patch("")) == "" and T.parse_patch("") == []
    junk = "not a patch\nat all\n"
    assert T.render_patch(T.parse_patch(junk)) == junk


def test_split_lines_only_on_newline():
    assert T.split_lines("a\x0cb\x1cc d\r\ne\n") == ["a\x0cb\x1cc d\r\n", "e\n"]
    assert T.split_lines("no newline") == ["no newline"] and T.split_lines("") == []


def test_parse_patch_all_74_roundtrip_fast():
    t0 = time.monotonic()
    for tid in T.TASK_IDS:
        t = T.load_task(tid)
        for kind in ("patch", "test_patch"):
            assert T.render_patch(T.parse_patch(t[kind])) == t[kind], (tid, kind)
    assert time.monotonic() - t0 < 1.0                                                # measured 0.06 s


def test_added_tests_and_qualnames():
    tp = ("--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,3 +1,9 @@ class TestA:\n"
          " class TestA:\n     def test_old(self):\n         pass\n"
          "+    def test_new(self):\n+        pass\n+\n+async def test_async():\n+    pass\n"
          "+\n def test_context_after_blank():\n")
    tp = tp.replace("@@ -1,3 +1,9 @@", "@@ -1,4 +1,10 @@")
    assert T.render_patch(T.parse_patch(tp)) == tp
    assert T.added_tests(tp) == [("tests/test_x.py", "test_new", 4), ("tests/test_x.py", "test_async", 7)]
    src = ("class TestA:\n    def test_old(self): pass\n    def test_new(self): pass\n"
           "    class Inner:\n        def test_deep(self): pass\nasync def test_async(): pass\n")
    assert T._qualnames(src) == {2: "TestA::test_old", 3: "TestA::test_new", 5: "TestA::Inner::test_deep",
                                 6: "test_async"}


def test_tamper_line_rules():
    def tp(body, hdr="@@ -10,5 +10,6 @@"):
        return f"--- a/tests/test_a.py\n+++ b/tests/test_a.py\n{hdr}\n{body}"
    # first change is an addition: the context line right before it (patch --fuzz 2 cannot drop it)
    assert T.tamper_line(tp(" a\n b\n c\n+d\n e\n f\n", "@@ -10,5 +10,6 @@"), "tests/test_a.py") == 12
    # first change is a removal: the removed line itself
    assert T.tamper_line(tp(" a\n-b\n+B\n c\n", "@@ -10,3 +10,3 @@"), "tests/test_a.py") == 11
    # no leading context: the first context line after the change
    assert T.tamper_line(tp("+x\n a\n b\n", "@@ -10,2 +10,3 @@"), "tests/test_a.py") == 10
    assert T.tamper_line(tp("+x\n", "@@ -10,0 +11,1 @@"), "tests/test_a.py") is None
    assert T.tamper_line(tp(" a\n+d\n", "@@ -1,1 +1,2 @@"), "tests/other.py") is None


def test_tamper_test_hunk_edits_inside_first_hunk(tmp_path):
    (tmp_path / "tests").mkdir()
    src = b"def f():\r\n    s = 1 + \\\r\n        2\r\n    return s\r\n"
    (tmp_path / "tests/test_a.py").write_bytes(src)
    tp = ("--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1,4 +1,5 @@\n def f():\n     s = 1 + \\\n"
          "+    # new\n         2\n     return s\n")
    assert T.tamper_line(tp, "tests/test_a.py") == 2                                   # the backslash line
    assert T.tamper_test_hunk(tmp_path, tp) == "tests/test_a.py"
    data = (tmp_path / "tests/test_a.py").read_bytes()
    compile(data, "test_a.py", "exec")                  # a comment after "\\" would not compile: a line is inserted
    assert data == b"def f():\r\n    # agent edit\r\n    s = 1 + \\\r\n        2\r\n    return s\r\n"
    (tmp_path / "tests/test_a.py").write_bytes(src.replace(b" + \\\r\n        2", b" + 2"))
    tp2 = "--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1,2 +1,3 @@\n def f():\n     s = 1 + 2\n+    x = 3\n"
    assert T.tamper_test_hunk(tmp_path, tp2) == "tests/test_a.py"
    assert (tmp_path / "tests/test_a.py").read_bytes().startswith(b"def f():\r\n    s = 1 + 2  # agent edit\r\n")
    new_only = "--- a/tests/test_new.py\n+++ b/tests/test_new.py\n@@ -0,0 +1 @@\n+def test_n(): pass\n"
    assert T.tamper_test_hunk(tmp_path, new_only) is None


def _mini_repo(root, fixed):
    (root / "tests").mkdir(parents=True)
    (root / "pkg.py").write_text(f"def f(x):\n    return x + {1 if fixed else 0}\n")
    (root / "tests" / "test_p.py").write_text(
        "import pytest\nfrom pkg import f\n"
        "def test_ok():\n    assert f(0) >= 0\n"
        "class TestC:\n    def test_fixed(self):\n        assert f(1) == 2\n"
        "@pytest.mark.parametrize('x', [0, 1])\ndef test_param(x):\n    assert f(x) == x + 1\n"
        "def test_always_bad():\n    assert False\n"
        "def test_hang():\n    while " + ("False" if fixed else "True") + ":\n        pass\n")


def test_hidden_outcomes_and_file_f2p(tmp_path):
    """The helper-independent F2P measurement behind R103: JUnit cases map to nodes (classes, parametrised cases),
    a missing node is 'missing', a hang is 'hang' within the caps, and file_f2p finds exactly the fixed functions."""
    T.kpar_python("rich")
    orig, gold = tmp_path / "o", tmp_path / "g"
    _mini_repo(orig, False)
    _mini_repo(gold, True)
    f = "tests/test_p.py"
    nodes = [f"{f}::test_ok", f"{f}::TestC::test_fixed", f"{f}::test_param", f"{f}::test_always_bad", f"{f}::test_nope"]
    env = T.sandbox_env(orig, "rich", None)
    assert T.hidden_outcomes(orig, nodes, env) == dict(zip(nodes, ["pass", "fail", "fail", "fail", "missing"]))
    genv = T.sandbox_env(gold, "rich", None)
    assert T.hidden_outcomes(gold, nodes[:4], genv) == dict(zip(nodes[:4], ["pass", "pass", "pass", "fail"]))
    t0 = time.monotonic()
    assert T.hidden_outcomes(orig, [f"{f}::test_hang", f"{f}::test_ok"], env, timeout=2, node_cap=1.5) == \
        {f"{f}::test_hang": "hang", f"{f}::test_ok": "pass"}
    assert time.monotonic() - t0 < 10                                                 # 2 s batch + 1.5 s + one run
    t0 = time.monotonic()
    got = T.file_f2p(orig, gold, [f], lambda tree: T.sandbox_env(tree, "rich", None), timeout=2, node_cap=1.5)
    assert sorted(got) == [f"{f}::TestC::test_fixed", f"{f}::test_hang", f"{f}::test_param"]
    assert time.monotonic() - t0 < 15
    assert T._junit_match(("test_p", "TestC", "test_fixed"), "tests.test_p.TestC", "test_fixed")
    assert not T._junit_match(("test_p", "test_fixed"), "test_p.TestC", "test_fixed")


def test_fetch_cmd_is_exact():
    missing = next(t for t in T.TASK_IDS if not T.has_snapshot(t)) if not all(map(T.has_snapshot, T.TASK_IDS)) \
        else "fastapi_5077"
    assert T.fetch_cmd(missing) == (f"cd {ROOT} && source /Users/carson/Projects/kaggriculture/.venv/bin/activate "
                                    f"&& python scripts/fetch_data.py snapshots/{missing}.tgz")


def test_missing_snapshot_and_venv_skip_with_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "SNAP_DIR", tmp_path)
    with pytest.raises(pytest.skip.Exception, match=r"fetch_data\.py snapshots/rich_3278\.tgz"):
        T.require_snapshot("rich_3278")
    monkeypatch.setattr(T, "KPAR", tmp_path / "kpar")
    with pytest.raises(pytest.skip.Exception, match=r"build_kpar\.sh rich"):
        T.kpar_python("rich_3278")
    with pytest.raises(pytest.skip.Exception, match=r"build_kpar\.sh fastapi.*Carson"):
        T.kpar_python("fastapi_5077")
    assert T.repo_key("psf/requests") == "requests" and T.repo_key("requests_6644") == "requests"


def test_sandbox_env_contract(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    env = T.sandbox_env(ws, "rich_3278")
    tmp = f"{ws}_tmp"
    assert env["HOME"] == env["TMPDIR"] == env["TEST_TMPDIR"] == tmp and Path(tmp).is_dir()
    assert env["SWE_DIR"] == f"{tmp}/swe" and env["PYTHONPATH"] == str(ws) and env["SWE_DUAL"] == "0"
    assert env["PATH"].startswith(str(T.KPAR / "rich" / "bin") + ":")
    assert env["PYTHONNOUSERSITE"] == env["PYTHONDONTWRITEBYTECODE"] == "1" and env["LANG"] == "C.UTF-8"
    assert env["SWE_DOCKER_TMP_FOR_TESTS"].startswith(tmp)                            # the host /tmp is never used
    assert "SWE_FAKE_CLOCK" not in T.sandbox_env(ws, "rich_3278", fake_clock=None)


def test_local_sandbox_maps_only_workspace(tmp_path):
    sb = T.LocalSandbox(tmp_path)
    r = sb.exec("x", "cd /workspace && pwd && echo /workspaces /x/workspace")
    assert r.exit_code == 0
    lines = r.stdout.split()
    assert Path(lines[0]).resolve() == tmp_path.resolve() and lines[1:] == ["/workspaces", "/x/workspace"]


def test_run_kills_the_whole_group(tmp_path):
    marker = tmp_path / "m"
    t0 = time.monotonic()
    r = T.run(f"sleep 37 & bash -c 'sleep 38; touch {marker}' & sleep 39", timeout=1)
    assert r.timed_out and r.rc is None and time.monotonic() - t0 < 4
    time.sleep(0.3)
    from v10_support.repo import list_processes     # /proc on Linux (python:3.12-slim has no ps), ps elsewhere
    ps = "\n".join(cmd for _pid, cmd in list_processes())
    assert not re.search(r"^sleep 3[789]$", ps, re.M) and not marker.exists()
    ok = T.run(["bash", "-c", "echo out; echo err >&2; exit 3"], timeout=10)
    assert (ok.rc, ok.out, ok.err, ok.timed_out) == (3, "out\n", "err\n", False)


def test_serial_retry_and_busy_guard(monkeypatch):
    out = {"a": {"id": "a", "x": 1}, "b": {"id": "b", "x": 5}, "c": {"id": "c", "skip": "s"},
           "d": {"id": "d", "error": "tb"}}
    calls = []

    def fn(tid):
        calls.append(tid)
        return {"id": tid, "x": 0}
    T._retry_serially(out, fn, lambda tid, r: r["x"] > 2)
    assert calls == ["b"] and out["a"] == {"id": "a", "x": 1} and "skip" in out["c"] and "error" in out["d"]
    assert out["b"] == {"id": "b", "x": 0, "retried_serially": True, "parallel": {"x": 5}}
    monkeypatch.setitem(T._META, "zz", {"load_start": 27.2, "ncpu": 10})
    assert "27.2" in T.busy_machine("zz")
    monkeypatch.setitem(T._META, "zz", {"load_start": 3.0, "ncpu": 10})
    assert T.busy_machine("zz") is None and T.busy_machine("never-ran") is None


def test_need_scaling():
    assert T.need(21, 40, 40) == 21 and T.need(34, 40, 40) == 34 and T.need(25, 39, 39) == 25
    assert T.need(21, 40, 74) == 39 and T.need(36, 39, 40) == 37 and T.need(5, 40, 0) == 0


# ============================================================================================ build_kpar.sh
def _kpar_script(args, tmp_path, **env):
    e = dict(os.environ, G4_KPAR=str(tmp_path / "kpar"), **env)
    return subprocess.run(["bash", str(T.BUILD_KPAR), *args], capture_output=True, text=True, env=e, timeout=300)


def test_build_kpar_script_contract(tmp_path):
    assert subprocess.run(["bash", "-n", str(T.BUILD_KPAR)]).returncode == 0
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", str(T.BUILD_KPAR)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
    r = _kpar_script(["bogus"], tmp_path)
    assert r.returncode == 2 and "unknown target" in r.stderr
    # regression (Linux gate, 2026-09-28): on a box without uv a bad target was reported as "uv not found"
    r = _kpar_script(["rich", "bogus"], tmp_path, PATH="/usr/bin:/bin")
    assert r.returncode == 2 and "unknown target 'bogus'" in r.stderr and not (tmp_path / "kpar").exists(), r.stderr
    text = T.BUILD_KPAR.read_text()
    assert 'KPAR="${G4_KPAR:-$HOME/.cache/g4/kpar}"' in text and not re.search(r'ROOT\W*/\.kpar', text)
    assert "--offline" in text
    assert "dirty-equals" not in text.split("FASTAPI_PINS=")[1].split(")")[0]


@pytest.mark.skipif(not shutil.which("uv"), reason="uv not installed")
def test_build_kpar_offline_rich_and_fastapi_refusal(tmp_path):
    t0 = time.monotonic()
    r = _kpar_script(["rich"], tmp_path)
    assert r.returncode == 0, r.stderr[-800:]
    d = tmp_path / "kpar" / "rich"
    assert (d / ".g4_kpar_ok").read_text().split() == [
        "pytest==8.4.2", "Pygments==2.20.0", "markdown-it-py==4.0.0", "mdurl==0.1.2", "typing_extensions==4.15.0",
        "attrs==26.1.0"]
    assert time.monotonic() - t0 < 60                                                  # measured 1.4 s offline
    r = _kpar_script(["fastapi"], tmp_path, G4_KPAR_ONLINE="0")                         # offline only: must refuse
    assert r.returncode == 2 and "G4_KPAR_ONLINE=1" in r.stderr and "Carson's call" in r.stderr
    assert not (tmp_path / "kpar" / "fastapi" / ".g4_kpar_ok").exists()


# ================================================================================================ R107
def test_kpar_matches_freeze():
    """R107: every built parity venv pins the Kaggle freeze versions; none has dirty-equals or inline-snapshot."""
    freeze = T.freeze_versions()
    T.kpar_python("rich")                                                              # skip with the build command
    checked = []
    for repo in ("rich", "requests", "fastapi"):
        if not T.kpar_ok(repo):
            continue
        have = T.kpar_versions(repo)
        for pkg in T.KPAR_PINS[repo]:
            assert have.get(T.canon(pkg)) == freeze[T.canon(pkg)], (repo, pkg, have.get(T.canon(pkg)))
        assert not [p for p in T.KPAR_FORBIDDEN if T.canon(p) in have], repo
        checked.append(repo)
    assert "rich" in checked


# ============================================================================== base workspaces (harness-exact)
def test_base_ws_is_harness_exact(tmp_path):
    tid = _first_local("rich")
    base = T.base_ws(tid)
    t0 = time.monotonic()
    assert T.base_ws(tid) == base and time.monotonic() - t0 < 0.05                     # cached
    ref = tmp_path / "ref"
    (ref / ".git" / "info").mkdir(parents=True)
    h = T._harness()
    h.cs.setup_git_exclude(T.LocalSandbox(ref), "x")                                   # the harness code, unmodified
    h.cs.setup_workspace_test_config(T.LocalSandbox(ref), "x", "r", workspace_dir=str(ref))
    assert (base / "pytest.ini").read_text() == (ref / "pytest.ini").read_text()
    try:                                                  # the shared constants of v10_support/repo.py agree
        from v10_support import repo as R
    except ImportError:
        R = None
    if R is not None:
        assert (base / "pytest.ini").read_text() == R.HARNESS_PYTEST_INI
        assert (base / ".git/info/exclude").read_text().rstrip("\n").endswith("\n".join(R.HARNESS_EXCLUDES))
    assert (base / "conftest.py").read_text().startswith("# Hermetic test discovery hook for SWE-gemma\n")
    assert (base / ".git/info/exclude").read_text().endswith((ref / ".git/info/exclude").read_text())
    head = T.git(base, "rev-parse", "HEAD").out.strip()
    assert T.git(base, "rev-parse", "_swegemma_baseline^{commit}").out.strip() == head
    assert T.git(base, "status", "--porcelain").out == ""
    tp = T.base_ws(tid, with_test_patch=True)
    assert tp != base and T.git(tp, "status", "--porcelain").out == ""
    for fp in T.parse_patch(T.load_task(tid)["test_patch"]):
        assert T.git(tp, "cat-file", "-e", f"_swegemma_baseline:{fp.path}").rc == 0, fp.path


def test_fresh_ws_is_a_fast_isolated_clone(tmp_path):
    tid = _first_local("rich")
    base = T.base_ws(tid)
    t0 = time.monotonic()
    ws = T.fresh_ws(tid, tmp_path)
    assert time.monotonic() - t0 < 3.0                                                 # APFS clone: 0.14 s measured
    assert ws == tmp_path / "ws" and (tmp_path / "ws_tmp").is_dir()
    target = next(p for p in ws.glob("*/__init__.py"))
    target.write_text("broken = (\n")
    assert (base / target.relative_to(ws)).read_text() != "broken = (\n"
    assert T.git(ws, "status", "--porcelain").out.strip() and T.git(base, "status", "--porcelain").out == ""


# ================================================================================================= R97
@ALL
def test_static_patch_facts(tid):
    """R97 (all 74, no snapshot needed): both patches parse and round-trip byte-exactly with consistent hunk counts;
    gold touches no protected file; every test_patch file is protected (harness rules, and the helpers' is_protected
    once built); the new-file classification matches the known set."""
    r = T.task_result("static", tid)
    g, tp = r["patch"], r["test_patch"]
    for side in (g, tp):
        assert side["roundtrip"] and side["counts_ok"] and side["new_consistent"] and side["files"]
    assert g["protected"] == [], g["protected"]
    assert sorted(tp["protected"]) == sorted(tp["files"]), set(tp["files"]) - set(tp["protected"])
    assert sorted(tp["harness_files"]) == sorted(tp["files"])
    assert len(g["new"]) == T.EXPECTED_NEW_FILES.get(tid, 0), g["new"]
    prot = T.helper_protection()
    if prot is not None:
        assert [f for f in g["files"] if prot[f]] == [], "gold file refused by is_protected"
        assert [f for f in tp["files"] if not prot[f]] == [], "hidden-test file not protected by is_protected"


def test_static_aggregate():
    rs = [T.task_result("static", tid) for tid in T.TASK_IDS]
    assert len(rs) == 74
    assert sum(any(f for f in r["test_patch"]["new"]) for r in rs) == 21                # test_plan section 3
    assert sum(len(r["test_patch"]["new"]) < len(r["test_patch"]["files"]) for r in rs) == 54
    assert sum(len(r["patch"]["new"]) for r in rs) == sum(T.EXPECTED_NEW_FILES.values()) == 31


@ALL
def test_static_stage_render(tid):
    """R97: every stage prompt rendered with this task's statement starts within the R94 budget (8,000 tokens)."""
    missing = [s for s in T.STAGES if not (T.BUNDLE / "prompts" / f"{s}.md").is_file()]
    if missing:
        pytest.skip(f"prompts not built yet: {missing}")
    t = T.load_task(tid)
    over = {s: n for s in T.STAGES if (n := T.stage_start_tokens(s, t)) > T.STAGE_BUDGET_TOKENS}
    assert not over, over


# ================================================================================================= R98
@ALL
def test_locate_budget(tid):
    """R98: locate.py with the problem statement as the query: LOCATE first line, 1,800 chars or fewer, 3 s or less
    (first, uncached call, under G4_J-way contention)."""
    r = T.task_result("locate", tid)
    assert r["installed"] and r["rc"] == 0 and not r["timed_out"], r["err"]
    assert r["first"].startswith("LOCATE:"), r["first"]
    assert r["chars"] <= 1800 and r["secs"] <= T.LOCATE_BUDGET_S, (r["chars"], r["secs"])


@pytest.mark.parametrize("tid", _xfail_known(T.KNOWN_LOCATE_MISS, "known locate miss (test_plan section 3)"))
def test_locate_rank(tid):
    """R98 per task: a gold file is in the top 8 (the six known misses xfail, not strict)."""
    r = T.task_result("locate", tid)
    assert r["rank"] <= 8, (r["ranks"], r["ranked"])


def test_locate_recall():
    """R98: gold file at rank 1 in 21/40 or more, top 3 in 28/40, top 8 in 34/40 (target 23/30/35)."""
    rs = T.computed("locate")
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    at = {k: sum(r["rank"] <= k for r in rs.values()) for k in (1, 3, 8)}
    bar = {1: T.need(21, 40, n), 3: T.need(28, 40, n), 8: T.need(34, 40, n)}
    assert all(at[k] >= bar[k] for k in at), f"recall {at} of {n}, need {bar}"


# ================================================================================================= R99
@ALL
def test_gold_hunks_via_edit(tid):
    """R99: every gold hunk through edit.py (SEARCH/REPLACE with the hunk's old/new lines; separately --lines
    bottom-up; new files via --create) leaves files byte-identical to git apply, and nothing else changed."""
    r = T.task_result("edit", tid)
    assert "error" not in r
    for mode in ("sr", "lines"):
        m = r["modes"][mode]
        assert m["ok"], (mode, m["mismatch"], m["stray"], m["log"])


# ================================================================================================ R100
@ALL
def test_verify_empty(tid):
    """R100: on the empty diff, verify.py says NO SOURCE CHANGE in under 1 s."""
    r = T.task_result("verify_empty", tid)
    assert r["first"].startswith("VERIFY: NO SOURCE CHANGE"), (r["first"], r["err"])
    assert r["secs"] < T.VERIFY_EMPTY_BUDGET_S, r["secs"]


# ================================================================================================ R101
@ALL
def test_discovery_collectable(tid):
    """R101 per task: with gold applied, verify.py --list-tests never lists a non-collectable file."""
    r = T.task_result("discovery", tid)
    assert r["first"].startswith("TESTS"), r["first"]
    assert r["noncollectable"] == [], r["picked"]


def test_discovery_recall():
    """R101: the list includes a file the test_patch modifies in 25/39 or more (v9: 23; target 30)."""
    rs = {k: v for k, v in T.computed("discovery").items() if v["targets"]}
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    hits = sum(r["hit"] for r in rs.values())
    assert hits >= T.need(25, 39, n), f"{hits}/{n} hit, need {T.need(25, 39, n)}; misses " \
                                      f"{sorted(k for k, v in rs.items() if not v['hit'])}"


# ========================================================================================== R102 (nightly)
@nightly
@ALL
def test_verify_gold(tid):
    """R102: gold applied, no repro: never RED, except confirmed regressions in KNOWN_BEHAVIOUR_CHANGE; the wording
    never says undo or must fix."""
    r = T.task_result("verify_gold", tid)
    assert not r["timed_out"] and r["first"].startswith("VERIFY:"), r["out"][-600:]
    assert not r["bad_words"], r["out"][-800:]
    if r["red"]:
        assert tid in T.KNOWN_BEHAVIOUR_CHANGE and r["first"].startswith("VERIFY: RED - regressions"), r["out"][-800:]
    assert r["secs"] <= 62, r["secs"]                                                  # the 60 s global deadline


@nightly
def test_verify_gold_p90():
    rs = T.computed("verify_gold")
    if not rs:
        pytest.skip("no local task ran")
    secs = sorted(r["secs"] for r in rs.values())
    p90 = secs[min(len(secs) - 1, int(0.9 * len(secs)))]
    busy = T.busy_machine("verify_gold")
    if p90 > T.VERIFY_GOLD_P90_S and busy:
        pytest.skip(f"p90 {p90:.1f}s not measurable: {busy}")
    assert p90 <= T.VERIFY_GOLD_P90_S, f"p90 {p90:.1f}s over {len(secs)} tasks"


# ========================================================================================== R103 (nightly)
@nightly
@ALL
def test_repro_flip_hidden(tid):
    """R103 per task: the hidden tests that fail on the original (committed into the baseline, measured with plain
    pytest) as claims: verify.py --repro-only never calls them BROKEN and, after gold, reports a k/n claims line."""
    r = T.task_result("repro", tid)
    assert "BROKEN" not in r["orig"], r["out_orig"]
    assert r["repro_line"], r["out_after"][-800:]


@nightly
def test_repro_flip_aggregate():
    """R103: every claim fails (or hangs) on original and gold fixes k/k in 36/39 tasks or more (tasks with at least
    one fail-to-pass hidden test)."""
    rs = T.computed("repro")
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    good = sorted(k for k, r in rs.items() if r["orig_fails"] and r["flip"])
    bad = {k: (r["orig"][:70], r["repro_line"]) for k, r in rs.items() if k not in good}
    assert len(good) >= T.need(36, 39, n), f"{len(good)}/{n}, need {T.need(36, 39, n)}; {bad}"


# ========================================================================================== R104 (nightly)
@nightly
@ALL
def test_finalize_saves_tampered_gold(tid):
    """R104 per task: gold + a raw edit inside the first hidden-test hunk + root repro.py/reproduce_issue.py:
    finalize prints READY, the final diff applies to a fresh baseline without the tamper or the scratch files, and
    the test_patch applies on top."""
    r = T.task_result("finalize", tid)
    assert r["ready"], r["out"]
    assert r["diff_applies"] and r["test_patch_applies"], r
    assert not r["scratch_left"] and r["tampered"] not in r["final_files"], r["final_files"]


@nightly
def test_finalize_saves_tampered_gold_aggregate():
    """R104: mini_verify of the finalized patch resolves in 38/39 or more (known: requests_6644)."""
    rs = T.computed("finalize")
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    ok = sum(r["resolved"] for r in rs.values())
    assert ok >= T.need(38, 39, n), {k: r["why"] for k, r in rs.items() if not r["resolved"]}


# ========================================================================================== R105 (nightly)
@nightly
@ALL
def test_mini_verify_gold_empty(tid):
    """R105: the verify_task port resolves gold (in under 30 s) and does not resolve the empty patch (20 s hang cap;
    KNOWN_FREE resolves empty because its tests import site-packages, F10)."""
    r = T.task_result("mini", tid)
    assert r["gold"] or tid in T.KNOWN_GOLD_LOST, r["gold_why"]
    assert r["gold_secs"] < T.MINI_GOLD_BUDGET_S, r["gold_secs"]
    assert (not r["empty"]) or tid in T.KNOWN_FREE, "empty patch resolved"
    assert r["empty_secs"] < T.MINI_GOLD_BUDGET_S, r["empty_secs"]                      # the 20 s hang cap holds
    if tid in T.KNOWN_EMPTY_HANG:                                                       # documented hangs reproduce
        assert "hang" in (r["empty_why"] or ""), r["empty_why"]


@nightly
def test_mini_verify_gold_aggregate():
    rs = T.computed("mini")
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    ok = sum(r["gold"] for r in rs.values())
    assert ok >= T.need(39, 40, n), {k: r["gold_why"] for k, r in rs.items() if not r["gold"]}


# ========================================================================================== R106 (nightly)
class F1Lost(AssertionError):
    """The harness reset left an agent-edited hidden-test file modified (F1)."""


@nightly
@ALL
@pytest.mark.xfail(strict=True, raises=F1Lost, reason="F1: `git checkout HEAD -- <list incl. sitecustomize.py>` "
                   "aborts on the missing pathspec, so the tampered test file is never reset")
def test_tamper_lost_under_harness(tid):
    """R106 documents F1: gold + an edit inside the first test_patch hunk, then the harness-exact reset. The reset is
    a no-op, plain git apply of the test_patch then fails, and the task is lost unless `patch` fuzz relocates the
    hunk (BSD patch here rescued 4 of 39; the scorer's GNU patch 1 of those 4, measured). If the reset ever works
    (XPASS, strict), the harness was fixed and v10's hygiene assumptions can be revisited."""
    r = T.task_result("tamper", tid)
    if r["reset_ok"]:
        return
    assert r["tp_git_apply_ok"] is False, "the tamper missed the hidden-test hunk"          # a plain failure
    assert r["lost"] or r["resolved"], f"lost for another reason: {r['why']}"
    raise F1Lost(f"reset no-op; {'lost: ' + r['why'][:120] if r['lost'] else 'rescued by patch fuzz'}")


@nightly
def test_tamper_lost_aggregate():
    """R106: the no-op reset loses most tampered tasks (39/39 with git apply alone; patch fuzz rescues a few)."""
    rs = T.computed("tamper")
    n = len(rs)
    if not n:
        pytest.skip("no local task ran")
    lost = sum(r["lost"] for r in rs.values())
    assert all(r["tp_git_apply_ok"] is False for r in rs.values())
    assert lost >= T.need(35, 39, n), {k: r["why"] for k, r in rs.items() if not r["lost"]}


# ================================================================================= timing budgets (asserted)
def test_results_written_and_timed():
    """Every computed kind is on disk (eval/offline/v10_<kind>.json) with its wall time."""
    done = [k for k in T.KINDS if k in T._RESULTS]
    if not done:
        pytest.skip("no kind computed in this session")
    for k in done:
        doc = json.loads((T.OFFLINE_OUT / f"v10_{k}.json").read_text())
        assert doc["kind"] == k and set(doc["tasks"]) == set(T._RESULTS[k]) and doc["wall_secs"] >= 0
    static = T.OFFLINE_OUT / "v10_static.json"
    if static.is_file():
        assert json.loads(static.read_text())["wall_secs"] < 30


def test_ci_kinds_fit_the_ci_budget():
    """SPEC 8: the CI per-task group takes about 45-90 s for 40 tasks at J=4; assert a 4-minute ceiling per kind."""
    walls = {k: json.loads((T.OFFLINE_OUT / f"v10_{k}.json").read_text())["wall_secs"]
             for k in ("locate", "edit", "verify_empty", "discovery") if k in T._RESULTS}
    if not walls:
        pytest.skip("no CI kind computed in this session")
    ok = all(w < 240 for w in walls.values()) and statistics.fmean(walls.values()) < 120
    busy = [b for k in walls if (b := T.busy_machine(k))]
    if not ok and busy:
        pytest.skip(f"CI walls {walls} not measurable: {busy[0]}")
    assert ok, walls
