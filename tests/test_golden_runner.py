"""Component (b) of docs/eval/GOLDEN_EVALS_SPEC.md v1.1: stage router, child hooks, suite CLI (section 5, 12(b)).

Default tier: the synthetic calc task of tests/test_v10_flow.py (no network, no model, no GPU). Real child runs go
through the REAL swegemma Evaluator (scripts/run_eval.py) with the router answering; they all start concurrently in one
module fixture (``runs``): the 5.10 parity pair, the 5.9 controls of L, F and V, the live cap with a slow pre-stage,
and the key/forwarding run (folded into the cap run). The budget stop and --resume run in test_golden_trace.py. NIGHTLY (G4_NIGHTLY=1): controls on 3 real
rich tasks per suite, and the 5.10 parity on 2 real rich tasks. No OpenRouter call anywhere: "openrouter" runs point
--upstream-base at a local fake.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
for _p in (str(TESTS), str(ROOT / "scripts" / "golden"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("swegemma.evaluate")

from v10_support import sandbox as S  # noqa: E402
from v10_support.mock_llm import MockLLM, Request, cmd, submit, text  # noqa: E402
from v10_support.repo import no_orphans  # noqa: E402,F401  (autouse)
from golden_data import golden_calc as GC  # noqa: E402
from golden_data.fake_upstream import FakeUpstream  # noqa: E402

import checks as CK  # noqa: E402
import router as RT  # noqa: E402
import run_suite as RS  # noqa: E402
import stage_child as SC  # noqa: E402
import stage_scripts as SS  # noqa: E402
import trace_writer as TW  # noqa: E402

pytestmark = pytest.mark.skipif(S.bundle_missing() is not None, reason=S.bundle_missing() or "")
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
SECRET = "sk-or-v1-TESTSECRET-" + "9f" * 16
KPAR_OK = CK.T().kpar_ok("rich")
needs_kpar = pytest.mark.skipif(not KPAR_OK, reason=f"kpar venv missing: {CK.T().build_cmd('rich')}")


# ---------------------------------------------------------------------------------------------------- test doubles
def body_for(agent: str | None, messages: list | None = None, tools: list | None = None, **extra) -> dict:
    """A chat-completions body as the harness sends it (system first, ADK identity line)."""
    sys_txt = f'You are an agent. Your internal name is "{agent}".\n\nprompt' if agent else "no identity"
    msgs = [{"role": "system", "content": sys_txt}] + list(messages or [{"role": "user", "content": "go"}])
    b = {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": msgs,
         "tools": tools or [{"type": "function", "function": {"name": "run_command", "parameters": {}}}]}
    b.update(extra)
    return b


def summarizer_body() -> dict:
    return {"model": "m", "messages": [{"role": "user", "content": RT.SUMMARIZER_MARK + " ... events ..."}]}


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def route_router(endpoint=None, *, live="fixer", scripts=None, live_script=None, cap_s=253.0, clock=None,
                 budget=None, log_dir=None, log_bodies=False):
    r = RT.StageRouter(endpoint or RT.make_endpoint("oracle"), budget, clock=clock or FakeClock(),
                       log_bodies=log_bodies)
    r.add_route("k", "case_k", live, scripts or {}, live_script or [], cap_s,
                log_path=(log_dir / "router.jsonl") if log_dir else None,
                bodies_path=(log_dir / "bodies.jsonl") if log_dir else None)
    return r


def served(r, key="k"):
    return [(x["agent"], x["served"]) for x in r.route(key).records]


# ------------------------------------------------------------------------------------------------ stage scripts
def labels(steps):
    return [SS.describe(s) for s in steps]


def test_clock_cmd_is_scaled_and_exact():
    assert SS.clock_cmd(47) == "python3 -c \"import time;open('/tmp/swe/t0','w').write(repr(time.time()-47.0))\""
    assert "time.time()-23.5" in SS.clock_cmd(47, 2.0)
    with pytest.raises(ValueError):
        SS.clock_cmd(47, 0)


def test_neighbour_scripts_per_suite_and_variant():
    L = SS.neighbour_scripts(GC.case("L"))
    assert "locator" not in L
    assert labels(L["setup"]) == ["run_skill_script:install.py", "run_command:" + SS.clock_cmd(2)[:60], "text"]
    assert L["fixer"] == [text("CHANGED: nothing")] and labels(L["verifier"]) == ["submit_patch:", "text"]
    assert labels(L["submitter"]) == ["submit_patch:", "text"]
    F = SS.neighbour_scripts(GC.case("F", t0=33))        # the CLOCK value is the case's t0, never a literal
    assert "fixer" not in F and labels(F["setup"]) == ["run_skill_script:install.py", "text"]
    loc = labels(F["locator"])
    assert loc[0].startswith('run_command:python3 /tmp/swe/locate.py "calc.ops.add')
    assert loc[1].startswith("run_command:python3 /tmp/swe/verify.py --repro-only")
    assert F["locator"][2]["args"]["command"] == SS.clock_cmd(33) and loc[3] == "PLAN"
    F_norepro = SS.neighbour_scripts(GC.case("F", repro=None))
    assert labels(F_norepro["locator"])[1].startswith("run_command:python3 -c") and len(F_norepro["locator"]) == 3
    for variant, n_replay in (("gold", 1), ("wrong", 1), ("empty", 0)):
        V = SS.neighbour_scripts(GC.case("V", variant))
        assert "verifier" not in V and labels(V["locator"])[-1] == "PLAN"
        fx = V["fixer"]
        assert fx[:n_replay] == GC.golden("V", variant)["replay_steps"]
        assert fx[n_replay] == SS.VERIFY and fx[n_replay + 1]["args"]["command"] == SS.clock_cmd(91)
        assert SS.describe(fx[-1]) == "NOTES" and len(fx) == n_replay + 3
        assert labels(V["submitter"]) == ["submit_patch:", "text"]
    assert SS.neighbour_scripts(GC.case("F"), scale=2.0)["locator"][2]["args"]["command"] == SS.clock_cmd(47, 2.0)


def test_title_words_are_shell_safe():
    assert SS.safe_title('fix `rm -rf` $HOME "x" \\y') == "fix rm -rf HOME x y"
    assert SS.safe_title("") == "issue"


def _tool_msg(call_id, stdout):
    inner = json.dumps({"status": "ok", "stdout": stdout, "stderr": "", "exit_code": 0})
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps({"result": inner})}


def _call(call_id, command):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": "run_command",
                                                          "arguments": json.dumps({"command": command})}}]}


def _req(messages):
    return Request("k", "locator", 3, body_for("locator", messages))


def test_plan_reads_the_repro_result_past_the_clock_write():
    """gotcha 15: CLOCK is the last call, so the newest tool result is the clock write."""
    plan = GC.PLAN.replace("REPRO: fails on original", "REPRO: none")
    msgs = [{"role": "user", "content": "For context:"},
            _call("a", "python3 /tmp/swe/locate.py \"x\""), _tool_msg("a", "LOCATE: 3 symbols\n[t=0s]\n"),
            _call("b", "python3 /tmp/swe/verify.py --repro-only <<'EOF'\nassert 0\nEOF"),
            _tool_msg("b", "REPRO: fails on original (1 of 1 claims)\n[t=0s]\n"),
            _call("c", SS.clock_cmd(47)), _tool_msg("c", "")]
    req = _req(msgs)
    assert req.last_tool_result().find("fails on original") == -1        # the v1 defect would read this one
    out = SS.plan_step(plan)(req)["text"]
    assert "REPRO: fails on original" in out and "REPRO: none" not in out
    hang = [m if m.get("tool_call_id") != "b" else _tool_msg("b", "REPRO: hangs on original\n") for m in msgs]
    assert "REPRO: fails on original" in SS.plan_step(plan)(_req(hang))["text"]
    passes = [m if m.get("tool_call_id") != "b" else _tool_msg("b", "REPRO: passes on original\n") for m in msgs]
    assert "REPRO: none" in SS.plan_step(GC.PLAN)(_req(passes))["text"]
    no_repro = [m for m in msgs if m.get("tool_call_id") != "b"
                and "--repro-only" not in json.dumps(m.get("tool_calls") or "")]
    assert "REPRO: none" in SS.plan_step(GC.PLAN)(_req(no_repro))["text"]
    compacted = [{"role": "tool", "tool_call_id": "zz", "content": json.dumps(
        {"result": json.dumps({"stdout": "REPRO: fails on original\n"})})}, _tool_msg("q", "")]
    assert "REPRO: fails on original" in SS.plan_step(plan)(_req(compacted))["text"]


def test_notes_read_the_verify_result_past_the_clock_write():
    msgs = [_call("a", "python3 /tmp/swe/edit.py calc/ops.py --lines 3-3 <<'EOF'\nx\nEOF"),
            _tool_msg("a", "OK (lines): calc/ops.py\n[t=5s]\n"),
            _call("b", "python3 /tmp/swe/verify.py"),
            _tool_msg("b", "VERIFY: GREEN\nDIFF: calc/ops.py +1 -1\n[t=6s]\n"),
            _call("c", SS.clock_cmd(91)), _tool_msg("c", "")]
    out = SS.notes_step("CHANGED: calc/ops.py add (3-3)")(_req(msgs))["text"]
    assert out == "CHANGED: calc/ops.py add (3-3)\nVERIFY: VERIFY: GREEN"
    assert SS.notes_step("CHANGED: nothing")(_req(msgs[:2] + msgs[4:]))["text"].endswith("VERIFY: not run")


def test_tool_text_unwraps_the_adk_result_envelope():
    inner = json.dumps({"status": "ok", "stdout": "VERIFY: GREEN\nX\n", "stderr": ""})
    assert SS.tool_text(json.dumps({"result": inner})).splitlines()[0] == "VERIFY: GREEN"
    assert SS.tool_text("plain text") == "plain text"
    assert SS.tool_text(json.dumps({"stdout": "a", "stderr": "b"})) == "a\nb"


def test_oracle_scripts_follow_5_9():
    assert labels(SS.oracle_script(GC.case("L")))[-1] == "PLAN"
    assert labels(SS.oracle_script(GC.case("L")))[0].startswith("run_command:python3 /tmp/swe/verify.py --repro-only")
    f = SS.oracle_script(GC.case("F"))
    assert "edit.py calc/ops.py --lines 1-6" in f[0]["args"]["command"] and f[1] == SS.VERIFY
    assert SS.describe(f[-1]) == "NOTES"
    end = [SS.VERIFY, SS.FINALIZE, submit(), text("Submitted.")]
    assert SS.oracle_script(GC.case("V", "gold")) == [SS.STATUS] + end
    w = SS.oracle_script(GC.case("V", "wrong"))
    assert w[0]["args"]["command"] == "cd /workspace && git checkout -q _swegemma_baseline -- calc/ops.py"
    built = SS.edit_steps(GC.GOLD)                                # wrong/empty carry their own tree: gold is built
    assert w[1:] == built + end and "--lines 1-6" in built[0]["args"]["command"]
    assert SS.oracle_script(GC.case("V", "empty")) == built + end
    assert SS.gold_replay(GC.case("V", "gold")) == GC.GOLD_STEPS          # the V gold tree's validated steps


def test_revert_and_replay_edge_cases():
    new_and_old = ("--- a/my dir/a.py\n+++ b/my dir/a.py\n@@ -1 +1 @@\n-x\n+y\n"
                   "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+z\n")
    assert SS.revert_cmd(new_and_old) == ("cd /workspace && git checkout -q _swegemma_baseline -- 'my dir/a.py' && "
                                          "rm -f -- new.py")
    assert SS.revert_cmd("") is None
    steps, mode, why = SS.replay_steps(new_and_old)
    assert mode == "edit" and why is None
    assert steps[0]["args"]["command"].startswith("python3 /tmp/swe/edit.py 'my dir/a.py' --lines 1-1 <<'EOF'\ny\n")
    assert steps[1]["args"]["command"].startswith("python3 /tmp/swe/edit.py new.py --create <<'EOF'\nz\n")
    ins = "--- a/a.py\n+++ b/a.py\n@@ -2,0 +3 @@\n+q\n@@ -5 +5,0 @@\n-r\n"
    st = SS.edit_steps(ins)
    assert "--lines 5-5 --delete" in st[0]["args"]["command"] and "--insert-after 2" in st[1]["args"]["command"]
    for bad, reason in (("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+EOF\n", "EOF"),
                        ("--- a/a.rst\n+++ b/a.rst\n@@ -1 +1 @@\n-x\n+=======\n", "SEARCH/REPLACE"),
                        ("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+p = '/tmp/x'\n", "/tmp"),
                        ("--- a/a.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n", "deletes"),
                        ("diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n", "binary")):
        steps, mode, why = SS.replay_steps(bad)
        assert mode == "git_apply" and reason in why, (bad, why)
        assert "base64.b64decode('" in steps[0]["args"]["command"] and "/tmp" not in steps[0]["args"]["command"]


# ------------------------------------------------------------------------------------------------------- router
def test_router_scripted_steps_exhaustion_and_stage_runs(tmp_path):
    seen = []

    def reactive(req):
        seen.append((req.agent, req.index))
        return text("PLAN from " + req.agent)
    r = route_router(live="fixer", scripts={"setup": [SS.INSTALL, text("READY")], "locator": [reactive]},
                     log_dir=tmp_path)
    st, out = r.answer("k", body_for("setup"))
    assert st == 200 and out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "run_skill_script"
    assert out["usage"]["prompt_tokens"] > 0 and out["choices"][0]["finish_reason"] == "tool_calls"
    assert r.answer("k", body_for("setup"))[1]["choices"][0]["message"]["content"] == "READY"
    assert r.answer("k", body_for("locator"))[1]["choices"][0]["message"]["content"] == "PLAN from locator"
    assert seen == [("locator", 0)]
    assert r.answer("k", body_for("locator"))[1]["choices"][0]["message"]["content"] == "done"
    assert served(r) == [("setup", "script"), ("setup", "script"), ("locator", "script"), ("locator", "exhausted")]
    r.answer("k", body_for("setup"))                                        # a restart: setup's second stage-run
    recs = [json.loads(x) for x in (tmp_path / "router.jsonl").read_text().splitlines()]
    assert [x["stage_run"] for x in recs] == [0, 0, 0, 0, 1]
    assert [x["i"] for x in recs] == [0, 1, 2, 3, 4]
    assert recs[0]["tools"] == ["run_command"] and "tools" not in recs[1]
    for x in recs:
        for k in ("t_in", "t_out", "agent", "kind", "live", "served", "http_status", "retries", "prompt_tokens",
                  "completion_tokens", "reasoning_tokens", "usage_estimated", "finish_reason", "latency_s",
                  "cost_usd", "provider", "error"):
            assert k in x, k


def test_router_forwards_live_requests_verbatim_except_model(tmp_path):
    up = FakeUpstream({"fixer": [cmd("python3 /tmp/swe/verify.py")]})
    try:
        ep = RT.make_endpoint("openrouter", upstream_base=up.base, key=SECRET, or_provider="Prov1",
                              upstream_extra={"reasoning": {"enabled": False}}, seed_mode="case")
        r = route_router(ep, live="fixer", log_dir=tmp_path, log_bodies=True)
        body = body_for("fixer", temperature=1.0, max_tokens=2048, extra_field={"x": [1, 2]})
        st, out = r.answer("k", body)
        assert st == 200 and out["provider"] == "FakeProv"
        got = up.seen[0]
        assert got["path"] == "/v1/chat/completions"
        assert got["headers"]["Authorization"] == "Bearer " + SECRET
        fwd = got["body"]
        assert fwd["model"] == RT.OPENROUTER_MODEL
        assert fwd["provider"] == {"order": ["Prov1"], "allow_fallbacks": False}
        assert fwd["reasoning"] == {"enabled": False}
        assert fwd["seed"] == int(__import__("hashlib").sha256(b"case_k").hexdigest()[:8], 16)
        rest = {k: v for k, v in fwd.items() if k not in ("model", "provider", "reasoning", "seed")}
        assert rest == {k: v for k, v in body.items() if k != "model"}          # otherwise verbatim
        rec = r.route("k").records[0]
        assert rec["served"] == "upstream" and rec["reasoning_tokens"] == 7 and rec["provider"] == "FakeProv"
        pt, ct = out["usage"]["prompt_tokens"], out["usage"]["completion_tokens"]
        assert (ep.price_in, ep.price_out) == (RT.PRICE_IN_DEFAULT, RT.PRICE_OUT_DEFAULT) == (0.14, 0.40)
        assert rec["cost_usd"] == pytest.approx((pt * 0.14 + max(ct, ct + 7 if 7 > ct else ct) * 0.40) / 1e6)
        assert rec["cost_source"] == "estimate"                   # the fake sends no billed usage.cost
        vl = RT.make_endpoint("vllm", upstream_base=up.base)
        r2 = route_router(vl, live="fixer")
        r2.answer("k", body_for("fixer"))
        assert up.seen[-1]["headers"]["Authorization"] == "Bearer EMPTY"
        assert up.seen[-1]["body"]["model"] == RT.VLLM_MODEL and "seed" not in up.seen[-1]["body"]
        # the key is in no log line and no body log (gotcha 14)
        for f in tmp_path.iterdir():
            assert SECRET not in f.read_text(), f
        assert SECRET not in repr(ep) and SECRET not in json.dumps(ep.public())
    finally:
        up.close()


def test_router_pins_one_openrouter_provider_and_budgets_the_billed_cost():
    """Regression (review 2026-09-30): PROXY runs forwarded no provider unless --or-provider was given, so arms could be
    served by fp4, fp8 or bf16 deployments of google/gemma-4-31b-it (15 endpoints on the public listing), and cost was
    tokens x fixed $0.09/$0.34 although tool-capable endpoints bill $0.10 to $0.75 per M in. Now openrouter is pinned
    to RT.OR_PROVIDER_DEFAULT (bf16, tools) unless another pin or 'any' is given, and the budget counts usage.cost."""
    up = FakeUpstream({"fixer": [text("a"), text("b"), text("c")]}, cost=0.0123)
    try:
        ep = RT.make_endpoint("openrouter", upstream_base=up.base, key=SECRET)
        assert ep.provider == RT.OR_PROVIDER_DEFAULT == "crusoe/bf16" and ep.public()["or_provider"] == "crusoe/bf16"
        budget = RT.Budget(1.0)
        r = route_router(ep, live="fixer", budget=budget)
        st, out = r.answer("k", body_for("fixer"))
        assert st == 200 and up.seen[-1]["body"]["provider"] == {"order": ["crusoe/bf16"], "allow_fallbacks": False}
        rec = r.route("k").records[-1]
        assert rec["cost_usd"] == 0.0123 and rec["cost_source"] == "billed" and budget.spent == pytest.approx(0.0123)
        for pin in ("any", "none", "ANY"):
            un = RT.make_endpoint("openrouter", upstream_base=up.base, key=SECRET, or_provider=pin)
            assert un.provider is None and "provider" not in un.forward_body(body_for("fixer"), "c")
        nov = RT.make_endpoint("openrouter", upstream_base=up.base, key=SECRET, or_provider="novita/bf16")
        assert nov.forward_body(body_for("fixer"), "c")["provider"]["order"] == ["novita/bf16"]
        with pytest.raises(ValueError, match="--or-provider"):
            RT.make_endpoint("openrouter", upstream_base=up.base, key=SECRET, upstream_extra={"provider": {}})
        # vLLM is free per token: a cost field in its reply is ignored, and the price figure is only an estimate
        vl = RT.make_endpoint("vllm", upstream_base=up.base)
        vb = RT.Budget(None)
        rv = route_router(vl, live="fixer", budget=vb)
        rv.answer("k", body_for("fixer"))
        assert "provider" not in up.seen[-1]["body"]
        rec = rv.route("k").records[-1]
        assert rec["cost_usd"] == 0.0 and rec["cost_source"] == "est_usd_at_proxy_prices"
        assert rec["est_usd_at_proxy_prices"] > 0 and rec["est_usd_at_proxy_prices"] != 0.0123
        assert vb.spent == pytest.approx(rec["est_usd_at_proxy_prices"], abs=1e-8) and vb.allow()   # uncapped
        assert vl.billed({"cost": 5.0}) is None and ep.billed({"cost": True}) is None and ep.billed({}) is None
    finally:
        up.close()


def test_cost_estimate_reprices_the_race2_mix():
    """EST_COST was computed at $0.09/$0.34; est_cost reprices it with the per-stage token mix, so the pre-launch
    estimate follows the pinned endpoint's prices."""
    for s in ("L", "F", "V"):
        assert RS.est_cost(s) == pytest.approx(RS.EST_COST[s])
        tin, tout = RS.EST_TOKENS[s]
        assert RS.est_cost(s, 0.14, 0.40) == pytest.approx(
            RS.EST_COST[s] * (tin * 0.14 + tout * 0.40) / (tin * 0.09 + tout * 0.34))
    assert RS.est_cost("F", 0.14, 0.40) == pytest.approx(0.0177, abs=1e-4)
    assert RS.needed_usd(29 * 3 * RS.est_cost("F", 0.14, 0.40)) == 1.94          # the ablation arm: pass 2.00
    assert RS.needed_usd(0.0) == 0.01


