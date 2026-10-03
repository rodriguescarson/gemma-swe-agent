"""scripts/analyze_failures.py: classify every unsolved task of an L4 run (results.jsonl + traces/) into one failure
class, with the gold files from tasks.jsonl. Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_failures.py"


def _trace(calls, last_author="fixer"):
    steps = [{"step_id": 1, "source": "user", "message": "task"}]
    for i, (name, args, obs) in enumerate(calls, start=2):
        steps.append({"step_id": i, "source": "agent", "tool_calls": [{"function_name": name, "arguments": args,
                      "extra": {"author": last_author, "elapsed_s": 10.0}}], "observation": {"content": obs}})
    return {"schema_version": 1, "steps": steps, "final_metrics": {}}


def test_classes_and_summary(tmp_path):
    gold = "--- a/src/pkg/core.py\n+++ b/src/pkg/core.py\n@@ -1 +1 @@\n-a\n+b\n"
    (tmp_path / "tasks.jsonl").write_text("".join(json.dumps({"instance_id": f"t{i}", "patch": gold}) + "\n" for i in range(6)))
    rows = [
        {"id": "t0", "resolved": True, "err": None, "patch": gold, "secs": 100, "calls": 10},
        {"id": "t1", "resolved": False, "err": "Sandbox execution error: Extra data", "patch": "", "secs": 50, "calls": 3},
        {"id": "t2", "resolved": False, "err": "Agent exceeded session timeout (5.0 min)", "patch": "", "secs": 305, "calls": 40},
        {"id": "t3", "resolved": False, "err": None, "patch": "", "secs": 200, "calls": 30},
        {"id": "t4", "resolved": False, "err": None, "patch": "diff --git a/src/pkg/other.py b/src/pkg/other.py\n--- a/src/pkg/other.py\n+++ b/src/pkg/other.py\n@@ -1 +1 @@\n-x\n+y\n", "secs": 200, "calls": 30},
        {"id": "t5", "resolved": False, "err": None, "patch": "diff --git a/src/pkg/core.py b/src/pkg/core.py\n--- a/src/pkg/core.py\n+++ b/src/pkg/core.py\n@@ -1 +1 @@\n-a\n+c\n", "secs": 200, "calls": 30},
    ]
    run = tmp_path / "run"; (run / "traces").mkdir(parents=True)
    (run / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for r in rows:
        calls = [("run_command", {"command": "python3 /tmp/swe/edit.py src/pkg/core.py"}, '{"status": "ok"}'),
                 ("run_command", {"command": "pytest -q tests/test_core.py"}, "1 failed"),
                 ("run_command", {"command": "sleep 500"}, '{"status": "error", "error_message": "Command timed out after 180s"}')]
        (run / "traces" / f"trace_{r['id']}.json").write_text(json.dumps(_trace(calls)))
    out = tmp_path / "report.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(run), "--tasks", str(tmp_path / "tasks.jsonl"), "--out", str(out)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    rep = json.loads(out.read_text())
    cls = {t["id"]: t["class"] for t in rep["tasks"]}
    assert cls == {"t1": "crash", "t2": "timeout_no_patch", "t3": "no_patch", "t4": "wrong_files", "t5": "right_file_wrong_fix"}
    assert rep["summary"]["solved"] == 1 and rep["summary"]["unsolved"] == 5
    assert rep["summary"]["classes"]["wrong_files"] == 1
    t5 = next(t for t in rep["tasks"] if t["id"] == "t5")
    assert t5["edit_calls"] == 1 and t5["test_runs"] == 1 and t5["cmd_timeouts"] == 1 and t5["gold_files"] == ["src/pkg/core.py"]
    assert "wrong_files" in r.stdout and "right_file_wrong_fix" in r.stdout


def test_pallets_run_format(tmp_path):
    """scripts/pallets/run_eval_pallets.py writes task_results.jsonl with instance_id / resolved as a string / error /
    duration_seconds / tool_calls and the diff under patches/<id>.patch; the taxonomy must read that layout too."""
    gold = "--- a/src/click/core.py\n+++ b/src/click/core.py\n@@ -1 +1 @@\n-a\n+b\n"
    (tmp_path / "tasks.jsonl").write_text(json.dumps({"instance_id": "click_1", "patch": gold}) + "\n"
                                          + json.dumps({"instance_id": "click_2", "patch": gold}) + "\n")
    run = tmp_path / "s1"; (run / "patches").mkdir(parents=True); (run / "traces").mkdir()
    (run / "task_results.jsonl").write_text(
        json.dumps({"instance_id": "click_1", "resolved": "False", "error": None, "duration_seconds": "200.5", "tool_calls": "12"}) + "\n"
        + json.dumps({"instance_id": "click_2", "resolved": "True", "error": None, "duration_seconds": "100", "tool_calls": "9"}) + "\n")
    (run / "patches" / "click_1.patch").write_text("diff --git a/src/click/core.py b/src/click/core.py\n--- a/src/click/core.py\n+++ b/src/click/core.py\n@@ -1 +1 @@\n-a\n+c\n")
    out = tmp_path / "rep.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(run), "--tasks", str(tmp_path / "tasks.jsonl"), "--out", str(out)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    rep = json.loads(out.read_text())
    assert rep["summary"]["solved"] == 1 and rep["summary"]["unsolved"] == 1
    t = rep["tasks"][0]
    assert t["id"] == "click_1" and t["class"] == "right_file_wrong_fix" and t["secs"] == 200.5 and t["calls"] == 12
