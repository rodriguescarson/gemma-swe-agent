"""scripts/analyze_helper_reachability.py: per run, how many tasks hit "can't open file" on a /tmp/swe helper and WHY
(helper before any install / install in the same response / failure after the helper had worked). Written first."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_helper_reachability.py"
CANT = "python3: can't open file '/tmp/sbx/tmp/swe/locate.py': [Errno 2] No such file or directory"


def _step(author, calls, obs):
    return {"source": "agent", "tool_calls": [dict(c, extra={"author": author}) for c in calls], "observation": {"content": obs}}


def _inst():
    return {"function_name": "run_skill_script", "arguments": {"skill_name": "swe-tools", "file_path": "install.py"}}


def _loc():
    return {"function_name": "run_command", "arguments": {"command": 'python3 /tmp/swe/locate.py "x"'}}


def _write(d, name, steps):
    p = d / "results" / "traces"; p.mkdir(parents=True, exist_ok=True)
    (p / f"trace_{name}.json").write_text(json.dumps({"steps": [{"source": "user", "message": "task"}] + steps}))


def test_classifies_first_failures_and_counts(tmp_path):
    run = tmp_path / "run"
    _write(run, "a", [_step("locator", [_loc()], CANT), _step("locator", [_inst()], "installed"), _step("locator", [_loc()], "ok")])
    _write(run, "b", [_step("setup", [_inst()], "installed"), _step("locator", [_loc()], "ok")])
    _write(run, "c", [_step("locator", [_inst(), _loc()], CANT)])
    _write(run, "d", [_step("locator", [_inst()], "installed"), _step("locator", [_loc()], "ok"), _step("fixer", [_loc()], CANT)])
    r = subprocess.run([sys.executable, str(SCRIPT), "--json", str(run)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)[str(run)]
    assert rep["tasks"] == 4 and rep["tasks_with_failure"] == 3
    assert rep["first_failure"] == {"helper_before_install": 1, "install_same_response": 1, "after_helper_worked": 1}
    assert rep["helpers"]["locate"] == {"ok": 3, "fail": 3}


def test_gate_mode_fails_when_any_task_has_a_failure(tmp_path):
    run = tmp_path / "run"
    _write(run, "a", [_step("locator", [_loc()], CANT)])
    r = subprocess.run([sys.executable, str(SCRIPT), "--max-tasks-with-failure", "0", str(run)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "FAIL" in r.stdout