def test_router_retries_only_429_502_503():
    sleeps = []
    up = FakeUpstream(fail=[429, 503], retry_after=None)
    try:
        ep = RT.make_endpoint("vllm", upstream_base=up.base)
        ep.sleep = sleeps.append
        r = route_router(ep, live="fixer")
        st, _ = r.answer("k", body_for("fixer"))
        assert st == 200 and sleeps == [4.0, 8.0] and r.route("k").records[0]["retries"] == 2
        up.fail, up.retry_after, sleeps[:] = [429], "3", []
        assert r.answer("k", body_for("fixer"))[0] == 200 and sleeps == [3.0]          # Retry-After honoured
        up.fail, sleeps[:] = [502, 502, 502], []
        st, _ = r.answer("k", body_for("fixer"))
        assert st == 502 and len(sleeps) == 2 and r.route("k").upstream_failed_last       # twice, then give up
        up.fail, sleeps[:] = [500], []
        n = len(up.seen)
        st, out = r.answer("k", body_for("fixer"))
        assert st == 500 and sleeps == [] and len(up.seen) == n + 1                        # 500: never retried
        assert r.route("k").state()["fail_streak_s"] is not None
        assert r.answer("k", body_for("fixer"))[0] == 200 and not r.route("k").upstream_failed_last
        assert r.route("k").state()["fail_streak_s"] is None
    finally:
        up.close()


