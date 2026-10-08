"""v7d fix 1 in the harness's real subprocess sandbox (swegemma.sandbox.subprocess.SubprocessManager: /tmp and /workspace
are rewritten in command text, TMPDIR is the sandbox's own tmp, PYTHONPATH the workspace; research/harness_runtime.md
2.3-2.4). An identical re-read of an unchanged range prints its lines again under one SHOWN AGAIN line, one run_command
call each, a new process each, with v7c's run of re-reads persisting in the ledger through the /tmp rewrite: again, again,
outline, again, again, outline; an OK edit resets it and the edited range reads plainly again. The locate cap (3) is
unchanged through the rewrite. No model: the shell lines the prompts show, through tests/test_v7_sandbox.py's fixture with
its scripts dir pointed at v7d. v7c's own sandbox tests are re-run on v7d, except the two that assert the ALREADY SHOWN
line (replaced below). Written before the change (strict test-first)."""
import json
from pathlib import Path

import pytest

import test_v7_sandbox as v7s
import test_v7c_sandbox as v7cs
from test_v7_sandbox import m, sandbox_tmp  # noqa: F401  (m: a fresh sandbox workspace per test)

ROOT = Path(__file__).resolve().parents[1]
V7D = ROOT / "submissions" / "v7d"
SCRIPTS = V7D / "skills" / "swe-tools" / "scripts"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"
LINES = "1| def f(x):\n2|     return x\n"
AGAIN = ("SHOWN AGAIN: pkg/mod.py lines 1-2 are unchanged since they were shown earlier in this task, so use them now instead "
         "of viewing them again\n" + LINES)
OUTLINE = "1-2 def f(x)\noutline only: pick a range and edit it now with `python3 /tmp/swe/edit.py pkg/mod.py --lines A-B`\n"


@pytest.fixture(autouse=True)
def _v7d_bundle(monkeypatch):
    """skill() installs from, and verifier_repro_lines() reads, the bundle named by test_v7_sandbox's globals."""
    monkeypatch.setattr(v7s, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7s, "V7", V7D)
    monkeypatch.setattr(v7cs, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7cs, "V7C", V7D)


def ledger_through_the_rewrite(m):
    return json.loads(m.run_command("cat /tmp/swe/.ledger.json").stdout)


def test_a_re_read_prints_the_lines_again_and_the_run_persists_across_calls_through_the_tmp_rewrite(m):
    assert "installed:" in v7s.skill(m, "install.py")
    swe = sandbox_tmp(m) / "swe"
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False, "repeat_key": None, "repeat_run": 0}
    for i in range(16):                                                 # distinct reads: plain lines, no note
        r = m.run_command(f"python3 /tmp/swe/view.py m.py {10 * i + 1}-{10 * i + 5}")
        assert r.exit_code == 0 and r.stdout.splitlines() == [f"{n}| line{n}" for n in range(10 * i + 1, 10 * i + 6)], r.stdout
    assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout == LINES
    outs, runs = [], []
    for _ in range(6):                                                  # one run_command call each, a new process each
        r = m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2")
        assert r.exit_code == 0, r.stderr
        outs.append(r.stdout)
        runs.append(ledger_through_the_rewrite(m)["repeat_run"])
    assert outs == [AGAIN, AGAIN, OUTLINE, AGAIN, AGAIN, OUTLINE], outs
    assert runs == [1, 2, 0, 1, 2, 0]
    led = json.loads((swe / ".ledger.json").read_text())
    assert led == ledger_through_the_rewrite(m) == {"locate": 0, "view": 23, "edited": False, "repeat_key": "pkg/mod.py:1-2",
                                                    "repeat_run": 0}, led
    for q in ("f", "mod", "x"):
        assert "workspace=" in m.run_command(f'python3 /tmp/swe/locate.py "{q}"').stdout
    assert m.run_command('python3 /tmp/swe/locate.py "f"').stdout.strip() == SEARCH_CAP     # the locate cap is unchanged
    for _ in range(2):
        assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout == AGAIN
    ok = m.run_command("python3 /tmp/swe/edit.py pkg/mod.py --lines 2-2 <<'EOF'\n    return x * 2\nEOF")
    assert ok.stdout.startswith("OK pkg/mod.py"), ok.stdout + ok.stderr
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 3, "view": 25, "edited": True, "repeat_key": None, "repeat_run": 0}
    assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout == "1| def f(x):\n2|     return x * 2\n"   # changed: plain
    fixed = AGAIN.replace(LINES, "1| def f(x):\n2|     return x * 2\n")
    assert [m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout for _ in range(3)] == [fixed, fixed, OUTLINE]
    assert (swe / ".views.json").exists()                                # the ledger still sits next to the views log
    assert "ALREADY SHOWN" not in "".join(outs) + fixed


def test_view_shapes_through_the_rewrite(m):
    v7s.skill(m, "install.py")
    a = m.run_command("python3 /tmp/swe/view.py m.py 30-40").stdout
    assert a.startswith("30| line30") and a.splitlines()[-1] == "40| line40", a
    b = m.run_command("python3 /tmp/swe/view.py m.py 30:40").stdout     # the same range in another shape: shown again
    assert b.startswith("SHOWN AGAIN: m.py lines 30-40 ") and b.splitlines()[1:] == a.splitlines(), b
    c = m.run_command("python3 /tmp/swe/view.py m.py").stdout
    assert c.startswith("1| line1") and c.strip().splitlines()[-1] == "120| line120", c[-200:]


REPLACED = {"test_sixteen_distinct_reads_then_the_repeat_run_persists_across_calls_through_the_tmp_rewrite":
            "test_a_re_read_prints_the_lines_again_and_the_run_persists_across_calls_through_the_tmp_rewrite",
            "test_v7_rerun_view_shapes_through_the_rewrite": "test_view_shapes_through_the_rewrite",
            "test_every_v7_sandbox_test_is_rerun_on_v7c_but_the_cap_ledger_one": "test_every_v7c_sandbox_test_is_rerun_on_v7d_but_the_replaced_ones"}
V7C_TESTS = sorted(n for n in vars(v7cs) if n.startswith("test_") and callable(getattr(v7cs, n)))
for _name in V7C_TESTS:
    if _name not in REPLACED:
        globals()["test_v7c_rerun_" + _name[len("test_"):]] = getattr(v7cs, _name)


def test_every_v7c_sandbox_test_is_rerun_on_v7d_but_the_replaced_ones():
    assert set(REPLACED) <= set(V7C_TESTS), set(REPLACED) - set(V7C_TESTS)
    assert {n for n in globals() if n.startswith("test_v7c_rerun_")} == {
        "test_v7c_rerun_" + n[len("test_"):] for n in V7C_TESTS if n not in REPLACED}
    assert all(callable(globals().get(r)) for r in REPLACED.values())
