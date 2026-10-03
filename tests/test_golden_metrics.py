"""Golden-eval metric library and generated agents-cli files (docs/eval/GOLDEN_EVALS_SPEC.md v1.1 sections 7, 12c).

Every metric of the 7.2 registry on synthetic instances (base and edge cases: empty agent_data, no live events,
missing exec_checks, vacuous functions, a plan without FILES:, unparsed tool-call text, restarts, capped), the
library's own contract (Python 3.8 syntax, stdlib whitelist, no module-level side effects, replay_l4 constants), the
generated files (in sync, each exec'd standalone the way agents-cli 1.7.0 does it: gotcha 2), and agreement of the X
metrics with scripts/replay_l4.py on every r2_v10_1 trace (gotcha 23). No network, no model, no GPU.
"""
import ast
import copy
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "eval" / "golden", ROOT / "scripts" / "golden", ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import golden_metrics as GM  # noqa: E402
import gen_config as GC  # noqa: E402
import replay_l4 as R  # noqa: E402

LIB = ROOT / "eval" / "golden" / "golden_metrics.py"
R2 = ROOT / "eval" / "race2" / "eval" / "runs" / "r2_v10_1"
AGENT = {"L": "locator", "F": "fixer", "V": "verifier"}
PREV = {"L": "setup", "F": "locator", "V": "fixer"}
NEXT = {"L": "fixer", "F": "verifier", "V": "submitter"}
CAPS = {"setup": 256, "locator": 768, "fixer": 2048, "verifier": 2048, "submitter": 1024}


# ---------------------------------------------------------------------------------------------------------------------
# Synthetic instance builders (spec 6.2 shapes)
# ---------------------------------------------------------------------------------------------------------------------
def call(author, name, args=None):
    return {"author": author, "content": {"role": "model", "parts": [{"function_call": {"name": name, "args": args or {}}}]}}


def resp(author, name, response):
    return {"author": author, "content": {"role": "user", "parts": [{"function_response": {"name": name,
                                                                                          "response": response}}]}}


def text(author, t):
    return {"author": author, "content": {"role": "model", "parts": [{"text": t}]}}


def cmd(author, command, stdout="", t=None):
    out = stdout + ("\n[t=%ds]\n" % t if t is not None else "")
    return [call(author, "run_command", {"command": command}),
            resp(author, "run_command", {"status": "ok", "stdout": out, "stderr": "", "exit_code": 0})]


def lc(agent, i, served="upstream", live=True, pt=1000, ct=50, finish="tool_calls", kind="agent", t_in=None):
    return {"i": i, "t_in": float(i) if t_in is None else t_in, "t_out": float(i) + 0.5, "agent": agent,
            "kind": kind, "live": live, "stage_run": 0, "served": served, "prompt_tokens": pt,
            "completion_tokens": ct, "finish_reason": finish, "latency_s": 1.0, "cost_usd": 0.0001}


def inst(suite, live_events, before=None, after=None, **golden):
    """A case whose live stage is `live_events`, with scripted stages around it."""
    a = AGENT[suite]
    ev = [{"author": "user", "content": {"role": "user", "parts": [{"text": "task prompt"}]}}]
    ev += before if before is not None else (cmd("setup", "install", "swe-tools ready\n[t=1s]") + [text("setup", "READY")]
                                             + ([text(PREV[suite], "prev stage said")] if suite != "L" else []))
    ev += live_events
    ev += after if after is not None else [call(NEXT[suite], "submit_patch"), resp(NEXT[suite], "submit_patch",
                                                                                   {"status": "ok"}),
                                           text(NEXT[suite], "Submitted.")]
    g = {"schema": "golden-case-v1", "suite": suite, "task": "rich_1", "variant": "-", "split": "dev", "repo": "rich",
         "stratum": "rich/none", "runnable": True, "gradable": True, "status": "ok", "crash_class": None,
         "live_agents": [a], "gold_files": ["rich/text.py"], "gold_new_files": [],
         "gold_functions": [{"file": "rich/text.py", "qualname": "Text.split", "name": "split"}],
         "llm_calls": [lc(PREV[suite], 0, served="script", live=False), lc(a, 1), lc(a, 2),
                       lc(NEXT[suite], 3, served="script", live=False)],
         "run": {"label": "CONTROL", "max_output_tokens": dict(CAPS)}, "final_patch": "", "exec_checks": None}
    g.update(golden)
    last_text = next((e["content"]["parts"][0]["text"] for e in reversed(live_events)
                      if e["author"] == a and "text" in e["content"]["parts"][0]), "")
    return {"eval_case_id": "%s__rich_1__s0" % suite, "agent_data": {"agents": {}, "turns": [
        {"turn_index": 0, "events": ev}]}, "response": {"role": "model", "parts": [{"text": last_text}]},
        "reference": {"response": {"role": "model", "parts": [{"text": "ref"}]}}, "golden": g}


def S(name, instance):
    """(score, applicable, detail) through the generated-file entry point."""
    r = GM._score(name, instance)
    ok, detail = GM.explain(r)
    return r["score"], ok, detail


PLAN = ("FILES: rich/text.py:10-20 (Text.split)\nCAUSE: split drops the separator.\nFIX: keep it.\n"
        "REPRO: fails on original\nTESTS: tests/test_text.py")
PATCH = ("diff --git a/rich/text.py b/rich/text.py\nindex 1..2 100644\n--- a/rich/text.py\n+++ b/rich/text.py\n"
         "@@ -1 +1 @@\n-a\n+b\n")


# ---------------------------------------------------------------------------------------------------------------------
# Registry and library contract
# ---------------------------------------------------------------------------------------------------------------------
SPEC_NAMES = {
    "X": "x_invented_tool_calls x_bare_helper_calls x_malformed_calls x_forbidden_edit_tools x_edit_helper_failures "
         "x_text_tool_calls x_compaction_exceedances x_compactions x_runaway_outputs x_cant_open_file x_crash "
         "x_live_restarts x_capped x_clean",
    "L": "l_all_gold_files_named l_gold_files_named l_gold_functions_named l_plan_format l_plan_words "
         "l_plan_within_words l_repro_fails_on_original l_repro_valid l_ended_by_text l_t_end l_within_time l_calls "
         "l_within_calls l_llm_calls l_prompt_tokens l_l4_s l_files_named_n l_gold_files_in_files_line",
    "F": "f_hidden_pass f_touches_all_gold_files f_gold_files_touched f_nonempty f_applies f_compiles f_no_protected "
         "f_no_scratch f_notes_format f_ended_by_text f_first_edit_t f_first_edit_in_time f_verify_rounds f_t_end "
         "f_calls f_llm_calls f_prompt_tokens f_l4_s",
    "V": "v_variant_goal v_hidden_pass v_not_worse v_hidden_nodes_delta v_submitted_by_verifier "
         "v_finalize_before_submit v_no_protected v_no_scratch v_ended_by_text v_t_end v_calls v_llm_calls "
         "v_prompt_tokens v_l4_s",
}


def test_registry_matches_spec_7_2():
    want = {n for v in SPEC_NAMES.values() for n in v.split()}
    assert set(GM.METRICS) == want and len(want) == 64
    for n, m in GM.METRICS.items():
        assert callable(getattr(GM, "m_" + n)), n
        assert set(m) == {"suites", "kind", "better", "headline", "doc"} and m["doc"], n
        assert m["kind"] in ("binary", "count", "numeric") and m["better"] in ("higher", "lower"), n
        assert m["suites"] == ("LFV" if n.startswith("x_") else n[0].upper()), n
    assert {GM.headline(s) for s in "LFVX"} == {"l_all_gold_files_named", "f_hidden_pass", "v_variant_goal", "x_clean"}
    assert sum(m["headline"] for m in GM.METRICS.values()) == 4
    assert GM.METRICS["x_capped"]["kind"] == "binary" and GM.METRICS["x_clean"]["better"] == "higher"
    for s in "LFV":   # suite metrics first, X last (the spec's config order)
        names = GM.metric_names(s)
        assert names == SPEC_NAMES[s].split() + SPEC_NAMES["X"].split()
    assert GM.metric_names("X") == SPEC_NAMES["X"].split() and GM.metric_names("?") == []
    assert GM.metric_names() == [n for s in "LFVX" for n in SPEC_NAMES[s].split()]
    assert (GM.CAP_S, GM.L_T_MAX, GM.L_CALLS_MAX, GM.PLAN_WORDS_MAX, GM.NOTES_WORDS_MAX, GM.F_FIRST_EDIT_T,
            GM.COMPACTION_LINE, GM.RUNAWAY_FRAC) == (300, 90, 12, 120, 60, 150, 14336, 0.95)


