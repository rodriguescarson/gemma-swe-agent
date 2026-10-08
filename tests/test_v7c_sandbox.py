"""v7c fixes 1 and 2 in the harness's real subprocess sandbox (swegemma.sandbox.subprocess.SubprocessManager: /tmp and
/workspace are rewritten in command text, TMPDIR is the sandbox's own tmp, PYTHONPATH the workspace;
research/harness_runtime.md 2.3-2.4). No read cap: 16 distinct reads (past v7's 14) all print their lines. The run of
identical re-reads lives in the ledger in the sandbox tmp, so it must persist from one run_command call to the next
through the /tmp rewrite, the way the box and the scorer run it: line, line, outline, line, line, outline; an OK edit
resets it and the edited range reads again. The locate cap (3) is unchanged through the rewrite. No model: the shell
lines the prompts show, through tests/test_v7_sandbox.py's fixture with its scripts dir pointed at v7c. v7's own sandbox
tests are re-run on v7c, except the cap-ledger one (it expects the read-cap line after 14 reads; replaced below).
Written before the change (strict test-first)."""
import json
from pathlib import Path

import pytest

import test_v7_sandbox as v7s
from test_v7_sandbox import m, sandbox_tmp  # noqa: F401  (m: a fresh sandbox workspace per test)

ROOT = Path(__file__).resolve().parents[1]
V7C = ROOT / "submissions" / "v7c"
SCRIPTS = V7C / "skills" / "swe-tools" / "scripts"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"
ALREADY = ("ALREADY SHOWN: pkg/mod.py lines 1-2 are unchanged since you saw them, so edit now with python3 /tmp/swe/edit.py "
           "or view different lines instead")
OUTLINE = "1-2 def f(x)\noutline only: pick a range and edit it now with `python3 /tmp/swe/edit.py pkg/mod.py --lines A-B`"


@pytest.fixture(autouse=True)
def _v7c_bundle(monkeypatch):
    """skill() installs from, and verifier_repro_lines() reads, the bundle named by test_v7_sandbox's globals."""
    monkeypatch.setattr(v7s, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7s, "V7", V7C)


def ledger_through_the_rewrite(m):
    return json.loads(m.run_command("cat /tmp/swe/.ledger.json").stdout)


def test_sixteen_distinct_reads_then_the_repeat_run_persists_across_calls_through_the_tmp_rewrite(m):
    assert "installed:" in v7s.skill(m, "install.py")
    swe = sandbox_tmp(m) / "swe"
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False, "repeat_key": None, "repeat_run": 0}
    for i in range(16):                                                 # past v7's cap of 14: every read prints its lines
        r = m.run_command(f"python3 /tmp/swe/view.py m.py {10 * i + 1}-{10 * i + 5}")
        assert r.exit_code == 0 and r.stdout.splitlines() == [f"{n}| line{n}" for n in range(10 * i + 1, 10 * i + 6)], r.stdout
    assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout == "1| def f(x):\n2|     return x\n"
    outs, runs = [], []
    for _ in range(6):                                                  # one run_command call each, a new process each
        r = m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2")
        assert r.exit_code == 0, r.stderr
        outs.append(r.stdout.strip())
        runs.append(ledger_through_the_rewrite(m)["repeat_run"])
    assert outs == [ALREADY, ALREADY, OUTLINE, ALREADY, ALREADY, OUTLINE], outs
    assert runs == [1, 2, 0, 1, 2, 0]
    led = json.loads((swe / ".ledger.json").read_text())
    assert led == ledger_through_the_rewrite(m) == {"locate": 0, "view": 23, "edited": False, "repeat_key": "pkg/mod.py:1-2",
                                                    "repeat_run": 0}, led
    for q in ("f", "mod", "x"):
        assert "workspace=" in m.run_command(f'python3 /tmp/swe/locate.py "{q}"').stdout
    assert m.run_command('python3 /tmp/swe/locate.py "f"').stdout.strip() == SEARCH_CAP     # the locate cap is unchanged
    for _ in range(2):
        assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout.strip() == ALREADY
    ok = m.run_command("python3 /tmp/swe/edit.py pkg/mod.py --lines 2-2 <<'EOF'\n    return x * 2\nEOF")
    assert ok.stdout.startswith("OK pkg/mod.py"), ok.stdout + ok.stderr
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 3, "view": 25, "edited": True, "repeat_key": None, "repeat_run": 0}
    assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout == "1| def f(x):\n2|     return x * 2\n"   # changed: shown
    assert [m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout.strip() for _ in range(3)] == [ALREADY, ALREADY, OUTLINE]
    assert (swe / ".views.json").exists()                                # the ledger still sits next to the views log


V7_CAP_LEDGER = "test_the_cap_ledger_lives_in_the_sandbox_tmp_next_to_the_views_log"
V7_TESTS = sorted(n for n in vars(v7s) if n.startswith("test_") and callable(getattr(v7s, n)))
for _name in V7_TESTS:
    if _name != V7_CAP_LEDGER:                                          # replaced by the test above
        globals()["test_v7_rerun_" + _name[len("test_"):]] = getattr(v7s, _name)


def test_every_v7_sandbox_test_is_rerun_on_v7c_but_the_cap_ledger_one():
    assert len(V7_TESTS) == 3 and V7_CAP_LEDGER in V7_TESTS
    assert {n for n in globals() if n.startswith("test_v7_rerun_")} == {
        "test_v7_rerun_" + n[len("test_"):] for n in V7_TESTS if n != V7_CAP_LEDGER}
