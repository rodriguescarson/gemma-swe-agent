"""run.py and status.py (SPEC 4.8, 4.13, 4.14): R25, R26, R27.

Helpers are copied to a temp dir and run as subprocesses against a throwaway harness-like repo, exactly as the model runs
them through run_command. Timing budgets are asserted (medians, to stay stable on a loaded machine).
"""
import json, os, pathlib, re, statistics, subprocess, sys, time
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import (no_orphans, make_repo, copy_helpers, helper_env, run_helper, run_py, run_as_skill,  # noqa: F401,E402
                              skill_args, git, find_orphans, kill_processes, unique_sleep, SCRIPTS_SRC, PY, TAG)

pytestmark = pytest.mark.skipif(not (SCRIPTS_SRC / "run.py").exists() or not (SCRIPTS_SRC / "status.py").exists(),
                                reason="run.py/status.py not built")

HANG_NOTE = "If the issue is about a hang or loop, this may be the bug."
DISABLED_NOTE = ("Test runners are disabled by the harness here: check behaviour with a reproduction "
                 "(verify.py --repro-only) instead.")


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


def run(scripts, args, ws, env, **kw):
    r = run_helper(scripts, "run", args, ws=ws, env=env, **kw)
    assert r.returncode == 0 and r.stderr == "" and "HELPER ERROR" not in r.stdout, r.stdout + r.stderr
    return r.stdout


def lines(out):
    return out.rstrip("\n").split("\n")


