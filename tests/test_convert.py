"""Converter regressions: each case is a bug that once silently dropped every trajectory or corrupted paths."""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "train"))
import convert_nebius as cv

def tc(i, name, **args): return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
def traj(extra_calls=()):
    t = [{"role": "system", "content": "sys"},
         {"role": "user", "content": "Consider <issue_description>Fix foo</issue_description>"},
         {"role": "assistant", "content": "look", "tool_calls": [tc(1, "str_replace_editor", command="view", path="/workspace/o__r__1/pkg/a.py")]},
         {"role": "tool", "tool_call_id": "c1", "content": "     1\tdef foo():\n     2\t    return 1"}]
    for i, (name, args, result) in enumerate(extra_calls, start=10):
        t.append({"role": "assistant", "content": "", "tool_calls": [tc(i, name, **args)]})
        if result is not None: t.append({"role": "tool", "tool_call_id": f"c{i}", "content": result})
    t.append({"role": "assistant", "content": "done", "tool_calls": [tc(99, "finish", message="ok")]})   # finish has NO tool result
    return t

def test_finish_without_result_is_kept():
    out = cv.convert(traj())
    assert out is not None, cv.REASONS
    assert out[-1]["tool_calls"][-1]["function"]["name"] == "submit_patch"

def test_task_tracker_and_think_are_dropped_not_rejected():
    out = cv.convert(traj([("task_tracker", {"command": "plan"}, "ok"), ("think", {"thought": "hmm"}, "Your thought has been logged.")]))
    assert out is not None
    names = [c["function"]["name"] for m in out if m["role"] == "assistant" for c in (m.get("tool_calls") or [])]
    assert "task_tracker" not in names and "think" not in names

def test_paths_are_repo_relative_and_args_are_dicts():
    out = cv.convert(traj())
    call = out[2]["tool_calls"][0]
    assert call["function"]["name"] == "read_file"
    assert isinstance(call["function"]["arguments"], dict)          # Gemma template raises on string arguments
    assert call["function"]["arguments"]["filepath"] == "pkg/a.py"

def test_rel_edge_cases():
    assert cv.rel("/workspace") == "."
    assert cv.rel("/workspace/o__r__1") == "."
    assert cv.rel("/workspace/o__r__1/src/x.py") == "src/x.py"
    assert cv.rel("/testbed/x.py") == "x.py"

def test_directory_view_becomes_listing():
    out = cv.convert(traj([("str_replace_editor", {"command": "view", "path": "/workspace/o__r__1"}, "listing")]))
    cmds = [c["function"] for m in out if m["role"] == "assistant" for c in (m.get("tool_calls") or []) if c["function"]["name"] == "run_command"]
    assert cmds and cmds[0]["arguments"]["command"].startswith("find . ")

def test_read_file_result_strips_line_numbers():
    out = cv.convert(traj())
    res = json.loads(out[3]["content"])
    assert res["content"].startswith("def foo():")

def test_rejections_are_counted():
    cv.REASONS.clear()
    assert cv.convert(traj([("str_replace_editor", {"command": "undo_edit", "path": "/workspace/o__r__1/a.py"}, "x")])) is None
    assert cv.REASONS.get("editor_undo_edit") == 1

def test_only_harness_tool_names_are_emitted():
    allowed = {t["name"] for t in cv.TOOLS}
    out = cv.convert(traj([("execute_bash", {"command": "ls"}, "a\n[The command completed with exit code 0.]"),
                           ("str_replace_editor", {"command": "str_replace", "path": "/workspace/o__r__1/a.py", "old_str": "1", "new_str": "2"}, "edited")]))
    names = {c["function"]["name"] for m in out if m["role"] == "assistant" for c in (m.get("tool_calls") or [])}
    assert names <= allowed, names - allowed