def test_library_is_py38_stdlib_only_and_side_effect_free():
    src = LIB.read_text()
    tree = ast.parse(src, feature_version=(3, 8))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or ".")
    assert imported <= {"re", "json", "math", "shlex"}, imported
    for node in tree.body:   # module level: docstring, imports, constant assignments, defs only
        if isinstance(node, ast.Expr):
            assert node is tree.body[0] and isinstance(node.value, ast.Constant), ast.dump(node)[:80]
        else:
            assert isinstance(node, (ast.Import, ast.Assign, ast.FunctionDef)), ast.dump(node)[:80]
        if isinstance(node, ast.Assign):
            calls = [c.func for c in ast.walk(node.value) if isinstance(c, ast.Call)]
            names = {getattr(f, "attr", getattr(f, "id", None)) for f in calls}
            assert names <= {"compile", "frozenset", "join"}, (ast.dump(node)[:80], names)
    for bad in ("removeprefix", "removesuffix", "functools", "dataclass", "open(", "print("):
        assert bad not in src, bad
    assert not [type(n).__name__ for n in ast.walk(tree) if type(n).__name__ in ("Match", "NamedExpr", "TypeAlias")]


def test_copied_constants_and_helpers_equal_replay_l4():
    assert GM.TOOLS == R.TOOLS and GM.HELPER_NAMES == R.HELPER_NAMES
    for k in ("TOOLCALL_TEXT", "HELPER_SHELL", "FOOT_T", "SCRATCH_ROOT", "SCRATCH_ANY", "VENDORED"):
        assert (getattr(GM, k).pattern, getattr(GM, k).flags) == (getattr(R, k).pattern, getattr(R, k).flags), k
    assert GM.COMPACTION_LINE == R.COMPACTION_LINE
    paths = ["rich/text.py", "tests/test_x.py", "conftest.py", "a/testing/b.py", "x_test.py", "pyproject.toml",
             "pkg/foo.pth", "Tests/util.py", "docs/tests/readme.md", "repro.py", "scratch/a.py", "out.log",
             "lib/site-packages/x.py", "a.dist-info/RECORD", ".coverage"]
    for p in paths:
        assert GM.is_protected(p) == R.is_protected(p), p
        assert GM.scratch_files([(p, True)]) == R.scratch_files([(p, True)]), p
    diff = PATCH + ('diff --git "a/sp ace.py" "b/sp ace.py"\nnew file mode 100644\n--- /dev/null\n+++ b/sp ace.py\n'
                    "@@ -0,0 +1 @@\n+x\n")
    assert GM.patch_files(diff) == R.patch_files(diff) == [("rich/text.py", False), ("sp ace.py", True)]
    for msg in ("<|tool_call>call:run_command{x}", "<|tool_call> call:grep.py {", "<|tool_call>", "no call", None):
        assert GM._call_name(msg) == R._call_name(msg)


BIZARRE = [None, {}, [], "text", {"golden": None}, {"golden": "x"}, {"agent_data": "x", "golden": {"suite": "F"}},
           {"golden": {"suite": "L", "status": "ok"}, "agent_data": {"turns": [None, {"events": [None, {}, {
               "content": None}, {"content": {"parts": [None, {"text": None}, {"function_call": None}]}}]}]}},
           {"golden": {"suite": "V", "status": "ok", "gradable": True, "exec_checks": {"patch_files": [None, [], [3]],
                                                                                      "hidden_pass": "yes"},
                       "llm_calls": [None, {"live": True, "served": "upstream", "prompt_tokens": "many"}],
                       "gold_files": [None, 3], "gold_functions": [None, {"name": 3}], "variant": "gold",
                       "run": {"max_output_tokens": None}, "final_patch": 7}}]


@pytest.mark.parametrize("k", range(len(BIZARRE)))
def test_scores_are_always_floats_with_json_explanations(k):
    """agents-cli counts None as an error; every metric returns a float and a parseable explanation on any input."""
    for n in GM.METRICS:
        r = GM._score(n, BIZARRE[k])
        assert isinstance(r["score"], float), (n, r)
        e = json.loads(r["explanation"])
        assert set(e) == {"applicable", "detail"} and isinstance(e["applicable"], bool), (n, e)
        assert not (isinstance(e["detail"], dict) and "error" in e["detail"]), (n, e)   # no metric crashed


def test_unknown_metric_and_crash_become_inapplicable_errors(monkeypatch):
    assert S("nope", {})[1:] == (False, {"error": "unknown metric nope"})
    monkeypatch.setattr(GM, "m_x_crash", lambda instance, _c=None: 1 / 0)
    sc, ok, detail = S("x_crash", inst("F", [text("fixer", "CHANGED: x\nVERIFY: GREEN")]))
    assert (sc, ok) == (0.0, False) and detail["error"].startswith("ZeroDivisionError")
    assert GM.score_all(inst("F", []))["x_crash"] == GM._score("x_crash", inst("F", []))


# ---------------------------------------------------------------------------------------------------------------------
# Gates: golden block, suite, status, gradable
# ---------------------------------------------------------------------------------------------------------------------
def test_gates():
    i = inst("F", [text("fixer", "CHANGED: a\nVERIFY: GREEN")])
    assert S("l_plan_format", i)[1:] == (False, "suite F")
    assert S("f_notes_format", i)[:2] == (1.0, True)
    for st in ("infra_error", "skipped"):
        j = copy.deepcopy(i)
        j["golden"]["status"] = st
        assert all(not GM.explain(r)[0] for r in GM.score_all(j).values()), st
    j = copy.deepcopy(i)
    j["golden"]["gradable"] = False
    assert S("f_notes_format", j)[1:] == (False, "not gradable")
    assert S("x_clean", j)[:2] == (1.0, True)          # X applies to every trace
    k = inst("L", [text("locator", PLAN)], gradable=False)
    assert S("l_plan_format", k)[:2] == (1.0, True)    # L does not need gradability
    no_golden = {k2: v for k2, v in i.items() if k2 != "golden"}
    assert S("x_clean", no_golden)[1:] == (False, "no golden block")
    j = copy.deepcopy(i)
    del j["golden"]["suite"]                            # suite from the case id
    assert S("f_notes_format", j)[:2] == (1.0, True)


def test_model_error_counts_as_failure_and_crash():
    i = inst("F", [text("fixer", "x")], status="model_error", crash_class="unknown_tool",
             exec_checks={"hidden_pass": True, "patch_files": [["rich/text.py", False]]})
    assert S("f_hidden_pass", i)[:2] == (0.0, True)
    assert S("x_crash", i)[:2] == (1.0, True) and S("x_clean", i)[0] == 0.0
    j = copy.deepcopy(i)
    j["golden"]["crash_class"] = None
    assert S("x_crash", j)[:2] == (1.0, True)          # model_error without a class still crashed
    v = inst("V", [text("verifier", "done")], variant="empty", status="model_error",
             exec_checks={"patch_files": [["rich/text.py", False]]})
    assert S("v_variant_goal", v)[:2] == (0.0, True)