def test_router_budget_refuses_before_forwarding():
    up = FakeUpstream({"fixer": [text("a"), text("b")]})
    try:
        ep = RT.make_endpoint("vllm", upstream_base=up.base, price_in=5000.0, price_out=5000.0)
        budget = RT.Budget(0.05)
        r = route_router(ep, live="fixer", budget=budget)
        assert r.answer("k", body_for("fixer"))[0] == 200 and budget.spent > 0.05
        n = len(up.seen)
        st, out = r.answer("k", body_for("fixer"))
        assert st == 500 and out["error"]["message"] == RT.BUDGET_MSG and len(up.seen) == n
        assert r.route("k").records[-1]["served"] == "refused" and "budget" in r.route("k").state()["infra"]
        assert budget.refused == 1
        assert not RT.Budget(0.0).allow() and RT.Budget(None).allow()
    finally:
        up.close()


def test_router_done_after_end_on_a_harness_restart():
    """gotcha 9: a pass without submit_patch re-runs the SequentialAgent; the live stage must not run twice."""
    live = [cmd("python3 /tmp/swe/status.py"), text("notes")]
    r = route_router(live="fixer", scripts={"setup": [text("READY"), text("READY")],
                                            "locator": [text("plan"), text("plan")]}, live_script=live)
    for a in ("setup", "locator", "fixer", "fixer", "verifier", "submitter", "setup", "locator", "fixer"):
        r.answer("k", body_for(a))
    assert served(r)[2:4] == [("fixer", "oracle"), ("fixer", "oracle")]
    assert served(r)[-1] == ("fixer", "done_after_end")
    assert r.route("k").records[-1]["stage_run"] == 1


def test_router_live_cap_with_an_injectable_clock():
    """gotcha 16: the live stage is capped at helper t=300, i.e. (300 - t0)/scale after its first request."""
    for t0, scale in ((47, 1.0), (91, 2.0)):
        clk = FakeClock(500.0)
        cap = RS.cap_seconds(t0, scale)
        r = route_router(live="verifier", scripts={"setup": [text("READY")]}, cap_s=cap, clock=clk,
                         live_script=[cmd("x")] * 5)
        r.answer("k", body_for("setup"))
        clk.t = 620.0                                    # a slow pre-stage (120 s) does not eat the live budget
        r.answer("k", body_for("verifier"))
        clk.t = 620.0 + cap - 0.01
        r.answer("k", body_for("verifier"))
        clk.t = 620.0 + cap
        st, out = r.answer("k", body_for("verifier"))
        assert out["choices"][0]["message"]["content"] == "done"
        assert served(r)[1:] == [("verifier", "oracle"), ("verifier", "oracle"), ("verifier", "cap")]
        s = r.route("k").state()
        assert s["capped"] and s["pre_stage_s"] == pytest.approx(120.0)
    assert RS.cap_seconds(91, 2.0) == pytest.approx(104.5)


def test_router_summarizer_and_unknown_requests(tmp_path):
    up = FakeUpstream()
    try:
        r = route_router(RT.make_endpoint("vllm", upstream_base=up.base), live="fixer")
        r.answer("k", body_for("fixer"))
        st, out = r.answer("k", summarizer_body())
        assert out["choices"][0]["message"]["content"] == "SUMMARY" and len(up.seen) == 2     # forwarded
        r.answer("k", body_for("fixer"))                  # a compaction inside the live stage does not end it
        assert served(r) == [("fixer", "upstream"), ("_summarizer", "upstream"), ("fixer", "upstream")]
        assert [x["live"] for x in r.route("k").records] == [True, False, True]
    finally:
        up.close()
    r = route_router(RT.make_endpoint("null"), live="fixer")
    st, out = r.answer("k", summarizer_body())
    assert out["choices"][0]["message"]["content"] == RT.SUMMARY_TEXT and served(r) == [("_summarizer", "script")]
    assert r.answer("k", body_for("fixer"))[1]["choices"][0]["message"]["content"] == "done"
    assert served(r)[-1] == ("fixer", "null")
    st, out = r.answer("k", {"model": "m", "messages": [{"role": "user", "content": "who am i"}]})
    assert st == 200 and r.route("k").state()["infra"] == ["unknown_request"]
    assert r.route("k").records[-1]["error"] == "unknown_request"


def test_router_http_routes_are_isolated():
    with RT.StageRouter(RT.make_endpoint("oracle")) as r:
        ua = r.add_route("a", "A", "fixer", {"setup": [text("A")]}, [], 100)
        ub = r.add_route("b", "B", "fixer", {"setup": [text("B")]}, [], 100)
        import urllib.request as U

        def post(base):
            req = U.Request(base + "/chat/completions", data=json.dumps(body_for("setup")).encode(),
                            headers={"Content-Type": "application/json"})
            return json.loads(U.urlopen(req, timeout=10).read())["choices"][0]["message"]["content"]
        assert (post(ua), post(ub)) == ("A", "B")
        try:
            U.urlopen(U.Request(r.url("zz") + "/chat/completions", data=b"{}"), timeout=10)
            raise AssertionError("unknown route answered")
        except U.HTTPError as e:
            assert e.code == 404


