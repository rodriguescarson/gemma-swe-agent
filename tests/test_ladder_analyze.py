"""ladder_analyze.py must count tool calls the way the harness does (swegemma budget_gated + check_budget), because the
hook's snapshots are keyed by the harness count. The first version counted every non-get_status call and scored 4 solved
L1 tasks as unsolved (2026-11-07)."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ladder"))
import ladder_analyze as A  # noqa: E402

MALFORMED = ('{"error": "Invoking `edit_file()` failed as the following mandatory input parameters are not present:\\n'
             'old_string\\nYou could retry calling this tool"}')
CMD_TIMEOUT = '{"status": "error", "error_type": "TimeoutExceeded", "error_message": "Command timed out after 180 s"}'
CALLS_OUT = '{"status": "error", "error_type": "BudgetExceeded", "error_message": "Tool call budget exhausted (2 calls)"}'


def _step(name, content, end):
    return {"tool_calls": [{"function_name": name}],
            "observation": {"content": content, "extra": {"elapsed_s": end}}}


def _write_run(tmp_path, steps, task="t1", calls=2, snaps=()):
    (tmp_path / "results" / "traces").mkdir(parents=True)
    (tmp_path / "results" / "traces" / f"trace_{task}.json").write_text(json.dumps({"steps": steps}))
    (tmp_path / "results.jsonl").write_text(json.dumps({"id": task, "resolved": True, "calls": calls, "patch": ""}) + "\n")
    (tmp_path / "snapshots.jsonl").write_text("".join(json.dumps(s) + "\n" for s in snaps))
    return tmp_path


def test_classify_follows_the_harness(tmp_path):
    steps = [
        _step("run_command", '{"status": "ok"}', 5.0),       # counted
        _step("edit_file", MALFORMED, 9.0),                  # rejected by ADK before the wrapper: skipped
        _step("get_status", '{"status": "ok"}', 10.0),       # count_tool_call=False: skipped
        _step("run_command", CMD_TIMEOUT, 200.0),            # the command's own timeout ran inside the wrapper: counted
        _step("read_file", CALLS_OUT, 201.0),                # refused by check_budget: snapshotted, not counted
        _step("submit_patch", '{"status": "ok"}', 202.0),    # count_tool_call=False: skipped
    ]
    run = _write_run(tmp_path, steps)
    kinds = [k for k, _ in A.classify(run / "results" / "traces" / "trace_t1.json")]
    assert kinds == ["counted", "skipped", "skipped", "counted", "refused", "skipped"]
    assert A.counted_ends(str(run / "results" / "traces" / "trace_t1.json")) == [5.0, 200.0]


def test_check_counts_flags_a_disagreement(tmp_path):
    steps = [_step("run_command", '{"status": "ok"}', 5.0), _step("run_command", '{"status": "ok"}', 9.0),
             _step("read_file", CALLS_OUT, 10.0)]
    snaps = [{"task": "t1", "k": 0}, {"task": "t1", "k": 1}, {"task": "t1", "k": 2}]   # 2 counted + 1 refused
    run = _write_run(tmp_path, steps, calls=2, snaps=snaps)
    rows = {"t1": {"calls": 2}}
    assert A.check_counts(["t1"], rows, None, str(run)) == []
    rows = {"t1": {"calls": 3}}
    assert A.check_counts(["t1"], rows, None, str(run)) != []


def test_empty_tree_passes_only_on_the_known_tasks(tmp_path):
    steps = [_step("run_command", '{"status": "ok"}', 5.0)]
    empty = hashlib.sha1(b"").hexdigest()
    for task, want in (("fastapi_14851", True), ("t1", False)):
        d = tmp_path / task
        d.mkdir()
        run = _write_run(d, steps, task=task, calls=1, snaps=[{"task": task, "k": 0, "sha": empty, "dt": 0.0}])
        rows, snaps, _, _ = {task: {"resolved": want, "calls": 1, "patch": ""}}, {task: {0: empty}}, {task: []}, {}
        A.DT.clear()
        assert A.solved_at(task, 480, 40, rows, snaps, {task: []}, {}, str(run)) is want
