"""scripts/a6000/forensics_lib.py: pure classification of stored traces (docs/a6000/FAILURE_FORENSICS.md, P5). Written before the code."""
import importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "a6000"))
spec = importlib.util.spec_from_file_location("forensics_lib", ROOT / "scripts" / "a6000" / "forensics_lib.py")
fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)


def _obs(payload):
    return {"content": json.dumps(payload)}


def _step(author, fn, args, payload, sid=1):
    return {"step_id": sid, "source": "agent", "extra": {"author": author}, "tool_calls": [{"function_name": fn, "arguments": args}], "observation": _obs(payload)}


def _msg(author, text, sid=1):
    return {"step_id": sid, "source": "agent", "extra": {"author": author}, "message": text}


def _trace(steps):
    return {"steps": steps}


def cmd_err(stdout="", stderr="", msg=""):
    return {"status": "error", "error_type": "CommandError", "error_message": msg, "details": {"stdout": stdout, "stderr": stderr, "exit_code": 1}}


def ok(stdout=""):
    return {"status": "ok", "stdout": stdout, "stderr": "", "exit_code": 0}


def test_arm_of_paths():
    assert fx.arm_of("/x/runs/p2/items/v6p-think/arrow_1/traces/trace_arrow_1.json") == "v6p-think"
    assert fx.arm_of("/x/runs/p4/results/traces/trace_rich_1.json") == "v5h2"
    assert fx.arm_of("/x/runs/p2/probe_v6p-b_T2/v6p-b/t/traces/trace_t.json") == "v6p-b"


def test_prompt_shape_echoed_into_the_command_is_ours():
    c = fx.classify("run_command", {"command": 'run_command(command="git grep -n x")'}, cmd_err(stderr="/bin/bash: -c: line 1: syntax error near unexpected token `command=\"git grep -n x\"'"))
    assert c.mechanism == "prompt call-shape echoed into the command" and c.owner == "ours"
    c = fx.classify("run_command", {"command": 'run_command "git grep -ln x -- tests"'}, cmd_err(stderr="/bin/bash: line 1: run_command: command not found"))
    assert c.mechanism == "prompt call-shape echoed into the command"
    c = fx.classify("run_command", {"command": "submit_patch"}, cmd_err(stderr="/bin/bash: line 1: submit_patch: command not found"))
    assert c.mechanism == "prompt call-shape echoed into the command" and "submit_patch" in c.detail
    c = fx.classify("run_command", {"command": 'run_skill_script(skill_name="swe-tools", file_path="install.py")'}, cmd_err(stderr="syntax error near unexpected token `skill_name"))
    assert c.mechanism == "prompt call-shape echoed into the command"


def test_parser_corrupted_arguments_are_the_harness_parsers():
    c = fx.classify("read_file", {"filepath": "tests/test_x.py`,start_line:151"}, {"status": "error", "error_type": "FileReadError", "error_message": "Source path /workspace/tests/test_x.py`,start_line:151 not found in sandbox 1"})
    assert c.mechanism == "parser-corrupted arguments (gemma4 tool parser)" and c.owner == "harness"
    c = fx.classify("read_file", {"filepath": "f.py", "start_line": 1, "end_line": '390<|"|>'}, {"status": "error", "error_type": "FileReadError", "error_message": "Invalid integer for end_line: '390<|\"|>'"})
    assert c.mechanism == "parser-corrupted arguments (gemma4 tool parser)"
    c = fx.classify("run_skill_script", {"file_path": '":"', "skill_name": "swe-tools"}, {"error": "Script '\":\"' not found in skill 'swe-tools'.", "error_code": "SCRIPT_NOT_FOUND"})
    assert c.mechanism == "parser-corrupted arguments (gemma4 tool parser)"
    c = fx.classify("run_skill_script", {"file_path": "install.py", "skill_name": "「swe-tools」"}, {"error": "Skill not found", "error_code": "SKILL_NOT_FOUND"})
    assert c.mechanism == "parser-corrupted arguments (gemma4 tool parser)"
    c = fx.classify("run_skill_script", {}, {"error": "Argument 'skill_name' is required.", "error_code": "INVALID_ARGUMENTS"})
    assert c.mechanism == "harness rejection: INVALID_ARGUMENTS (arguments dropped)" and c.owner == "harness"
    c = fx.classify("read_file", {"filepath": "nope.py"}, {"status": "error", "error_type": "FileReadError", "error_message": "Source path /workspace/nope.py not found in sandbox 1"})
    assert c.mechanism == "file not found (model path)" and c.owner == "model"
    c = fx.classify("read_file", {"filepath": "f.py", "start_line": 9, "end_line": 2}, {"status": "error", "error_type": "ValueError", "error_message": "start_line (9) cannot be greater than end_line (2)"})
    assert c.mechanism == "read_file bad range (model)"