def test_read_env_key_and_endpoint_validation(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    f = tmp_path / ".env"
    f.write_text("# x\nOTHER=1\nexport OPENROUTER_KEY='sk-file'\n")
    assert RT.read_env_key("OPENROUTER_KEY", str(f)) == "sk-file"
    assert RT.read_env_key("OPENROUTER_KEY", str(tmp_path / "missing")) is None
    monkeypatch.setenv("OPENROUTER_KEY", "sk-env")
    assert RT.read_env_key("OPENROUTER_KEY", str(f)) == "sk-env"
    monkeypatch.delenv("OPENROUTER_KEY")
    with pytest.raises(ValueError):
        RT.make_endpoint("openrouter", env_file=str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        RT.make_endpoint("vllm")
    assert RT.make_endpoint("openrouter", env_file=str(f)).label == "PROXY"
    assert RT.make_endpoint("vllm", upstream_base="http://x/v1").label == "FAITHFUL"
    assert RT.make_endpoint("null").label == RT.make_endpoint("oracle").label == "CONTROL"


# --------------------------------------------------------------------------------------------- the child process
def test_child_env_has_no_secret_and_its_own_route(monkeypatch, tmp_path):
    """gotcha 14: the key never reaches a child; the harness's endpoint overrides are stripped."""
    for k, v in (("OPENROUTER_KEY", SECRET), ("OPENAI_API_BASE", "http://evil"), ("OPENAI_API_KEY", "sk-x"),
                 ("MODEL_PROXY_URL", "http://p"), ("MODEL_PROXY_API_KEY", "k"), ("LITELLM_API_BASE", "http://l"),
                 ("LOCAL_INFERENCE_URL", "http://i"), ("MY_COPY", "prefix" + SECRET), ("G4_COMPACTION", "0"),
                 ("G4_L4_SCALE", "2"), ("TEST_TMPDIR", "/x")):
        monkeypatch.setenv(k, v)
    env = RS.child_env("http://127.0.0.1:1/r/c/v1", tmp_path, scale=1.0, faithful=False, plain_cache=None,
                       secrets=(SECRET,))
    assert SECRET not in json.dumps(env)
    for k in ("OPENROUTER_KEY", "OPENAI_API_BASE", "MODEL_PROXY_URL", "MODEL_PROXY_API_KEY", "LITELLM_API_BASE",
              "LOCAL_INFERENCE_URL", "MY_COPY", "G4_COMPACTION", "G4_L4_SCALE", "TEST_TMPDIR"):
        assert k not in env, k
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:1/r/c/v1" and env["OPENAI_API_KEY"] == "EMPTY"
    assert env["TMPDIR"] == str(tmp_path) and env["G4_FAITHFUL_ENV"] == "0" and env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert RS.child_env("u", tmp_path, scale=2.0, faithful=True, plain_cache=None)["G4_L4_SCALE"] == "2.0"
    assert RS.child_env("u", tmp_path, scale=2.0, faithful=True, plain_cache=None)["G4_FAITHFUL_ENV"] == "1"


def test_harness_budget_formula():
    assert RS.harness_minutes(47, 150, 1.0) == pytest.approx((253 + 150) / 60)
    m = RS.harness_minutes(91, 150, 2.0)                  # run_eval divides by scale: (300-91)/2 + 150 seconds
    assert m * 60 / 2.0 == pytest.approx(209 / 2 + 150)


def _snapshot(tmp_path: Path) -> Path:
    tasks, snaps = GC.make_task(tmp_path / "t", files={**GC.FILES, "bin/run.sh": "#!/bin/sh\necho hi\n",
                                                       "calc/link.py": "x = 1\n"})
    repo = tmp_path / "t" / "repo"
    os.chmod(repo / "bin" / "run.sh", 0o755)
    os.symlink("ops.py", repo / "calc" / "ops_link.py")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=a", "-c", "user.email=b", "commit", "-qm", "more"], cwd=repo, check=True,
                   capture_output=True)
    tgz = snaps / f"{GC.TID}.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(repo, arcname=".")
    return tgz


def _tree(ws: Path) -> dict:
    out = {}
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws).as_posix()
        st = p.lstat()
        kind = "l" if p.is_symlink() else ("d" if p.is_dir() else "f")
        data = os.readlink(p) if kind == "l" else (p.read_bytes() if kind == "f" else b"")
        out[rel] = (kind, stat.S_IMODE(st.st_mode) if kind != "l" else 0, data)
    return out


def _fast_box(mgr, root: Path, sid: str) -> str:
    """A sandbox registered with the real SubprocessManager (same layout as start(), minus the pip venv)."""
    base = root / "sbx" / f"swegemma_sandbox_{sid}"
    paths = {k: base / k for k in ("workspace", "tmp", "wheels", "venv")}
    for p in paths.values():
        p.mkdir(parents=True)
    paths["root"] = base
    mgr._sandboxes[sid] = paths
    return sid


def test_cached_extraction_is_identical_and_leaves_no_attribute(tmp_path):
    """gotcha 17: the per-call INSTANCE attribute is gone afterwards; the tree equals the harness tar extraction."""
    from swegemma.harness import container_setup as cs
    from swegemma.sandbox.subprocess import SubprocessManager
    tgz = _snapshot(tmp_path)
    mgr = SubprocessManager(base_dir=tmp_path / "sbx")
    try:
        a, b = _fast_box(mgr, tmp_path, "a"), _fast_box(mgr, tmp_path, "b")
        cs.extract_snapshot(mgr, a, tgz)
        seen = []

        def spy(docker, cid, snap, **kw):
            seen.append(hasattr(docker, "extract_archive_to_container"))
            return cs.extract_snapshot(docker, cid, snap, **kw)
        hook = SC.make_extract_hook(spy, tmp_path / "plain")
        hook(mgr, b, tgz)
        assert seen == [True] and not hasattr(mgr, "extract_archive_to_container")
        assert not hasattr(SubprocessManager(), "extract_archive_to_container")        # never class-level
        wa, wb = (Path(mgr.sandboxes[x]["workspace"]) for x in (a, b))
        assert _tree(wa) == _tree(wb)
        ls = [subprocess.run(["git", "ls-files", "-s"], cwd=w, capture_output=True, text=True).stdout for w in (wa, wb)]
        assert ls[0] == ls[1] and "calc/ops.py" in ls[0]
        assert (tmp_path / "plain" / GC.TID).is_dir() and (tmp_path / "plain" / f"{GC.TID}.stamp").is_file()

        def boom(docker, cid, snap, **kw):
            assert hasattr(docker, "extract_archive_to_container")
            raise RuntimeError("harness setup failed")
        with pytest.raises(RuntimeError):
            SC.make_extract_hook(boom, tmp_path / "plain")(mgr, b, tgz)
        assert not hasattr(mgr, "extract_archive_to_container")                         # even on an exception
    finally:
        mgr.cleanup_all()


def test_install_hooks_compose_with_run_eval_and_restore(tmp_path):
    """The agent-env hook has no _g4, so run_eval records it as the harness original and adds the clock-scale write
    after it; every wrapped module global is restored."""
    import run_eval
    import swegemma.evaluate as ev
    import swegemma.harness.agent_runner as ar
    import swegemma.harness.container_setup as cs
    import swegemma.harness.verification as vf
    before = {(m, n): getattr(m, n) for m, n in ((ar, "setup_baseline_commit"), (ar, "extract_snapshot"),
                                                 (ar, "install_test_dependencies"), (ev, "verify_task"),
                                                 (vf, "install_test_dependencies"), (cs, "install_test_dependencies"))}
    restore = SC.install_hooks(kpar="/K/site-packages", cache_root=tmp_path)
    try:
        assert not getattr(ar.install_test_dependencies, "_g4", False)
        assert ar.extract_snapshot is not before[(ar, "extract_snapshot")]
        orig = run_eval.install_patches(faithful=False, scale=2.0)
        assert orig[ar].__wrapped__ is before[(ar, "install_test_dependencies")]      # ours = the "harness original"
        venv = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / SC.HOST_PTH).write_text("/host\n")
        calls = []

        class SubprocessManager:              # the harness's install is a no-op for this class name, as in a run
            sandboxes = {"s": {"venv": tmp_path / "venv"}}

            def exec(self, cid, c):
                calls.append(c)
                return SimpleNamespace(exit_code=0, stdout="", stderr="")
        docker = SubprocessManager()
        ar.install_test_dependencies(docker, "s", "Textualize/rich")
        assert (venv / SC.KPAR_PTH).read_text() == "/K/site-packages\n"
        assert sorted(p.name for p in venv.glob("*.pth")) == [SC.KPAR_PTH, SC.HOST_PTH]     # _g4 sorts first
        assert calls and "clock_scale" in calls[-1]            # run_eval's clock-scale write composed AFTER ours
        assert ar.install_test_dependencies.__name__ == "agent_install_with_clock_scale"
    finally:
        restore()
        for (m, n), v in before.items():
            setattr(m, n, v)
    for (m, n), v in before.items():
        assert getattr(m, n) is v


def test_verify_skip_keeps_kw_saves_the_trace_and_the_patch(tmp_path):
    """gotchas 13 and 19: evaluate.py inspects the signature; the stub saves the trace itself."""
    from adk_eval_core.tracing import SessionTrace
    stub = SC.make_verify_skip()
    ps = inspect.signature(stub).parameters
    assert list(ps)[:4] == ["docker", "config", "task", "snapshot_path"]
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in ps.values())
    tr = SessionTrace()
    tr.start()
    cfg = SimpleNamespace(results_dir=tmp_path)
    task = SimpleNamespace(instance_id="calc_1", repo="synthetic/calc")
    res = asyncio.run(stub(None, cfg, task, tmp_path / "x.tgz", agent_patch="diff", agent_error=None, trace=tr,
                           start_time=time.perf_counter(), base_snapshot_path=None, patch_path=None))
    assert res.agent_patch == "diff" and res.resolved is False and res.test_exit_code == -2
    assert (tmp_path / "traces" / "trace_calc_1.json").is_file() and res.trace_json_path


def test_kpar_with_faithful_env_is_refused(tmp_path):
    a = RS.parser().parse_args(["run", "--suite", "F", "--split", "dev", "--endpoint", "null", "--faithful-env",
                                "--agent-env", "kpar", "--dataset", str(tmp_path / "none.json")])
    with pytest.raises(RS.UsageError, match="faithful"):
        RS.Runner(a).prepare()
    assert SC.main(["--agent-env", "kpar", "--kpar-site", "/x", "--faithful-env", "--", "eval"]) == 2


def test_bundle_with_other_sub_agents_is_refused(tmp_path):
    b = S.copy_bundle(tmp_path)
    y = (b / "agent.yaml").read_text()
    (b / "agent.yaml").write_text(y.replace("  - config_path: sub_agents/submitter.yaml\n", ""))
    with pytest.raises(RS.UsageError, match="exactly"):
        RS.check_bundle(b)
    assert RS.check_bundle(S.BUNDLE) == list(RS.EXPECTED_AGENTS)
    assert len(RS.bundle_sha(S.BUNDLE)) == 64 and RS.bundle_sha(b) != RS.bundle_sha(S.BUNDLE)


