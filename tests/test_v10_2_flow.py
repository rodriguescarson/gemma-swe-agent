"""R147 (docs/v10/SPEC_v10_2.md section 7): the compiled v10.2 bundle end to end in the REAL Evaluator with a scripted
model (tests/v10_support/mock_llm.py), R113 style: real sandboxes, the real SequentialAgent and skill toolset, real
compaction at 14,336 tokens and the real hidden-test verification.

(i)   a locator that makes 20 gated calls is refused from call 15, replies, and the fixer's status.py reopens the
      helpers; the scripted gold edit resolves the task;
(ii)  a locator whose final reply is a tool call written as text (the lost plan of diag M1): the fixer's first call,
      status.py, prints a LOCATOR DIGEST that names the file the locator viewed;
(iii) a fixer that views before status.py gets one refusal (the locator closed at 14 calls), runs status.py and goes on;
(iv)  a locator compacted mid-stage (AMNESIA) runs status.py, whose phase-start form tells it to reply, and replies.
Every scenario resolves, and every stage's last prompt stays under the compaction line.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402
from v10_support.mock_llm import MockLLM, cmd, heredoc, skill, submit, text, COMPACTION_LINE  # noqa: E402
from v10_support.v102 import V102  # noqa: E402
from test_v10_flow import (CLAIM, EDIT, FINALIZE, GOLD, LOCATE, NOTES, PLAN, REPRO, SETUP_OK, STATUS, TID, VERIFY,  # noqa: E402
                           make_task, observations, requests)

try:
    from v10_support.repo import no_orphans  # noqa: F401,E402  (autouse, R120)
except ImportError:  # pragma: no cover
    pass

pytest.importorskip("swegemma.evaluate")
pytestmark = pytest.mark.skipif(not (V102 / "agent.yaml").exists(), reason="v10.2 bundle not built")

VIEW = cmd("python3 /tmp/swe/view.py calc/ops.py add")
VIEW_RANGE = cmd("python3 /tmp/swe/view.py calc/ops.py 1 3")
# A tool call written as plain text (the harness's parser runs <tool_call> blocks, so that form is not lost): the stage
# ends and this text is the plan the fixer is handed.
LOST_PLAN = text('run_command(command="python3 /tmp/swe/view.py calc/ops.py 1 9")')
VERIFIER = [STATUS, VERIFY, FINALIZE, submit(), text("Submitted.")]
SCENARIOS = {
    "i": {"setup": SETUP_OK, "locator": [LOCATE] + [VIEW_RANGE] * 19 + [PLAN],
          "fixer": [STATUS, VIEW, EDIT, VERIFY, NOTES], "verifier": VERIFIER},
    "ii": {"setup": SETUP_OK, "locator": [LOCATE, VIEW, REPRO, LOST_PLAN],
           "fixer": [STATUS, EDIT, VERIFY, NOTES], "verifier": VERIFIER},
    "iii": {"setup": SETUP_OK, "locator": [LOCATE] + [VIEW_RANGE] * 13 + [PLAN],
            "fixer": [VIEW, STATUS, VIEW, EDIT, VERIFY, NOTES], "verifier": VERIFIER},
    "iv": {"setup": SETUP_OK, "locator": [LOCATE, {**VIEW, "ptok": 15000}, STATUS, REPRO, PLAN],
           "fixer": [STATUS, EDIT, VERIFY, NOTES], "verifier": VERIFIER},
}


@pytest.fixture(scope="module")
def flows(tmp_path_factory):
    root = tmp_path_factory.mktemp("flows102")
    bundle = S.copy_bundle(root, V102)
    tasks, snaps = make_task(root / "task")
    out = {}
    with MockLLM() as mock:
        routes = {k: mock.add_route("v102_%s" % k, v) for k, v in SCENARIOS.items()}

        def one(k):
            return k, S.run_eval_cli(bundle=bundle, tasks=tasks, snapshots=snaps, results=root / ("res_%s" % k),
                                     api_base=routes[k], task_ids=[TID], timeout=420)
        with ThreadPoolExecutor(len(SCENARIOS)) as ex:
            runs = dict(ex.map(one, SCENARIOS))
        for k, run in runs.items():
            out[k] = (run, mock.log("v102_%s" % k), mock.summarizer_calls("v102_%s" % k))
        assert not mock.errors, mock.errors
    return out


def resolved(run, log):
    row = run.row(TID)
    assert run.rc == 0 and "Traceback" not in run.stderr, run.stderr[-3000:]
    assert row["error"] is None and row["resolved"] is True, (row, run.patch(TID), run.log(TID)[-3000:])
    patch = run.patch(TID)
    assert "calc/ops.py" in patch and "+    return a + b" in patch and "tests/" not in patch
    assert not [e for e in log if e["exhausted"]], [(e["agent"], e["index"]) for e in log if e["exhausted"]]
    calls = [e for e in log if e["kind"] == "agent"]
    for agent in {e["agent"] for e in calls}:                         # every stage's last prompt, and the biggest
        last = max((e for e in calls if e["agent"] == agent), key=lambda e: e["t_in"])
        assert last["est_prompt_tokens"] < COMPACTION_LINE, (agent, last["est_prompt_tokens"])
    return row


def test_flow_i_close_at_call_15(flows):
    run, log, _ = flows["i"]
    resolved(run, log)
    loc = [o for a, t, o in observations(run, "locator") if t == "run_command"]
    assert len(loc) == 20
    assert not any("LOCATOR CLOSED" in o for o in loc[:14]), loc[13][:300]
    assert all("LOCATOR CLOSED" in o for o in loc[14:]), [o[:120] for o in loc[14:]]
    assert "after 14 calls" in loc[14] and "FILES: calc/ops.py:1-3 (add)" in loc[14], loc[14][:600]
    assert "Reply with your plan now (the draft is above)" in loc[16]          # the loop guard's short form
    fix = [o for a, t, o in observations(run, "fixer") if t == "run_command"]
    assert "LOCATOR DIGEST" in fix[0] and "locator closed after 14 helper calls" in fix[0], fix[0][:600]
    assert "LOCATOR CLOSED" not in fix[1] and "def add" in fix[1], fix[1][:300]  # status reopened the helpers


def test_flow_ii_lost_plan_digest(flows):
    run, log, _ = flows["ii"]
    resolved(run, log)
    fix = [o for a, t, o in observations(run, "fixer") if t == "run_command"]
    assert "LOCATOR DIGEST" in fix[0], fix[0][:600]
    assert "viewed: calc/ops.py 1-3 (add)" in fix[0] and "repro: fails on original (1 of 1 claims)" in fix[0], fix[0]
    first_fixer = requests(log, "fixer")[0]
    msgs = " ".join(str(m.get("content")) for m in first_fixer["body"].get("messages", []))
    assert '[locator] said: run_command(command=' in msgs              # the lost plan is what the fixer was handed


def test_flow_iii_fixer_views_before_status(flows):
    run, log, _ = flows["iii"]
    resolved(run, log)
    fix = [o for a, t, o in observations(run, "fixer") if t == "run_command"]
    assert "LOCATOR CLOSED" in fix[0] and "Any later stage: run python3 /tmp/swe/status.py first" in fix[0], fix[0]
    assert "LOCATOR DIGEST" in fix[1]
    assert "LOCATOR CLOSED" not in fix[2] and "def add" in fix[2], fix[2][:300]
    assert sum("LOCATOR CLOSED" in o for o in fix) == 1


def test_flow_iv_compacted_locator(flows):
    run, log, summ = flows["iv"]
    resolved(run, log)
    assert summ >= 1, "the forced 15,000-token prompt must trigger an in-flow compaction"
    loc = [o for a, t, o in observations(run, "locator") if t == "run_command"]
    st = next(o for o in loc if "STATUS [t=" in o)
    assert "LOCATOR DIGEST" in st and "a locator replies with its plan now" in st, st[:600]
    rep = [o for o in loc if "REPRO:" in o]
    assert rep and "fails on original" in rep[-1], rep            # the helpers answer after the locator's status
    fix = [o for a, t, o in observations(run, "fixer") if t == "run_command"]
    assert "STATUS [t=" in fix[0] and "JOURNAL (last" in fix[0] and "LOCATOR DIGEST" not in fix[0], fix[0][:600]   # a later status: v10.1's form