def test_helper_usage_errors_and_cant_open_are_ours():
    c = fx.classify("run_command", {"command": "cd /tmp/wa && python3 /tmp/swe/view.py a.py 150-160"}, ok("usage: python3 /tmp/swe/view.py FILE START END   (line numbers, at most 120 lines)\n"))
    assert c.mechanism == "helper usage/argument error (view)" and c.owner == "ours" and "150-160" in c.detail
    c = fx.classify("run_command", {"command": "python3 /tmp/swe/test.py"}, ok("give args={'target': 'tests/test_file.py[::test_name]'}"))
    assert c.mechanism == "helper usage/argument error (test)"
    c = fx.classify("run_command", {"command": "python3 /tmp/swe/locate.py x"}, cmd_err(stderr="python3: can't open file '/tmp/sbx/tmp/swe/locate.py': [Errno 2] No such file or directory"))
    assert c.mechanism == "can't open file: helper not installed (locate)" and c.owner == "ours"
    c = fx.classify("run_command", {"command": "python3 /tmp/swe/check.py --mode preflight"}, cmd_err(stderr='Traceback (most recent call last):\n  File "/tmp/sbx/tmp/swe/check.py", line 12, in <module>\n    x\nKeyError: 1'))
    assert c.mechanism == "helper traceback (check)" and c.owner == "ours"


def test_harness_budget_timeout_and_write_outside_workspace():
    c = fx.classify("run_command", {"command": "git diff"}, {"status": "error", "error_type": "BudgetExceeded", "error_message": "Tool call budget exhausted (70 calls)"})
    assert c.mechanism == "budget exhausted (70 tool calls)" and c.owner == "harness"
    c = fx.classify("run_command", {"command": "python3 -c x"}, {"status": "error", "error_type": "TimeoutExceeded", "error_message": "Command timed out after 180 seconds"})
    assert c.mechanism == "command timeout" and c.owner == "model"
    c = fx.classify("write_file", {"filepath": "/tmp/repro.py", "content": "x"}, {"status": "error", "error_type": "FileWriteError", "error_message": "Path traversal detected: '/tmp/repro.py' escapes workspace root."})
    assert c.mechanism == "write_file outside the workspace refused" and c.owner == "ours"