def _run_args(root: Path, env: dict, ds: Path, *extra: str) -> list:
    return ["--split", "dev", "--dataset", str(ds), "--out", str(root / "runs"), "--tasks-jsonl", env["tasks_jsonl"],
            "--snapshots-dir", env["snapshots_dir"], "--ws-cache", str(root / "ws"), "--plain-cache",
            str(root / "plain"), "--holdout-log", str(root / "holdout_log.jsonl"), *extra]


def test_holdout_needs_a_reason_and_is_logged(tmp_path):
    env = GC.make_env(tmp_path)
    c = GC.case("F", runnable=False)
    c["golden"]["split"] = "holdout"
    ds = GC.write_dataset(tmp_path / "F_holdout.json", [c])
    args = _run_args(tmp_path, env, ds)
    args[1] = "holdout"
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", "--run-id", "h1", *args]) == 2
    assert not (tmp_path / "holdout_log.jsonl").exists()
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", "--run-id", "h2", "--holdout-reason", "v11 final",
                    *args]) == 0
    log = [json.loads(x) for x in (tmp_path / "holdout_log.jsonl").read_text().splitlines()]
    assert len(log) == 1 and log[0]["reason"] == "v11 final" and log[0]["run_id"] == "h2" and log[0]["suite"] == "F"
    assert set(log[0]) == {"ts", "suite", "bundle_sha", "run_id", "reason"}
    flat = json.loads((tmp_path / "runs" / "h2" / "cases" / "F__calc_1__s0.json").read_text())
    assert flat["status"] == "skipped" and "not runnable" in flat["status_detail"]
    run = json.loads((tmp_path / "runs" / "h2" / "run.json").read_text())
    assert run["holdout_reason"] == "v11 final" and run["cases"]["skipped"] == 1
    for k in ("run_id", "created", "git_head", "git_dirty", "suite", "split", "dataset_path", "dataset_sha",
              "fixture_manifest_sha", "endpoint", "label", "upstream_base", "upstream_model", "or_provider",
              "providers_seen", "l4_scale", "agent_env", "samples", "seed_mode", "bundle_path", "bundle_sha",
              "versions", "t0", "budget_usd", "spent_usd", "wall_s", "mean_live_latency_s", "cases",
              "holdout_reason"):
        assert k in run, k


def test_select_cases_filters_and_env_defaults(monkeypatch):
    cases = [GC.case("V", v) for v in ("gold", "wrong", "empty")] + [GC.case("V", "gold", task="other")]
    got = RS.select_cases(cases, suite="V", split="dev", tasks=[GC.TID], variants=["gold", "empty"])
    assert [c["eval_case_id"] for c in got] == ["V__calc_1__empty", "V__calc_1__gold"]
    with pytest.raises(RS.UsageError, match="suite"):
        RS.select_cases(cases, suite="F", split="dev")
    with pytest.raises(RS.UsageError, match="split"):
        RS.select_cases(cases, suite="V", split="holdout")
    for k, v in (("G4_GOLDEN_ENDPOINT", "null"), ("G4_GOLDEN_UPSTREAM_BASE", "http://u/v1"),
                 ("G4_GOLDEN_UPSTREAM_MODEL", "m1"), ("G4_GOLDEN_J", "3"), ("G4_GOLDEN_MAX_USD", "0.25")):
        monkeypatch.setenv(k, v)
    a = RS.parser().parse_args(["run", "--suite", "F", "--split", "dev"])
    assert (a.endpoint, a.upstream_base, a.upstream_model, a.j, a.max_usd) == ("null", "http://u/v1", "m1", 3, 0.25)
    assert a.agent_env == "kpar" and a.samples == 1 and a.l4_scale == 1.0 and a.seed_mode == "off"


def test_task_filter_is_validated_and_recorded(tmp_path):
    """Regression (integration smoke 2026-09-30): a `--tasks` run kept no record of its filter, so its summary read
    'F dev: 2 gradable of 2 runnable of 2 tasks' as if that were the dev population, and a mistyped task id or
    variant was dropped without a word (the run silently covered fewer tasks than asked)."""
    cases = [GC.case("V", v) for v in ("gold", "wrong", "empty")] + [GC.case("V", "gold", task="other")]
    with pytest.raises(RS.UsageError, match="calc_9"):
        RS.select_cases(cases, suite="V", split="dev", tasks=[GC.TID, "calc_9"])
    with pytest.raises(RS.UsageError, match="bogus"):
        RS.select_cases(cases, suite="V", split="dev", variants=["gold", "bogus"])
    assert len(RS.select_cases(cases, suite="V", split="dev", tasks=[GC.TID, "other"])) == 4
    env = GC.make_env(tmp_path)
    ds = GC.write_dataset(tmp_path / "F_dev.json", [GC.case("F", runnable=False),
                                                    GC.case("F", task="other", runnable=False)])
    args = _run_args(tmp_path, env, ds)
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", "--run-id", "sub", "--tasks", GC.TID, *args]) == 0
    run = json.loads((tmp_path / "runs" / "sub" / "run.json").read_text())
    assert (run["task_filter"], run["variant_filter"], run["dataset_tasks"]) == ([GC.TID], None, 2)
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", "--run-id", "all", *args]) == 0
    run = json.loads((tmp_path / "runs" / "all" / "run.json").read_text())
    assert (run["task_filter"], run["variant_filter"], run["dataset_tasks"]) == (None, None, 2)
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", "--run-id", "typo", "--tasks", "calc_9", *args]) == 2
    assert not (tmp_path / "runs" / "typo").exists()


def test_max_usd_caps_openrouter_by_default_and_vllm_only_when_given(tmp_path):
    """Regression (review 2026-09-30): vllm (FAITHFUL, free per token) ran under a dollar budget priced at OpenRouter
    rates with the $1.00 default, so a 3-sample decision run was truncated by a made-up cost (alphabetically last
    tasks first). Now only openrouter is capped by default; vllm only by an explicit --max-usd."""
    env = GC.make_env(tmp_path)
    (tmp_path / ".env").write_text(f"OPENROUTER_KEY={SECRET}\n")
    ds = GC.write_dataset(tmp_path / "F_dev.json", [GC.case("F", runnable=False)])

    def prep(*extra):
        a = RS.parser().parse_args(["run", "--suite", "F", *_run_args(tmp_path, env, ds, *extra)])
        r = RS.Runner(a)
        r.prepare()
        return r
    assert RS.parser().parse_args(["run", "--suite", "F", "--split", "dev"]).max_usd is None
    assert prep("--endpoint", "vllm", "--upstream-base", "http://127.0.0.1:9/v1", "--run-id", "v").cap is None
    assert prep("--endpoint", "vllm", "--upstream-base", "http://127.0.0.1:9/v1", "--max-usd", "0.5",
                "--run-id", "v2").cap == 0.5
    orr = prep("--endpoint", "openrouter", "--env-file", str(tmp_path / ".env"), "--run-id", "o")
    assert orr.cap == RS.DEFAULT_MAX_USD == 1.00 and orr.endpoint.provider == RT.OR_PROVIDER_DEFAULT
    assert prep("--endpoint", "null", "--max-usd", "0.5", "--run-id", "n").cap is None     # controls spend nothing
    assert RS.main(["run", "--suite", "F", "--endpoint", "vllm", "--upstream-base", "http://127.0.0.1:9/v1",
                    *_run_args(tmp_path, env, ds, "--run-id", "vrun")]) == 0
    run = json.loads((tmp_path / "runs" / "vrun" / "run.json").read_text())
    assert run["budget_usd"] is None and run["spent_usd"] == 0.0 and run["est_usd_at_proxy_prices"] == 0.0


@needs_kpar
def test_a_run_whose_estimate_exceeds_the_cap_is_refused_before_anything_starts(tmp_path, capsys):
    """Before launching, a capped run compares race-2 tokens x the endpoint's prices x the case samples it will run
    with --max-usd and refuses, printing the value that fits; the refused run leaves no run dir."""
    env = GC.make_env(tmp_path)
    (tmp_path / ".env").write_text(f"OPENROUTER_KEY={SECRET}\n")
    ds = GC.write_dataset(tmp_path / "F_dev.json", [GC.case("F"), GC.case("F", task="calc_x", runnable=False)])
    base = ["run", "--suite", "F", "--endpoint", "openrouter", "--env-file", str(tmp_path / ".env"),
            "--upstream-base", "http://127.0.0.1:9/v1"]
    est = 30 * RS.est_cost("F", 0.14, 0.40)                      # the calc case x 30 samples; the other is skipped
    rc = RS.main([*base, *_run_args(tmp_path, env, ds, "--samples", "30", "--max-usd", "0.25", "--run-id", "big")])
    err = capsys.readouterr().err
    assert rc == 2 and f"estimated ${round(est, 4):.3f} for 30 case samples" in err, err
    assert f"pass --max-usd {RS.needed_usd(round(est, 4)):.2f}" in err and "exceeds --max-usd 0.25" in err
    assert not (tmp_path / "runs" / "big").exists()
    a = RS.parser().parse_args([*base, *_run_args(tmp_path, env, ds, "--samples", "30", "--max-usd", "0.7",
                                                  "--run-id", "fits")])
    r = RS.Runner(a)
    r.prepare()                                                   # 0.53 <= 0.7: accepted
    assert r.est_usd == round(est, 4) and r.cap == 0.7
    a = RS.parser().parse_args(["run", "--suite", "F", "--endpoint", "vllm", "--upstream-base",
                                "http://127.0.0.1:9/v1", *_run_args(tmp_path, env, ds, "--samples", "30",
                                                                    "--run-id", "vfree")])
    RS.Runner(a).prepare()                                        # vllm uncapped: no refusal whatever the estimate


