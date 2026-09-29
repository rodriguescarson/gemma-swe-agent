"""Component (b) of docs/eval/GOLDEN_EVALS_SPEC.md v1.1: trace writer (6.2), exec checks and the flat per-case record
(6.3), `write` and `--resume` (5.8), and one agents-cli grade of written traces (gotcha 1).

Writer tests run on trimmed real ATIF traces from r2_v10_1 (tests/golden_data/atif_*.json); exec checks run on the
synthetic calc task in the rich Kaggle-parity venv (skipped with the build command when it is absent). No network, no
model, no GPU.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
DATA = TESTS / "golden_data"
for _p in (str(TESTS), str(ROOT / "scripts" / "golden"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("swegemma.evaluate")

from v10_support import sandbox as S  # noqa: E402
from v10_support.repo import no_orphans  # noqa: E402,F401  (autouse)
from golden_data import golden_calc as GC  # noqa: E402

import checks as CK  # noqa: E402
import run_suite as RS  # noqa: E402
import stage_scripts as SS  # noqa: E402
import trace_writer as TW  # noqa: E402

AGENTS_CLI = Path("/Users/carson/.local/bin/agents-cli")
KPAR_OK = CK.T().kpar_ok("rich")
needs_kpar = pytest.mark.skipif(not KPAR_OK, reason=f"kpar venv missing: {CK.T().build_cmd('rich')}")
SAMPLES = ("rich_3043", "fastapi_14492", "fastapi_14419", "fastapi_13537")


def atif(tid: str) -> dict:
    return json.loads((DATA / f"atif_{tid}.json").read_text())


@pytest.fixture(scope="module")
def agents():
    return TW.agents_map(S.BUNDLE)


@pytest.fixture(scope="module", autouse=True)
def tasks_globals():
    """The checks point v10_support.tasks at the calc task; restore its module globals afterwards."""
    t = CK.T()
    saved = (t.TASKS_JSONL, t.SNAP_DIR, t.CACHE, t.WORK, t._TASKS, dict(t._BASE_MEMO))
    yield
    t.TASKS_JSONL, t.SNAP_DIR, t.CACHE, t.WORK, t._TASKS = saved[:5]
    t._BASE_MEMO.clear()
    t._BASE_MEMO.update(saved[5])


def evs(ad: dict) -> list:
    return TW.events(ad)


def parts(e: dict) -> list:
    return (e.get("content") or {}).get("parts") or []


# ---------------------------------------------------------------------------------------------------------- writer
@pytest.mark.parametrize("tid", SAMPLES)
def test_writer_turns_authors_and_call_response_pairing(agents, tid):
    ad, warn = TW.atif_to_agent_data(atif(tid), agents)
    case = {"eval_case_id": tid, "responses": [{"response": {"role": "model", "parts": [{"text": ""}]}}],
            "agent_data": ad}
    assert TW.validate_case(case) == []
    assert [t["turn_index"] for t in ad["turns"]] == list(range(len(ad["turns"])))
    first = evs(ad)[0]
    assert first["author"] == "user" and first["content"]["role"] == "user"
    assert "You are evaluating a software engineering task" in parts(first)[0]["text"]
    pending = []
    for e in evs(ad):
        assert e["author"] == "user" or e["author"] in agents
        for p in parts(e):
            if "function_call" in p:
                assert e["content"]["role"] == "model"
                pending.append((e["author"], p["function_call"]["name"]))
            elif "function_response" in p:
                assert e["content"]["role"] == "user"
                who, name = pending.pop(0)
                assert (e["author"], p["function_response"]["name"]) == (who, name)
                assert isinstance(p["function_response"]["response"], dict)
    n_calls = sum(len(s.get("tool_calls") or []) for s in atif(tid)["steps"])
    n_resp = sum(1 for e in evs(ad) for p in parts(e) if "function_response" in p)
    if tid == "fastapi_13537":
        assert pending == [("locator", "view.py")] and n_resp == n_calls - 1       # the crash left one unanswered
    else:
        assert pending == [] and n_resp == n_calls
    assert "unpaired_observation=" not in " ".join(warn)


def test_writer_multi_call_steps_take_the_system_observation(agents):
    """fastapi_14492: two run_command calls in one step; the second result is a `source: system` step."""
    ad, warn = TW.atif_to_agent_data(atif("fastapi_14492"), agents)
    e = evs(ad)
    i = next(k for k, x in enumerate(e) if len([p for p in parts(x) if "function_call" in p]) == 2)
    calls = [p["function_call"] for p in parts(e[i])]
    assert [c["args"]["command"] for c in calls] == ['python3 /tmp/swe/grep.py "Apache-2.0"',
                                                     'python3 /tmp/swe/grep.py "MIT"']
    r1, r2 = parts(e[i + 1])[0]["function_response"], parts(e[i + 2])[0]["function_response"]
    assert e[i + 1]["author"] == e[i + 2]["author"] == "locator"
    assert "GREP: 0 hits" in r1["response"]["stdout"] and "GREP: 42 hits" in r2["response"]["stdout"]
    assert warn == []


def test_writer_drops_thinking_text_and_keeps_its_call(agents):
    ad, warn = TW.atif_to_agent_data(atif("fastapi_14419"), agents)
    assert "thinking_dropped=1" in warn
    assert "thought<|channel>" not in json.dumps(ad)
    reads = [p["function_call"] for e in evs(ad) for p in parts(e)
             if "function_call" in p and p["function_call"]["name"] == "read_file"]
    assert {"filepath": "fastapi/dependencies/models.py", "start_line": 46, "end_line": 52} in [r["args"] for r in reads]


def test_writer_nudges_compaction_and_unknown_steps(agents):
    steps = [
        {"step_id": 1, "source": "user", "message": "TASK", "extra": {"event_type": "task_prompt", "author": "harness"}},
        {"step_id": 2, "source": "agent", "tool_calls": [{"tool_call_id": "c1", "function_name": "run_command",
                                                          "arguments": {"command": "ls"}, "extra": {"author": "fixer"}}],
         "observation": {"content": "not json"}, "extra": {"author": "fixer"}},
        {"step_id": 3, "source": "system", "message": "summary of events",
         "extra": {"event_type": "compaction", "author": "user"}},
        {"step_id": 4, "source": "agent", "message": "thought", "extra": {"event_type": "thinking", "author": "fixer"}},
        {"step_id": 5, "source": "agent", "message": "done", "extra": {"event_type": "final", "author": "fixer"}},
        {"step_id": 6, "source": "system", "message": "Please continue your work using the available tools",
         "extra": {"event_type": "continuation_nudge", "author": "harness"}},
        {"step_id": 7, "source": "agent", "message": "READY", "extra": {"event_type": "final", "author": "setup"}},
        {"step_id": 8, "source": "ghost", "message": "boo", "extra": {"event_type": "odd"}},
        {"step_id": 9, "source": "agent", "message": "hi", "extra": {"event_type": "final", "author": "stranger"}},
    ]
    ad, warn = TW.atif_to_agent_data({"steps": steps}, agents)
    assert len(ad["turns"]) == 2 and [t["turn_index"] for t in ad["turns"]] == [0, 1]
    t0, t1 = ad["turns"][0]["events"], ad["turns"][1]["events"]
    assert parts(t0[0])[0]["text"] == "TASK"
    assert parts(t0[2])[0]["function_response"]["response"] == {"result": "not json"}
    assert [parts(e)[0].get("text") for e in t0[3:]] == ["done"]          # compaction and thinking dropped
    assert t1[0]["author"] == "user" and "Please continue" in parts(t1[0])[0]["text"]
    assert parts(t1[2]) == [{"text": "[ghost] boo"}] and t1[2]["author"] == "user"
    assert t1[3]["author"] == "stranger" and "stranger" in ad["agents"]
    assert sorted(warn) == ["compaction_dropped=1", "other_step:ghost:odd=1", "thinking_dropped=1",
                            "unknown_author:stranger=1"]
    case = {"eval_case_id": "x", "responses": [{"response": {"role": "model", "parts": [{"text": ""}]}}],
            "agent_data": ad}
    assert TW.validate_case(case) == []


def test_build_case_responses_reference_and_no_prompt(agents):
    """gotcha 1: responses[0] is always present (the live stage's last text in its first stage-run); no prompt."""
    a = atif("rich_3043")
    finals = [s["message"] for s in a["steps"] if (s.get("extra") or {}).get("author") == "fixer"
              and (s.get("extra") or {}).get("event_type") == "final"]
    case = GC.case("F")
    c = TW.build_case(case=case, sample=0, case_id="F__calc_1__s0", agents=agents, atif=a,
                      extra_golden={"live_agents": ["fixer"], "status": "ok", "llm_calls": [{"i": 0}]})
    assert "prompt" not in c and c["responses"][0]["response"]["parts"][0]["text"] == finals[0]
    assert c["reference"] == case["reference"]
    g = c["golden"]
    assert g["case_id"] == "F__calc_1__s0" and g["dataset_case_id"] == "F__calc_1" and g["sample"] == 0
    assert g["suite"] == "F" and g["plan"] == GC.PLAN and g["llm_calls"] == [{"i": 0}] and g["writer_warnings"] == []
    empty = TW.build_case(case=case, sample=1, case_id="F__calc_1__s1", agents=agents, atif=None,
                          extra_golden={"live_agents": ["fixer"], "status": "skipped"})
    assert empty["responses"][0]["response"]["parts"] == [{"text": ""}] and TW.validate_case(empty) == []
    assert empty["golden"]["writer_warnings"] == ["no_atif_trace"]
    assert parts(evs(empty["agent_data"])[0])[0]["text"] == GC.STATEMENT


def test_stage_runs_repro_text_and_live_counts(agents):
    a = atif("rich_3043")
    ad, _ = TW.atif_to_agent_data(a, agents)
    loc = TW.first_stage_run(ad, "locator")
    assert loc and all(e["author"] == "locator" for e in loc)
    cmds = [tc["arguments"]["command"] for s in a["steps"] for tc in s.get("tool_calls") or []
            if (tc.get("extra") or {}).get("author") == "locator" and "--repro-only" in str(tc.get("arguments"))]
    body = TW.repro_text_of(ad, "locator")
    if cmds:
        want = cmds[-1].split("\n", 1)[1].rsplit("\nEOF", 1)[0] + "\n"
        assert body == want
    else:
        assert body is None
    n = sum(1 for s in a["steps"] for tc in s.get("tool_calls") or [] if (tc.get("extra") or {}).get("author") == "fixer")
    assert TW.live_tool_calls(ad, "fixer") == n
    assert TW.live_final_text(ad, "setup") == "READY"


def test_agents_map_from_the_bundle():
    bundle = TW.bundle_agents(S.BUNDLE)
    assert [n for n, _ in bundle] == ["setup", "locator", "fixer", "verifier", "submitter"]
    m = TW.agents_map(S.BUNDLE)
    assert m["fixer"]["instruction"] == (S.BUNDLE / "prompts" / "fixer.md").read_text()
    names = {a: [d["name"] for d in v["tools"][0]["function_declarations"]] for a, v in m.items()}
    assert "run_command" in names["setup"] and "run_skill_script" in names["setup"]
    assert "submit_patch" in names["verifier"] and "submit_patch" not in names["fixer"]
    over = TW.agents_map(S.BUNDLE, {"fixer": ["a", "b"]})
    assert [d["name"] for d in over["fixer"]["tools"][0]["function_declarations"]] == ["a", "b"]
    assert TW.max_output_tokens(S.BUNDLE) == {"setup": 256, "locator": 768, "fixer": 2048, "verifier": 2048,
                                              "submitter": 1024}


# ----------------------------------------------------------------------------------------------- status and parsing
def test_decide_status_rules():
    ok_route = {"infra": [], "t_live0": 5.0, "pre_stage_s": 3.0, "upstream_failed_last": False}
    row = {"error": None}
    D = CK.decide_status
    assert D(skipped="not runnable: x") == ("skipped", "not runnable: x")
    assert D(row=row, route_state=ok_route) == ("ok", "")
    assert D(budget_refused=True, row=row, route_state=ok_route)[1] == "budget"
    assert D(row=row, route_state={**ok_route, "infra": ["budget"]}) == ("infra_error", "budget")
    assert D(launched=False) == ("infra_error", "not launched")
    assert D(child_timeout=True, row=row, route_state=ok_route) == ("infra_error", "child_timeout")
    assert D(row=row, route_state={**ok_route, "infra": ["unknown_request"]}) == ("infra_error", "unknown_request")
    assert D(row=row, route_state={**ok_route, "upstream_failed_last": True}) == ("infra_error", "upstream_http")
    assert D(row=None, child_rc=1, route_state=ok_route)[0] == "infra_error"
    assert D(row={"error": "Snapshot file not found: x"}, route_state=ok_route)[1].startswith("setup:")
    assert D(row=row, route_state=ok_route, replay_bad=["edit.py a.py"])[1].startswith("replay step not OK")
    assert D(row=row, route_state={**ok_route, "t_live0": None}) == ("infra_error", "live stage never started")
    assert D(row=row, route_state={**ok_route, "pre_stage_s": 151.0}, pre_s=150)[1].startswith("pre_stage_slow")
    assert D(row=row, route_state={**ok_route, "pre_stage_s": 149.0}, pre_s=150) == ("ok", "")
    assert D(row={"error": "Sandbox execution error: Tool 'view.py' not found."}, route_state=ok_route,
             crash="unknown_tool") == ("model_error", "unknown_tool")
    # an infra cause outranks a model crash: the case is excluded, not counted as a model failure
    assert D(row=row, route_state={**ok_route, "infra": ["budget"]}, crash="key_error")[0] == "infra_error"


def test_crash_classes_match_replay_l4():
    assert CK.crash_class(["Sandbox execution error: Tool 'view.py' not found."]) == "unknown_tool"
    assert CK.crash_class(["litellm.ContextWindowExceededError: ..."]) == "context_overflow"
    assert CK.crash_class(["KeyError: 'plan'"]) == "key_error"
    assert CK.crash_class(["No LlmAgent model available"]) == "post_invocation"
    assert CK.crash_class(["Agent exceeded session timeout (2.9 min)", None, ""]) is None


def test_replay_failures_and_repro_body():
    def step(author, command, stdout, code=0):
        return {"source": "agent", "tool_calls": [{"function_name": "run_command", "arguments": {"command": command},
                                                   "extra": {"author": author}}],
                "observation": {"content": json.dumps({"status": "ok" if code == 0 else "error", "stdout": stdout,
                                                       "exit_code": code})}, "extra": {"author": author}}
    steps = [step("fixer", "python3 /tmp/swe/edit.py a.py --lines 1-2 <<'EOF'\nx\nEOF", "OK (lines): a.py"),
             step("fixer", "python3 /tmp/swe/edit.py b.py --lines 1-2 <<'EOF'\nx\nEOF", "REFUSED: b.py is a test"),
             step("fixer", SS.git_apply_step(GC.GOLD)["args"]["command"], "", code=1),
             step("verifier", "python3 /tmp/swe/edit.py c.py --lines 1-2 <<'EOF'\nx\nEOF", "NO MATCH"),
             step("fixer", "python3 /tmp/swe/verify.py", "VERIFY: RED")]
    bad = CK.replay_failures(steps, "fixer")
    assert bad == ["python3 /tmp/swe/edit.py b.py --lines 1-2 <<'EOF'", "git apply replay"]
    assert CK.replay_failures(steps, "verifier") == ["python3 /tmp/swe/edit.py c.py --lines 1-2 <<'EOF'"]
    assert CK.repro_body("python3 /tmp/swe/verify.py --repro-only <<'EOF'\nimport x\nassert 1\nEOF") == \
        "import x\nassert 1\n"
    assert CK.repro_body("python3 /tmp/swe/verify.py --repro-only") is None
    assert CK.repro_body("python3 /tmp/swe/verify.py") is None


def test_patch_files_formats():
    git = ("diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x\n"
           "diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
    assert CK.patch_files(git) == [["new.py", True], ["old.py", False]]
    assert CK.deleted_files(git) == {"old.py"}
    assert CK.patch_files(GC.GOLD) == [["calc/ops.py", False]]
    assert CK.patch_files("") == []
    files = [["tests/test_new.py", True], ["repro.py", True], ["conftest.py", True], ["calc/ops.py", False],
             ["debug.log", True]]
    assert CK.protected_paths(files) == ["tests/test_new.py", "conftest.py"]
    assert CK.scratch_paths(files) == ["repro.py", "debug.log"]


def test_known_flaky_is_the_flow_tests_list():
    import test_v10_flow as flow
    assert CK.KNOWN_FLAKY == flow.KNOWN_FLAKY
    assert CK.all_flaky([("tests.test_console", "test_brokenpipeerror")])
    assert CK.all_flaky([("test_console", "test_brokenpipeerror")])
    assert not CK.all_flaky([("tests.test_console", "test_brokenpipeerror"), ("tests.test_text", "test_x")])
    assert not CK.all_flaky([]) and not CK.all_flaky(None)


# ------------------------------------------------------------------------------------------------------ exec checks
@pytest.fixture(scope="module")
def calc(tmp_path_factory):
    root = tmp_path_factory.mktemp("golden_checks")
    env = GC.make_env(root)
    CK.configure_tasks(env["tasks_jsonl"], env["snapshots_dir"], root / "ws")
    return root


SYNTAX = GC.GOLD.replace("+    return a + b", "+    return a +")
GARBAGE = "--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -40,3 +40,3 @@\n not here\n-nothing\n+something\n"
EXTRA = ("diff --git a/tests/test_new.py b/tests/test_new.py\nnew file mode 100644\n--- /dev/null\n"
         "+++ b/tests/test_new.py\n@@ -0,0 +1 @@\n+x = 1\n"
         "diff --git a/repro.py b/repro.py\nnew file mode 100644\n--- /dev/null\n+++ b/repro.py\n@@ -0,0 +1 @@\n"
         "+print(1)\n")


@needs_kpar
def test_checks_gold_passes_and_wrong_fails(calc):
    g = CK.compute(GC.case("V", "gold"), GC.GOLD)
    assert (g["applies"], g["compiles"], g["hidden_pass"], g["hidden_retried"]) == (True, True, True, False)
    assert (g["hidden_nodes_total"], g["hidden_nodes_pass"], g["pre_hidden_nodes_pass"]) == (1, 1, 1)
    assert g["patch_files"] == [["calc/ops.py", False]] and g["errors"] == [] and g["not_computed"] == ""
    w = CK.compute(GC.case("V", "wrong"), GC.WRONG)
    assert (w["applies"], w["compiles"], w["hidden_pass"]) == (True, True, False)
    assert (w["hidden_nodes_total"], w["hidden_nodes_pass"]) == (1, 0) and "failed" in w["hidden_why"]
    assert not re.search(r" in \d", w["hidden_why"])            # pytest's duration is stripped: `write` is deterministic
    f = CK.compute(GC.case("F"), GC.GOLD)
    assert f["hidden_pass"] is True and f["hidden_nodes_total"] is None          # F counts nodes only with --nodes
    assert CK.compute(GC.case("F"), GC.GOLD, nodes=True)["hidden_nodes_pass"] == 1
    e = CK.compute(GC.case("V", "empty"), "")
    assert (e["applies"], e["compiles"], e["hidden_pass"], e["hidden_nodes_pass"]) == (True, True, False, 0)


@needs_kpar
def test_checks_garbage_does_not_apply_and_syntax_error_does_not_compile(calc):
    g = CK.compute(GC.case("F"), GARBAGE)
    assert g["applies"] is False and g["compiles"] is False and g["hidden_pass"] is False
    assert "did not apply" in g["hidden_why"]
    s = CK.compute(GC.case("F"), SYNTAX)
    assert s["applies"] is True and s["compiles"] is False and s["hidden_pass"] is False
    assert [e[0] for e in s["compile_errors"]] == ["calc/ops.py"]


@needs_kpar
def test_checks_list_protected_and_scratch_paths(calc):
    c = CK.compute(GC.case("F"), EXTRA)
    assert c["applies"] is True and c["compiles"] is True
    assert c["protected_paths"] == ["tests/test_new.py"] and c["scratch_paths"] == ["repro.py"]
    assert c["patch_files"] == [["tests/test_new.py", True], ["repro.py", True]]


@needs_kpar
def test_checks_L_repro_validity(calc, monkeypatch):
    c = CK.compute(GC.case("L"), "", repro_text=GC.CLAIM)
    assert (c["repro_fails_orig"], c["repro_passes_gold"], c["repro_text"]) == (True, True, GC.CLAIM)
    ok_everywhere = CK.compute(GC.case("L"), "", repro_text="print('fine')\n")
    assert (ok_everywhere["repro_fails_orig"], ok_everywhere["repro_passes_gold"]) == (False, True)
    monkeypatch.setattr(CK, "REPRO_TIMEOUT", 2)
    ws_path = CK.compute(GC.case("L"), "", repro_text="import os\nassert os.path.isfile('/workspace/calc/ops.py')\n"
                         "import time\nfrom calc.ops import add\nwhile add(2, 3) != 5:\n    time.sleep(1)\n")
    assert (ws_path["repro_fails_orig"], ws_path["repro_passes_gold"]) == (True, True)    # /workspace mapped; hang
    assert CK.compute(GC.case("L"), "")["repro_fails_orig"] is None


@needs_kpar
@pytest.mark.xfail(strict=True, reason="tests/test_v10_flow.py GOLD has no trailing context, so git apply anchors its "
                   "hunk at end-of-file and the harness apply pipeline rejects it; the flow test only stores it as the "
                   "task's reference patch (golden_calc.GOLD is the real `git diff -U3` of the same change)")
def test_flow_test_gold_patch_applies(calc):
    ws = CK.T().fresh_ws(CK.T().base_ws(GC.TID), calc / "flowgold")
    rc, err = CK.T().harness_apply(ws, GC.FLOW_GOLD)
    assert rc == 0, err


def test_checks_never_raise_when_not_runnable(calc):
    """gotcha 12: tasks.py would pytest.skip on a missing snapshot or venv; checks record why instead."""
    missing = GC.case("F", task="calc_missing")
    out = CK.compute(missing, GC.GOLD)
    assert out["hidden_pass"] is None and out["applies"] is None and "calc_missing" in out["not_computed"]
    assert out["patch_files"] == [["calc/ops.py", False]]
    no_venv = GC.case("F")
    no_venv["golden"]["repo"] = "no_such_repo_venv"
    ok, why = CK.runnable(GC.TID, no_venv["golden"])
    assert not ok and "kpar venv missing" in why
    assert CK.compute(no_venv, GC.GOLD)["hidden_pass"] is None
    ug = GC.case("F", gradable=False)
    if KPAR_OK:
        out = CK.compute(ug, GC.GOLD)
        assert out["hidden_pass"] is None and out["applies"] is True and out["not_computed"].startswith("not gradable")


# ------------------------------------------------------------------------------------ write, resume and agents-cli
def _budget_run(root: Path, env: dict) -> dict:
    """A vllm run with an explicit cap below the router's 0.01 margin: the first live request is refused (HTTP 500)
    before anything is forwarded; the parent kills that child at once and launches nothing more. Near-zero prices keep
    the pre-launch estimate under the cap, so this is the mid-run refusal, not the pre-launch one."""
    from golden_data.fake_upstream import FakeUpstream
    up = FakeUpstream({"fixer": [{"text": "x"}]})
    try:
        ds = GC.write_dataset(root / "F_budget.json", [GC.case("F"), dict(GC.case("F"), eval_case_id="F__calc_1_b")])
        rc = RS.main(["run", "--suite", "F", "--split", "dev", "--endpoint", "vllm", "--upstream-base", up.base,
                      "--max-usd", "0.005", "--price-in", "1e-9", "--price-out", "1e-9", "--dataset", str(ds),
                      "--out", str(root / "runs"), "--tasks-jsonl",
                      env["tasks_jsonl"], "--snapshots-dir", env["snapshots_dir"], "--ws-cache", str(root / "ws"),
                      "--plain-cache", str(root / "plain"), "--holdout-log", str(root / "hl.jsonl"), "--run-id",
                      "budget", "-j", "1"])
        return {"rc": rc, "dir": root / "runs" / "budget", "seen": list(up.seen)}
    finally:
        up.close()


@pytest.fixture(scope="module")
def resume_run(tmp_path_factory, calc):
    """A null F run with one good case and one whose preparation fails, then the same run with --resume (and, in
    parallel, the budget-stop run)."""
    if not KPAR_OK:
        pytest.skip(f"kpar venv missing: {CK.T().build_cmd('rich')}")
    root = tmp_path_factory.mktemp("golden_write")
    env = GC.make_env(root)
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)
    budget = pool.submit(_budget_run, root, env)
    ds = GC.write_dataset(root / "F_dev.json", [GC.case("F"), dict(GC.case("F"), eval_case_id="F__calc_1_bad"),
                                                GC.case("F", task="calc_missing")])
    calls = {"bad": 0}

    def hook(case, k, scripts, live_script):
        if case["eval_case_id"].endswith("_bad"):
            calls["bad"] += 1
            raise RuntimeError(f"scripted failure {calls['bad']}")
        return scripts, live_script
    argv = ["run", "--suite", "F", "--split", "dev", "--endpoint", "null", "--dataset", str(ds), "--out",
            str(root / "runs"), "--tasks-jsonl", env["tasks_jsonl"], "--snapshots-dir", env["snapshots_dir"],
            "--ws-cache", str(root / "ws"), "--plain-cache", str(root / "plain"), "--holdout-log",
            str(root / "hl.jsonl"), "--run-id", "w", "-j", "3"]
    d = RS.Runner(RS.parser().parse_args(argv), script_hook=hook).run()
    first = {p.name: json.loads(p.read_text()) for p in (d / "cases").glob("*.json")}
    meta_ok = (d / "cases" / "F__calc_1__s0" / "meta.json").stat().st_mtime_ns
    traces1 = (d / "traces" / "F_dev.json").read_text()
    RS.Runner(RS.parser().parse_args(argv + ["--resume"]), script_hook=hook).run()
    second = {p.name: json.loads(p.read_text()) for p in (d / "cases").glob("*.json")}
    b = budget.result()
    pool.shutdown()
    CK.configure_tasks(env["tasks_jsonl"], env["snapshots_dir"], root / "ws")
    return {"dir": d, "first": first, "second": second, "calls": calls["bad"], "traces1": traces1,
            "meta_same": meta_ok == (d / "cases" / "F__calc_1__s0" / "meta.json").stat().st_mtime_ns, "budget": b}


def test_budget_refusal_stops_the_run(resume_run):
    b = resume_run["budget"]
    d = b["dir"]
    a2 = json.loads((d / "cases" / "F__calc_1__s0.json").read_text())
    b2 = json.loads((d / "cases" / "F__calc_1_b__s0.json").read_text())
    assert a2["status"] == "infra_error" and a2["status_detail"] == "budget" and a2["wall_s"] < 90   # killed at once
    assert b2["status"] == "infra_error" and b2["status_detail"] == "budget" and b2["wall_s"] is None   # not launched
    assert b["seen"] == []                                                     # nothing was forwarded
    recs = [json.loads(x) for x in (d / "cases" / "F__calc_1__s0" / "router.jsonl").read_text().splitlines()]
    assert any(r["served"] == "refused" and r["http_status"] == 500 for r in recs)
    meta = json.loads((d / "cases" / "F__calc_1__s0" / "meta.json").read_text())
    assert meta["killed"] == "budget"


def test_assemble_without_a_bundle_path(resume_run, tmp_path):
    """Regression: Path("") is "." (a directory), so a run.json without bundle_copy once made the writer read the cwd."""
    d = tmp_path / "copy"
    shutil.copytree(resume_run["dir"], d, ignore=shutil.ignore_patterns("bundle"))
    run = json.loads((d / "run.json").read_text())
    run.pop("bundle_copy")
    (d / "run.json").write_text(json.dumps(run))
    rec = RS.assemble(d, "F__calc_1__s0", checks=False)
    assert rec["flat"]["status"] == "ok" and TW.validate_case(rec["trace"]) == []
    assert rec["trace"]["golden"]["run"]["max_output_tokens"] == {}


def test_grade_calls_agents_cli_and_summary_as_subprocesses(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    (run_dir / "traces").mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"suite": "F"}))
    monkeypatch.setattr(RS, "AGENTS_CLI", tmp_path / "missing-agents-cli")
    assert RS.grade(run_dir)["agents_cli"] is None                       # skipped when absent
    log = tmp_path / "calls.txt"
    cli = tmp_path / "agents-cli"
    cli.write_text(f"#!/bin/sh\necho \"cli $*\" >> {log}\n")
    cli.chmod(0o755)
    summ = tmp_path / "summary.py"
    summ.write_text(f"import sys\nopen({str(log)!r}, 'a').write('summary ' + ' '.join(sys.argv[1:]) + chr(10))\n")
    (tmp_path / "eval_config_F.yaml").write_text("metrics_to_run: []\n")
    monkeypatch.setattr(RS, "AGENTS_CLI", cli)
    monkeypatch.setattr(RS, "SUMMARY", summ)
    monkeypatch.setattr(RS, "EVAL_DIR", tmp_path)
    res = RS.grade(run_dir)
    assert res == {"agents_cli": 0, "summary": 0}
    lines = log.read_text().splitlines()
    assert lines[0] == (f"cli eval grade --traces {run_dir / 'traces'} --config {tmp_path / 'eval_config_F.yaml'} "
                        f"--output {run_dir / 'grade'} --qps 500")
    assert lines[1] == f"summary {run_dir}"


