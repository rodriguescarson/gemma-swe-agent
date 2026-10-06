"""v6p helpers honour a per-copy working directory (docs/GAPS_2026-10-06.md AC-B2). The three parallel fixers run
`cd /tmp/wK && python3 /tmp/swe/<helper>.py ...` in ONE sandbox whose /workspace still holds the original checkout and
whose environment exports PYTHONPATH=<workspace> (research/harness_runtime.md 2.4). v5h2's _ws.ws() put /workspace
before the cwd, so view.py/test.py would have read and tested the original, and view.py's repeat guard keyed ranges
by the relative path, so fixer b would have been refused a range fixer a had read. Written before the change."""
import os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "submissions" / "v6p" / "skills" / "swe-tools" / "scripts"


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, check=True).stdout


def setup(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "pkg" / "__init__.py").write_text("")
    (ws / "pkg" / "mod.py").write_text("def f(x):\n    return x\n")
    (ws / "tests" / "test_mod.py").write_text(
        "import os\nfrom pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n\n\n"
        "def test_env():\n    p = os.environ['PYTHONPATH'].split(os.pathsep)[0]\n"
        "    assert os.path.realpath(p) == os.path.realpath(os.getcwd())\n")
    git(tmp_path, "init", "-q", str(ws))
    git(ws, "add", "-A")
    git(ws, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "b")
    tmp = tmp_path / "sbtmp"
    tmp.mkdir()
    copies = {}
    for k in "ab":
        d = tmp / f"w{k}"
        shutil.copytree(ws, d)
        copies[k] = d
    (copies["a"] / "pkg" / "mod.py").write_text("def f(x):\n    return x * 2  # copy a\n")
    return ws, tmp, copies


def run(helper, cwd, ws, tmp, *args, stdin=None):
    """As the sandbox runs it after `cd /tmp/wK`: bash sets PWD to the copy, PYTHONPATH still names the workspace."""
    env = {k: v for k, v in os.environ.items() if k != "SWE_WS"}
    env.update(PWD=str(cwd), PYTHONPATH=str(ws), TMPDIR=str(tmp), TEST_TMPDIR=str(tmp), HOME=str(tmp))
    return subprocess.run([sys.executable, str(S / helper), *args], cwd=str(cwd), env=env, input=stdin,
                          capture_output=True, text=True, timeout=120).stdout


def test_ws_prefers_a_git_root_cwd_over_workspace(tmp_path):
    ws, tmp, c = setup(tmp_path)
    code = "import sys; sys.path.insert(0, %r); from _ws import ws; print(ws())" % str(S)
    env = {k: v for k, v in os.environ.items() if k != "SWE_WS"}
    out = subprocess.run([sys.executable, "-c", code], cwd=str(c["a"]), env=dict(env, PWD=str(ws)),
                         capture_output=True, text=True).stdout.strip()
    assert os.path.realpath(out) == os.path.realpath(c["a"])
    # outside any repo (run_skill_script chdirs into a temp dir) it still finds the workspace through PWD
    out = subprocess.run([sys.executable, "-c", code], cwd=str(tmp), env=dict(env, PWD=str(ws)),
                         capture_output=True, text=True).stdout.strip()
    assert os.path.realpath(out) == os.path.realpath(ws)
    # an explicit SWE_WS still wins
    out = subprocess.run([sys.executable, "-c", code], cwd=str(c["a"]), env=dict(env, SWE_WS=str(c["b"])),
                         capture_output=True, text=True).stdout.strip()
    assert os.path.realpath(out) == os.path.realpath(c["b"])


def test_view_reads_the_copy_and_the_repeat_guard_is_per_copy(tmp_path):
    ws, tmp, c = setup(tmp_path)
    out_a = run("view.py", c["a"], ws, tmp, "pkg/mod.py", "1", "2")
    assert "copy a" in out_a
    out_b = run("view.py", c["b"], ws, tmp, "pkg/mod.py", "1", "2")
    assert "ALREADY SHOWN" not in out_b and "return x" in out_b and "copy a" not in out_b
    assert "ALREADY SHOWN" in run("view.py", c["a"], ws, tmp, "pkg/mod.py", "1", "2")


def test_test_py_runs_the_copy_with_the_copy_first_on_pythonpath(tmp_path):
    ws, tmp, c = setup(tmp_path)
    out = run("test.py", c["a"], ws, tmp, "--target", "tests/test_mod.py")
    assert out.startswith("exit=0"), out                                      # copy a's fix, and PYTHONPATH[0] == copy
    out = run("test.py", c["b"], ws, tmp, "--target", "tests/test_mod.py")
    assert out.startswith("exit=1"), out                                      # copy b is unfixed


def test_edit_in_a_copy_never_touches_the_workspace(tmp_path):
    ws, tmp, c = setup(tmp_path)
    block = "<<<<<<< SEARCH\n    return x\n=======\n    return x * 2\n>>>>>>> REPLACE\n"
    out = run("edit.py", c["b"], ws, tmp, "pkg/mod.py", stdin=block)
    assert out.startswith("OK"), out
    assert "x * 2" in (c["b"] / "pkg" / "mod.py").read_text()
    assert (ws / "pkg" / "mod.py").read_text() == "def f(x):\n    return x\n"


def test_workspace_behaviour_is_unchanged_from_the_workspace_cwd(tmp_path):
    ws, tmp, c = setup(tmp_path)
    assert "return x" in run("view.py", ws, ws, tmp, "pkg/mod.py", "1", "2")
    out = run("test.py", ws, ws, tmp, "--target", "tests/test_mod.py::test_env")
    assert out.startswith("exit=0"), out


# ---------------------------------------------------------------- repro.py (S3): the locator's /tmp/repro.py, per copy

def test_repro_runs_against_the_copy_it_is_started_in(tmp_path):
    ws, tmp, c = setup(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(3) == 6, f(3)\n")
    assert run("repro.py", c["a"], ws, tmp).startswith("REPRO PASS")
    out = run("repro.py", c["b"], ws, tmp)
    assert out.startswith("REPRO FAIL") and "AssertionError" in out, out
    assert run("repro.py", ws, ws, tmp).startswith("REPRO FAIL")              # the locator's check: fails before


def test_repro_gets_the_repo_root_as_argv1_and_cwd(tmp_path):
    ws, tmp, c = setup(tmp_path)
    (tmp / "repro.py").write_text("import os, sys\nprint('ROOT', sys.argv[1])\n"
                                  "assert os.path.realpath(sys.argv[1]) == os.path.realpath(os.getcwd())\n")
    out = run("repro.py", c["b"], ws, tmp)
    assert out.startswith("REPRO PASS") and os.path.realpath(c["b"]) in out.replace("ROOT ", ""), out


def test_repro_missing_timeout_and_compact_output(tmp_path):
    ws, tmp, c = setup(tmp_path)
    assert run("repro.py", c["a"], ws, tmp).startswith("REPRO MISSING")
    (tmp / "repro.py").write_text("import time\ntime.sleep(30)\n")
    assert run("repro.py", c["a"], ws, tmp, "--timeout", "2").startswith("REPRO TIMEOUT")
    (tmp / "repro.py").write_text("print('x' * 50000)\nraise SystemExit(3)\n")
    out = run("repro.py", c["a"], ws, tmp)
    assert out.startswith("REPRO FAIL exit=3") and len(out) < 2000, len(out)