def test_resume_refuses_other_settings_and_cases_carry_what_served_them(tmp_path, capsys):
    """Regression (review 2026-09-30): --resume checked only the bundle sha, then overwrote run.json's endpoint, label
    and model, and assemble labelled every case from run.json: cases answered by a null endpoint came out FAITHFUL
    after a `--resume --endpoint vllm`, which defeats compare's label refusal. Now a resume with other settings is
    refused, and each case's meta.json carries the endpoint and label that served it."""
    env = GC.make_env(tmp_path)
    ds = GC.write_dataset(tmp_path / "F_dev.json", [GC.case("F", runnable=False)])
    args = _run_args(tmp_path, env, ds, "--run-id", "r")
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", *args]) == 0
    d = tmp_path / "runs" / "r"
    before = (d / "run.json").read_text()
    for extra, what in ((["--endpoint", "vllm", "--upstream-base", "http://127.0.0.1:9/v1"], "endpoint: 'null' -> 'vllm'"),
                        (["--endpoint", "null", "--l4-scale", "2"], "l4_scale: 1.0 -> 2.0"),
                        (["--endpoint", "null", "--samples", "3"], "samples: 1 -> 3"),
                        (["--endpoint", "null", "--seed-mode", "case"], "seed_mode: 'off' -> 'case'"),
                        (["--endpoint", "null", "--agent-env", "host"], "agent_env: 'kpar' -> 'host'")):
        assert RS.main(["run", "--suite", "F", *extra, *args, "--resume"]) == 2
        err = capsys.readouterr().err
        assert what in err and "use a new --run-id" in err, err
        assert (d / "run.json").read_text() == before                  # nothing touched
    ds2 = GC.write_dataset(tmp_path / "other" / "F_dev.json", [GC.case("F", runnable=False, t0=50)])
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", *_run_args(tmp_path, env, ds2, "--run-id", "r"),
                    "--resume"]) == 2 and "dataset_sha" in capsys.readouterr().err
    assert RS.main(["run", "--suite", "F", "--endpoint", "null", *args, "--resume"]) == 0   # same settings: resumes
    run = json.loads((d / "run.json").read_text())
    assert run["resumes"] == 1 and run["endpoint"] == "null"
    assert not (d / "attempts").exists() and run["attempts_kept"] == 0    # a skipped case leaves no attempt behind
    assert not RS.worth_keeping(d / "cases" / "missing") and not RS.worth_keeping(d / "cases" / "F__calc_1__s0")
    meta = json.loads((d / "cases" / "F__calc_1__s0" / "meta.json").read_text())
    assert (meta["endpoint"], meta["label"], meta["upstream_model"], meta["or_provider"]) == ("null", "CONTROL", None,
                                                                                            None)
    run["endpoint"], run["label"] = "vllm", "FAITHFUL"                     # a run.json that says otherwise
    (d / "run.json").write_text(json.dumps(run))
    rec = RS.assemble(d, "F__calc_1__s0", checks=False)
    assert (rec["flat"]["endpoint"], rec["flat"]["label"]) == ("null", "CONTROL")
    assert (rec["trace"]["golden"]["run"]["endpoint"], rec["trace"]["golden"]["run"]["label"]) == ("null", "CONTROL")
    meta.pop("endpoint"), meta.pop("label")                                  # a case written before the stamp
    (d / "cases" / "F__calc_1__s0" / "meta.json").write_text(json.dumps(meta))
    assert RS.assemble(d, "F__calc_1__s0", checks=False)["flat"]["label"] == "FAITHFUL"


def test_smoke_selection_and_estimate_offline():
    def c(s, tid, variant="-", **g):
        x = {"golden": {"suite": s, "task": tid, "variant": variant, "split": "dev", "runnable": True,
                        "gradable": True, "repo": "rich", **g}}
        return x
    lines = {"a": 5, "b": 1, "c": 3, "d": 2}
    orig = RS.gold_lines
    RS.gold_lines = lambda case: lines[case["golden"]["task"]]
    try:
        ds = {"L": [c("L", t) for t in "abcd"] + [c("L", "z", repo="fastapi")],
              "F": [c("F", t) for t in "abc"] + [c("F", "d", gradable=False)],
              "V": [c("V", t, v) for t in "abc" for v in ("gold", "empty")] + [c("V", "c", "wrong"),
                                                                                c("V", "a", "wrong")]}
        sel = RS.smoke_selection(ds)
    finally:
        RS.gold_lines = orig
    assert sel == {"L": ["b", "d"], "F": ["b", "c"], "V": ["c"]}
    assert RS.smoke_estimate(sel) == pytest.approx(2 * 0.0102 + 2 * 0.0115 + 3 * 0.0070)
    assert RS.SMOKE_CAP == 0.40 and RS.parser().parse_args(["smoke"]).max_usd == 0.40


# --------------------------------------------------------------------------------------- real children (module)
def _norm(obj) -> str:
    """Normalise tool-call ids, [t=Ns] footers and journal t=Ns times (5.10 step 3)."""
    s = json.dumps(obj, sort_keys=True)
    ids = {}
    s = re.sub(r"call_[0-9a-f]{6,}", lambda m: ids.setdefault(m.group(0), f"call_{len(ids)}"), s)
    return re.sub(r"t=\d+s", "t=Ns", s)


@pytest.fixture(scope="module", autouse=True)
def tasks_globals():
    """Restore v10_support.tasks module globals (the runner points them at the calc task)."""
    t = CK.T()
    saved = (t.TASKS_JSONL, t.SNAP_DIR, t.CACHE, t.WORK, t._TASKS, dict(t._BASE_MEMO))
    yield
    t.TASKS_JSONL, t.SNAP_DIR, t.CACHE, t.WORK, t._TASKS = saved[:5]
    t._BASE_MEMO.clear()
    t._BASE_MEMO.update(saved[5])


@pytest.fixture(scope="module")
def runs(tmp_path_factory, tasks_globals):
    """Every real-child scenario, concurrently: {name: result}."""
    if not KPAR_OK:
        pytest.skip(f"kpar venv missing: {CK.T().build_cmd('rich')}")
    root = tmp_path_factory.mktemp("golden_runs")
    env = GC.make_env(root)
    saved_key = os.environ.pop("OPENROUTER_KEY", None)
    (root / ".env").write_text(f"OPENROUTER_KEY={SECRET}\n")
    out: dict = {}
    V = GC.golden("V", "gold")
    fixer_steps = [*V["replay_steps"], SS.VERIFY, SS.notes_step(V["notes_changed"])]
    ver_steps = [SS.STATUS, SS.VERIFY, SS.FINALIZE, submit(), text("Submitted.")]
    loc_steps = [SS.locate_step(V["title_words"]), SS.repro_step(V["repro"]), SS.plan_step(V["plan"])]
    bundle = S.copy_bundle(root / "flow_bundle")
    probe = cmd('python3 -c "import pygments,sys;print(pygments.__file__)"', delay=2)
    fake_or = FakeUpstream({"fixer": [probe] + [{**SS.STATUS, "delay": 2}] * 20})

    def run(name, suite, cases, *extra, cmd_="run", hook=None):
        ds = GC.write_dataset(root / f"ds_{name}_{suite}.json", cases)
        argv = [cmd_, "--suite", suite, *_run_args(root, env, ds, "--run-id", name, *extra)]
        t = time.monotonic()
        if hook is None:
            rc = RS.main(argv)
        else:
            a = RS.parser().parse_args(argv)
            rc = RS.Runner(a, script_hook=hook).run()
        return {"rc": rc, "secs": time.monotonic() - t, "dir": root / "runs" / name}

    def controls(suite):
        cases = [GC.case("V", v) for v in ("gold", "wrong", "empty")] if suite == "V" else [GC.case(suite)]
        if suite == "V":
            cases.append(GC.case("V", "gold", task="calc_missing"))     # not in tasks.jsonl -> skipped
        return run("ctl", suite, cases, "-j", "6", cmd_="controls")

    def parity(mock):
        full = mock.add_route("full", {"setup": [SS.INSTALL, text("READY")], "locator": loc_steps,
                                       "fixer": fixer_steps, "verifier": ver_steps})
        upf, upv = mock.add_route("upF", {"fixer": fixer_steps}), mock.add_route("upV", {"verifier": ver_steps})
        with ThreadPoolExecutor(3) as ex:
            fa = ex.submit(S.run_eval_cli, bundle=bundle, tasks=Path(env["tasks_jsonl"]),
                           snapshots=Path(env["snapshots_dir"]), results=root / "full", api_base=full,
                           task_ids=[GC.TID], timeout=300)
            fb = ex.submit(run, "par_F", "F", [GC.case("F")], "--endpoint", "vllm", "--upstream-base", upf,
                           "--log-bodies")
            fc = ex.submit(run, "par_V", "V", [GC.case("V", "gold")], "--endpoint", "vllm", "--upstream-base", upv,
                           "--log-bodies")
            res = {"full": fa.result(), "F": fb.result(), "V": fc.result()}
        res["log"] = mock.log("full")
        return res

    def cap_hook(case, k, scripts, live_script):
        scripts = {a: list(s) for a, s in scripts.items()}
        scripts["locator"][0] = {**scripts["locator"][0], "delay": 4}          # a slow pre-stage within pre_s
        return scripts, live_script

    try:
        with MockLLM() as mock, ThreadPoolExecutor(10) as ex:
            futs = {
                "ctl_L": ex.submit(controls, "L"), "ctl_F": ex.submit(controls, "F"), "ctl_V": ex.submit(controls, "V"),
                "parity": ex.submit(parity, mock),
                # the live cap after a slow pre-stage, kpar shadowing, and the key/forwarding path end to end:
                # an "openrouter" endpoint whose --upstream-base is a local fake (no network)
                "cap": ex.submit(run, "cap", "F", [GC.case("F", t0=290, pre_s=40)], "--endpoint", "openrouter",
                                 "--upstream-base", fake_or.base, "--env-file", str(root / ".env"), "--log-bodies",
                                 hook=cap_hook),
            }
            for k, f in futs.items():
                out[k] = f.result()
            assert not mock.errors, mock.errors
        out["fake_or"], out["root"] = fake_or.seen, root
    finally:
        fake_or.close()
        if saved_key is not None:
            os.environ["OPENROUTER_KEY"] = saved_key
    return out