# ---------------------------------------------------------------------------------------------------------------------
# Edge: empty agent_data, no live events
# ---------------------------------------------------------------------------------------------------------------------
def test_empty_agent_data_and_no_live_events():
    empty = inst("L", [])
    empty["agent_data"] = {}
    no_live = inst("L", [])          # setup and the later stages ran, the locator never did
    for i in (empty, no_live):
        for n in GM.metric_names("X"):
            if n != "x_clean":
                assert S(n, i)[:2] == (0.0, True), n
        assert S("x_clean", i)[:2] == (1.0, True)
        assert S("l_ended_by_text", i)[:2] == (0.0, True)
        assert S("l_calls", i)[:2] == (0.0, True) and S("l_within_calls", i)[:2] == (1.0, True)
        assert S("l_t_end", i)[1] is False and S("l_within_time", i)[1] is False
        assert S("l_repro_fails_on_original", i)[:2] == (0.0, True)
        assert S("l_plan_format", i)[:2] == (0.0, True) and S("l_plan_words", i)[1] is False
    # agent_data missing entirely: the plan falls back to the case response
    i = inst("L", [text("locator", PLAN)])
    i["agent_data"] = None
    assert S("l_plan_format", i)[:2] == (1.0, True) and S("l_ended_by_text", i)[:2] == (0.0, True)


# ---------------------------------------------------------------------------------------------------------------------
# X metrics
# ---------------------------------------------------------------------------------------------------------------------
def test_x_invented_bare_helper_and_text_calls():
    a = "fixer"
    live = [call(a, "locate"), resp(a, "locate", {"error": "Tool 'locate' not found"}),
            call(a, "call:grep.py"), resp(a, "call:grep.py", {"error": "x"}),
            call(a, "frobnicate"), resp(a, "frobnicate", {"error": "x"}),
            call(a, "run_command", {"command": "view.py rich/text.py 1 20\necho"}),
            resp(a, "run_command", {"stdout": "sh: view.py: command not found"}),
            call(a, "run_command", {"command": "python3 /tmp/swe/view.py rich/text.py 1 20"}),
            resp(a, "run_command", {"stdout": "ok\n[t=50s]"}),
            call(a, "run_command", {"command": "  verify.pyc"}), resp(a, "run_command", {"stdout": ""}),
            text(a, "<|tool_call>call:run_command{command:<|\"|>ls<|\"|>}<tool_call|>")]
    i = inst("F", live)
    sc, ok, d = S("x_invented_tool_calls", i)
    assert (sc, d["parsed"], d["unparsed"]) == (3.0, 3, 0)
    sc, _, d = S("x_bare_helper_calls", i)
    assert (sc, d["parsed"], d["unparsed"], d["helper_shell"]) == (3.0, 2, 0, 1)
    assert S("x_text_tool_calls", i)[0] == 1.0            # a real tool written as text: text call, not invented
    j = inst("F", [text(a, "<|tool_call>call:grep.py{regex:<|\"|>x<|\"|>}")])
    assert S("x_invented_tool_calls", j)[2]["unparsed"] == 1 and S("x_bare_helper_calls", j)[0] == 1.0
    k = inst("F", [text(a, "thinking... <|tool_call> garbled")])   # no call: -> name "" -> invented, not a helper
    assert S("x_invented_tool_calls", k)[0] == 1.0 and S("x_bare_helper_calls", k)[0] == 0.0
    assert S("x_text_tool_calls", k)[0] == 1.0 and S("x_clean", k)[0] == 0.0
    # a text part next to a function call is not a text reply (replay_l4 kind "text" needs no tool calls)
    mixed = {"author": a, "content": {"role": "model", "parts": [{"text": "<|tool_call>call:x{"},
                                                                  {"function_call": {"name": "run_command",
                                                                                     "args": {"command": "ls"}}}]}}
    assert S("x_text_tool_calls", inst("F", [mixed]))[0] == 0.0


def test_x_malformed_forbidden_edit_failures_cant_open():
    a = "verifier"
    live = [call(a, "edit_file", {"filepath": "a.py"}),
            resp(a, "edit_file", {"error": "Invoking `edit_file()` failed as the following mandatory input parameters "
                                           "are not present:\nold_string"}),
            call(a, "write_file", {"filepath": "b.py"}), resp(a, "write_file", {"status": "ok"})]
    live += cmd(a, "python3 /tmp/swe/edit.py a.py --lines 3-4 <<'EOF'\nx\nEOF", "REFUSED: tests/test_a.py (protected)")
    live += cmd(a, "python3 /tmp/swe/edit.py a.py <<'EOF'\n...\nEOF", "NO MATCH (block 2 of 3; no block was applied): x")
    live += cmd(a, "python3 /tmp/swe/edit.py a.py --lines 1-1 <<'EOF'\nx\nEOF", "REVERTED: syntax error at line 1")
    live += cmd(a, "python3 /tmp/swe/edit.py a.py --lines 1-1 <<'EOF'\nx\nEOF",
                "OK (lines): a.py lines 1-1 replaced. Now lines\n  12| REFUSED = 1\n  13| # NO MATCH here", t=80)
    live += cmd(a, "grep REFUSED a.py", "REFUSED")              # not an edit.py call
    live += cmd(a, "python3 /tmp/swe/nothere.py", "python3: can't open file '/tmp/swe/nothere.py': [Errno 2]")
    live += cmd(a, "python3 nothere.py", "python3: can't open file 'nothere.py'")   # no /tmp/swe/ -> not counted
    i = inst("V", live, variant="gold")
    assert S("x_malformed_calls", i)[0] == 1.0
    assert S("x_forbidden_edit_tools", i)[0] == 2.0
    sc, _, d = S("x_edit_helper_failures", i)
    assert sc == 3.0 and sorted(d["examples"]) == ["NO MATCH", "REFUSED", "REVERTED"]
    assert S("x_cant_open_file", i)[0] == 1.0
    assert S("x_clean", i)[0] == 0.0 and set(S("x_clean", i)[2]["dirty"]) == {
        "x_malformed_calls", "x_forbidden_edit_tools", "x_edit_helper_failures", "x_cant_open_file"}


def test_x_counts_only_the_live_first_stage_run():
    a = "fixer"
    bad = [call(a, "locate"), resp(a, "locate", {"error": "x"})]
    before = cmd("setup", "install") + [text("setup", "READY"), call("locator", "frob"), resp("locator", "frob", {}),
                                        text("locator", "<|tool_call>call:grep.py{")]
    restart = [text("verifier", "ok")] + [text(a, "done")] + bad   # a harness restart: a second fixer stage-run
    i = inst("F", [text(a, "CHANGED: x\nVERIFY: GREEN")], before=before, after=restart)
    for n in GM.metric_names("X"):
        if n != "x_clean":
            assert S(n, i)[0] == 0.0, n
    assert S("x_clean", i)[0] == 1.0
    # events authored "tool" do not break the stage-run
    t = inst("F", [call(a, "locate"), {"author": "tool", "content": {"parts": [{"function_response": {
        "name": "locate", "response": {"error": "x"}}}]}}, call(a, "frob"), resp(a, "frob", {})])
    assert S("x_invented_tool_calls", t)[0] == 2.0