def test_one_failing_case_does_not_stop_others_and_resume_reruns_only_failures(resume_run):
    r = resume_run
    f1, f2 = r["first"], r["second"]
    assert f1["F__calc_1__s0.json"]["status"] == "ok"
    assert f1["F__calc_1_bad__s0.json"]["status"] == "infra_error"
    assert f1["F__calc_1_bad__s0.json"]["status_detail"] == "runner: RuntimeError: scripted failure 1"
    assert f1["F__calc_missing__s0.json"]["status"] == "skipped"
    assert r["calls"] == 2                                            # the failed case was attempted again
    assert f2["F__calc_1_bad__s0.json"]["status_detail"] == "runner: RuntimeError: scripted failure 2"
    assert r["meta_same"] and f2["F__calc_1__s0.json"]["wall_s"] == f1["F__calc_1__s0.json"]["wall_s"]
    run = json.loads((r["dir"] / "run.json").read_text())
    assert run["cases"] == {"total": 3, "ok": 1, "model_error": 0, "infra_error": 1, "skipped": 1}


def test_flat_record_has_every_field_of_6_3(resume_run):
    f = resume_run["second"]["F__calc_1__s0.json"]
    for k in ("case_id", "dataset_case_id", "suite", "task", "variant", "sample", "split", "status", "status_detail",
              "crash_class", "endpoint", "label", "upstream_model", "providers", "bundle_sha", "fixture_sha",
              "wall_s", "pre_stage_s", "capped", "live", "harness", "paths", "exec_checks"):
        assert k in f, k
    assert set(f["live"]) >= {"agent", "llm_calls", "tool_calls", "prompt_tokens", "completion_tokens", "cost_usd",
                              "max_prompt_tokens", "t_first", "t_last"}
    assert set(f["harness"]) == {"error", "tool_calls", "llm_calls", "duration_s"}
    assert set(f["paths"]) == {"patch", "atif", "router_log"}
    ec = f["exec_checks"]
    for k in ("patch_files", "applies", "compiles", "compile_errors", "hidden_pass", "hidden_why", "hidden_secs",
              "hidden_retried", "hidden_nodes_total", "hidden_nodes_pass", "pre_hidden_nodes_pass", "repro_text",
              "repro_fails_orig", "repro_passes_gold", "harness_resolved"):
        assert k in ec, k
    assert f["label"] == "CONTROL" and f["live"]["agent"] == "fixer" and ec["hidden_pass"] is False
    skipped = resume_run["second"]["F__calc_missing__s0.json"]
    assert skipped["exec_checks"] == {"not_computed": "status skipped"}


