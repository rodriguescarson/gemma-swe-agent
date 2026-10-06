"""v6p select_best.py (docs/GAPS_2026-10-06.md AC-B2 + S3): pick the best of the three fixers' candidates and apply it
to the workspace. Synthetic git repos only; written before the script (strict test-first).

Named select_best.py, not select.py: installed into /tmp/swe, a select.py shadows the stdlib `select` module for every
helper started as `python3 /tmp/swe/<helper>.py` (sys.path[0] is the script's dir), and `import subprocess` then fails
in test.py and check.py (checked 2026-10-06).

Selection rules: a candidate = the fixer's copy /tmp/wK (diff vs HEAD, untracked files included) or, without the copy,
/tmp/wK.diff. Test/config files are dropped from every candidate. Each candidate is applied to a clean copy and
checked with the locator's repro (/tmp/repro.py, S3) and the locator's TEST file. Ranking: repro pass first, then the
TEST file, then the smallest diff; a repro that already passes on the unedited code is ignored; empty candidates never
win; all empty -> the workspace is left exactly as it was."""
import os, runpy, shutil, subprocess, sys, textwrap, time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "submissions" / "v6p" / "skills" / "swe-tools" / "scripts"
SELECT = SCRIPTS / "select_best.py"

SRC = "def f(x):\n    return x\n"
TEST = "from pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n"
GOOD = "def f(x):\n    return x * 2\n"
GOOD_BIG = "def f(x):\n    # doubled\n    # because the issue says so\n    y = x * 2\n    return y\n"
BAD = "def f(x):\n    return x + 1\n"
SLOW = "import time\n\n\ndef f(x):\n    time.sleep(30)\n    return x * 2\n"


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, check=True).stdout


def make_ws(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "pkg" / "__init__.py").write_text("")
    (ws / "pkg" / "mod.py").write_text(SRC)
    (ws / "tests" / "test_mod.py").write_text(TEST)
    (ws / "conftest.py").write_text("")                                    # the harness writes one; it is tracked
    git(tmp_path, "init", "-q", str(ws))
    git(ws, "add", "-A")
    git(ws, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "baseline")
    with open(ws / ".git" / "info" / "exclude", "a") as f:                  # what container_setup appends
        f.write("\n__pycache__/\n*.pyc\n.pytest_cache/\n.adk_exec_*.py\n")
    tmp = tmp_path / "sbtmp"
    tmp.mkdir()
    return ws, tmp


def fork(ws, tmp, k, files):
    """A fixer's copy /tmp/wK with `files` ({rel: text or None to delete}) changed."""
    d = tmp / f"w{k}"
    shutil.copytree(ws, d, symlinks=True)
    for rel, text in files.items():
        p = d / rel
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    return d


def diff_only(ws, tmp, k, files):
    """Only /tmp/wK.diff, no copy (the fixer wrote its diff and its copy is gone)."""
    d = fork(ws, tmp, k, files)
    git(d, "add", "-N", ".")
    (tmp / f"w{k}.diff").write_text(git(d, "diff", "--binary"))
    shutil.rmtree(d)


def run_select(ws, tmp, *args, env=None, timeout=120):
    e = dict(os.environ, **(env or {}))
    e.pop("SWE_WS", None)
    r = subprocess.run([sys.executable, str(SELECT), "--ws", str(ws), "--tmp", str(tmp), *args], capture_output=True,
                       text=True, timeout=timeout, env=e, cwd=str(tmp))
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def ws_diff(ws):
    git(ws, "add", "-N", ".")
    return git(ws, "diff")


def pick(out):
    return [l for l in out.splitlines() if l.startswith("PICK")][0]


# ---------------------------------------------------------------- selection rules

def test_passing_beats_failing_even_when_bigger(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": BAD})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    fork(ws, tmp, "c", {"pkg/mod.py": BAD})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK b"), out
    assert (ws / "pkg" / "mod.py").read_text() == GOOD_BIG


def test_ties_go_to_the_smallest_diff(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD_BIG})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    fork(ws, tmp, "c", {"pkg/mod.py": GOOD})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK c"), out
    assert (ws / "pkg" / "mod.py").read_text() == GOOD


def test_none_pass_takes_the_nonempty_diff_with_most_passes(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(0) == 1\n")   # only BAD's x + 1 satisfies this
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD})                               # 0 of 2
    fork(ws, tmp, "b", {"pkg/mod.py": "def f(x):\n    return x + 1  # the bigger one\n"})  # 1 of 2
    fork(ws, tmp, "c", {})                                                 # empty: never picked
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK b"), out
    assert "the bigger one" in (ws / "pkg" / "mod.py").read_text()


