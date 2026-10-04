"""train/build_sft.py: capture JSONL -> SFT rows, success-only, leak-guarded, deduplicated (P0.3)."""
import json, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train import build_sft as B  # noqa: E402
from train.scorer_render import EMPTY_THOUGHT  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "r", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}}}}]


def body(task_stmt, stage, continuation=False):
    msgs = [{"role": "system", "content": f'You are {stage}. Your internal name is "{stage}".'},
            {"role": "user", "content": "You are evaluating a software engineering task for repository x/y.\n\nProblem Statement:\n" + task_stmt + "\n\n## Task Budget"}]
    if continuation:
        msgs += [{"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"filepath": "a.py"})}}]},
                 {"role": "tool", "tool_call_id": "c0", "content": json.dumps({"result": "{\"status\": \"ok\", \"content\": \"x\"}"})}]
    return {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": msgs, "tools": TOOLS, "chat_template_kwargs": {"enable_thinking": False}}


def reply(tool_call=None, text=None, finish="stop"):
    msg = {"role": "assistant", "content": text}
    if tool_call:
        msg["tool_calls"] = [{"id": "x", "type": "function", "function": {"name": tool_call[0], "arguments": json.dumps(tool_call[1])}}]
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture
def world(tmp_path):
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("\n".join(json.dumps({"instance_id": t, "problem_statement": f"Issue {t}: " + "words " * 50 + t}) for t in ("t_ok", "t_bad", "t_eval")) + "\n")
    results = tmp_path / "task_results.jsonl"
    results.write_text("\n".join(json.dumps({"instance_id": t, "resolved": r}) for t, r in (("t_ok", True), ("t_bad", False), ("t_eval", True))) + "\n")
    stmt = lambda t: f"Issue {t}: " + "words " * 50 + t  # noqa: E731
    cap = tmp_path / "cap.jsonl"
    rows = [
        {"t": 1, "body": body(stmt("t_ok"), "fixer"), "response": reply(("read_file", {"filepath": "a.py"}))},
        {"t": 2, "body": body(stmt("t_ok"), "fixer", continuation=True), "response": reply(text="Changed a.py.")},
        {"t": 3, "body": body(stmt("t_ok"), "fixer"), "response": reply(("read_file", {"filepath": "a.py"}))},   # duplicate of row 1
        {"t": 4, "body": body(stmt("t_bad"), "fixer"), "response": reply(("read_file", {"filepath": "b.py"}))},  # unsolved task
        {"t": 5, "body": body(stmt("t_ok"), "locator"), "response": reply(text="", finish="length")},             # cut off
        {"t": 6, "body": body(stmt("t_ok"), "locator"), "response": reply(text="  ")},                            # empty
        {"t": 7, "body": body("something not in tasks"), "response": reply(text="hi")} if False else None,
    ]
    cap.write_text("\n".join(json.dumps(r) for r in rows if r) + "\n")
    return tmp_path, tasks, results, cap, stmt


def test_rows_success_only_dedup_and_shapes(world):
    tmp, tasks, results, cap, stmt = world
    rows, stats = B.build([str(cap)], str(tasks), [str(results)])
    assert stats["rows"] == 2 and stats["duplicate"] == 1 and stats["unsolved_or_unknown"] == 1 and stats["cut_off"] == 1 and stats["empty_reply"] == 1
    first, second = rows
    assert {k: v for k, v in first["meta"].items() if k != "traj"} == {"task": "t_ok", "stage": "fixer", "continuation": False, "tool": "read_file"}
    assert first["prompt"].startswith("<bos>") and first["prompt"].endswith(EMPTY_THOUGHT)          # generation prompt supplies the channel
    assert first["completion"].startswith("<|tool_call>call:read_file{") and first["completion"].endswith("<|tool_response>")
    assert second["meta"]["continuation"] is True and second["completion"] == EMPTY_THOUGHT + "Changed a.py.<turn|>"
    assert second["prompt"].endswith("<tool_response|>")                                           # mid-turn, no generation prompt


def test_all_outcomes_keeps_unsolved(world):
    tmp, tasks, results, cap, stmt = world
    rows, stats = B.build([str(cap)], str(tasks), [str(results)], success_only=False)
    assert stats["rows"] == 3 and any(r["meta"]["task"] == "t_bad" for r in rows)


def test_leak_guard_refuses_excluded_task(world):
    tmp, tasks, results, cap, stmt = world
    with open(cap, "a") as f:
        f.write(json.dumps({"t": 9, "body": body(stmt("t_eval"), "fixer"), "response": reply(text="x")}) + "\n")
    excl = tmp / "dev40.txt"; excl.write_text("t_eval\n")
    p = subprocess.run([sys.executable, str(ROOT / "train" / "build_sft.py"), "--capture", str(cap), "--tasks", str(tasks),
                        "--results", str(results), "--out", str(tmp / "rows.jsonl"), "--exclude-ids", str(excl)], capture_output=True, text=True)
    assert p.returncode == 2 and "LEAK GUARD" in p.stderr and not (tmp / "rows.jsonl").exists()


def test_unmatched_calls_are_counted_not_crashed(world):
    tmp, tasks, results, cap, stmt = world
    with open(cap, "a") as f:
        f.write(json.dumps({"t": 9, "body": body("an unknown statement", "fixer"), "response": reply(text="x")}) + "\n")
    rows, stats = B.build([str(cap)], str(tasks), [str(results)])
    assert stats["no_task"] == 1 and stats["rows"] == 2


def test_pairs_judge_each_sample_by_its_own_results(world, tmp_path):
    tmp, tasks, results, cap, stmt = world
    # sample 2: the same task unsolved; its capture must contribute nothing even though the pool says t_ok resolved
    cap2 = tmp / "cap2.jsonl"; res2 = tmp / "res2.jsonl"
    cap2.write_text(json.dumps({"t": 1, "body": body(stmt("t_ok"), "fixer"), "response": reply(("read_file", {"filepath": "z.py"}))}) + "\n")
    res2.write_text(json.dumps({"instance_id": "t_ok", "resolved": False}) + "\n")
    rows, stats = B.build([], str(tasks), [], pairs=[(str(cap), [str(results)]), (str(cap2), [str(res2)])])
    assert stats["rows"] == 2 and stats["unsolved_or_unknown"] == 2 and not any("z.py" in r["completion"] for r in rows)


def test_rows_carry_their_trajectory_id(world, tmp_path):
    """meta.traj = <capture file name>|<task>: one sample of one task is one trajectory, so the v11b repeat filter can
    drop repeated calls within a run without dropping the same correct call made by different runs."""
    tmp, tasks, results, cap, stmt = world
    rows, _ = B.build([], str(tasks), [], pairs=[(str(cap), [str(results)])])
    assert rows and all(r["meta"]["traj"] == f"{Path(cap).name}|{r['meta']['task']}" for r in rows)