def test_x_router_metrics_compaction_runaway_restarts_capped():
    a = "fixer"
    calls = [lc("setup", 0, served="script", live=False), lc("locator", 1, served="script", live=False, pt=20000),
             lc("_summarizer", 2, served="upstream", live=False, kind="summarizer"),   # before the live 1st request
             lc(a, 3, pt=14336), lc(a, 4, pt=14335, ct=1946),                           # 1946 >= 0.95 * 2048
             lc("_summarizer", 5, served="upstream", live=False, kind="summarizer"),
             lc(a, 6, finish="length", ct=10), lc(a, 7, ct=1945),
             lc("_summarizer", 8, served="upstream", live=False, kind="summarizer"),   # before the verifier: not live
             lc("verifier", 9, served="script", live=False, pt=30000),
             lc(a, 10, served="done_after_end"), lc("verifier", 11, served="done_after_end", live=False),
             lc(a, 12, served="cap", pt=50000)]
    i = inst("F", [text(a, "CHANGED: x\nVERIFY: GREEN")], llm_calls=calls)
    assert S("x_compaction_exceedances", i)[0] == 1.0      # 14336 counts, 14335 not, scripted/cap not live
    assert S("x_compactions", i)[0] == 2.0
    assert S("x_runaway_outputs", i)[0] == 2.0             # finish length + 1946 tokens; 1945 < 1945.6
    assert S("x_live_restarts", i)[0] == 1.0               # the fixer's done_after_end only
    assert S("x_capped", i)[:2] == (1.0, True)
    dirty = set(S("x_clean", i)[2]["dirty"])
    assert dirty == {"x_compaction_exceedances", "x_compactions", "x_runaway_outputs", "x_live_restarts"}
    # capped alone leaves x_clean at 1 (running out of time is a pacing result)
    j = inst("F", [text(a, "CHANGED: x\nVERIFY: GREEN")], llm_calls=[lc(a, 1), lc(a, 2, served="cap")])
    assert S("x_capped", j)[0] == 1.0 and S("x_clean", j)[0] == 1.0
    # a summariser as the very last record belongs to the request before it; order follows "i", not list order
    k = inst("F", [], llm_calls=[lc("_summarizer", 9, live=False, kind="summarizer"), lc(a, 1), lc(a, 2)])
    assert S("x_compactions", k)[0] == 1.0
    # no max_output_tokens: only finish_reason length counts
    m = inst("F", [], llm_calls=[lc(a, 1, ct=5000), lc(a, 2, finish="length")], run={})
    assert S("x_runaway_outputs", m)[0] == 1.0


# ---------------------------------------------------------------------------------------------------------------------
# L metrics
# ---------------------------------------------------------------------------------------------------------------------
def test_l_gold_files_and_functions():
    a = "locator"
    g = dict(gold_files=["rich/text.py", "rich/console.py"],
             gold_functions=[{"name": "split"}, {"name": "print_json"}, {"name": ""}, {"name": "module level"}])
    i = inst("L", [text(a, "FILES: ./rich/text.py:3-9 (Text.split), /workspace/rich/console.py:1-2 (x)")], **g)
    assert S("l_all_gold_files_named", i)[0] == 1.0 and S("l_gold_files_named", i)[0] == 1.0
    assert S("l_gold_functions_named", i)[0] == 0.5       # split yes, print_json no; vacuous entries dropped
    j = inst("L", [text(a, "FILES: rich/text.pyi, xrich/text.py, rich/console.py/x, `rich/console.py`.")], **g)
    assert S("l_all_gold_files_named", j)[0] == 0.0 and S("l_gold_files_named", j)[0] == 0.5
    assert S("l_all_gold_files_named", j)[2]["missing"] == ["rich/text.py"]
    k = inst("L", [text(a, "FILES: rich/text.py resplit splitter")], gold_functions=[{"name": "split"}])
    assert S("l_gold_functions_named", k)[0] == 0.0       # whole words only
    for vac in ([], [{"name": "module level"}, {"name": ""}, {"qualname": "x"}], None):
        v = inst("L", [text(a, PLAN)], gold_functions=vac)
        assert S("l_gold_functions_named", v)[1:] == (False, "no gold functions (module level or none)")
    assert S("l_all_gold_files_named", inst("L", [text(a, PLAN)], gold_files=[]))[1] is False


def test_l_plan_format_and_words():
    a = "locator"
    assert S("l_plan_format", inst("L", [text(a, "\n" + PLAN)]))[0] == 1.0
    assert S("l_plan_format", inst("L", [text(a, "Plan:\n" + PLAN)]))[:2] == (0.0, True)       # no leading FILES:
    no_tests = PLAN.replace("\nTESTS: tests/test_text.py", "")
    assert S("l_plan_format", inst("L", [text(a, no_tests)]))[2]["missing"] == ["TESTS"]
    assert S("l_plan_format", inst("L", [text(a, "FILES: x\nCAUSES: y\nFIXED: z\nREPRO: n\nTESTS: t")]))[0] == 0.0
    assert S("l_plan_words", inst("L", [text(a, PLAN)]))[0] == float(len(PLAN.split()))
    long_plan = PLAN + " w" * (121 - len(PLAN.split()))
    assert S("l_plan_within_words", inst("L", [text(a, long_plan)]))[:2] == (0.0, True)
    assert S("l_plan_within_words", inst("L", [text(a, long_plan.rsplit(" ", 1)[0])]))[0] == 1.0
    empty = inst("L", [text(a, "  ")])
    assert S("l_plan_words", empty)[1] is False and S("l_plan_within_words", empty)[1] is False
    assert S("l_plan_format", empty)[:2] == (0.0, True)


def test_l_repro_and_ended_by_text():
    a = "locator"
    rp = "python3 /tmp/swe/verify.py --repro-only <<'EOF'\n# CLAIM 1: x\nassert f()\nEOF"
    fails = "REPRO: fails on original (1 of 1 claims): claim 1 AssertionError"
    passes = "REPRO: claim 1 passes on original - it misses the bug; rewrite it once with another input shape."
    i = inst("L", cmd(a, rp, passes, t=10) + cmd(a, rp, fails, t=20) + [text(a, PLAN)])
    assert S("l_repro_fails_on_original", i)[:2] == (1.0, True)
    j = inst("L", cmd(a, rp, fails, t=10) + cmd(a, rp, passes, t=20) + [text(a, PLAN)])
    assert S("l_repro_fails_on_original", j)[0] == 0.0     # the LAST repro run decides
    h = inst("L", cmd(a, rp, "REPRO: claim 1 hangs on original (expected for hang bugs).") + [text(a, PLAN)])
    assert S("l_repro_fails_on_original", h)[0] == 1.0
    imp = inst("L", cmd(a, rp, "IMPORT: fails on original too\nREPRO: the claims did not finish") + [text(a, PLAN)])
    assert S("l_repro_fails_on_original", imp)[0] == 0.0   # only the REPRO: line counts (verify.py:308)
    other = inst("L", cmd(a, "python3 /tmp/swe/verify.py", fails) + [text(a, PLAN)])   # not --repro-only
    assert S("l_repro_fails_on_original", other)[2] == {"repro_runs": 0}
    assert S("l_ended_by_text", i)[:2] == (1.0, True)
    tc = inst("L", cmd(a, rp, fails) + [text(a, "<|tool_call>call:run_command{command:ls}")])
    assert S("l_ended_by_text", tc)[:2] == (0.0, True)
    cut = inst("L", cmd(a, rp, fails))                     # capped mid-stage: last event is a tool result
    assert S("l_ended_by_text", cut)[:2] == (0.0, True)


def test_l_repro_valid():
    base = [text("locator", PLAN)]
    ok = {"repro_text": "x", "repro_fails_orig": True, "repro_passes_gold": True}
    assert S("l_repro_valid", inst("L", base, exec_checks=ok))[:2] == (1.0, True)
    assert S("l_repro_valid", inst("L", base, exec_checks=dict(ok, repro_passes_gold=False)))[:2] == (0.0, True)
    assert S("l_repro_valid", inst("L", base, exec_checks={"repro_text": None, "repro_fails_orig": None,
                                                           "repro_passes_gold": None}))[:2] == (0.0, True)
    assert S("l_repro_valid", inst("L", base, exec_checks={"repro_text": "x", "repro_fails_orig": None,
                                                           "repro_passes_gold": True}))[1] is False
    assert S("l_repro_valid", inst("L", base, exec_checks=None))[1:] == (False, "no exec_checks")