def test_none_pass_with_equal_passes_takes_the_smallest_nonempty(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": "def f(x):\n    return x + 1\n\n\n# padding\n# padding\n"})
    fork(ws, tmp, "b", {"pkg/mod.py": BAD})
    fork(ws, tmp, "c", {})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK b"), out


def test_all_empty_leaves_the_workspace_exactly_as_it_was(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (ws / "pkg" / "mod.py").write_text(SRC + "# locator touched this\n")     # whatever is there stays
    (ws / "scratch_note.txt").write_text("x")
    before = ws_diff(ws)
    fork(ws, tmp, "a", {"pkg/mod.py": SRC})                                # reverts to HEAD -> empty vs HEAD
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK none"), out
    assert ws_diff(ws) == before and (ws / "scratch_note.txt").exists()


def test_no_candidates_at_all_is_a_clean_no_op(tmp_path):
    ws, tmp = make_ws(tmp_path)
    out = run_select(ws, tmp)
    assert pick(out).startswith("PICK none") and ws_diff(ws) == ""
    assert "No such file" not in out and "can't open file" not in out      # the Kaggle helper probe greps for these


def test_test_and_config_changes_are_excluded(tmp_path):
    ws, tmp = make_ws(tmp_path)
    cheat = TEST.replace("== 4", "== 2")
    fork(ws, tmp, "a", {"tests/test_mod.py": cheat})                       # only a test edit -> empty
    fork(ws, tmp, "b", {"tests/test_mod.py": cheat, "pyproject.toml": "[tool.x]\n", "pkg/mod.py": BAD})
    fork(ws, tmp, "c", {"pkg/mod.py": GOOD_BIG, "tests/test_new.py": "def test_x(): pass\n"})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK c"), out                             # b's test cheat does not count
    d = ws_diff(ws)
    assert "tests/" not in d and "pyproject" not in d and "doubled" in d
    assert (ws / "tests" / "test_mod.py").read_text() == TEST


def test_a_slow_candidate_is_cut_by_its_own_timeout(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": SLOW})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    t = time.time()
    out = run_select(ws, tmp, "--test", "tests/test_mod.py", "--timeout", "3")
    assert time.time() - t < 20, out
    assert pick(out).startswith("PICK b"), out
    assert "timeout" in out.lower()


def test_whole_selection_respects_the_total_budget(tmp_path):
    ws, tmp = make_ws(tmp_path)
    for k in "abc":
        fork(ws, tmp, k, {"pkg/mod.py": SLOW.replace("x * 2", "x * 2  # " + k)})
    t = time.time()
    out = run_select(ws, tmp, "--test", "tests/test_mod.py", "--timeout", "20", "--total", "6")
    assert time.time() - t < 15, out
    assert pick(out).startswith("PICK "), out


def test_report_is_compact(tmp_path):
    ws, tmp = make_ws(tmp_path)
    many = {f"pkg/m{i:02d}_{'x' * 40}.py": "y = 1\n" * 50 for i in range(40)}
    noisy = TEST.replace("assert f(2) == 4", "print('NOISE' * 5000)\n    assert False")
    (tmp / "repro.py").write_text("print('R' * 20000)\nraise SystemExit(1)\n")
    (ws / "tests" / "test_mod.py").write_text(noisy)                       # make every test run print a lot
    git(ws, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qam", "noisy")
    fork(ws, tmp, "a", dict(many, **{"pkg/mod.py": BAD}))
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD})
    fork(ws, tmp, "c", {"pkg/mod.py": BAD + "#c\n"})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert len(out) < 2000, len(out)
    assert out.count("\n") < 30


# ---------------------------------------------------------------- inputs and outputs

def test_reads_wk_diff_when_the_copy_is_gone_and_applies_new_files(tmp_path):
    ws, tmp = make_ws(tmp_path)
    diff_only(ws, tmp, "a", {"pkg/mod.py": GOOD, "pkg/helper.py": "H = 1\n"})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK a"), out
    assert (ws / "pkg" / "helper.py").read_text() == "H = 1\n"


def test_copy_wins_over_a_stale_diff_file(tmp_path):
    ws, tmp = make_ws(tmp_path)
    diff_only(ws, tmp, "a", {"pkg/mod.py": BAD})                           # stale: written before the last edit
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert (ws / "pkg" / "mod.py").read_text() == GOOD, out


def test_scratch_files_in_a_copy_are_not_part_of_the_candidate(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD, "repro_issue.py": "print(1)\n", "debug_out.txt": "x\n"})
    run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert not (ws / "repro_issue.py").exists() and not (ws / "debug_out.txt").exists()
    assert (ws / "pkg" / "mod.py").read_text() == GOOD


def test_apply_resets_the_workspace_first_but_keeps_ignored_harness_files(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (ws / "pkg" / "__init__.py").write_text("STRAY = 1\n")                 # a stray tracked edit in /workspace
    (ws / "notes.py").write_text("n = 1\n")                                 # a stray untracked file
    (ws / ".adk_exec_deadbeef.py").write_text("# the run_skill_script wrapper\n")
    (ws / "pkg" / "__pycache__").mkdir()
    (ws / "pkg" / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\0")
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD})
    shutil.rmtree(tmp / "wa" / "pkg" / "__pycache__")
    (tmp / "wa" / "pkg" / "__init__.py").write_text("")
    (tmp / "wa" / "notes.py").unlink()
    run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert (ws / "pkg" / "__init__.py").read_text() == ""
    assert not (ws / "notes.py").exists()
    assert (ws / ".adk_exec_deadbeef.py").exists()                          # git-excluded: never cleaned
    assert (ws / "pkg" / "__pycache__" / "mod.cpython-312.pyc").exists()
    assert (ws / "conftest.py").exists()                                    # tracked harness file untouched
    assert git(ws, "diff", "--name-only").split() == ["pkg/mod.py"]


def test_repro_scripts_run_against_the_candidate_not_the_workspace(tmp_path):
    """The sandbox exports PYTHONPATH=<workspace>; a repro under /tmp would import the unfixed workspace."""
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(3) == 6\n")
    fork(ws, tmp, "a", {"pkg/mod.py": BAD})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    out = run_select(ws, tmp, env={"PYTHONPATH": str(ws)})                  # no --test: repro is the only check
    assert pick(out).startswith("PICK b"), out


def test_repro_ranks_before_the_test_file(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(3) == 6\n")
    # a: passes the TEST file (f(2) == 4) but not the repro; b: passes the repro but breaks the TEST file
    fork(ws, tmp, "a", {"pkg/mod.py": "def f(x):\n    return 4 if x == 2 else x\n"})
    fork(ws, tmp, "b", {"pkg/mod.py": "def f(x):\n    return 6 if x == 3 else x\n# b is the bigger one\n"})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK b"), out


def test_a_repro_that_passes_before_the_fix_is_ignored(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(1) == 1\n")      # true on HEAD: no signal
    fork(ws, tmp, "a", {"pkg/mod.py": GOOD_BIG})                                         # TEST yes, repro no
    fork(ws, tmp, "b", {"pkg/mod.py": "def f(x):\n    return x if x == 1 else x + 1\n"})  # TEST no, repro yes
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK a"), out
    assert "passes before the fix" in out


def test_repro_gets_the_candidate_root_as_argv_and_cwd(tmp_path):
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text(
        "import os, sys\nroot = sys.argv[1]\nassert os.path.realpath(root) == os.path.realpath(os.getcwd())\n"
        "assert os.path.isfile(os.path.join(root, 'pkg', 'mod.py'))\n"
        "assert 'x * 2' in open(os.path.join(root, 'pkg', 'mod.py')).read()\n")
    fork(ws, tmp, "a", {"pkg/mod.py": BAD})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    out = run_select(ws, tmp)
    assert pick(out).startswith("PICK b"), out


def test_missing_test_arg_falls_back_to_the_test_file_named_after_the_changed_module(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": BAD})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    out = run_select(ws, tmp)
    assert "tests/test_mod.py" in out and pick(out).startswith("PICK b"), out


def test_a_nonexistent_test_arg_falls_back_too(tmp_path):
    ws, tmp = make_ws(tmp_path)
    fork(ws, tmp, "a", {"pkg/mod.py": BAD})
    fork(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    out = run_select(ws, tmp, "--test", "tests/test_nope.py::test_x")
    assert pick(out).startswith("PICK b"), out


def test_identical_candidates_are_checked_once(tmp_path):
    ws, tmp = make_ws(tmp_path)
    for k in "abc":
        fork(ws, tmp, k, {"pkg/mod.py": GOOD})
    out = run_select(ws, tmp, "--test", "tests/test_mod.py")
    assert pick(out).startswith("PICK a"), out
    assert "same as a" in out


# ---------------------------------------------------------------- end-to-end dry run, sandbox-shaped

def test_end_to_end_dry_run_as_run_skill_script_runs_it(tmp_path):
    """No --ws/--tmp: the workspace comes from PWD and the candidates from $TMPDIR, as in the subprocess sandbox where
    run_skill_script materialises the skill in a temp dir, chdirs into it and runs the script with runpy."""
    ws, tmp = make_ws(tmp_path)
    (tmp / "repro.py").write_text("from pkg.mod import f\nassert f(5) == 10\n")
    diff_only(ws, tmp, "a", {"pkg/mod.py": BAD})
    diff_only(ws, tmp, "b", {"pkg/mod.py": GOOD_BIG})
    diff_only(ws, tmp, "c", {"pkg/mod.py": GOOD, "tests/test_mod.py": TEST + "\n# cheat\n"})
    skill_td = tmp / "skill_td"
    shutil.copytree(SCRIPTS, skill_td / "scripts")
    wrapper = tmp / "wrapper.py"
    wrapper.write_text(textwrap.dedent(f"""
        import os, runpy, sys
        os.chdir({str(skill_td)!r})
        sys.argv = ["scripts/select_best.py", "--test", "tests/test_mod.py"]
        runpy.run_path("scripts/select_best.py", run_name="__main__")
    """))
    env = {k: v for k, v in os.environ.items() if k not in ("SWE_WS",)}
    env.update(PWD=str(ws), TMPDIR=str(tmp), TEST_TMPDIR=str(tmp), HOME=str(tmp), PYTHONPATH=str(ws))
    r = subprocess.run([sys.executable, str(wrapper)], cwd=str(ws), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert pick(r.stdout).startswith("PICK c"), r.stdout                    # smallest of the two that pass both checks
    assert (ws / "pkg" / "mod.py").read_text() == GOOD
    assert (ws / "tests" / "test_mod.py").read_text() == TEST
    assert len(r.stdout) < 2000
