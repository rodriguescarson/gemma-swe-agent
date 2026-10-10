"""Thinking-on trajectories through train/scorer_render.py, train/build_sft.py and train/validate_rows.py (plan
~/.claude/plans/nifty-sleeping-liskov.md, Track C step 6). Since the 2026-10-09 scorer the model reasons on every call
(`<|channel>thought ... <channel|>` in front of its reply) and, with include_thoughts true, the harness sends the earlier
reasoning back as reasoning_content, which the June template renders into the context. A training row must therefore
carry the thought in its completion, and the next call's prompt must begin with the previous prompt + completion byte for
byte (stitching is then exact). Written before the code (test-first)."""
import json, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import build_sft as B  # noqa: E402
from train import scorer_render as R  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "r", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}}}}]
STMT = "Issue t_ok: " + "words " * 50 + "t_ok"
R1, R2 = "The issue names a.py, so I read it first.", "The file shows the bug on line 2; I will state the fix."


def body(messages, thinking=True):
    return {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": messages, "tools": TOOLS, "chat_template_kwargs": {"enable_thinking": thinking}}


def base_msgs():
    return [{"role": "system", "content": 'You are fixer. Your internal name is "fixer".'},
            {"role": "user", "content": "You are evaluating a software engineering task for repository x/y.\n\nProblem Statement:\n" + STMT + "\n\n## Task Budget"}]


CALL = {"id": "c0", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"filepath": "a.py"})}}


def reply(reasoning, tool_call=None, text=None, finish="stop"):
    msg = {"role": "assistant", "content": text, "reasoning_content": reasoning}
    if tool_call:
        msg["tool_calls"] = [tool_call]
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_the_completion_carries_the_models_thought_in_the_templates_form():
    msg = reply(R1, CALL)["choices"][0]["message"]
    c = R.canonical_completion(msg, continuation=False, thinking=True)
    assert c.startswith("<|channel>thought\n" + R1 + "\n<channel|><|tool_call>call:read_file{") and c.endswith("<|tool_response>")
    t = R.canonical_completion(reply(R2, text="Fixed.")["choices"][0]["message"], continuation=True, thinking=True)
    assert t == "<|channel>thought\n" + R2 + "\n<channel|>Fixed.<turn|>"
    # thinking on but the model reasoned nothing: the empty channel it emits itself
    e = R.canonical_completion(reply("", text="Fixed.")["choices"][0]["message"], continuation=False, thinking=True)
    assert e == R.EMPTY_THOUGHT + "Fixed.<turn|>"
    # thinking off: unchanged (the generation prompt supplies the empty channel on first calls)
    assert R.canonical_completion({"role": "assistant", "content": "x"}, continuation=False) == "x<turn|>"
    assert R.canonical_completion({"role": "assistant", "content": "x"}, continuation=True) == R.EMPTY_THOUGHT + "x<turn|>"


def test_a_thinking_trajectory_is_a_byte_exact_prefix_chain():
    """prompt2 starts with prompt1 + completion1: the thought the model produced is what the template renders back."""
    b1 = body(base_msgs())
    msg1 = reply(R1, CALL)["choices"][0]["message"]
    c1 = R.canonical_completion(msg1, continuation=False, thinking=True)
    p1 = R.render(b1)
    assert p1.endswith("<|turn>model\n") and "<|think|>" in p1 and not p1.endswith(R.EMPTY_THOUGHT)   # thinking on: no empty thought supplied
    hist = base_msgs() + [{"role": "assistant", "content": "", "reasoning_content": R1, "tool_calls": [CALL]},
                          {"role": "tool", "tool_call_id": "c0", "content": json.dumps({"status": "ok", "content": "line1\nline2"})}]
    p2 = R.render(body(hist))
    assert p2.startswith(p1 + c1), (p1[-200:], c1, p2[len(p1) - 50:len(p1) + len(c1) + 80])
    msg2 = reply(R2, text="Fixed.")["choices"][0]["message"]
    c2 = R.canonical_completion(msg2, continuation=True, thinking=True)
    assert c2.startswith("<|channel>thought\n" + R2)
    # without reasoning_content in the history the template renders no thought: the chain breaks (the harness carries it with include_thoughts true)
    hist_bare = [dict(m, reasoning_content="") if m.get("role") == "assistant" else m for m in hist]
    assert not R.render(body(hist_bare)).startswith(p1 + c1)