def test_write_is_idempotent(resume_run):
    d = resume_run["dir"]
    before = {p.name: json.loads(p.read_text()) for p in (d / "cases").glob("*.json")}
    assert RS.main(["write", str(d), "-j", "2"]) == 0
    after = {p.name: json.loads(p.read_text()) for p in (d / "cases").glob("*.json")}

    def strip(x):
        x = json.loads(json.dumps(x))
        if isinstance(x.get("exec_checks"), dict):
            x["exec_checks"].pop("hidden_secs", None)
        return x
    assert {k: strip(v) for k, v in before.items()} == {k: strip(v) for k, v in after.items()}
    tr = json.loads((d / "traces" / "F_dev.json").read_text())
    assert [c["eval_case_id"] for c in tr["eval_cases"]] == ["F__calc_1__s0", "F__calc_1_bad__s0",
                                                               "F__calc_missing__s0"]
    for c in tr["eval_cases"]:
        assert TW.validate_case(c) == [] and "prompt" not in c


@needs_kpar
def test_resume_counts_every_attempt_and_caps_the_run_total(tmp_path, calc):
    """Regression (review 2026-09-30): --resume deleted a re-run case's dir (router.jsonl included), so the earlier
    attempt's spend vanished from spent_usd, and each invocation started a fresh budget, so --max-usd did not cap the
    run's total; wall_s also spanned the idle gap between invocations. Now the earlier attempt moves to
    attempts/<case>.attempt<N>/, spent_usd sums every attempt, the budget starts at what the run already spent, and
    wall_s counts active time only."""
    from golden_data.fake_upstream import FakeUpstream
    env = GC.make_env(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_KEY=sk-or-v1-test\n")
    ds = GC.write_dataset(tmp_path / "F_dev.json", [GC.case("F")])
    up = FakeUpstream({"fixer": [SS.STATUS] * 5}, fail=[200] + [400] * 40, cost=0.02)
    t = CK.T()
    saved = (t.TASKS_JSONL, t.SNAP_DIR, t.CACHE)                      # RS.main repoints the checks; the calc tests
    d = tmp_path / "runs" / "r"
    cid = "F__calc_1__s0"

    def run(max_usd):
        return RS.main(["run", "--suite", "F", "--split", "dev", "--endpoint", "openrouter", "--upstream-base",
                        up.base, "--env-file", str(tmp_path / ".env"), "--price-in", "1e-9", "--price-out", "1e-9",
                        "--max-usd", str(max_usd), "--dataset", str(ds), "--out", str(tmp_path / "runs"),
                        "--tasks-jsonl", env["tasks_jsonl"], "--snapshots-dir", env["snapshots_dir"], "--ws-cache",
                        str(tmp_path / "ws"), "--plain-cache", str(tmp_path / "plain"), "--holdout-log",
                        str(tmp_path / "hl.jsonl"), "--run-id", "r", "-j", "1", *(["--resume"] if resumed else [])])
    try:
        resumed = False
        assert run(1.0) == 0                                          # 1 billed call, then HTTP 400s
        f1 = json.loads((d / "cases" / f"{cid}.json").read_text())
        run1 = json.loads((d / "run.json").read_text())
        assert f1["status"] == "infra_error" and f1["status_detail"] == "upstream_http"
        assert run1["spent_usd"] == 0.02 and run1["budget_usd"] == 1.0
        resumed = True
        up.fail = []
        # attempt 2 under a cap of 0.025: the budget starts at the 0.02 already spent, so the router refuses at once
        # (0.02 >= 0.025 - 0.01); a fresh budget would have forwarded
        n_seen = len(up.seen)
        assert run(0.025) == 0
        f2 = json.loads((d / "cases" / f"{cid}.json").read_text())
        assert f2["status_detail"] == "budget" and len(up.seen) == n_seen
        assert (d / "attempts" / f"{cid}.attempt1" / "router.jsonl").is_file()
        assert json.loads((d / "attempts" / f"{cid}.attempt1" / "flat.json").read_text())["status_detail"] == \
            "upstream_http"
        run2 = json.loads((d / "run.json").read_text())
        assert run2["spent_usd"] == 0.02 and run2["prior_spent_usd"] == 0.02
        # attempt 3 succeeds; an old t_start (a day ago) must not leak the idle gap into wall_s
        run2["t_start"] = run2["t_start"] - 86400
        (d / "run.json").write_text(json.dumps(run2))
        up.counters, up.script = {}, {"fixer": [SS.STATUS, {"text": "CHANGED: nothing\nVERIFY: none"}]}
        assert run(1.0) == 0
        f3 = json.loads((d / "cases" / f"{cid}.json").read_text())
        run3 = json.loads((d / "run.json").read_text())
        paid3 = sum(r["cost_usd"] for r in map(json.loads, (d / "cases" / cid / "router.jsonl").read_text()
                                                .splitlines()))
        assert f3["status"] == "ok" and f3["prior_attempts"] == 2 and paid3 == pytest.approx(0.04)   # 2 live calls
        assert run3["spent_usd"] == pytest.approx(0.02 + 0.0 + paid3) and run3["attempts_kept"] == 2
        assert sorted(p.name for p in (d / "attempts").iterdir()) == [f"{cid}.attempt1", f"{cid}.attempt2"]
        assert run3["wall_s"] < 3600 and run3["wall_s"] >= run2["wall_s"] and run3["resumes"] == 2
        assert run3["providers_seen"] == ["FakeProv"] and run3["cases"]["ok"] == 1
    finally:
        up.close()
        CK.configure_tasks(*saved)


SIG_DRIVER = """
import json, signal, sys, time
signal.signal(signal.SIGINT, signal.default_int_handler)   # a background job starts with SIGINT ignored
from pathlib import Path
ROOT = Path(%r)
sys.path[:0] = [str(ROOT / "scripts" / "golden"), str(ROOT / "tests"), str(ROOT / "scripts")]
import run_suite as RS
from golden_data import golden_calc as GC
root, resume = Path(sys.argv[1]), sys.argv[2] == "resume"
if resume:
    env = json.loads((root / "env.json").read_text())
else:
    env = GC.make_env(root)
    (root / "env.json").write_text(json.dumps(env))
cases = [dict(GC.case("F"), eval_case_id="F__calc_1_%%d" %% i) for i in range(4)]
ds = GC.write_dataset(root / "F_dev.json", cases)
argv = ["run", "--suite", "F", "--split", "dev", "--dataset", str(ds), "--out", str(root / "runs"),
        "--tasks-jsonl", env["tasks_jsonl"], "--snapshots-dir", env["snapshots_dir"], "--ws-cache", str(root / "ws"),
        "--plain-cache", str(root / "plain"), "--holdout-log", str(root / "hl.jsonl"), "--endpoint", "null",
        "--run-id", "sig", "-j", "4" if resume else "1"] + (["--resume"] if resume else [])

def hook(case, k, scripts, live):
    scripts = {a: list(s) for a, s in scripts.items()}
    if not resume:
        scripts["locator"][0] = dict(scripts["locator"][0], delay=6)     # each case takes over 6 s
    return scripts, live
try:
    RS.Runner(RS.parser().parse_args(argv), script_hook=hook).run()
except KeyboardInterrupt:
    sys.exit(130)
""" % str(ROOT)


@needs_kpar
@pytest.mark.parametrize("sig", ["SIGINT", "SIGTERM"])
def test_a_signal_stops_launching_kills_children_and_writes_a_resumable_run(tmp_path, calc, sig):
    """Regression (review 2026-09-30): Ctrl-C did not stop a run. The executor's shutdown waited for every queued case,
    and the children (own session) never saw the terminal's SIGINT, so cases kept launching and forwarding upstream up
    to --max-usd; run.json was left 'running' with no traces. Now the first SIGINT or SIGTERM cancels queued cases,
    kills the live children, writes the partial run as 'interrupted' and exits 130; --resume then finishes it."""
    drv = tmp_path / "drv.py"
    drv.write_text(SIG_DRIVER)
    import os
    import signal as S_
    import threading
    import time
    p = subprocess.Popen([sys.executable, "-u", str(drv), str(tmp_path), "fresh"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    lines, got_launch = [], threading.Event()

    def reader():
        for ln in p.stdout:
            lines.append((time.monotonic(), ln.rstrip()))
            if " launch F__" in ln:
                got_launch.set()
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        assert got_launch.wait(120), [x for _, x in lines]
        time.sleep(2.0)                                           # mid-case: its locator is scripted to take 6 s
        t_sig = time.monotonic()
        os.kill(p.pid, getattr(S_, sig))
        rc = p.wait(timeout=120)
        t_exit = time.monotonic()
    finally:
        if p.poll() is None:
            p.kill()
    th.join(10)
    text_out = "\n".join(x for _, x in lines)
    assert rc == 130, text_out
    launches = [(t, x) for t, x in lines if " launch F__" in x]
    assert [x.split()[-1] for _, x in launches] == ["F__calc_1_0__s0"], text_out   # nothing launched after it
    assert t_exit - t_sig < 30, (t_exit - t_sig, text_out)        # the uninterrupted run takes 4 x 12+ s
    assert "interrupted: no new launches" in text_out and "continue it with the same command plus --resume" in text_out
    d = tmp_path / "runs" / "sig"
    run = json.loads((d / "run.json").read_text())
    assert run["status"] == "interrupted" and run["cases"]["total"] == 1 and run["cases"]["infra_error"] == 1
    flat = json.loads((d / "cases" / "F__calc_1_0__s0.json").read_text())
    assert flat["status"] == "infra_error" and flat["status_detail"] == "interrupted"
    assert json.loads((d / "cases" / "F__calc_1_0__s0" / "meta.json").read_text())["killed"] == "interrupted"
    tr = json.loads((d / "traces" / "F_dev.json").read_text())
    assert [c["eval_case_id"] for c in tr["eval_cases"]] == ["F__calc_1_0__s0"]
    assert sorted(x.name for x in (d / "cases").iterdir() if x.is_dir()) == ["F__calc_1_0__s0"]
    if sig == "SIGINT":                                           # the interrupted run resumes to completion
        r = subprocess.run([sys.executable, "-u", str(drv), str(tmp_path), "resume"], capture_output=True, text=True,
                           timeout=600)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        run = json.loads((d / "run.json").read_text())
        assert run["status"] == "written" and run["cases"]["total"] == 4 and run["cases"]["ok"] == 4, run["cases"]
        assert (d / "attempts" / "F__calc_1_0__s0.attempt1" / "meta.json").is_file()


@pytest.mark.skipif(not AGENTS_CLI.is_file(), reason=f"{AGENTS_CLI} absent")
def test_agents_cli_grades_written_traces_with_zero_errors(resume_run, agents, tmp_path):
    """gotcha 1 end to end: real runner traces plus writer output from four real ATIF traces, local code metrics."""
    traces = tmp_path / "traces"
    traces.mkdir()
    shutil.copy(resume_run["dir"] / "traces" / "F_dev.json", traces / "F_dev.json")
    cases = [TW.build_case(case=GC.case("F"), sample=0, case_id=f"S__{tid}__s0", agents=agents, atif=atif(tid),
                           extra_golden={"live_agents": ["fixer"], "status": "ok", "llm_calls": []})
             for tid in SAMPLES]
    TW.write_dataset(traces / "samples.json", cases)
    (tmp_path / "m_calls.py").write_text(
        "import json\n"
        "def evaluate(instance):\n"
        "    n = 0\n"
        "    for t in (instance.get('agent_data') or {}).get('turns', []):\n"
        "        for e in t.get('events', []):\n"
        "            n += sum(1 for p in (e.get('content') or {}).get('parts', []) if 'function_call' in p)\n"
        "    g = instance.get('golden') or {}\n"
        "    return {'score': float(n), 'explanation': json.dumps({'applicable': True, 'suite': g.get('suite')})}\n")
    (tmp_path / "m_reply.py").write_text(
        "def evaluate(instance):\n"
        "    r = instance.get('response') or {}\n"
        "    return {'score': float(len(''.join(p.get('text', '') for p in r.get('parts', [])))), 'explanation': ''}\n")
    (tmp_path / "cfg.yaml").write_text("metrics_to_run: [m_calls, m_reply]\ncustom_metrics:\n"
                                       "  - name: m_calls\n    custom_function_file: m_calls.py\n"
                                       "  - name: m_reply\n    custom_function_file: m_reply.py\n")
    r = subprocess.run([str(AGENTS_CLI), "eval", "grade", "--traces", str(traces), "--config",
                        str(tmp_path / "cfg.yaml"), "--output", str(tmp_path / "grade"), "--qps", "500"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    res = json.loads(next((tmp_path / "grade").glob("results_*.json")).read_text())
    summ = {m["metric_name"]: m for m in res["summary_metrics"]}
    for name in ("m_calls", "m_reply"):
        assert summ[name]["num_cases_error"] == 0 and summ[name]["num_cases_valid"] == 7, summ[name]


def test_gitignore_keeps_run_sandboxes_out_of_git():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert "eval/golden/runs/*/cases/*/" in lines and "eval/golden/runs/*/bundle/" in lines