# ----------------------------------------------------------------------------------------------------------------- R25
def timeout_rule(scripts, argv, env, ws):
    code = ("import json, runpy, sys\ng = runpy.run_path(sys.argv[1], run_name='probe')\nC = g['C']\n"
            "a = C.parse_args(json.loads(sys.argv[2]), g['FLAGS'], (), usage=g['USAGE'], interspersed=False)\n"
            "print(json.dumps(g['effective_timeout'](a)))")
    r = subprocess.run([PY, "-c", code, str(scripts / "run.py"), json.dumps(argv)], cwd=str(ws),
                       env=dict(env, PWD=str(ws)), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_run_timeout_rule(scripts, ws, env):
    assert timeout_rule(scripts, [], env, ws) == [20.0, []]                               # default 20
    assert timeout_rule(scripts, ["--timeout", "500"], env, ws) == [90.0, []]             # clamped to RUN_MAX
    assert timeout_rule(scripts, ["--timeout", "0"], env, ws) == [1.0, []]                # clamped to 1
    assert timeout_rule(scripts, ["--timeout", "-3"], env, ws) == [1.0, []]
    assert timeout_rule(scripts, ["--timeout", "7s"], env, ws) == [7.0, []]
    assert timeout_rule(scripts, ["--timeout", "abc"], env, ws) == [20.0, ["NOTE: --timeout must be an integer; used 20"]]
    near_cap = dict(env, SWE_FAKE_CLOCK="290")                                             # then real_budget: 300-290-4
    assert timeout_rule(scripts, ["--timeout", "30"], near_cap, ws) == [6.0, [
        "NOTE: timeout cut to 6s by the remaining task time."]]
    assert timeout_rule(scripts, [], dict(env, SWE_FAKE_CLOCK="400"), ws)[0] == 1.0


def test_run_contract(tmp_path, scripts, ws, swe, env):
    # line 1, cwd = ws even from a subdirectory, env additions
    out = run(scripts, ['pwd -P; echo "$PYTHONDONTWRITEBYTECODE $NO_COLOR $TERM $COLUMNS"'], ws / "pkg", env)
    assert lines(out)[0] == "exit=0"
    assert lines(out)[1] == os.path.realpath(ws) and lines(out)[2] == "1 1 dumb 120"
    assert lines(out)[-1].startswith("[t=")
    # exit codes and stderr merged
    out = run(scripts, ["echo to-err >&2; exit 3"], ws, env)
    assert lines(out)[:2] == ["exit=3", "to-err"]
    # no output
    assert lines(run(scripts, ["true"], ws, env))[:2] == ["exit=0", "(no output)"]
    # several words: the calling shell split them; quoting is restored
    out = run(scripts, ["--timeout", "10", PY, "-c", "print(1 + 1)"], ws, env)
    assert lines(out)[:2] == ["exit=0", "2"]
    out = run(scripts, ["python3", "-c", "import sys; print(sys.argv[1:])", "a b", "--tb=short"], ws, env)
    assert "['a b', '--tb=short']" in out
    # --cmd (the skill form) and run_skill_script itself
    assert lines(run(scripts, ["--cmd", "echo via-cmd", "--timeout", "5"], ws, env))[:2] == ["exit=0", "via-cmd"]
    r = run_as_skill(scripts, "run", skill_args({"cmd": "echo hi-skill", "timeout": 5}), ws=ws, env=env)
    assert r.returncode == 0 and lines(r.stdout)[:2] == ["exit=0", "hi-skill"], r.stdout + r.stderr
    # TIMEOUT keeps partial output
    t0 = time.monotonic()
    out = run(scripts, ["--timeout", "1", "echo partial; sleep 5"], ws, env)
    assert time.monotonic() - t0 < 3
    assert lines(out)[0] == "TIMEOUT after 1s (partial output below). " + HANG_NOTE and lines(out)[1] == "partial"
    # an invalid --timeout gives the note and uses 20
    out = run(scripts, ["--timeout", "abc", "echo ok"], ws, env)
    assert lines(out)[:2] == ["exit=0", "ok"] and "NOTE: --timeout must be an integer; used 20" in out
    # the session clamp shows when the task is almost out of time
    out = run(scripts, ["--timeout", "30", "echo late"], ws, dict(env, SWE_FAKE_CLOCK="290"))
    assert "NOTE: timeout cut to 6s by the remaining task time." in out and "TIME: t>=250s." in out
    # no command: USAGE
    out = run(scripts, [], ws, env)
    assert lines(out)[0] == 'USAGE: python3 /tmp/swe/run.py [--timeout N] "COMMAND"'


def test_run_output_cap_summary_collapse_and_log(tmp_path, scripts, ws, swe, env):
    prog = ("import sys\nfor i in range(3000):\n    print('line %d' % i)\n"
            "print('==== 2 failed, 5 passed in 0.12s ====')\nprint('after')\n")
    (tmp_path / "big.py").write_text(prog)
    out = run(scripts, ["%s %s" % (PY, tmp_path / "big.py")], ws, env)
    assert len(out.rstrip("\n")) <= 2500
    assert lines(out)[0] == "exit=0" and lines(out)[1] == "line 0" and lines(out)[-1].startswith("[t=")
    assert "==== 2 failed, 5 passed in 0.12s ====" in out and "after" in out
    assert re.search(r"\.\.\. \[\d+ lines cut; full output: /tmp/swe/last\.log\] \.\.\.", out)
    log = (swe / "last.log").read_text()
    assert "line 1500" in log and "line 2999" in log and log.startswith("exit=0\n")
    # identical lines collapse; blank runs shrink; ANSI and CR redraws are cleaned
    out = run(scripts, ["yes | head -50; printf '\\n\\n\\n\\033[31mred\\033[0m\\n'; printf 'p 10%%\\rp 100%%\\n'"], ws, env)
    assert lines(out)[1] == "y (x50)" and lines(out)[2] == "" and lines(out)[3] == "red" and lines(out)[4] == "p 100%"
    assert "\x1b" not in out
    # the harness pytest mask gets its note
    out = run(scripts, ["echo 'pytest is disabled in this environment to prevent slow full-repo test runs' >&2; exit 1"],
              ws, env)
    assert lines(out)[0] == "exit=1" and DISABLED_NOTE in out
    # the third identical (command, output) gets the repeat note, not the first two
    notes = ["NOTE: same command, same output 3 times; change something." in run(scripts, ["echo same"], ws, env)
             for _ in range(3)]
    assert notes == [False, False, True]
    assert "change something" not in run(scripts, ["echo different"], ws, env)
    # the journal records runs for status.py
    js = [json.loads(x) for x in (swe / "journal.jsonl").read_text().splitlines()]
    assert any(j.get("h") == "run" and "echo same" in j.get("msg", "") for j in js)


def test_run_overhead_budget(tmp_path, scripts, ws, env):
    run(scripts, ["true"], ws, env)                                    # warm the install and caches
    ours, bare = [], []
    for _ in range(7):
        t0 = time.monotonic()
        run(scripts, ["true"], ws, env)
        ours.append(time.monotonic() - t0)
        t0 = time.monotonic()
        subprocess.run(["bash", "-c", "true"], env=env, cwd=str(ws))
        bare.append(time.monotonic() - t0)
    over = min(ours) - min(bare)            # min: the fixed cost, robust to a loaded machine (medians are noisy)
    assert over <= 0.1, (ours, bare)


# ----------------------------------------------------------------------------------------------------------------- R26
def test_run_timeout_kills_group(tmp_path, scripts, ws, env):
    S = unique_sleep(tmp_path)
    t0 = time.monotonic()
    out = run(scripts, ["--timeout", "2", "%s 30 & bash -c '%s 20'" % (S, S)], ws, env, timeout=20)
    assert time.monotonic() - t0 <= 4.0
    assert lines(out)[0].startswith("TIMEOUT after 2s")
    time.sleep(0.5)
    left = find_orphans([S])
    kill_processes(left)
    assert not left, left


def test_run_reaps_background_children_on_normal_exit(tmp_path, scripts, ws, env):
    S = unique_sleep(tmp_path)
    t0 = time.monotonic()
    out = run(scripts, ["%s 30 & echo started" % S], ws, env, timeout=20)
    assert time.monotonic() - t0 < 2.0 and lines(out)[:2] == ["exit=0", "started"]
    time.sleep(0.3)
    left = find_orphans([S])
    kill_processes(left)
    assert not left, left


def test_run_command_reading_stdin_does_not_block(scripts, ws, env):
    t0 = time.monotonic()
    p = subprocess.Popen([PY, str(scripts / "run.py"), "--timeout", "5", "cat; echo eof"], cwd=str(ws),
                         env=dict(env, PWD=str(ws)), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out = p.communicate(timeout=20)[0]                     # stdin stays open: the child still sees /dev/null
    assert time.monotonic() - t0 < 3 and lines(out)[:2] == ["exit=0", "eof"]


# ----------------------------------------------------------------------------------------------------------------- R27
def status(scripts, ws, env, *args):
    r = run_helper(scripts, "status", list(args), ws=ws, env=env)
    assert r.returncode == 0 and r.stderr == "" and "HELPER ERROR" not in r.stdout, r.stdout + r.stderr
    return r.stdout


def test_status_contract(tmp_path, scripts, ws, swe, env):
    out = status(scripts, ws, env)
    assert re.match(r"^STATUS \[t=\d+s\] helpers v10\.0 \| repro: none \| checkpoints: 0\n", out)
    assert "JOURNAL: empty" in out and "DIFF: no source change" in out and lines(out)[-1].startswith("[t=")
    # journal tail of 8, diffstat, bounded diff, repro and checkpoint summaries
    code = ("for i in range(10):\n    C.journal({'h': 'run', 'msg': 'run echo %d: exit=0' % i, 't': 10 + i})\n"
            "def f(s):\n"
            "    s['repro'] = {'sha': 'x', 'orig': {'1': {'status': 'FAIL'}, '2': {'status': 'HANG'}}}\n"
            "    s['ckpts'] = [{'id': 1, 'score': [1, 1, 1, 1, 0, 0], 'verdict': 'RED', 't': 90.0},\n"
            "                  {'id': 2, 'score': [1, 1, 1, 1, 2, 0], 'verdict': 'GREEN', 't': 118.0}]\n"
            "C.state_update(f)\nprint(1)")
    assert run_py(scripts, code, env=env, cwd=ws).returncode == 0
    mod = ws / "pkg/mod.py"
    mod.write_text(mod.read_text().replace("    return x\n", "    return x * 2\n", 1))
    (ws / "pkg/new.py").write_text("NEW = 1\nOTHER = 2\n")
    (ws / "repro.py").write_text("print(1)\n")
    (ws / "tests/test_mod.py").write_text("def test_p():\n    pass\n")
    out = status(scripts, ws, env, "--ignored-arg")
    ls = lines(out)
    assert ls[0].endswith("| repro: 2 claims (fails on original) | checkpoints: 2 (best GREEN #2)")
    j = ls.index("JOURNAL (last 8):")
    assert ls[j + 1] == "  t=12s run echo 2: exit=0" and ls[j + 8] == "  t=19s run echo 9: exit=0"
    assert "DIFF: pkg/mod.py +1 -1 | pkg/new.py +2 -0" in out
    assert "PROTECTED (reverted by edit.py, verify.py and finalize.py): tests/test_mod.py" in out
    assert "UNTRACKED (not source): repro.py" in out
    assert "+    return x * 2" in out and "+NEW = 1" in out and "diff --git a/pkg/new.py b/pkg/new.py" in out
    assert "test_mod" not in out.split("DIFF:")[1].split("PROTECTED")[1].split("\n", 1)[1]   # diff: source only
    assert len(out.rstrip("\n")) <= 2200
    # repro summary variants
    code = ("C.state_update(lambda s: s.update(repro={'orig': {'1': {'status': 'PASS'}, '2': {'status': 'FAIL'}, "
            "'3': {'status': 'FAIL', 'broken': 'SyntaxError'}}}))\nprint(1)")
    assert run_py(scripts, code, env=env, cwd=ws).returncode == 0
    assert "| repro: 3 claims (1 fail on original, 1 pass on original, 1 broken) |" in status(scripts, ws, env)
    # CHANGED AFTER FINALIZE, and the FINAL banner while the tree still matches
    code = ("C.state_update(lambda s: s.update(final_done=True, final_sha=C.diff_sha(), final_t=131.0))\nprint(1)")
    assert run_py(scripts, code, env=env, cwd=ws).returncode == 0
    out = status(scripts, ws, env)
    assert "CHANGED AFTER FINALIZE" not in out and "FINAL: the patch was finalized at t=131s;" in out
    (ws / "pkg/new.py").write_text("NEW = 1\nOTHER = 3\n")
    out = status(scripts, ws, env)
    assert "CHANGED AFTER FINALIZE: run finalize.py again." in out and "FINAL:" not in out


def test_status_bounds_with_huge_diff_and_timing(tmp_path, scripts, swe):
    body = "".join("VALUE_%05d = %d\n" % (i, i) for i in range(40000))
    ws = make_repo(tmp_path, {"pkg/__init__.py": "", "pkg/big.py": body, "pkg/other.py": "A = 1\n"})
    env = helper_env(ws, swe)
    (ws / "pkg/big.py").write_text(body.replace(" = ", " =  "))                   # every line changes: 2+ MB diff
    (ws / "pkg/other.py").write_text("A = 2\n")
    assert int(git(ws, "diff", "--shortstat").split()[3]) == 40000 + 1
    status(scripts, ws, env)
    walls = []
    for _ in range(3):
        t0 = time.monotonic()
        out = status(scripts, ws, env)
        walls.append(time.monotonic() - t0)
    assert len(out.rstrip("\n")) <= 2200
    assert "DIFF: pkg/big.py +40000 -40000 | pkg/other.py +1 -1" in out, repr(out)
    assert "hunk bodies not shown" in out and "@@ " in out and lines(out)[-1].startswith("[t=")
    assert statistics.median(walls) <= 0.5, walls


def test_status_timing_small_repo(tmp_path, scripts, ws, env):
    mod = ws / "pkg/mod.py"
    mod.write_text(mod.read_text() + "X = 1\n")
    status(scripts, ws, env)
    walls = []
    for _ in range(5):
        t0 = time.monotonic()
        status(scripts, ws, env)
        walls.append(time.monotonic() - t0)
    assert statistics.median(walls) <= 0.5, walls