def test_edit_verdicts_and_bash_heredoc_and_model_scripts():
    e = lambda first: fx.classify("run_command", {"command": "python3 /tmp/swe/edit.py a.py <<'EOF'\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\nEOF"}, cmd_err(stdout=first))
    assert e("NO MATCH in a.py for the SEARCH block (5 lines). Closest current lines:").mechanism == "edit.py verdict: NO MATCH"
    assert e("AMBIGUOUS in a.py: the SEARCH block matches 2 places").mechanism == "edit.py verdict: AMBIGUOUS"
    assert e("SYNTAX ERROR after the edit, so it was REVERTED (a.py unchanged):").mechanism == "edit.py verdict: SYNTAX ERROR (reverted)"
    assert e("REFUSED tests/test_a.py: test and config files are replaced at grading").mechanism == "edit.py verdict: REFUSED (test/config file)"
    assert e("NO CHANGE: the replacement equals the current text of a.py.").mechanism == "edit.py verdict: NO CHANGE"
    assert e("ERROR: the edit ended early (no ======= or no >>>>>>> REPLACE line arrived)").mechanism == "edit.py verdict: edit ended early (heredoc)"
    assert e("ERROR: --lines 5167-5244 is outside the file (5243 lines).").mechanism == "edit.py verdict: --lines outside the file"
    for v in (e("NO MATCH x"), e("NO CHANGE x")):
        assert v.owner == "model"
    c = fx.classify("run_command", {"command": "python3 /tmp/swe/edit.py a.py <<'EOF'\nx\nEOF"}, cmd_err(stderr="/bin/bash: -c: line 17: syntax error near unexpected token `>>'"))
    assert c.mechanism == "bash syntax error in the heredoc (model)" and c.owner == "model"
    c = fx.classify("run_command", {"command": "python3 /tmp/repro.py"}, cmd_err(msg="Traceback (most recent call last):\n  File \"/tmp/repro.py\", line 3\nAssertionError"))
    assert c.mechanism == "model script traceback (repro / python -c)" and c.owner == "model"
    c = fx.classify("run_command", {"command": "git grep -n x"}, cmd_err())
    assert c.mechanism == "command non-zero exit (grep no match etc.)" and c.owner == "model"
    c = fx.classify("run_command", {"command": "pytest tests/x.py"}, cmd_err(stdout="============================= test session starts ===\n1 failed"))
    assert c.mechanism == "pytest run red"


