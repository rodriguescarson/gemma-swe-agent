"""scripts/a6000/p2_report.py: per-arm table, paired contrasts, health flags for a p2_race.py output dir. Written before the code."""
import importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))
spec = importlib.util.spec_from_file_location("p2_report", ROOT / "scripts" / "a6000" / "p2_report.py")
rep = importlib.util.module_from_spec(spec); spec.loader.exec_module(rep)

CAP = "Agent exceeded session timeout (5.0 min)"


def put(out, arm, task, resolved=False, secs=100.0, error=None, patch=10, calls=5, trace_calls=None):
    d = out / "items" / arm / task
    d.mkdir(parents=True, exist_ok=True)
    (d / "task_results.jsonl").write_text(json.dumps({"instance_id": task, "resolved": resolved, "duration_seconds": secs,
                                                      "error": error, "agent_patch_size": patch, "tool_calls": calls}) + "\n")
    if trace_calls is not None:
        (d / "traces").mkdir(exist_ok=True)
        steps = [{"source": "agent", "tool_calls": [{"function_name": n, "arguments": a}], "extra": {"author": "fixer"}} for n, a in trace_calls]
        (d / "traces" / f"trace_{task}.json").write_text(json.dumps({"steps": steps}))


def test_classify():
    c = rep.classify
    assert c({"resolved": True, "error": None, "agent_patch_size": 5}) == {"solved", }
    assert c({"resolved": False, "error": CAP, "agent_patch_size": 0}) == {"cap", "empty"}
    assert c({"resolved": False, "error": "Agent exceeded turns budget (150 turns)", "agent_patch_size": 3}) == {"budget"}
    assert c({"resolved": False, "error": "litellm.APIError: boom", "agent_patch_size": 0}) == {"error", "empty"}


def test_stats_and_flags(tmp_path):
    for i in range(10):
        put(tmp_path, "v4h2", f"t{i}", resolved=i < 4, secs=40 + i)           # median ~44 s -> flag
    for i in range(10):
        put(tmp_path, "v6p", f"t{i}", resolved=i < 6, secs=200.0, error=("litellm.APIError" if i < 2 else (CAP if i == 9 else None)))
    s = rep.summarize(str(tmp_path), ["v4h2", "v6p"])
    assert s["v4h2"]["n"] == 10 and s["v4h2"]["solved"] == 4 and s["v4h2"]["median_s"] == 44.5
    assert "median under 60 s" in s["v4h2"]["flags"] and not any("errored" in f for f in s["v4h2"]["flags"])
    assert s["v6p"]["errors"] == 2 and s["v6p"]["cap"] == 1 and any("errored" in f for f in s["v6p"]["flags"])


def test_loops_count_identical_calls_in_a_row(tmp_path):
    same = [("run_command", {"command": "ls"})] * 5
    put(tmp_path, "v6p", "a", trace_calls=same)
    put(tmp_path, "v6p", "b", trace_calls=same[:4] + [("view", {})] + same[:4])
    assert rep.summarize(str(tmp_path), ["v6p"])["v6p"]["loops"] == 1


def test_paired_contrast_excludes_error_rows_and_reports_cap_gap(tmp_path):
    for i in range(12):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i in (0, 1)), secs=100.0)
        put(tmp_path, "v6p", f"t{i}", resolved=(i in range(2, 10)), secs=100.0, error=CAP if i >= 10 else None)
    put(tmp_path, "v6p", "t0", resolved=False, error="litellm.APIError: boom")        # infra error: dropped from the pairing
    c = rep.contrast(str(tmp_path), "v6p", "v4h2")
    assert c["n"] == 11 and c["wins"] == 8 and c["losses"] == 1 and c["verdict"] in ("BETTER", "NO EVIDENCE")
    assert abs(c["cap_gap"] - 2 / 12) < 1e-9
