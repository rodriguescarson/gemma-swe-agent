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


def test_verify_failures_are_the_arms_own_failure_not_infrastructure(tmp_path):
    c = rep.classify
    v = {"resolved": False, "error": "Failed to apply test_patch: git apply /tmp/sbx_x/work: patch does not apply", "agent_patch_size": 3066}
    assert c(v) == {"verify"}                                           # an unsolved task, neither an error nor excluded from the pairing
    assert c({"resolved": False, "error": "Tool 'python3 /tmp/swe/edit.py' not found", "agent_patch_size": 0}) == {"error", "empty"}
    assert "infra" in c({"resolved": False, "error": "litellm.APIConnectionError: Connection error.", "agent_patch_size": 0})
    assert "infra" in c({"resolved": False, "error": "EXC RuntimeError('x')", "agent_patch_size": 0})
    for i in range(4):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i == 0))
        put(tmp_path, "v6p", f"t{i}", resolved=False, error=("Failed to apply test_patch: boom" if i == 1 else None))
    c1 = rep.contrast(str(tmp_path), "v6p", "v4h2")
    assert c1["n"] == 4 and c1["losses"] == 1                          # the verify failure stays in the pairing (v4h2 solved t0; v6p did not)
    put(tmp_path, "v6p", "t2", resolved=False, error="litellm.APIConnectionError: x")
    assert rep.contrast(str(tmp_path), "v6p", "v4h2")["n"] == 3        # an infrastructure row is dropped from the pairing


def test_classify():
    c = rep.classify
    assert c({"resolved": True, "error": None, "agent_patch_size": 5}) == {"solved", }
    assert c({"resolved": False, "error": CAP, "agent_patch_size": 0}) == {"cap", "empty"}
    assert c({"resolved": False, "error": "Agent exceeded turns budget (150 turns)", "agent_patch_size": 3}) == {"budget"}
    assert c({"resolved": False, "error": "litellm.APIError: boom", "agent_patch_size": 0}) == {"error", "infra", "empty"}


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


def test_summarize_and_contrast_can_be_limited_to_a_set_of_ids(tmp_path):
    for i in range(6):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i == 0))
        put(tmp_path, "v6p", f"t{i}", resolved=(i in (0, 1, 2, 3)))
    s = rep.summarize(str(tmp_path), ["v6p"], ids=["t0", "t1", "t2"])
    assert s["v6p"]["n"] == 3 and s["v6p"]["solved"] == 3
    c = rep.contrast(str(tmp_path), "v6p", "v4h2", ids=["t0", "t1", "t2"])
    assert c["n"] == 3 and c["wins"] == 2 and c["losses"] == 0


def test_markdown_section_has_a_row_per_arm_and_a_verdict_per_contrast(tmp_path):
    spec3 = importlib.util.spec_from_file_location("p2_results_md", ROOT / "scripts" / "a6000" / "p2_results_md.py")
    md = importlib.util.module_from_spec(spec3); spec3.loader.exec_module(md)
    for i in range(10):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i < 2), secs=300.0)
        put(tmp_path, "v6p", f"t{i}", resolved=(i < 9), secs=320.0)
        put(tmp_path, "v6p-think", f"t{i}", resolved=(i < 2), secs=330.0, error=CAP if i > 6 else None)
    text, contrasts = md.section("stage 1a", str(tmp_path), [f"t{i}" for i in range(10)], ["v4h2", "v6p", "v6p-think"], "v4h2")
    assert "| v4h2 |" in text and "| v6p |" in text and "| v6p-think |" in text and "BETTER" in text
    assert contrasts["v6p"] == {"wins": 7, "losses": 0}
    assert "A6000 screen" in text


def test_contended_items_can_be_excluded_from_tables_and_pairings(tmp_path):
    for i in range(5):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i == 0))
        put(tmp_path, "v6p", f"t{i}", resolved=(i in (0, 1, 2)))
    ex = {("v6p", "t1")}
    s = rep.summarize(str(tmp_path), ["v6p"], exclude=ex)
    assert s["v6p"]["n"] == 4 and s["v6p"]["solved"] == 2                       # t1 (a v6p win) is out of the arm's own table
    c_all = rep.contrast(str(tmp_path), "v6p", "v4h2")
    c_ex = rep.contrast(str(tmp_path), "v6p", "v4h2", exclude=ex)
    assert (c_all["n"], c_all["wins"]) == (5, 2) and (c_ex["n"], c_ex["wins"]) == (4, 1)      # the whole task leaves the pairing
    assert rep.contrast(str(tmp_path), "v4h2", "v6p", exclude={("v4h2", "t2")})["n"] == 4   # contended in the base arm: also dropped


def test_markdown_shows_both_tables_when_a_contended_file_exists(tmp_path):
    spec3 = importlib.util.spec_from_file_location("p2_results_md2", ROOT / "scripts" / "a6000" / "p2_results_md.py")
    md = importlib.util.module_from_spec(spec3); spec3.loader.exec_module(md)
    for i in range(6):
        put(tmp_path, "v4h2", f"t{i}", resolved=(i < 2)); put(tmp_path, "v6p", f"t{i}", resolved=(i < 4)); put(tmp_path, "v6p-think", f"t{i}", resolved=False)
    cf = tmp_path / "contended.json"; cf.write_text(json.dumps({"items": [["v6p", "t3"]], "why": "ran while two runners were alive"}))
    text = md.both_tables("stage 1a", str(tmp_path), [f"t{i}" for i in range(6)], md.ARMS, "v4h2", str(cf))
    assert "all items" in text and "without contended items" in text and "v6p/t3" in text and text.count("| v6p |") >= 2