def _flat(d: Path, cid: str) -> dict:
    return json.loads((d / "cases" / f"{cid}.json").read_text())


def _trace_cases(d: Path) -> dict:
    tr = json.loads(next((d / "traces").glob("*.json")).read_text())
    return {c["eval_case_id"]: c for c in tr["eval_cases"]}


def _bodies(d: Path, cid: str, agent: str, served: str | None = None) -> list:
    rows = [json.loads(x) for x in (d / "cases" / cid / "router_bodies.jsonl").read_text().splitlines()]
    return [r["request"] for r in rows if r["agent"] == agent and (served is None or r["served"] == served)]


def test_parity_the_live_stage_sees_what_a_full_pipeline_shows(runs):
    """5.10 (gotcha 8): the first live request of the stage runs F and V equals the full pipeline's."""
    p = runs["parity"]
    assert p["full"].rc == 0 and p["full"].row(GC.TID)["error"] is None, p["full"].stderr[-2000:]
    assert p["F"]["rc"] == 0 and p["V"]["rc"] == 0
    for suite, agent, cid in (("F", "fixer", "F__calc_1__s0"), ("V", "verifier", "V__calc_1__gold__s0")):
        full = [e["body"] for e in p["log"] if e["agent"] == agent]
        stage = _bodies(p[suite]["dir"], cid, agent)
        assert full and stage
        f0, s0 = full[0], stage[0]
        assert f0["messages"][0] == s0["messages"][0] and f0["messages"][0]["role"] == "system"      # byte-identical
        assert f0["messages"][1] == s0["messages"][1] and "For context:" in json.dumps(s0["messages"][1])
        assert f0["tools"] == s0["tools"]
        assert f0["messages"] == s0["messages"]
        assert _norm(full[1]["messages"]) == _norm(stage[1]["messages"])      # helper state after a tool call
        assert _flat(p[suite]["dir"], cid)["status"] == "ok"
    assert "[locator] said: FILES: calc/ops.py" in json.dumps(_bodies(p["F"]["dir"], "F__calc_1__s0", "fixer")[0])
    assert "[fixer] said: CHANGED: calc/ops.py add (3-3)\\nVERIFY: VERIFY: GREEN" in json.dumps(
        _bodies(p["V"]["dir"], "V__calc_1__gold__s0", "verifier")[0])


@pytest.mark.parametrize("suite", ["L", "F", "V"])
def test_controls_hold_on_the_calc_task(runs, suite):
    """5.9: oracle and null arms meet the pre-registered expectations (a violation is a runner or grader bug)."""
    r = runs[f"ctl_{suite}"]
    assert r["rc"] == 0, r
    rep = json.loads((r["dir"].parent / f"ctl_{suite}_dev_controls.json").read_text())
    assert rep["oracle"]["violations"] == [] and rep["null"]["violations"] == []
    for arm in ("oracle", "null"):
        run = json.loads((Path(rep[arm]["run_dir"]) / "run.json").read_text())
        assert run["label"] == "CONTROL" and run["spent_usd"] == 0
        assert run["cases"]["ok"] == (3 if suite == "V" else 1)
        assert run["cases"]["skipped"] == (1 if suite == "V" else 0)


def _live_footers(trace: dict) -> list:
    live = trace["golden"]["live_agents"][0]
    out = []
    for e in TW.first_stage_run(trace["agent_data"], live):
        for p in e["content"]["parts"]:
            if "function_response" in p:
                out += [int(x) for x in re.findall(r"\[t=(\d+)s\]", json.dumps(p))][-1:]
    return out


@pytest.mark.parametrize("suite,cid,t0", [("L", "L__calc_1__s0", 2), ("F", "F__calc_1__s0", 47),
                                          ("V", "V__calc_1__gold__s0", 91), ("V", "V__calc_1__empty__s0", 91)])
def test_first_live_footer_reads_t0(runs, suite, cid, t0):
    """gotcha 7: the baseline-date hook + CLOCK make the live stage's first helper footer read t0 (+-2 s)."""
    d = Path(json.loads((runs[f"ctl_{suite}"]["dir"].parent / f"ctl_{suite}_dev_controls.json").read_text())
             ["oracle"]["run_dir"])
    foot = _live_footers(_trace_cases(d)[cid])
    assert foot and abs(foot[0] - t0) <= 2, foot


def test_verification_stub_still_writes_patch_and_trace(runs):
    """gotcha 13: the stub saves the ATIF trace; results.py writes patches/<tid>.patch from TaskResult.agent_patch."""
    d = Path(json.loads((runs["ctl_F"]["dir"].parent / "ctl_F_dev_controls.json").read_text())["oracle"]["run_dir"])
    res = d / "cases" / "F__calc_1__s0" / "results"
    assert (res / "traces" / f"trace_{GC.TID}.json").is_file()
    assert "+    return a + b" in (res / "patches" / f"{GC.TID}.patch").read_text()
    row = json.loads((res / "task_results.jsonl").read_text().splitlines()[0])
    assert row["test_exit_code"] == -2 and row["resolved"] is False and row["error"] is None
    assert not (res / "test_outputs").exists() or not any((res / "test_outputs").iterdir())
    f = _flat(d, "F__calc_1__s0")
    assert f["harness_resolved"] is None and f["exec_checks"]["hidden_pass"] is True
    assert not (d / "cases" / "F__calc_1__s0" / "sbx").exists()           # removed by write (no --keep-sandboxes)


def test_null_L_ends_in_one_pass_with_an_empty_submit(runs):
    """gotcha 10: submit_patch accepts an empty diff, so the L pipeline ends without a harness restart."""
    d = Path(json.loads((runs["ctl_L"]["dir"].parent / "ctl_L_dev_controls.json").read_text())["null"]["run_dir"])
    recs = [json.loads(x) for x in (d / "cases" / "L__calc_1__s0" / "router.jsonl").read_text().splitlines()]
    assert max(r["stage_run"] for r in recs if r["kind"] == "agent") == 0
    assert not [r for r in recs if r["served"] in ("done_after_end", "exhausted")]
    assert [r["agent"] for r in recs if r["kind"] == "agent"] == ["setup", "setup", "setup", "locator", "fixer",
                                                                    "verifier", "verifier"]
    f = _flat(d, "L__calc_1__s0")
    assert f["harness"]["error"] is None and f["paths"]["patch"] is None and f["status"] == "ok"
    assert f["exec_checks"]["patch_files"] == [] and f["live"]["llm_calls"] == 1


def test_live_cap_after_a_slow_pre_stage_and_kpar_shadowing(runs):
    """gotchas 16 and 18: the live stage keeps its full (300 - t0)/scale after a slow pre-stage and is capped by the
    router, not killed by the harness; inside the sandbox the kpar .pth shadows the host packages."""
    r = runs["cap"]
    d = r["dir"]
    f = _flat(d, "F__calc_1__s0")
    assert f["status"] == "ok" and f["capped"] is True and f["harness"]["error"] is None, f
    assert 4.0 <= f["pre_stage_s"] <= 40, f["pre_stage_s"]
    recs = [json.loads(x) for x in (d / "cases" / "F__calc_1__s0" / "router.jsonl").read_text().splitlines()]
    live = [x for x in recs if x["live"]]
    first_cap = next(x for x in live if x["served"] == "cap")
    assert first_cap["t_in"] - live[0]["t_in"] >= 10.0                           # (300 - 290) / 1
    assert all(x["served"] == "upstream" for x in live[:live.index(first_cap)])
    assert len(live[:live.index(first_cap)]) >= 4
    assert any(x["agent"] == "verifier" and x["served"] == "script" for x in recs[recs.index(first_cap):])
    probe = TW.first_stage_run(_trace_cases(d)["F__calc_1__s0"]["agent_data"], "fixer")[1]
    out = json.dumps(probe)
    kpar = str(CK.T().kpar_dir("rich"))
    assert kpar in out and "gemma-swe-agent/.venv" not in out, out[:600]


def test_openrouter_route_forwards_with_the_key_that_never_lands_anywhere(runs):
    """gotcha 14 end to end: the upstream saw the key and the rewritten model; no file of the run holds the key."""
    d = runs["cap"]["dir"]
    f = _flat(d, "F__calc_1__s0")
    assert f["status"] == "ok" and f["label"] == "PROXY" and f["exec_checks"]["hidden_pass"] is False
    assert f["providers"] == ["FakeProv"] and f["live"]["cost_usd"] > 0
    seen = runs["fake_or"]
    assert seen and all(s["headers"]["Authorization"] == "Bearer " + SECRET for s in seen)
    assert all(s["body"]["model"] == RT.OPENROUTER_MODEL for s in seen)
    reqs = _bodies(d, "F__calc_1__s0", "fixer", served="upstream")
    assert len(seen) == len(reqs) >= 4
    pin = {"order": [RT.OR_PROVIDER_DEFAULT], "allow_fallbacks": False}           # the default provider pin
    assert all(s["body"]["provider"] == pin for s in seen) and not any("provider" in b for b in reqs)
    assert [dict(s["body"], model=None, provider=None) for s in seen] == [dict(b, model=None, provider=None)
                                                                           for b in reqs]   # else verbatim
    for p in d.rglob("*"):
        if p.is_file():
            assert SECRET.encode() not in p.read_bytes(), p
    run = json.loads((d / "run.json").read_text())
    assert run["providers_seen"] == ["FakeProv"] and run["spent_usd"] > 0
    assert run["upstream_base"].startswith("http://127.0.0.1") and run["upstream_model"] == RT.OPENROUTER_MODEL
    assert run["or_provider"] == RT.OR_PROVIDER_DEFAULT and f["or_provider"] == RT.OR_PROVIDER_DEFAULT
    assert run["budget_usd"] == RS.DEFAULT_MAX_USD and run["est_usd"] > 0          # openrouter: capped by default