def test_ok_empty_and_designed_refusals():
    assert fx.classify("run_command", {"command": "ls"}, ok("a\n")).mechanism == "ok"
    assert fx.classify("run_command", {"command": "cp -a /workspace /tmp/wa"}, ok("")).mechanism == "empty output"
    c = fx.classify("run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok("ALREADY SHOWN: a.py lines 1-120, unchanged since."))
    assert c.mechanism == "view.py repeat refused (ours, by design)" and c.owner == "model"
    assert fx.classify("run_command", {"command": "python3 /tmp/swe/repro.py"}, ok("REPRO MISSING")).mechanism == "repro.py: no /tmp/repro.py to run"
    assert fx.classify("read_file", {"filepath": "a.py"}, {"status": "ok", "filepath": "a.py", "content": "x"}).mechanism == "ok"
    assert fx.classify("run_command", {"command": "x"}, None).mechanism == "unparseable observation"


def test_leaked_tool_call_text_counts_raw_tool_syntax_in_agent_messages():
    t = _trace([_msg("locator", '�<|tool_call>call:read_file{filepath:<|"|>a.py<|"|>,start_line:840,end_line:865}<tool_call|>'), _msg("fixer", "done")])
    assert fx.leaked_tool_calls(t) == 1


def test_find_loops_needs_five_identical_consecutive_calls_and_groups_by_reply():
    err = {"status": "error", "error_type": "BudgetExceeded", "error_message": "Tool call budget exhausted (70 calls)"}
    steps = [_step("verifier", "run_command", {"command": "git diff"}, err, i) for i in range(5)]
    steps.insert(2, _msg("verifier", "Trying again.", 99))
    loops = fx.find_loops(_trace(steps))
    assert len(loops) == 1 and loops[0].count == 5 and loops[0].identical_replies and loops[0].reply_kind == "error: BudgetExceeded" and loops[0].author == "verifier"
    assert loops[0].text_between == ["Trying again."]
    assert fx.find_loops(_trace(steps[:4])) == []
    steps2 = [_step("locator", "run_command", {"command": "grep -n x a.py"}, ok("59: x %d" % i), i) for i in range(6)]
    l2 = fx.find_loops(_trace(steps2))[0]
    assert l2.reply_kind == "normal result" and not l2.identical_replies and l2.owner == "model"
    steps3 = [_step("fixer", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok("ALREADY SHOWN: a.py lines 1-120"), i) for i in range(5)]
    assert fx.find_loops(_trace(steps3))[0].reply_kind == "our repeat refusal (ALREADY SHOWN)"
    steps4 = [_step("locator", "run_command", {"command": "grep -rn x ."}, ok(""), i) for i in range(5)]
    l4 = fx.find_loops(_trace(steps4))[0]
    assert l4.reply_kind == "empty output" and l4.owner == "ours"          # an empty reply the model cannot act on: ours to make informative


def test_empty_patch_causes():
    budget = {"status": "error", "error_type": "BudgetExceeded", "error_message": "Tool call budget exhausted (70 calls)"}
    t = _trace([_step("locator", "run_command", {"command": "ls"}, ok("x")), _step("locator", "run_command", {"command": "ls"}, budget), _step("verifier", "run_command", {"command": "git diff"}, budget)])
    assert fx.empty_patch_cause(t, {"error": None}).startswith("budget exhausted at the locator")
    assert fx.empty_patch_cause(_trace([_step("fixer", "run_command", {"command": "ls"}, ok("x"))]), {"error": "Agent exceeded session timeout (5.0 min)"}).startswith("time cap hit at the fixer")
    t = _trace([_step("locator", "run_command", {"command": "ls"}, ok("x")), _step("fixer", "run_command", {"command": "ls"}, ok("x"))])
    assert fx.empty_patch_cause(t, {"error": None}) == "verifier never ran (stopped after the fixer, no error)"
    sel = ok("select_best: test=t.py (from --test) | repro=none\na: empty\nb: empty\nc: empty\nPICK none: every candidate is empty; workspace unchanged")
    t = _trace([_step("locator", "run_command", {"command": "ls"}, ok("x")), _step("selector", "run_skill_script", {"file_path": "select_best.py", "skill_name": "swe-tools"}, {"skill_name": "swe-tools", "file_path": "select_best.py", "stdout": sel["stdout"], "status": "success"}),
                _step("verifier", "submit_patch", {}, {"status": "ok"})])
    assert fx.empty_patch_cause(t, {"error": None}) == "selector: every candidate empty (fixers produced no diff)"
    t = _trace([_step("fixer", "run_command", {"command": "python3 /tmp/swe/edit.py tests/test_a.py <<'EOF'\nEOF"}, cmd_err(stdout="REFUSED tests/test_a.py: test and config files")), _step("verifier", "submit_patch", {}, {"status": "ok"})])
    assert fx.empty_patch_cause(t, {"error": None}) == "only test-file edits attempted (refused by edit.py); submitted empty"
    t = _trace([_step("fixer", "run_command", {"command": "python3 /tmp/swe/edit.py a.py <<'EOF'\nEOF"}, ok("OK a.py: lines 1-2 replaced")), _step("verifier", "run_command", {"command": "python3 /tmp/swe/check.py --mode preflight"}, ok("DIFF:\nnone\nPROBLEMS:\nreverted a.py")), _step("verifier", "submit_patch", {}, {"status": "ok"})])
    assert fx.empty_patch_cause(t, {"error": None}) == "verifier submitted an empty diff after 1 successful edit(s)"


def test_v6p_pipeline_steps():
    sel_out = "select_best: test=t.py (from --test) | repro=fails before the fix (fail)\na: 6 lines in a.py [copy] | repro PASS | test PASS\nb: empty\nc: 2 lines in a.py [copy] | repro FAIL | test FAIL\nPICK a: repro PASS, test PASS, 6 changed lines; applied to the workspace (2s)"
    steps = [_step("locator", "run_command", {"command": "cat > /tmp/repro.py <<'EOF'\nassert 1 == 2\nEOF"}, ok("")),
             _step("locator", "run_command", {"command": "python3 /tmp/swe/repro.py"}, ok("REPRO FAIL exit=1")),
             _step("fixer_a", "run_command", {"command": "rm -rf /tmp/wa && cp -a /workspace /tmp/wa && git -C /tmp/wa status --short | head -5"}, ok("")),
             _step("fixer_b", "run_command", {"command": "rm -rf /tmp/wb && cp -a /workspace /tmp/wb && git -C /tmp/wb status --short | head -5"}, ok("")),
             _step("fixer_a", "run_command", {"command": "cd /tmp/wa && git -C /tmp/wa add -N . && git -C /tmp/wa diff > /tmp/wa.diff; git -C /tmp/wa diff --stat"}, ok(" a.py | 6 +-\n 1 file changed")),
             _step("fixer_b", "run_command", {"command": "cd /tmp/wb && git -C /tmp/wb add -N . && git -C /tmp/wb diff > /tmp/wb.diff; git -C /tmp/wb diff --stat"}, ok("")),
             _step("selector", "run_skill_script", {"file_path": "select_best.py", "skill_name": "swe-tools", "args": {"test": "t.py"}}, {"skill_name": "swe-tools", "file_path": "select_best.py", "stdout": sel_out, "status": "success"}),
             _step("verifier", "submit_patch", {}, {"status": "ok"})]
    p = fx.v6p_pipeline(_trace(steps))
    assert p["locator_wrote_repro"] and p["repro_run_how"] == "helper" and p["repro_failed_before_fix"] and p["copies"] == {"a": True, "b": True, "c": False}
    assert p["nonempty_diffs"] == 1 and p["select_ran"] and p["select_repro"] == "fails before the fix" and p["pick"] == "a" and p["applied"] and p["verifier_submitted"]
    assert p["first_broken"] == "fixer_c copy"
    steps[1] = _step("locator", "run_command", {"command": "python3 /tmp/repro.py"}, ok("Now: indi\n"))
    p = fx.v6p_pipeline(_trace(steps))
    assert p["repro_run_how"] == "direct" and p["repro_failed_before_fix"] is False
    steps[6] = _step("selector", "run_skill_script", {"file_path": "select_best.py", "skill_name": "swe-tools"}, {"skill_name": "swe-tools", "file_path": "select_best.py", "stdout": "", "stderr": '{"error_type": "BudgetExceeded"}', "status": "error"})
    p = fx.v6p_pipeline(_trace(steps))
    assert p["select_ran"] is False and p["first_broken"] == "locator repro fails before the fix"


def test_first_divergence_skips_setup_and_normalises_sandbox_paths():
    a = _trace([_step("setup", "run_skill_script", {"file_path": "install.py"}, ok("")), _step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py x"}, ok("")), _step("locator", "read_file", {"filepath": "a.py"}, {"status": "ok"})])
    b = _trace([_step("locator", "run_command", {"command": "python3 /tmp/swe/locate.py x"}, ok("")), _step("locator", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1 50"}, ok(""))])
    d = fx.first_divergence(a, b)
    assert d["index"] == 1 and d["a"]["fn"] == "read_file" and d["b"]["fn"] == "run_command" and "view.py" in d["b"]["call"]
    assert fx.first_divergence(a, a)["index"] is None


def test_mechanism_table_counts_calls_and_tasks_with_an_example():
    traces = {"v6p": {"t1": _trace([_step("locator", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1-5"}, ok("usage: python3 /tmp/swe/view.py FILE START END")),
                                      _step("locator", "run_command", {"command": "python3 /tmp/swe/view.py a.py 2-5"}, ok("usage: python3 /tmp/swe/view.py FILE START END"))]),
                      "t2": _trace([_step("locator", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1-5"}, ok("usage: python3 /tmp/swe/view.py FILE START END")), _step("fixer", "run_command", {"command": "ls"}, ok("x"))])}}
    tab = fx.mechanism_table(traces)
    row = tab["v6p"]["helper usage/argument error (view)"]
    assert row["calls"] == 3 and row["tasks"] == {"t1", "t2"} and row["example"]["task"] == "t1" and "view.py" in row["example"]["call"] and len(row["example"]["reply"]) <= 300
    assert tab["v6p"]["ok"]["calls"] == 1