@pytest.fixture
def world(tmp_path):
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"instance_id": "t_ok", "problem_statement": STMT}) + "\n")
    results = tmp_path / "task_results.jsonl"
    results.write_text(json.dumps({"instance_id": "t_ok", "resolved": True}) + "\n")
    hist = base_msgs() + [{"role": "assistant", "content": "", "reasoning_content": R1, "tool_calls": [CALL]},
                          {"role": "tool", "tool_call_id": "c0", "content": json.dumps({"status": "ok", "content": "x"})}]
    cap = tmp_path / "cap.jsonl"
    rows = [{"t": 1, "body": body(base_msgs()), "response": reply(R1, CALL)},
            {"t": 2, "body": body(hist), "response": reply(R2, text="Fixed.")},
            {"t": 3, "body": body(hist), "response": reply("", text="Fixed again.")}]         # thinking on, no reasoning
    cap.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path, tasks, results, cap


def test_build_sft_keeps_thoughts_and_require_thinking_drops_reasonless_rows(world):
    tmp, tasks, results, cap = world
    rows, stats = B.build([str(cap)], str(tasks), [str(results)])
    assert stats["rows"] == 3 and [r["meta"]["thinking"] for r in rows] == [True, True, True]
    assert rows[0]["completion"].startswith("<|channel>thought\n" + R1) and rows[0]["meta"]["reasoning_chars"] == len(R1)
    assert rows[1]["completion"] == "<|channel>thought\n" + R2 + "\n<channel|>Fixed.<turn|>" and rows[1]["meta"]["continuation"] is True
    assert rows[2]["completion"] == R.EMPTY_THOUGHT + "Fixed again.<turn|>" and rows[2]["meta"]["reasoning_chars"] == 0
    assert rows[1]["prompt"].startswith(rows[0]["prompt"] + rows[0]["completion"])            # the stitching property on real rows
    strict, st2 = B.build([str(cap)], str(tasks), [str(results)], require_thinking=True)
    assert st2["rows"] == 2 and st2["no_reasoning"] == 1 and all(r["meta"]["reasoning_chars"] for r in strict)


def test_validate_rows_counts_thoughts_and_can_require_them(world, tmp_path):
    tmp, tasks, results, cap = world
    rows, _ = B.build([str(cap)], str(tasks), [str(results)])
    out = tmp_path / "rows.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    base = [sys.executable, str(ROOT / "train" / "validate_rows.py"), str(out), "--min-rows", "0", "--no-tokenizer"]
    r = subprocess.run(base, capture_output=True, text=True)
    rep = json.loads(r.stdout)
    assert r.returncode == 0 and rep["ok"] and rep["rows_with_thought"] == 2, r.stdout[-600:]
    r2 = subprocess.run(base + ["--require-thought"], capture_output=True, text=True)
    rep2 = json.loads(r2.stdout)
    assert r2.returncode == 1 and any("no thought channel" in p[1] for p in rep2["first_problems"]), r2.stdout[-600:]
    # a completion that is only a (non-empty) thought and a terminator is still empty
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"prompt": "<bos>x", "completion": "<|channel>thought\nI think.\n<channel|><turn|>", "meta": {"task": "t_ok", "stage": "fixer"}}) + "\n")
    r3 = subprocess.run([sys.executable, str(ROOT / "train" / "validate_rows.py"), str(bad), "--min-rows", "0", "--no-tokenizer"], capture_output=True, text=True)
    assert r3.returncode == 1 and "empty completion" in r3.stdout