def test_l_time_calls_and_live_calls():
    a = "locator"
    live = []
    for k in range(13):
        live += cmd(a, "python3 /tmp/swe/grep.py x%d" % k, "GREP: 0 hits", t=5 + 7 * k)
    i = inst("L", live + [text(a, PLAN)])
    assert S("l_t_end", i)[0] == 89.0 and S("l_within_time", i)[0] == 1.0
    assert S("l_calls", i)[0] == 13.0 and S("l_within_calls", i)[:2] == (0.0, True)
    j = inst("L", cmd(a, "python3 /tmp/swe/locate.py x", "1. a.py\n[t=12s]\nmore [t=91s]") + [text(a, PLAN)])
    assert S("l_t_end", j)[0] == 91.0 and S("l_within_time", j)[0] == 0.0
    calls = [lc("setup", 0, served="script", live=False), lc(a, 1, pt=3000), lc(a, 2, served="oracle", pt=4000),
             lc(a, 3, served="null", pt=10), lc(a, 4, served="cap", pt=99999), lc(a, 5, served="exhausted", pt=7),
             lc("fixer", 6, served="script", live=False), lc(a, 7, served="done_after_end", pt=5)]
    k = inst("L", [text(a, PLAN)], llm_calls=calls)
    assert S("l_llm_calls", k)[0] == 3.0 and S("l_prompt_tokens", k)[0] == 7010.0
    no = inst("L", [text(a, PLAN)])
    del no["golden"]["llm_calls"]
    assert S("l_llm_calls", no)[1] is False and S("l_prompt_tokens", no)[1] is False
    assert S("l_llm_calls", inst("L", [text(a, PLAN)], llm_calls=[]))[:2] == (0.0, True)


# ---------------------------------------------------------------------------------------------------------------------
# F metrics
# ---------------------------------------------------------------------------------------------------------------------
def F_EC(**kw):
    ec = {"patch_files": [["rich/text.py", False]], "applies": True, "compiles": True, "compile_errors": [],
          "hidden_pass": True, "hidden_why": "", "hidden_secs": 3.0, "hidden_retried": False}
    ec.update(kw)
    return ec


def test_f_hidden_pass_and_exec_checks():
    a = "fixer"
    notes = [text(a, "CHANGED: rich/text.py split (10-12)\nVERIFY: GREEN all claims pass")]
    assert S("f_hidden_pass", inst("F", notes, exec_checks=F_EC()))[:2] == (1.0, True)
    assert S("f_hidden_pass", inst("F", notes, exec_checks=F_EC(hidden_pass=False)))[:2] == (0.0, True)
    assert S("f_hidden_pass", inst("F", notes, exec_checks=F_EC(hidden_pass=None)))[1] is False
    missing = inst("F", notes, exec_checks=None)
    for n in ("f_hidden_pass", "f_applies", "f_compiles"):
        assert S(n, missing)[1] is False, n
    assert S("f_applies", inst("F", notes, exec_checks=F_EC(applies=False)))[:2] == (0.0, True)
    assert S("f_compiles", inst("F", notes, exec_checks=F_EC(compiles=False)))[:2] == (0.0, True)
    # patch-file metrics fall back to golden.final_patch when exec_checks is absent
    fb = inst("F", notes, exec_checks=None, final_patch=PATCH)
    assert S("f_touches_all_gold_files", fb)[:2] == (1.0, True) and S("f_nonempty", fb)[0] == 1.0
    none = inst("F", notes, exec_checks=None, final_patch=None)
    assert S("f_nonempty", none)[1] is False and S("f_no_protected", none)[1] is False


def test_f_patch_file_metrics():
    a = "fixer"
    n = [text(a, "CHANGED: x\nVERIFY: GREEN")]
    two = dict(gold_files=["rich/text.py", "rich/console.py"])
    i = inst("F", n, exec_checks=F_EC(patch_files=[["rich/text.py", False], ["repro.py", True]]), **two)
    assert S("f_touches_all_gold_files", i)[:2] == (0.0, True) and S("f_gold_files_touched", i)[0] == 0.5
    assert S("f_no_scratch", i)[:2] == (0.0, True) and S("f_no_protected", i)[0] == 1.0
    assert S("f_nonempty", i)[0] == 1.0
    for files in ([["tests/test_text.py", False]], [["repro.py", True]], [["README.md", False]], []):
        assert S("f_nonempty", inst("F", n, exec_checks=F_EC(patch_files=files)))[:2] == (0.0, True), files
    assert S("f_nonempty", inst("F", n, exec_checks=F_EC(patch_files=[["rich/_x.pyi", False]])))[0] == 1.0
    assert S("f_nonempty", inst("F", n, exec_checks=F_EC(patch_files=[["repro.py", False]])))[0] == 1.0  # not new
    p = inst("F", n, exec_checks=F_EC(patch_files=[["rich/text.py", False], ["pyproject.toml", False]]))
    assert S("f_no_protected", p)[:2] == (0.0, True) and S("f_no_protected", p)[2]["protected"] == ["pyproject.toml"]
    assert S("f_touches_all_gold_files", inst("F", n, exec_checks=F_EC(), gold_files=[]))[1] is False


def test_f_notes_edits_and_verify_rounds():
    a = "fixer"
    ed = "python3 /tmp/swe/edit.py rich/text.py --lines 3-4 <<'EOF'\nx\nEOF"
    live = cmd(a, "python3 /tmp/swe/view.py rich/text.py 1 40", "...", t=50)
    live += cmd(a, ed, "NO MATCH: rich/text.py unchanged.", t=70)
    live += cmd(a, ed, "OK (lines): rich/text.py lines 3-4 replaced (2 old, 2 new). Now lines", t=120)
    live += cmd(a, ed, "OK (lines): again", t=130)
    live += cmd(a, "python3 /tmp/swe/verify.py", "VERIFY: GREEN", t=140)
    live += cmd(a, "python3 /tmp/swe/verify.py --repro-only <<'EOF'\nx\nEOF", "REPRO: x", t=145)
    live += cmd(a, "cd /workspace && python3 /tmp/swe/verify.py 2>&1 | head", "VERIFY: GREEN", t=160)
    live += [text(a, "CHANGED: rich/text.py split (3-4)\nVERIFY: GREEN")]
    i = inst("F", live, exec_checks=F_EC())
    assert S("f_first_edit_t", i)[0] == 120.0 and S("f_first_edit_in_time", i)[:2] == (1.0, True)
    assert S("f_verify_rounds", i)[0] == 2.0
    assert S("f_t_end", i)[0] == 160.0 and S("f_calls", i)[0] == 7.0
    assert S("f_notes_format", i)[:2] == (1.0, True) and S("f_ended_by_text", i)[0] == 1.0
    late = inst("F", cmd(a, ed, "OK (lines): x", t=151), exec_checks=F_EC())
    assert S("f_first_edit_in_time", late)[:2] == (0.0, True)
    none = inst("F", cmd(a, ed, "REVERTED: syntax error", t=60), exec_checks=F_EC())
    assert S("f_first_edit_t", none)[1] is False and S("f_first_edit_in_time", none)[1] is False
    for bad in ("CHANGED: x", "VERIFY: GREEN", "CHANGED: x\nVERIFY: GREEN" + " w" * 57):
        assert S("f_notes_format", inst("F", [text(a, bad)], exec_checks=F_EC()))[:2] == (0.0, True), bad
    assert S("f_notes_format", inst("F", [text(a, "CHANGED: x\nVERIFY: GREEN" + " w" * 56)]))[0] == 1.0


