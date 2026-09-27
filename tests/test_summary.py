"""eval/summary.py drives the final submission decision; it must count solved/empty/timeouts and paired wins correctly."""
import json, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).parent.parent

def run_dir(tmp, name, rows):
    d = tmp / name; (d / "traces").mkdir(parents=True)
    (d / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d

def test_summary_counts_and_pairs(tmp_path):
    base = run_dir(tmp_path, "base", [
        {"instance_id": "a", "resolved": True, "agent_patch_size": 10, "duration_seconds": 100, "tool_calls": 10},
        {"instance_id": "b", "resolved": False, "agent_patch_size": 0, "duration_seconds": 360, "tool_calls": 50, "error": "Agent exceeded session timeout (6.0 min)"}])
    new = run_dir(tmp_path, "new", [
        {"instance_id": "a", "resolved": False, "agent_patch_size": 5, "duration_seconds": 80, "tool_calls": 8},
        {"instance_id": "b", "resolved": True, "agent_patch_size": 9, "duration_seconds": 120, "tool_calls": 12}])
    out = subprocess.run([sys.executable, str(ROOT / "eval/summary.py"), str(base), str(new)], capture_output=True, text=True).stdout
    b = next(l for l in out.splitlines() if l.startswith("base")).split()
    n = next(l for l in out.splitlines() if l.startswith("new")).split()
    assert b[1:5] == ["2", "1", "1", "1"]          # n, solved, empty, timeouts
    assert n[1:5] == ["2", "1", "0", "0"]
    assert "1/1" in " ".join(n)                     # one win, one loss vs base
