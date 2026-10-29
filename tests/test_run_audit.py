"""eval/analysis/run_audit.py (2026-10-29): two defects found while ranking the optimisation backlog.

- The oracle and rescore runs (configs "L4 oracle_all" and "L4 rescore_fair", every row calls == 0) were counted as agent
  runs, so the reach line said "never solved by any run: 0" where the truth over agent runs is 27 never, 5 always, 42
  contested (eval/analysis/out/task_reach.json agrees).
- first_edit_s was set by the first successful edit_file/write_file of any path, so a repro script or a /tmp file made the
  agent look as if it had started fixing; it now needs a non-test source path inside the repository. A src_diff column
  says whether the run's final patch touches such a file.
Small fixture traces only; the full run over the real data is eval/analysis/out/run_audit.md.
"""
import importlib.util, json, pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "eval" / "analysis" / "run_audit.py"
OK = '{"status": "ok"}'


def _mod():
    spec = importlib.util.spec_from_file_location("run_audit", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def call(name, args, obs=OK, t=10.0):
    """One agent step with a single tool call and its observation."""
    return {"source": "agent", "extra": {"elapsed_s": t}, "tool_calls": [{"function_name": name, "arguments": args}],
            "observation": {"content": obs}}


def edit(path, t, name="edit_file", obs=OK):
    return call(name, {"filepath": path, "old_string": "a", "new_string": "b"} if name == "edit_file"
                else {"filepath": path, "content": "x"}, obs, t)


def first_edit(steps, patch=""):
    out = _mod().audit({"id": "t1", "resolved": False, "patch": patch}, {"steps": steps})
    return out["first_edit_s"]


# ----------------------------------------------------------------------------------------------------- first_edit_s
def test_a_scratch_file_write_does_not_set_first_edit():
    """Repro scripts (root level or /tmp), test files, an absolute path and a parser-garbled path are not source edits."""
    steps = [edit("/tmp/repro.py", 5, "write_file"), edit("repro.py", 8, "write_file"),
             edit("reproduce_issue.py", 9, "write_file"), edit("tests/test_forms.py", 12),
             edit("fastapi/test_helpers.py", 13), edit("/workspace/fastapi/routing.py", 14),
             edit("rich/cells.py`,new_string:", 15), edit("../outside/mod.py", 16), edit("", 17)]
    assert first_edit(steps) is None


def test_a_source_edit_sets_first_edit_at_its_own_time_not_the_scratch_time():
    steps = [edit("/tmp/repro.py", 5, "write_file"), edit("repro.py", 8, "write_file"),
             edit("fastapi/dependencies/utils.py", 40), edit("rich/cells.py", 55)]
    assert first_edit(steps) == 40


@pytest.mark.parametrize("path", ["fastapi/routing.py", "./rich/cells.py", "pkg/sub/mod.py", "docs_src/app/main.py"])
def test_source_paths_inside_the_repository_count(path):
    assert first_edit([edit(path, 30)]) == 30


def test_a_failed_source_edit_does_not_set_first_edit():
    err = '{"error": "old_string not found"}'
    assert first_edit([edit("fastapi/routing.py", 30, obs=err), edit("fastapi/routing.py", 44)]) == 44


def test_the_edit_helper_counts_only_when_it_succeeds():
    """swe-tools edit.py is the edit path of the helper bundles; it exits non-zero on NO CHANGE, a revert or a refusal."""
    cmd = "python3 /tmp/swe/edit.py %s <<'EOF'\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\nEOF"
    fail = '{"status": "error", "error_message": "NO CHANGE"}'
    steps = [call("run_command", {"command": cmd % "fastapi/routing.py"}, fail, 20.0),
             call("run_command", {"command": cmd % "tests/test_routing.py"}, OK, 25.0),
             call("run_command", {"command": cmd % "rich/cells.py"}, OK, 31.0)]
    assert first_edit(steps) == 31


def test_a_missing_observation_or_no_edit_leaves_first_edit_unset():
    assert first_edit([]) is None
    assert first_edit([call("read_file", {"filepath": "fastapi/routing.py", "start_line": 1, "end_line": 5})]) is None


# -------------------------------------------------------------------------------------------------------------- src_diff
def diff(*paths):
    return "".join(f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n" for p in paths)


@pytest.mark.parametrize("patch,want", [
    pytest.param(diff("fastapi/routing.py"), True, id="source"),
    pytest.param(diff("repro.py", "fastapi/routing.py"), True, id="one-source-among-scratch"),
    pytest.param(diff("tests/test_routing.py"), False, id="test-only"),
    pytest.param(diff("repro.py", "reproduce_issue.py"), False, id="scratch-only"),
    pytest.param(diff("tests/test_a.py", "docs/tests/b.py"), False, id="tests-in-subdirs"),
    pytest.param("", False, id="empty"),
    pytest.param(None, False, id="none"),
])
def test_src_diff_needs_a_non_test_source_file_in_the_final_patch(patch, want):
    out = _mod().audit({"id": "t1", "resolved": False, "patch": patch}, {"steps": []})
    assert out["src_diff"] is want


# ------------------------------------------------------------------------------- oracle and rescore runs are skipped
def write_run(root, base, name, rows, trace_steps):
    d = root / base / name
    (d / "results" / "traces").mkdir(parents=True)
    (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for r in rows:
        (d / "results" / "traces" / f"trace_{r['id']}.json").write_text(json.dumps({"steps": trace_steps(r)}))


def test_oracle_and_rescore_rows_are_skipped_in_the_table_and_the_reach_line(tmp_path, monkeypatch, capsys):
    """Three tasks: a solved by both agent configs, c by one, b by none. The oracle grades the gold patch (every row
    resolved, calls 0, empty trace) and a rescore grades saved patches (calls 0): neither may reach the table or the reach
    line, which used to read 'never solved by any run: 0'."""
    ids = ["a", "b", "c"]
    agent = lambda solved: [{"id": i, "resolved": i in solved, "calls": 3, "secs": 60.0, "patch": diff("fastapi/x.py")}
                            for i in ids]
    work = lambda r: [edit("fastapi/x.py", 20), call("submit_patch", {}, OK, 30.0)]
    write_run(tmp_path, "eval/kaggle", "agent_one", agent({"a", "c"}), work)
    write_run(tmp_path, "eval/a6000/results", "agent_two", agent({"a"}), work)
    write_run(tmp_path, "eval/kaggle", "oracle_all", [{"id": i, "resolved": True, "calls": 0, "secs": 7.0, "patch": diff("fastapi/x.py")}
                                                      for i in ids], lambda r: [])
    write_run(tmp_path, "eval/kaggle", "rescore_fair", [{"cfg": c, "id": i, "resolved": c == "p_v4", "calls": 0, "secs": 9.0,
                                                         "patch": diff("fastapi/x.py")} for c in ("p_v4", "p_v5") for i in ids],
              lambda r: [])
    ra = _mod()
    monkeypatch.setattr(ra, "ROOT", str(tmp_path))
    monkeypatch.setattr(ra, "IDS", set(ids))
    monkeypatch.setattr(ra, "MIN_ROWS", 3)
    out_json = tmp_path / "audit.json"
    ra.main(["--json", str(out_json)])
    text = capsys.readouterr().out
    cfgs = [ln.split("|")[1].strip() for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith("| cfg")]
    assert cfgs == ["L4 agent_one", "box agent_two"], cfgs
    assert "oracle" not in text.split("\n\n")[0] and "rescore" not in text.split("\n\n")[0]
    assert "2 agent configs, 6 runs (2 oracle/rescore configs without tool calls skipped)" in text
    assert "never solved by any run: 1; solved by every run: 1; contested: 1" in text
    saved = json.loads(out_json.read_text())
    assert saved["never"] == ["b"] and saved["always"] == ["a"]
    assert saved["skipped"] == ["L4 oracle_all", "L4 rescore_fair"] and len(saved["rows"]) == 6
    row = next(t for t in saved["table"] if t["cfg"] == "L4 agent_one")
    assert row["src_diff"] == 3 and row["first_edit"] == 20 and row["solved"] == 2


def test_a_run_with_tool_calls_in_its_results_is_kept_even_if_its_traces_are_bare(tmp_path, monkeypatch, capsys):
    """Only a run with no tool calls anywhere (traces and result rows) is an oracle; a bare trace does not demote an agent."""
    ids = ["a", "b"]
    write_run(tmp_path, "eval/kaggle", "bare_traces", [{"id": i, "resolved": i == "a", "calls": 12, "secs": 60.0, "patch": ""}
                                                       for i in ids], lambda r: [])
    ra = _mod()
    monkeypatch.setattr(ra, "ROOT", str(tmp_path))
    monkeypatch.setattr(ra, "IDS", set(ids))
    monkeypatch.setattr(ra, "MIN_ROWS", 2)
    ra.main([])
    assert "L4 bare_traces" in capsys.readouterr().out