# ---------------------------------------------------------------------------------------------------------------------
# V metrics
# ---------------------------------------------------------------------------------------------------------------------
def test_v_variant_goal_and_nodes():
    a = "verifier"
    live = [text(a, "done")]
    assert S("v_variant_goal", inst("V", live, variant="gold", exec_checks=F_EC()))[:2] == (1.0, True)
    assert S("v_variant_goal", inst("V", live, variant="wrong", exec_checks=F_EC(hidden_pass=False)))[:2] == (0.0, True)
    assert S("v_variant_goal", inst("V", live, variant="empty", exec_checks=F_EC(hidden_pass=False)))[:2] == (1.0, True)
    assert S("v_variant_goal", inst("V", live, variant="empty", exec_checks=F_EC(patch_files=[])))[:2] == (0.0, True)
    assert S("v_variant_goal", inst("V", live, variant="-", exec_checks=F_EC()))[1] is False
    ec = F_EC(hidden_nodes_total=5, hidden_nodes_pass=4, pre_hidden_nodes_pass=5)
    i = inst("V", live, variant="gold", exec_checks=ec)
    assert S("v_not_worse", i)[:2] == (0.0, True) and S("v_hidden_nodes_delta", i)[0] == -1.0
    j = inst("V", live, variant="wrong", exec_checks=F_EC(hidden_nodes_pass=3), pre_hidden_nodes_pass=1)
    assert S("v_not_worse", j)[0] == 1.0 and S("v_hidden_nodes_delta", j)[0] == 2.0   # pre from the fixture
    k = inst("V", live, variant="wrong", exec_checks=F_EC(hidden_nodes_pass=3, applies=False), pre_hidden_nodes_pass=1)
    assert S("v_not_worse", k)[0] == 0.0
    na = inst("V", live, variant="wrong", exec_checks=F_EC(hidden_nodes_pass=None), pre_hidden_nodes_pass=1)
    assert S("v_not_worse", na)[1] is False and S("v_hidden_nodes_delta", na)[1] is False
    assert S("v_hidden_pass", inst("V", live, variant="gold", exec_checks=F_EC(hidden_pass=False)))[0] == 0.0


def test_v_submit_and_finalize_order():
    a = "verifier"
    fin = cmd(a, "python3 /tmp/swe/finalize.py", "READY: 1 file", t=200)
    sub = [call(a, "submit_patch"), resp(a, "submit_patch", {"status": "ok", "patch_size": 120})]
    good = inst("V", cmd(a, "python3 /tmp/swe/status.py", "STATUS", t=95) + fin + sub + [text(a, "Submitted.")],
                variant="gold", exec_checks=F_EC())
    assert S("v_submitted_by_verifier", good)[0] == 1.0 and S("v_finalize_before_submit", good)[0] == 1.0
    assert S("v_ended_by_text", good)[0] == 1.0 and S("v_t_end", good)[0] == 200.0 and S("v_calls", good)[0] == 3.0
    late = inst("V", sub + fin + [text(a, "x")], variant="gold", exec_checks=F_EC())
    assert S("v_finalize_before_submit", late)[:2] == (0.0, True)
    never = inst("V", fin + [text(a, "I am done")], variant="gold", exec_checks=F_EC())
    assert S("v_submitted_by_verifier", never)[:2] == (0.0, True)
    assert S("v_finalize_before_submit", never)[1:] == (False, "the verifier never called submit_patch")
    # the scripted submitter's submit_patch is not the verifier's
    assert S("v_submitted_by_verifier", inst("V", [text(a, "x")], variant="gold"))[0] == 0.0
    p = inst("V", [text(a, "x")], variant="gold", exec_checks=F_EC(patch_files=[["out.log", True]]))
    assert S("v_no_scratch", p)[:2] == (0.0, True) and S("v_no_protected", p)[0] == 1.0


