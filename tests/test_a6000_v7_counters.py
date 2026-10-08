"""scripts/a6000/v7_counters.py: the forensics counters v7 is judged by (docs/GAPS_2026-10-06.md last section, PROMPTS P6), computed from a run's traces.
Written before the code."""
import importlib.util, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "a6000")); sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("v7_counters", ROOT / "scripts" / "a6000" / "v7_counters.py")
vc = importlib.util.module_from_spec(spec); spec.loader.exec_module(vc)


def _step(author, fn, args, payload):
    return {"source": "agent", "extra": {"author": author}, "tool_calls": [{"function_name": fn, "arguments": args}], "observation": {"content": json.dumps(payload)}}


def ok(stdout=""):
    return {"status": "ok", "stdout": stdout, "stderr": "", "exit_code": 0}


def cmd_err(stdout="", stderr=""):
    return {"status": "error", "error_type": "CommandError", "error_message": "", "details": {"stdout": stdout, "stderr": stderr, "exit_code": 1}}


def _write(out, arm, task, steps, resolved=False, layout="items"):
    if layout == "items":
        d = out / "items" / arm / task; d.mkdir(parents=True, exist_ok=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": task, "resolved": resolved, "agent_patch_size": 5, "error": None}) + "\n")
        (d / "traces").mkdir(exist_ok=True); (d / "traces" / f"trace_{task}.json").write_text(json.dumps({"steps": steps}))
    else:
        (out / "results" / "traces").mkdir(parents=True, exist_ok=True)
        (out / "results" / "traces" / f"trace_{task}.json").write_text(json.dumps({"steps": steps}))
        with open(out / "results.jsonl", "a") as f:
            f.write(json.dumps({"id": task, "resolved": resolved, "secs": 10, "err": None, "patch": "x"}) + "\n")


def test_counters_over_an_items_layout(tmp_path):
    bud = {"status": "error", "error_type": "BudgetExceeded", "error_message": "Tool call budget exhausted (70 calls)"}
    _write(tmp_path, "v7", "t1", [
        _step("locator", "run_command", {"command": "python3 /tmp/swe/view.py a.py 30-40"}, ok("usage: python3 /tmp/swe/view.py FILE START END")),
        _step("locator", "run_command", {"command": 'run_command(command="git grep x")'}, cmd_err(stderr="syntax error near unexpected token")),
        _step("verifier", "write_file", {"filepath": "/tmp/repro.py", "content": "x"}, {"status": "error", "error_type": "FileWriteError", "error_message": "Path traversal detected: '/tmp/repro.py' escapes workspace root."}),
        _step("fixer", "run_skill_script", {}, {"error": "Argument 'skill_name' is required.", "error_code": "INVALID_ARGUMENTS"}),
        _step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py x"}, ok("SHARE SPENT: your 5 counted helper calls are used")),
        _step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py y"}, cmd_err(stderr="python3: can't open file '/tmp/sbx/tmp/swe/locate.py': [Errno 2]"))] +
        [_step("fixer", "run_command", {"command": "git grep z"}, cmd_err()) for _ in range(5)] + [_step("verifier", "run_command", {"command": "git diff"}, bud)], resolved=True)
    _write(tmp_path, "v7", "t2", [_step("fixer", "run_command", {"command": "ls"}, ok("a"))], resolved=False)
    c = vc.counters(str(tmp_path), "v7")
    assert c["tasks"] == 2 and c["solved"] == 1
    assert c["view_usage_calls"] == 1 and c["literal_wrapper_commands"] == 1 and c["write_file_path_refusals"] == 1 and c["forced_install_empty_args"] == 1
    assert c["cap_refusals"] == 1 and c["loops_ge5"] == 1 and c["budget_exhausted_tasks"] == 1 and c["helper_unreachable_tasks"] == 1
    assert c["examples"]["view_usage_calls"][0]["task"] == "t1" and "view.py" in c["examples"]["view_usage_calls"][0]["call"]


def test_counters_over_a_p4_layout_and_the_must_zero_verdict(tmp_path):
    _write(tmp_path, "v7", "a", [_step("fixer", "run_command", {"command": "ls"}, ok("x"))], resolved=True, layout="p4")
    _write(tmp_path, "v7", "b", [_step("locator", "run_command", {"command": "python3 /tmp/swe/view.py f.py 1-9"}, ok("usage: python3 /tmp/swe/view.py FILE START END"))], layout="p4")
    c = vc.counters(str(tmp_path), None)
    assert c["tasks"] == 2 and c["solved"] == 1 and c["view_usage_calls"] == 1 and c["literal_wrapper_commands"] == 0
    v = vc.verdict(c, must_zero=("view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args"))
    assert v["pass"] is False and v["failing"] == ["view_usage_calls"]
    text = vc.markdown(c, v)
    assert "view_usage_calls" in text and "FAIL" in text and "b" in text                        # the example task is named


def test_counters_can_read_a_probe_layout_via_items_dir(tmp_path):
    d = tmp_path / "probe_v7_T2" / "v7" / "t1"; d.mkdir(parents=True)
    (d / "task_results.jsonl").write_text(json.dumps({"instance_id": "t1", "resolved": True, "agent_patch_size": 5, "error": None}) + "\n")
    (d / "traces").mkdir(); (d / "traces" / "trace_t1.json").write_text(json.dumps({"steps": [_step("fixer", "run_command", {"command": "ls"}, ok("x"))]}))
    c = vc.counters(str(tmp_path), "v7", items_dir="probe_v7_T2")
    assert c["tasks"] == 1 and c["solved"] == 1


OUTLINE_REPLY = ("4-7 def f(x)\n10-11 def g()\n"
                 "outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py pkg/e.py --lines A-B`")


def _v7c_run(tmp_path):
    """Two outline replies (v7b/v7c view.py) and the three cap texts (v7's search and read cap, v6p-b's SHARE SPENT)."""
    view = _step("fixer", "run_command", {"command": "python3 /tmp/swe/view.py pkg/e.py 4 8"}, ok(OUTLINE_REPLY))
    _write(tmp_path, "v7c", "t1", [view, view,
        _step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py x"}, ok("search cap reached: use `git grep -n <name>` or write the plan now")),
        _step("fixer", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1 5"}, ok("read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)")),
        _step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py y"}, ok("SHARE SPENT: your 5 counted helper calls are used"))], resolved=True)
    return tmp_path


def test_repeat_outlines_is_its_own_counter_and_cap_refusals_keeps_only_the_cap_texts(tmp_path):
    """2026-10-08, v7c pre-registration (docs/GAPS_2026-10-06.md): the outline answers an identical re-read, not a cap,
    so "outline only:" is counted under repeat_outlines and no longer under cap_refusals (SHARE SPENT, search cap
    reached, read cap reached). Written before the counter split (test-first)."""
    c = vc.counters(str(_v7c_run(tmp_path)), "v7c")
    assert c["repeat_outlines"] == 2 and c["cap_refusals"] == 3, {k: c[k] for k in vc.COUNTERS}
    assert vc.COUNTERS.index("repeat_outlines") == vc.COUNTERS.index("cap_refusals") + 1
    assert [e["task"] for e in c["examples"]["repeat_outlines"]] == ["t1", "t1"]
    assert c["view_usage_calls"] == 0                                     # an outline is never a usage line


def test_repeat_outlines_is_reported_not_gated_and_the_cli_is_unchanged(tmp_path):
    out = tmp_path / "c.json"
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "v7_counters.py"), str(_v7c_run(tmp_path / "run")),
                        "--arm", "v7c", "--json", str(out)], capture_output=True, text=True)
    assert p.returncode == 0 and "must-be-zero verdict: **PASS**" in p.stdout, p.stdout + p.stderr
    head, rule, row = p.stdout.splitlines()[:3]
    cols = [x.strip() for x in head.strip("|").split("|")]
    vals = [x.strip() for x in row.strip("|").split("|")]
    assert cols == ["tasks", "solved"] + list(vc.COUNTERS) and dict(zip(cols, vals))["repeat_outlines"] == "2", p.stdout
    assert dict(zip(cols, vals))["cap_refusals"] == "3" and rule.count("---") == len(cols)
    d = json.loads(out.read_text())
    assert d["counters"]["repeat_outlines"] == 2 and d["verdict"]["pass"] is True
    assert d["verdict"]["must_zero"] == ["view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args"]