def test_exec_checks_use_the_grader_timeout(runs, tasks_globals):
    """gotcha 21: every hidden-test run passes timeout=180 (mini_verify's 20 s default would score a slow suite as
    a hang)."""
    env = {"tasks_jsonl": str(runs["root"] / "task" / "tasks.jsonl"),
           "snapshots_dir": str(runs["root"] / "task" / "snapshots")}
    CK.configure_tasks(env["tasks_jsonl"], env["snapshots_dir"], runs["root"] / "ws")
    seen = []

    def fake_mv(base, patch, test_patch, **kw):
        seen.append(kw)
        return True, None, 0.1
    out = CK.hidden_pass(GC.TID, GC.GOLD, GC.TEST_PATCH, GC.golden("F"), mini_verify=fake_mv)
    assert out["hidden_pass"] and seen == [{"repo": "rich", "timeout": 180}]
    assert CK.HIDDEN_TIMEOUT == 180


def test_written_traces_are_valid_grading_input(runs):
    for name in ("cap",):
        for c in _trace_cases(runs[name]["dir"]).values():
            assert TW.validate_case(c) == [], c["eval_case_id"]
            assert c["golden"]["llm_calls"] or c["golden"]["status"] == "infra_error"
            assert c["golden"]["run"]["max_output_tokens"]["fixer"] == 2048


# --------------------------------------------------------------------------------------------------------- NIGHTLY
NIGHTLY_TIDS = ("rich_3278", "rich_3480", "rich_4075")


def _nightly_case(suite: str, tid: str, variant: str = "-") -> dict:
    t = CK.T()
    row = t.load_task(tid)
    gold = row["patch"]
    files = [fp.path for fp in t.parse_patch(gold) if fp.path]
    g = GC.golden(suite, variant, task=tid, repro=None)
    title = row["problem_statement"].splitlines()[0][:80].replace('"', "")
    plan = (f"FILES: {', '.join(files)}\nCAUSE: see the issue.\nFIX: see the issue.\nREPRO: none\n"
            f"TESTS: none")
    g.update(title_words=title, plan=plan, gold_files=files, gold_functions=[],
             hidden_nodes=t.hidden_claim_nodes(tid))
    if suite == "V":
        steps, mode, _ = SS.replay_steps(gold if variant == "gold" else "")
        g.update(tree_patch=gold if variant == "gold" else "", tree_source=variant if variant != "gold" else "gold",
                 replay=mode, replay_steps=steps, notes_changed=SS.changed_line(gold if variant == "gold" else ""))
    ref = plan if suite == "L" else gold
    cid = f"{suite}__{tid}" + (f"__{variant}" if suite == "V" else "")
    return {"eval_case_id": cid, "prompt": {"role": "user", "parts": [{"text": row["problem_statement"]}]},
            "reference": {"response": {"role": "model", "parts": [{"text": ref}]}}, "golden": g}


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
@pytest.mark.parametrize("suite", ["L", "F", "V"])
def test_nightly_controls_on_three_real_rich_tasks(tmp_path, suite, tasks_globals):
    """Controls (5.9) on 3 real rich dev tasks: component a's dataset when it exists, else minimal cases built here
    (gold and empty variants for V; no repro)."""
    t = CK.T()
    CK.configure_tasks(None, None, None)
    missing = [x for x in NIGHTLY_TIDS if not t.has_snapshot(x)]
    if missing or not KPAR_OK:
        pytest.skip(f"needs snapshots {missing} and the rich kpar venv")
    ds_real = RS.DATASETS / f"{suite}_dev.json"
    if ds_real.is_file():
        cases = [c for c in RS.load_dataset(ds_real) if c["golden"]["task"] in NIGHTLY_TIDS
                 and c["golden"].get("runnable") and c["golden"].get("gradable")]
    else:
        cases = [_nightly_case(suite, x, v) for x in NIGHTLY_TIDS for v in (("gold", "empty") if suite == "V" else "-")]
    if not cases:
        pytest.skip("no runnable gradable NIGHTLY cases in the dataset")
    ds = GC.write_dataset(tmp_path / "ds.json", cases)
    rc = RS.main(["controls", "--suite", suite, "--split", "dev", "--dataset", str(ds), "--out", str(tmp_path / "runs"),
                  "--plain-cache", str(tmp_path / "plain"), "--holdout-log", str(tmp_path / "hl.jsonl"),
                  "--run-id", "nightly", "-j", "4"])
    assert rc == 0, (tmp_path / "runs").glob("*controls.json")


PARITY_TIDS = ("rich_3278", "rich_3043")      # smallest gold patches of the runnable dev set: one with a repro, one without


def _parity_case(suite: str, tid: str) -> dict:
    """Component a's dataset case (F, or V gold) when the dataset has it runnable and gradable, else a minimal one."""
    ds_real = RS.DATASETS / f"{suite}_dev.json"
    cid = f"{suite}__{tid}" + ("__gold" if suite == "V" else "")
    if ds_real.is_file():
        for c in RS.load_dataset(ds_real):
            g = c["golden"]
            if c["eval_case_id"] == cid and g.get("runnable") and g.get("gradable"):
                return c
    return _nightly_case(suite, tid, "gold" if suite == "V" else "-")


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
@pytest.mark.parametrize("tid", PARITY_TIDS)
def test_nightly_parity_on_real_rich_tasks(tmp_path, tid, tasks_globals):
    """5.10 on real rich tasks: the first live request of stage runs F and V equals the full pipeline's (system message,
    For context message and tool declarations byte-identical; the next request equal after normalising ids and t=Ns).
    The stage runs use --agent-env host so both sides run the stock harness environment."""
    t = CK.T()
    CK.configure_tasks(None, None, None)
    if not t.has_snapshot(tid) or not KPAR_OK:
        pytest.skip(f"needs the {tid} snapshot ({t.fetch_cmd(tid)}) and the rich kpar venv")
    F, V = _parity_case("F", tid), _parity_case("V", tid)
    gv = V["golden"]
    rep = SS.repro_step(F["golden"].get("repro"))
    loc_steps = [SS.locate_step(F["golden"]["title_words"])] + ([rep] if rep else []) + [SS.plan_step(F["golden"]["plan"])]
    fixer_steps = [*[dict(x) for x in gv["replay_steps"]], SS.VERIFY, SS.notes_step(gv["notes_changed"])]
    ver_steps = [SS.STATUS, SS.VERIFY, SS.FINALIZE, submit(), text("Submitted.")]
    bundle = S.copy_bundle(tmp_path / "flow_bundle")

    def stage(name, suite, case, up):
        ds = GC.write_dataset(tmp_path / f"ds_{name}.json", [case])
        rc = RS.main(["run", "--suite", suite, "--split", "dev", "--dataset", str(ds), "--out", str(tmp_path / "runs"),
                      "--plain-cache", str(tmp_path / "plain"), "--holdout-log", str(tmp_path / "hl.jsonl"),
                      "--run-id", name, "--endpoint", "vllm", "--upstream-base", up, "--log-bodies",
                      "--agent-env", "host"])
        return rc, tmp_path / "runs" / name

    with MockLLM() as mock, ThreadPoolExecutor(3) as ex:
        full = mock.add_route("full", {"setup": [SS.INSTALL, text("READY")], "locator": loc_steps,
                                       "fixer": fixer_steps, "verifier": ver_steps})
        upf, upv = mock.add_route("upF", {"fixer": fixer_steps}), mock.add_route("upV", {"verifier": ver_steps})
        fa = ex.submit(S.run_eval_cli, bundle=bundle, tasks=RS.CK.DEFAULT_TASKS, snapshots=RS.CK.DEFAULT_SNAPS,
                       results=tmp_path / "full", api_base=full, task_ids=[tid], max_time_minutes=10, timeout=900)
        fb = ex.submit(stage, "par_F", "F", F, upf)
        fc = ex.submit(stage, "par_V", "V", V, upv)
        res_full, (rc_f, dir_f), (rc_v, dir_v) = fa.result(), fb.result(), fc.result()
        log_full = mock.log("full")
        assert not mock.errors, mock.errors
    assert res_full.rc == 0 and res_full.row(tid)["error"] is None, res_full.stderr[-2000:]
    assert rc_f == 0 and rc_v == 0
    for d, agent, cid in ((dir_f, "fixer", F["eval_case_id"] + "__s0"), (dir_v, "verifier", V["eval_case_id"] + "__s0")):
        f_reqs = [e["body"] for e in log_full if e["agent"] == agent]
        s_reqs = _bodies(d, cid, agent)
        assert f_reqs and s_reqs, (agent, len(f_reqs), len(s_reqs))
        f0, s0 = f_reqs[0], s_reqs[0]
        assert f0["messages"][0] == s0["messages"][0]
        assert f0["messages"][1] == s0["messages"][1] and "For context:" in json.dumps(s0["messages"][1])
        assert f0["tools"] == s0["tools"]
        assert f0["messages"] == s0["messages"]
        assert _norm(f_reqs[1]["messages"]) == _norm(s_reqs[1]["messages"]), agent
        assert _flat(d, cid)["status"] == "ok", _flat(d, cid)
    first_fixer = json.dumps(_bodies(dir_f, F["eval_case_id"] + "__s0", "fixer")[0])
    assert "[locator] said: FILES:" in first_fixer
    if F["golden"].get("reproducible"):        # gotcha 15 on real data: PLAN read the repro result past CLOCK
        assert "REPRO: fails on original" in first_fixer
    assert "[fixer] said: CHANGED:" in json.dumps(_bodies(dir_v, V["eval_case_id"] + "__s0", "verifier")[0])