# ---------------------------------------------------------------------------------------------------------------------
# Robustness: agents-cli drops None fields; camelCase parts; score_all == _score
# ---------------------------------------------------------------------------------------------------------------------
def _strip_none(x):
    if isinstance(x, dict):
        return {k: _strip_none(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_strip_none(v) for v in x]
    return x


def _camel(x):
    if isinstance(x, dict):
        ren = {"function_call": "functionCall", "function_response": "functionResponse"}
        return {ren.get(k, k): _camel(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_camel(v) for v in x]
    return x


def _samples():
    a = "fixer"
    ed = "python3 /tmp/swe/edit.py rich/text.py --lines 3-4 <<'EOF'\nx\nEOF"
    yield inst("F", cmd(a, ed, "OK (lines): x", t=90) + [call(a, "locate"), resp(a, "locate", {"error": None}),
                                                         text(a, "CHANGED: x\nVERIFY: GREEN")],
               exec_checks=F_EC(hidden_why=None, hidden_nodes_pass=None), crash_class=None)
    yield inst("L", cmd("locator", "python3 /tmp/swe/verify.py --repro-only <<'EOF'\nx\nEOF", "REPRO: fails on original")
               + [text("locator", PLAN)], exec_checks={"repro_text": "x", "repro_fails_orig": True,
                                                       "repro_passes_gold": None})
    yield inst("V", [text("verifier", "<|tool_call>call:finalize.py{}")], variant="empty",
               exec_checks=F_EC(patch_files=[]), llm_calls=[lc("verifier", 1, served="cap")])


def test_none_fields_camel_case_and_score_all_agree():
    for i in _samples():
        want = {n: GM._score(n, i) for n in GM.METRICS}
        assert GM.score_all(i, list(GM.METRICS)) == want
        assert GM.score_all(i) == {n: want[n] for n in GM.metric_names(i["golden"]["suite"])}
        stripped = _strip_none(copy.deepcopy(i))
        assert {n: GM._score(n, stripped) for n in GM.METRICS} == want
        camel = _camel(copy.deepcopy(i))
        assert {n: GM._score(n, camel) for n in GM.METRICS} == want


def test_make_instance_mirrors_agents_cli():
    case = {"eval_case_id": "F__a__s0", "responses": [{"response": {"role": "model", "parts": [{"text": "r"}]}}],
            "reference": {"response": {"parts": [{"text": "g"}]}}, "agent_data": {"turns": []},
            "golden": {"suite": "F"}, "prompt": None}
    i = GM.make_instance(case)
    assert set(i) == {"eval_case_id", "response", "reference", "agent_data", "golden"}
    assert i["response"] == {"role": "model", "parts": [{"text": "r"}]}
    assert GM.make_instance({"eval_case_id": "x"})["response"] is None


# ---------------------------------------------------------------------------------------------------------------------
# Generated files (gotcha 2)
# ---------------------------------------------------------------------------------------------------------------------
def test_generated_files_in_sync():
    assert GC.drift() == [], "run .venv/bin/python scripts/golden/gen_config.py"
    assert GC.main(["--check"]) == 0


def test_generated_files_exec_standalone_like_agents_cli():
    """agents-cli 1.7.0: exec(compile(source, '<custom_metric:NAME>', 'exec'), {}) then namespace['evaluate']."""
    samples = list(_samples())
    for n in GM.METRICS:
        src = (ROOT / "eval" / "golden" / "metrics" / (n + ".py")).read_text()
        assert src.startswith("# generated by scripts/golden/gen_config.py") and "do not edit" in src.splitlines()[0]
        ast.parse(src, feature_version=(3, 8))
        ns = {}
        exec(compile(src, "<custom_metric:%s>" % n, "exec"), ns)
        assert "__file__" not in ns and eval("__name__", ns) == "builtins"
        for i in samples:
            assert ns["evaluate"](copy.deepcopy(i)) == GM._score(n, i), n


def test_generated_files_need_no_sys_path(tmp_path):
    """One isolated interpreter (-I -S: no cwd, no site, no user paths) in an empty directory execs every file."""
    files = sorted(glob.glob(str(ROOT / "eval" / "golden" / "metrics" / "*.py")))
    i = next(_samples())
    code = ("import json,sys\nout={}\nfor fp in json.loads(sys.argv[1]):\n    ns={}\n"
            "    exec(compile(open(fp).read(),'<custom_metric>','exec'),ns)\n"
            "    out[fp]=ns['evaluate'](json.loads(sys.argv[2]))\nprint(json.dumps(out))")
    p = subprocess.run([sys.executable, "-I", "-S", "-c", code, json.dumps(files), json.dumps(i)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-2000:]
    got = json.loads(p.stdout)
    assert {Path(fp).stem for fp in got} == set(GM.METRICS) and len(got) == 64
    for fp, r in got.items():
        assert r == GM._score(Path(fp).stem, i), fp


def _yaml_metrics(text):
    """The metrics_to_run list and {name: custom_function_file} of a generated config (their fixed layout)."""
    run, files, cur, section = [], {}, None, None
    for line in text.splitlines():
        if line.startswith("metrics_to_run:"):
            section = "run"
        elif line.startswith("custom_metrics:"):
            section = "custom"
        elif section == "run" and line.startswith("  - "):
            run.append(line[4:])
        elif section == "custom" and line.startswith("  - name: "):
            cur = line[len("  - name: "):]
        elif section == "custom" and line.startswith("    custom_function_file: "):
            files[cur] = line.split(": ", 1)[1]
        elif section == "custom" and line.strip():
            assert line == "    execution: local", line
    return run, files


def test_configs_list_suite_then_x_metrics():
    cfgs = {s: ROOT / "eval" / "golden" / ("eval_config_%s.yaml" % s) for s in "LFV"}
    cfgs[None] = ROOT / "eval" / "golden" / "eval_config.yaml"
    for s, path in cfgs.items():
        t = path.read_text()
        assert t.startswith("# generated by scripts/golden/gen_config.py; do not edit\n")
        run, files = _yaml_metrics(t)
        assert run == GM.metric_names(s) and list(files) == run, s
        for n, f in files.items():
            assert f == "metrics/%s.py" % n and (path.parent / f).is_file(), n
    try:
        import yaml   # the .venv has PyYAML; the layout parser above is the no-dependency check
    except ImportError:
        return
    d = yaml.safe_load(cfgs["F"].read_text())
    assert d["metrics_to_run"] == GM.metric_names("F")
    assert all(set(m) == {"name", "custom_function_file", "execution"} for m in d["custom_metrics"])


def test_gen_config_check_detects_drift_and_stale_files(tmp_path):
    golden = tmp_path / "golden"
    GC.write(str(golden), str(LIB))
    assert GC.drift(str(golden), str(LIB)) == []
    assert GC.main(["--check", "--golden-dir", str(golden), "--library", str(LIB)]) == 0
    (golden / "metrics" / "x_clean.py").write_text("def evaluate(instance):\n    return 1.0\n")
    (golden / "metrics" / "x_gone.py").write_text("")
    (golden / "eval_config_F.yaml").unlink()
    bad = {(Path(p).name, why) for p, why in GC.drift(str(golden), str(LIB))}
    assert bad == {("x_clean.py", "differs"), ("x_gone.py", "stale (no such metric)"), ("eval_config_F.yaml", "missing")}
    assert GC.main(["--check", "--golden-dir", str(golden), "--library", str(LIB)]) == 1
    done = {(Path(p).name, act) for p, act in GC.write(str(golden), str(LIB))}
    assert done == {("x_clean.py", "updated"), ("x_gone.py", "removed"), ("eval_config_F.yaml", "created")}
    assert GC.drift(str(golden), str(LIB)) == []


# ---------------------------------------------------------------------------------------------------------------------
# Agreement with scripts/replay_l4.py on every r2_v10_1 trace (spec 12c, gotcha 23)
# ---------------------------------------------------------------------------------------------------------------------
def _obs_response(obs):
    content = obs.get("content") if isinstance(obs, dict) else None
    try:
        j = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        j = None
    return j if isinstance(j, dict) else {"result": content if isinstance(content, str) else ""}


def atif_to_instance(trace, skip_multi=True):
    """The spec 6.2 ATIF -> agent_data mapping, reduced to what the X metrics read. Returns (instance, step ids of
    skipped multi-call steps and their system observations, [(event, step id)])."""
    turns, evs, tagged, skipped = [], None, [], set()
    last_call_author, skip_system = None, False

    def add(ev, sid):
        evs.append(ev)
        tagged.append((ev, sid))

    for s in trace.get("steps") or []:
        src, sid, ex = s.get("source"), s.get("step_id"), s.get("extra") or {}
        if src == "user" or evs is None:
            turns.append({"turn_index": len(turns), "events": []})
            evs = turns[-1]["events"]
        if src == "user":
            add({"author": "user", "content": {"role": "user", "parts": [{"text": s.get("message") or ""}]}}, sid)
            continue
        if src == "agent":
            tcs = s.get("tool_calls") or []
            if len(tcs) > 1 and skip_multi:
                skipped.add(sid)
                skip_system = True
                continue
            skip_system = False
            if tcs:
                author = (tcs[0].get("extra") or {}).get("author") or ex.get("author") or "?"
                if s.get("message") and ex.get("event_type") != "thinking":   # the writer's split (none in race 2)
                    add({"author": author, "content": {"role": "model", "parts": [{"text": s["message"]}]}}, sid)
                add({"author": author, "content": {"role": "model", "parts": [
                    {"function_call": {"name": tc.get("function_name"), "args": tc.get("arguments")}} for tc in tcs]}},
                    sid)
                add({"author": author, "content": {"role": "user", "parts": [{"function_response": {
                    "name": tcs[0].get("function_name"), "response": _obs_response(s.get("observation"))}}]}}, sid)
                last_call_author = author
            elif ex.get("event_type") != "thinking":
                add({"author": ex.get("author") or "?", "content": {"role": "model", "parts": [
                    {"text": s.get("message") or ""}]}}, sid)
        elif src == "system":
            if skip_system:
                skipped.add(sid)
                continue
            obs = s.get("observation") or {}
            add({"author": last_call_author or "?", "content": {"role": "user", "parts": [{"function_response": {
                "name": (obs.get("extra") or {}).get("tool_name") or "", "response": _obs_response(obs)}}]}}, sid)
    authors = sorted({e["author"] for e, _ in tagged} - {"user", "?"})
    instance = {"eval_case_id": "X__trace", "agent_data": {"agents": {}, "turns": turns},
                "response": {"role": "model", "parts": [{"text": ""}]},
                "golden": {"suite": "F", "status": "ok", "gradable": True, "live_agents": authors, "llm_calls": [],
                           "crash_class": None}}
    return instance, skipped, tagged


def _first_run_sids(tagged):
    """Step ids inside each author's first stage-run, by the library's definition (user events break runs)."""
    sids, done, cur = set(), set(), None
    for ev, sid in tagged:
        a = ev["author"]
        if a != cur:
            if cur is not None:
                done.add(cur)
            cur = a
        if a not in done and a != "user":
            sids.add(sid)
    return sids


MULTI_CALL_STEPS = [("fastapi_14492", 4), ("fastapi_14492", 7)]   # the two-call steps of r2_v10_1


def _replay_counts(steps):
    c, _ = R.pipeline_diag({"steps": steps})
    return {"parsed_invented": c["parsed_invented"], "unparsed_invented": c["unparsed_invented"],
            "helper_shell": c["helper_shell"], "text_calls": c["stage_text_calls"],
            "malformed": sum(s["kind"] == "malformed" for s in steps),
            "cant_open": sum(s["fn"] == "run_command" and "/tmp/swe/" in s["args"] and "can't open file" in s["obs"]
                             for s in steps)}


@pytest.mark.skipif(not (R2 / "traces").is_dir(), reason="eval/race2/eval/runs/r2_v10_1 traces not present")
def test_x_metrics_agree_with_replay_l4_on_r2_v10_1():
    data = R.load(str(R2), keep_obs=True)
    files = sorted(glob.glob(str(R2 / "traces" / "trace_*.json")))
    assert len(files) == 74
    tot_first, tot_all, multi = {}, {}, []
    for fp in files:
        iid = os.path.basename(fp)[6:-5]
        trace = json.load(open(fp))
        instance, skipped, tagged = atif_to_instance(trace)
        multi += [(iid, sid) for sid in skipped if any(s.get("step_id") == sid and s.get("source") == "agent"
                                                       for s in trace["steps"])]
        steps = [s for s in data[iid]["steps"] if s["sid"] not in skipped]
        first = _first_run_sids(tagged)
        want = _replay_counts([s for s in steps if s["sid"] in first])
        got = {}
        _, _, d = S("x_invented_tool_calls", instance)
        got["parsed_invented"], got["unparsed_invented"] = d["parsed"], d["unparsed"]
        got["helper_shell"] = S("x_bare_helper_calls", instance)[2]["helper_shell"]
        got["text_calls"] = int(S("x_text_tool_calls", instance)[0])
        got["malformed"] = int(S("x_malformed_calls", instance)[0])
        got["cant_open"] = int(S("x_cant_open_file", instance)[0])
        assert int(S("x_invented_tool_calls", instance)[0]) == want["parsed_invented"] + want["unparsed_invented"], iid
        assert got == want, (iid, got, want)
        whole = GM._x_counts(GM._events(instance["agent_data"]))       # every stage-run, not only the first
        want_all = _replay_counts(steps)
        assert {k: whole[k] for k in want_all} == want_all, (iid, whole, want_all)
        for k in want:
            tot_first[k] = tot_first.get(k, 0) + want[k]
            tot_all[k] = tot_all.get(k, 0) + want_all[k]
    # the comparison is not vacuous: every counter fires somewhere in race 2. (No r2_v10_1 author has a second
    # stage-run, so the first-run restriction itself is exercised by test_x_counts_only_the_live_first_stage_run.)
    assert tot_all =={"parsed_invented": 1, "unparsed_invented": 29, "helper_shell": 6, "text_calls": 36,
                       "malformed": 4, "cant_open": 2}, tot_all
    assert all(v > 0 for v in tot_first.values()), tot_first
    # gotcha 23: replay_l4.load reads tcs[0] only, so the two-call steps are compared apart (next test)
    assert sorted(multi) == MULTI_CALL_STEPS, multi


@pytest.mark.skipif(not (R2 / "traces").is_dir(), reason="eval/race2/eval/runs/r2_v10_1 traces not present")
def test_multi_call_steps_count_every_call():
    """Gotcha 23: replay_l4 sees one call per step; the library counts both calls of a two-call step."""
    found = 0
    for fp in sorted(glob.glob(str(R2 / "traces" / "trace_*.json"))):
        trace = json.load(open(fp))
        multi = [s for s in trace["steps"] if s.get("source") == "agent" and len(s.get("tool_calls") or []) > 1]
        if not multi:
            continue
        found += len(multi)
        keep, _, _ = atif_to_instance(trace, skip_multi=False)
        drop, _, _ = atif_to_instance(trace, skip_multi=True)
        count = lambda i: sum(len(e["calls"]) for e in GM._events(i["agent_data"]))  # noqa: E731
        assert count(keep) - count(drop) == sum(len(s["tool_calls"]) for s in multi)
        iid = os.path.basename(fp)[6:-5]
        loaded = {s["sid"]: s for s in R.load(str(R2), keep_obs=True)[iid]["steps"]}
        for s in multi:
            assert loaded[s["step_id"]]["fn"] == s["tool_calls"][0]["function_name"]   # replay_l4 keeps tcs[0]
    assert found >= 1


def test_user_guide_tables_match_the_registry():
    """docs/eval/GOLDEN_EVALS.md lists every metric with the registry's kind and direction."""
    doc = (ROOT / "docs" / "eval" / "GOLDEN_EVALS.md").read_text()
    rows = {}
    for line in doc.splitlines():
        if line.startswith("| `") and line.count("|") >= 5:
            cells = [c.strip() for c in line.replace("\\|", "/").split("|")[1:-1]]
            name = cells[0].split("`")[1]
            if name in GM.METRICS:
                rows[name] = (cells[1], cells[2], "(headline)" in cells[0])
    assert set(rows) == set(GM.METRICS)
    for n, (kind, better, head) in rows.items():
        assert (kind, better, head) == (GM.METRICS[n]["kind"], GM.METRICS[n]["better"], GM.METRICS[n]["headline"]), n


@pytest.mark.parametrize("suite", ["F", "V"])
def test_f_v_live_call_metrics_count_only_their_stage(suite):
    a = AGENT[suite]
    calls = [lc("setup", 0, served="script", live=False, pt=900), lc(PREV[suite], 1, served="script", live=False),
             lc(a, 2, pt=5000), lc("_summarizer", 3, live=False, kind="summarizer", pt=16000), lc(a, 4, pt=6000),
             lc(a, 5, served="cap", pt=7000), lc(NEXT[suite], 6, served="script", live=False, pt=8000),
             lc(a, 7, served="done_after_end", pt=100)]
    i = inst(suite, [text(a, "CHANGED: x\nVERIFY: GREEN")], llm_calls=calls, variant="gold", exec_checks=F_EC())
    p = suite.lower()
    assert S(p + "_llm_calls", i)[:2] == (2.0, True)
    assert S(p + "_prompt_tokens", i)[:2] == (11000.0, True)
    assert S("x_live_restarts", i)[0] == 1.0 and S("x_capped", i)[0] == 1.0 and S("x_compactions", i)[0] == 1.0
    no = copy.deepcopy(i)
    del no["golden"]["llm_calls"]
    assert S(p + "_llm_calls", no)[1] is False and S(p + "_prompt_tokens", no)[1] is False


OLD_PY = "/usr/bin/python3"   # macOS ships 3.9; the oldest interpreter on this machine


def _old_py_version():
    try:
        out = subprocess.run([OLD_PY, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        return tuple(int(x) for x in out.split("."))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@pytest.mark.skipif(not os.path.exists(OLD_PY) or (_old_py_version() or (99,)) >= (3, 10),
                    reason="no Python older than 3.10 at %s" % OLD_PY)
def test_library_runs_on_the_oldest_local_python(tmp_path):
    """The AST check proves 3.8 syntax; this runs the library on an older interpreter to catch newer runtime APIs."""
    samples = list(_samples()) + BIZARRE
    code = ("import json,sys\nns={}\nexec(compile(open(sys.argv[1]).read(),'<lib>','exec'),ns)\n"
            "out=[{n: ns['_score'](n, i) for n in ns['METRICS']} for i in json.loads(sys.argv[2])]\n"
            "print(json.dumps(out))")
    p = subprocess.run([OLD_PY, "-I", "-S", "-c", code, str(LIB), json.dumps(samples)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-2000:]
    got = json.loads(p.stdout)
    for i, g in zip(samples, got):
        assert g == {n: GM._score(n, i) for n in GM.METRICS}


def test_text_split_from_its_calls_is_not_a_text_reply():
    """The trace writer emits a step's message and its tool calls as two events; ADK had one event, and replay_l4
    counts such a step as a tool step. The library re-joins them, so a <|tool_call> in that text is no text call."""
    a = "fixer"
    split = [text(a, "let me look <|tool_call>call:grep.py{"), call(a, "run_command", {"command": "ls"}),
             resp(a, "run_command", {"stdout": "x"}), text(a, "CHANGED: x\nVERIFY: GREEN")]
    i = inst("F", split)
    assert S("x_text_tool_calls", i)[0] == 0.0 and S("x_invented_tool_calls", i)[0] == 0.0
    assert S("f_notes_format", i)[0] == 1.0 and S("f_ended_by_text", i)[0] == 1.0
    # a real text reply followed by ANOTHER author's call stays a text reply
    j = inst("F", [text(a, "<|tool_call>call:grep.py{")], after=[call("verifier", "submit_patch")])
    assert S("x_text_tool_calls", j)[0] == 1.0 and S("f_ended_by_text", j)[0] == 0.0
