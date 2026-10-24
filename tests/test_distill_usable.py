"""scripts/distill/usable.py (G1/G2 metric) and split.g1_ids: what counts as a usable teacher trajectory, and the G1
pass rule, exactly as pre-registered in GAPS 'G1 pre-registration'."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "distill"))
sys.path.insert(0, str(ROOT / "tests"))
import split as S  # noqa: E402
import usable as U  # noqa: E402
from v10_support.mock_llm import SUMMARIZER_MARK  # noqa: E402

from train.build_sft import TaskIndex  # noqa: E402


def task_file(tmp_path, n=3):
    p = tmp_path / "tasks.jsonl"
    p.write_text("".join(json.dumps({"instance_id": f"t{i}", "problem_statement": f"Issue number {i}: widget {i} breaks "
                                     + "x" * 50}) + "\n" for i in range(n)))
    return p


def call(i, tool_calls=None, content=None, reasoning=None, system="You fix bugs."):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    if reasoning:
        msg["reasoning_content"] = reasoning
    body = {"tools": [{"type": "function", "function": {"name": "run_command"}}],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": f"Issue number {i}: widget {i} breaks " + "x" * 50}]}
    return {"body": body, "response": {"choices": [{"message": msg}]}}


def tc(name="run_command", args='{"command": "ls"}'):
    return {"id": "c", "type": "function", "function": {"name": name, "arguments": args}}


def test_call_ok():
    assert U.call_ok({"tool_calls": [tc()]})
    assert U.call_ok({"content": "done"})
    assert not U.call_ok({"tool_calls": [tc(args="{bad")]})
    assert not U.call_ok({"tool_calls": [tc(args="[1, 2]")]})
    assert not U.call_ok({"tool_calls": [tc(name="")]})


def test_usable_rule_boundaries(tmp_path):
    idx = TaskIndex(task_file(tmp_path, 5))
    rows = ([call(0, [tc()]), call(0, content="done")]                       # t0: fine
            + [call(1, [tc(args="{bad")])]                                  # t1: a call did not parse
            + [call(2, [tc()] * 41)]                                       # t2: 41 tool calls
            + [call(3, content="y" * 400)]                                 # t3: over the token budget (stub: 1 token/char)
            + [call(4, [tc()])])                                           # t4: not resolved
    summ = {"body": {"messages": [{"role": "user", "content": SUMMARIZER_MARK + " Issue number 0: widget 0 breaks "
                                   + "x" * 50}]}, "response": {"choices": [{"message": {"content": "z" * 9000}}]}}
    trajs = U.trajectories(rows + [summ], idx, lambda s: len(s) if "y" in s else 10)
    assert trajs["t0"]["calls"] == 2 and trajs["t0"]["tokens"] == 20         # the summariser call is not counted
    U.TOKEN_BUDGET = 300
    try:
        rep = U.evaluate(trajs, {"t0": True, "t1": True, "t2": True, "t3": True, "t4": False},
                         ["t0", "t1", "t2", "t3", "t4"], {"t0": False}, ec2_usd=0.5)
    finally:
        U.TOKEN_BUDGET = 8700
    assert [i for i, p in rep["tasks"].items() if p["usable"]] == ["t0"]
    assert rep["usable"] == 1 and rep["usable_gemma_never_solved"] == 1 and rep["usd_per_usable"] == 0.5
    assert rep["g1_pass"] is False                                         # 1 usable < 11


def test_g1_pass_rule():
    ids = [f"t{i}" for i in range(30)]
    trajs = {i: {"calls": 3, "tool_calls": 3, "tokens": 100, "parse_ok": True} for i in ids}
    gemma = {i: k < 20 for k, i in enumerate(ids)}                     # Gemma solved t0..t19
    solved = {i: k < 11 or k >= 26 for k, i in enumerate(ids)}          # 11 + 4 usable, 4 of them Gemma never solved
    rep = U.evaluate(trajs, solved, ids, gemma, ec2_usd=9.0)
    assert rep["usable"] == 15 and rep["usable_gemma_never_solved"] == 4 and rep["g1_pass"] is True
    assert U.evaluate(trajs, solved, ids, gemma, ec2_usd=9.1 * 15 / 0.6)["g1_pass"] is False     # too expensive
    only_old = {i: k < 15 for k, i in enumerate(ids)}                  # 15 usable, all Gemma already solved
    assert U.evaluate(trajs, only_old, ids, gemma, ec2_usd=1.0)["g1_pass"] is False


def test_g1_ids_deterministic_and_from_history():
    train = [f"r_{k:03d}" for k in range(100)]
    hist = {i: True for i in train[::2]}
    a = S.g1_ids(train, hist)
    assert len(a) == 30 and set(a) <= set(hist) and a == S.g1_ids(list(reversed(train)), hist)


def test_committed_g1_ids_are_train_ids():
    out = ROOT / "data" / "distill"
    if not (out / "g1_ids.txt").exists():
        return
    g1 = (out / "g1_ids.txt").read_text().split()
    assert len(g1) == 30 and set(g1) <= set((out / "train_ids.txt").read_text().split())
