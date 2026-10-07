"""v7b fix 1 in the harness's real subprocess sandbox (swegemma.sandbox.subprocess.SubprocessManager: /tmp and /workspace
are rewritten in command text, TMPDIR is the sandbox's own tmp, PYTHONPATH the workspace; research/harness_runtime.md
2.3-2.4). The run of refused reads lives in the cap ledger in the sandbox tmp, so it must persist from one run_command
call to the next through the /tmp rewrite, the way the box and the scorer run it. No model: the shell lines the v7b
prompts show, in stage order, through tests/test_v7_sandbox.py's fixture with its scripts dir pointed at v7b. v7's own
sandbox tests are re-run on v7b, except the ledger-shape one (v7b's ledger has one more key; the test below checks the
ledger's place and shape instead). Written before the change (strict test-first)."""
import json
from pathlib import Path

import pytest

import test_v7_sandbox as v7s
from test_v7_sandbox import m, sandbox_tmp  # noqa: F401  (m: a fresh sandbox workspace per test)

ROOT = Path(__file__).resolve().parents[1]
V7B = ROOT / "submissions" / "v7b"
SCRIPTS = V7B / "skills" / "swe-tools" / "scripts"
READ_CAP = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"
LAST = "outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py %s --lines A-B`"


@pytest.fixture(autouse=True)
def _v7b_bundle(monkeypatch):
    """skill() installs from, and verifier_repro_lines() reads, the bundle named by test_v7_sandbox's globals."""
    monkeypatch.setattr(v7s, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7s, "V7", V7B)


def ledger_through_the_rewrite(m):
    return json.loads(m.run_command("cat /tmp/swe/.ledger.json").stdout)


def test_the_refused_read_run_persists_across_calls_through_the_tmp_rewrite(m):
    assert "installed:" in v7s.skill(m, "install.py")
    swe = sandbox_tmp(m) / "swe"
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False, "refused_run": 0}
    for i in range(14):
        assert m.run_command(f"python3 /tmp/swe/view.py m.py {10 * i + 1}-{10 * i + 5}").stdout.startswith(f"{10 * i + 1}| ")
    outs, runs = [], []
    for _ in range(6):                                                  # one run_command call each, a new process each
        r = m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2")
        assert r.exit_code == 0, r.stderr
        outs.append(r.stdout.strip())
        runs.append(ledger_through_the_rewrite(m)["refused_run"])
    outline = "1-2 def f(x)\n" + LAST % "pkg/mod.py"
    assert outs == [READ_CAP, READ_CAP, outline, READ_CAP, READ_CAP, outline], outs
    assert runs == [1, 2, 0, 1, 2, 0]
    led = json.loads((swe / ".ledger.json").read_text())
    assert led == ledger_through_the_rewrite(m) == {"locate": 0, "view": 14, "edited": False, "refused_run": 0}, led
    for _ in range(2):
        assert m.run_command("python3 /tmp/swe/view.py pkg/mod.py 1 2").stdout.strip() == READ_CAP
    ok = m.run_command("python3 /tmp/swe/edit.py pkg/mod.py --lines 2-2 <<'EOF'\n    return x * 2\nEOF")
    assert ok.stdout.startswith("OK pkg/mod.py"), ok.stdout + ok.stderr
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 0, "view": 14, "edited": True, "refused_run": 0}
    assert m.run_command("python3 /tmp/swe/view.py m.py 200 210").stdout.startswith("200| ")   # uncapped after the edit
    assert (swe / ".views.json").exists()                                # the ledger still sits next to the views log


V7_LEDGER_SHAPE = "test_the_cap_ledger_lives_in_the_sandbox_tmp_next_to_the_views_log"
V7_TESTS = sorted(n for n in vars(v7s) if n.startswith("test_") and callable(getattr(v7s, n)))
for _name in V7_TESTS:
    if _name != V7_LEDGER_SHAPE:                                        # replaced by the test above
        globals()["test_v7_rerun_" + _name[len("test_"):]] = getattr(v7s, _name)


def test_every_v7_sandbox_test_is_rerun_on_v7b_but_the_ledger_shape():
    assert len(V7_TESTS) == 3 and V7_LEDGER_SHAPE in V7_TESTS
    assert {n for n in globals() if n.startswith("test_v7_rerun_")} == {
        "test_v7_rerun_" + n[len("test_"):] for n in V7_TESTS if n != V7_LEDGER_SHAPE}
