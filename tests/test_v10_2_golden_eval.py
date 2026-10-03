"""v10.2 evaluation instruments (docs/v10/SPEC_v10_2.md section 8: E1-E4, E7; docs/eval/V10_2_EVAL.md).

E1 the router's L4 model clock: a slow proxy call advances the helper clock by the modelled m, not its latency; a 429
storm does not move it; a fast call with many output tokens advances it by m (negative excess); the live cap fires at
modelled t=300; wall mode adds nothing to the records; mixed clocks are refused by compare, ablation and --resume.
E2 l_l4_s reproduces research/locator_diag/l4time.py (failed calls excepted, by design). E3 l_files_named_n and
l_gold_files_in_files_line. E4 chain_plans.py and compare --pair-by-task. E7 v102_gate.decide at every gate edge.
No network, no model.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
for _p in (str(TESTS), str(ROOT / "scripts" / "golden"), str(ROOT / "scripts"), str(ROOT / "eval" / "golden")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if not (ROOT / "eval" / "golden" / "golden_metrics.py").is_file():
    pytest.skip("eval/golden absent (partial repo copy)", allow_module_level=True)

import golden_metrics as GM  # noqa: E402
import router as RT  # noqa: E402
import summary as SM  # noqa: E402
import chain_plans as CP  # noqa: E402
import v102_gate as VG  # noqa: E402
from test_golden_summary import case as s_case, write_run  # noqa: E402
from v10_support.repo import no_orphans  # noqa: F401,E402  (R120: the orphan-process guard, autouse)

L_V101 = ROOT / "eval" / "golden" / "runs" / "L_dev_v101"
L4_REF = ROOT / "research" / "locator_diag" / "l4_L_dev_v101.json"


# ------------------------------------------------------------------------------------------------------------ E1
class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class SlowEndpoint(RT.Endpoint):
    """An openrouter-like endpoint whose post() advances an injected clock by a latency and answers c tokens."""

    def __init__(self, clock, latency=20.0, completion=100, status=200, **kw):
        super().__init__("vllm", base="http://127.0.0.1:9/v1", model="m", key="EMPTY", **kw)
        self._clock, self.lat, self.comp, self.st = clock, latency, completion, status

    def post(self, body):
        self._clock.t += self.lat
        if self.st != 200:
            return self.st, None, 5, "HTTP %d: storm" % self.st
        p = sum(len(str(m.get("content") or "")) for m in body.get("messages") or []) // 4 or 1
        return 200, {"choices": [{"message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": p, "completion_tokens": self.comp}}, 0, None


def body(agent, text="go"):
    return {"model": "m", "messages": [{"role": "system", "content": 'Your internal name is "%s".' % agent},
                                       {"role": "user", "content": text}]}


def make(tmp_path, ep, clock, *, l4_clock="model", cap_s=253.0, live="locator"):
    sbx = tmp_path / "sbx"
    swe = sbx / "box1" / "tmp" / "swe"
    swe.mkdir(parents=True)
    (swe / "t0").write_text(repr(5000.0))
    r = RT.StageRouter(ep, None, clock=clock, l4_clock=l4_clock)
    r.add_route("k", "case_k", live, {"setup": [{"text": "READY"}]}, [], cap_s, sbx=sbx)
    return r, swe / "t0"


def t0_of(p):
    return float(p.read_text())


def test_model_clock_charges_m_not_the_proxy_latency(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=20.0, completion=100)
    r, t0 = make(tmp_path, ep, clk)
    r.answer("k", body("setup"))
    st, _ = r.answer("k", body("locator", "a" * 4000))
    rec = r.route("k").records[-1]
    m = RT.l4_model_s(100, rec["prompt_tokens"])            # first live call: u = its whole prompt
    assert st == 200 and rec["l4_m"] == pytest.approx(m, abs=1e-3) and rec["l4_uncached"] == rec["prompt_tokens"]
    # the helper clock (now - t0) advanced by m +- 0.5 s over the call, not by 20 s
    assert t0_of(t0) - 5000.0 == pytest.approx(20.0 - m, abs=1e-6)
    assert (20.0 - (t0_of(t0) - 5000.0)) == pytest.approx(m, abs=0.5) and m < 4.0
    # second call: u is only the new prompt text
    p1, c1 = rec["prompt_tokens"], rec["completion_tokens"]
    r.answer("k", body("locator", "a" * 4400))
    rec2 = r.route("k").records[-1]
    assert rec2["l4_uncached"] == max(0, rec2["prompt_tokens"] - p1 - c1)
    s = r.route("k").state()
    assert s["l4_clock"] == "model" and s["excess_s"] == pytest.approx(40.0 - s["model_s"], abs=1e-3)
    assert s["t0_missing"] == 0


def test_a_429_storm_does_not_move_the_helper_clock(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=45.0, status=429)
    r, t0 = make(tmp_path, ep, clk)
    r.answer("k", body("setup"))
    st, _ = r.answer("k", body("locator"))
    rec = r.route("k").records[-1]
    assert st == 429 and rec["l4_m"] == 0.0 and rec["l4_excess"] == pytest.approx(45.0)
    assert t0_of(t0) == pytest.approx(5045.0)               # (now - t0) unchanged by the 45 s storm
    ep.st, ep.lat = 200, 1.0
    r.answer("k", body("locator", "b" * 800))
    rec = r.route("k").records[-1]
    assert rec["l4_uncached"] == rec["prompt_tokens"]        # a failed call does not count as the cached prefix


def test_a_fast_call_with_700_output_tokens_advances_the_clock_by_m(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=1.0, completion=700)
    r, t0 = make(tmp_path, ep, clk)
    r.answer("k", body("setup"))
    before = clk.t - t0_of(t0)
    r.answer("k", body("locator"))
    after = clk.t - t0_of(t0)
    m = r.route("k").records[-1]["l4_m"]
    assert m > 19.7 and after - before == pytest.approx(m, abs=1e-3)       # negative excess: t0 moved back
    assert r.route("k").records[-1]["l4_excess"] < 0


def test_the_live_cap_fires_at_modelled_t300(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=30.0, completion=50)
    r, _ = make(tmp_path, ep, clk, cap_s=253.0)
    r.answer("k", body("setup"))
    for _ in range(12):                                      # 360 s of proxy time, about 20 s modelled
        r.answer("k", body("locator"))
    assert r.route("k").records[-1]["served"] == "upstream"
    ep.lat = 0.0
    modelled = clk.t - r.route("k").t_live0 - r.route("k").excess_s
    clk.t += 253.0 - modelled - 0.01                        # tool time up to just under the cap
    r.answer("k", body("locator"))
    assert r.route("k").records[-1]["served"] == "upstream"
    clk.t += 0.02 + r.route("k").records[-1]["l4_m"]
    r.answer("k", body("locator"))
    assert r.route("k").records[-1]["served"] == "cap"


def test_summariser_during_the_live_stage_is_charged_too(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=10.0, completion=30)
    r, t0 = make(tmp_path, ep, clk)
    summ = {"model": "m", "messages": [{"role": "user", "content": RT.SUMMARIZER_MARK + " events"}]}
    r.answer("k", summ)                                      # before the live stage: not charged
    assert "l4_m" not in r.route("k").records[-1] and t0_of(t0) == 5000.0
    r.answer("k", body("setup"))
    r.answer("k", body("locator"))
    r.answer("k", summ)
    rec = r.route("k").records[-1]
    assert rec["kind"] == "summarizer" and rec["l4_uncached"] == rec["prompt_tokens"] and "l4_m" in rec


def test_wall_mode_adds_nothing(tmp_path):
    clk = Clock()
    ep = SlowEndpoint(clk, latency=20.0)
    r, t0 = make(tmp_path, ep, clk, l4_clock="wall")
    r.answer("k", body("setup"))
    r.answer("k", body("locator"))
    rec = r.route("k").records[-1]
    assert not [k for k in rec if k.startswith("l4_")] and t0_of(t0) == 5000.0
    assert set(r.route("k").state()) == {"t_first", "t_live0", "infra", "upstream_failed_last", "requests",
                                         "fail_streak_s", "pre_stage_s", "capped"}
    with pytest.raises(ValueError):
        RT.StageRouter(ep, None, l4_clock="L4")


def test_missing_t0_file_is_counted_not_fatal(tmp_path):
    clk = Clock()
    r = RT.StageRouter(SlowEndpoint(clk), None, clock=clk, l4_clock="model")
    r.add_route("k", "c", "locator", {}, [], 253.0, sbx=tmp_path / "nothing")
    r.answer("k", body("locator"))
    assert r.route("k").state()["t0_missing"] == 1 and r.route("k").records[-1]["l4_t0_files"] == 0


def test_mixed_clocks_are_refused(tmp_path):
    base = write_run(tmp_path / "b", [s_case("F", "rich_1")], run={"suite": "F", "split": "dev", "label": "PROXY"})
    cand = write_run(tmp_path / "c", [s_case("F", "rich_1")], run={"suite": "F", "split": "dev", "label": "PROXY",
                                                                   "l4_clock": "model"})
    why, _ = SM.compare(base, cand)
    assert any("L4 clocks differ: wall vs model" in w for w in why)
    same = write_run(tmp_path / "d", [s_case("F", "rich_1")], run={"suite": "F", "split": "dev", "label": "PROXY",
                                                                   "l4_clock": "wall"})
    assert SM.compare(base, same)[0] == []                   # a run.json without the key is a wall run
    assert "l4_clock" in SM.ABL_SETTINGS
    import run_suite as RS
    assert "l4_clock" in RS.RESUME_KEYS
    a = RS.parser().parse_args(["run", "--suite", "L", "--split", "dev", "--endpoint", "null", "--l4-clock", "model"])
    assert RS.l4_clock_of(a) == "model"
    assert RS.l4_clock_of(RS.parser().parse_args(["run", "--suite", "L", "--split", "dev", "--endpoint", "null"])) \
        == "wall"


def test_resume_refuses_another_clock(tmp_path):
    import run_suite as RS
    run_dir = tmp_path / "runs" / "rid"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"suite": "L", "l4_clock": "wall"}))
    a = RS.parser().parse_args(["run", "--suite", "L", "--split", "dev", "--endpoint", "null", "--l4-clock", "model",
                                "--run-id", "rid", "--out", str(tmp_path / "runs"), "--resume",
                                "--tasks", "rich_2943"])
    with pytest.raises(RS.UsageError, match="l4_clock: 'wall' -> 'model'"):
        RS.Runner(a).prepare()
    (run_dir / "run.json").write_text(json.dumps({"suite": "L"}))              # pre-E1 run: wall
    with pytest.raises(RS.UsageError, match="l4_clock: 'wall' -> 'model'"):
        RS.Runner(a).prepare()


# ------------------------------------------------------------------------------------------------------------ E2
def _calls_case(calls, suite="L"):
    c = s_case(suite, "rich_1")
    c["golden"]["llm_calls"] = calls
    return GM.make_instance(c)


def _call(i, p, c, t_in, t_out, status=200, agent="locator", served="upstream"):
    return {"i": i, "agent": agent, "kind": "agent", "live": True, "served": served, "prompt_tokens": p,
            "completion_tokens": c, "t_in": t_in, "t_out": t_out, "http_status": status}


def test_l4_s_rule_on_synthetic_calls():
    calls = [_call(0, 5000, 100, 0.0, 9.0), _call(1, 5300, 50, 10.0, 15.0), _call(2, 0, 0, 15.5, 60.0, status=429),
             _call(3, 5500, 20, 61.0, 70.0)]
    r = GM.score_all(_calls_case(calls), ["l_l4_s"])["l_l4_s"]
    want = (0.102 + 0.02815 * 100 + 0.000921 * 5000) + (0.102 + 0.02815 * 50 + 0.000921 * 200) + \
        (0.102 + 0.02815 * 20 + 0.000921 * 150) + (1.0 + 0.5 + 1.0)
    assert r["score"] == pytest.approx(want, abs=2e-3)
    assert GM.explain(r)[0]
    assert not GM.explain(GM.score_all(_calls_case([]), ["l_l4_s"])["l_l4_s"])[0]            # no calls: n/a
    f = GM.score_all(_calls_case([_call(0, 100, 10, 0, 1, agent="fixer")], "F"), ["f_l4_s"])["f_l4_s"]
    assert f["score"] == pytest.approx(0.102 + 0.2815 + 0.0921, abs=1e-3)


@pytest.mark.skipif(not (L_V101 / "traces").is_dir() or not L4_REF.is_file(), reason="L_dev_v101 run not present")
def test_l4_s_reproduces_the_diag_numbers_on_L_dev_v101():
    ref = json.loads(L4_REF.read_text())
    seen = 0
    for fp in sorted((L_V101 / "traces").glob("*.json")):
        for case in json.loads(fp.read_text())["eval_cases"]:
            cid = case["golden"]["case_id"]
            if cid not in ref or case["golden"]["status"] not in GM.COUNTED_STATUS:
                continue
            failed = any(r.get("agent") == "locator" and r.get("served") == "upstream" and r.get("http_status") != 200
                         for r in case["golden"]["llm_calls"])
            got = GM.score_all(GM.make_instance(case), ["l_l4_s"])["l_l4_s"]["score"]
            if failed:          # l4time charged a failed call 0.102 s and a full re-prefill; E1 models it to 0
                assert got < ref[cid]["l4_total"]
            else:
                assert got == pytest.approx(ref[cid]["l4_total"], abs=0.5), cid
                seen += 1
    assert seen >= 20


# ------------------------------------------------------------------------------------------------------------ E3
def _plan_case(reply, gold=("rich/text.py", "rich/style.py")):
    c = s_case("L", "rich_1")
    c["golden"]["gold_files"] = list(gold)
    for e in c["agent_data"]["turns"][0]["events"]:
        for p in e["content"]["parts"]:
            if "text" in p and e["author"] == "locator":
                p["text"] = reply
    c["responses"][0]["response"]["parts"][0]["text"] = reply
    return GM.make_instance(c)


def _s(reply, name, **kw):
    return GM.score_all(_plan_case(reply, **kw), [name])[name]


def test_also_only_hit_counts_for_the_headline_not_the_files_line():
    reply = "FILES: rich/text.py:1-9 (split)\nALSO: rich/style.py\nCAUSE: c\nFIX: f\nREPRO: none\nTESTS: t"
    assert _s(reply, "l_all_gold_files_named")["score"] == 1.0
    assert _s(reply, "l_gold_files_in_files_line")["score"] == 0.0
    assert _s(reply, "l_files_named_n")["score"] == 2.0


def test_files_line_with_prose_before_it_and_several_lines():
    reply = "Here is the plan.\n\nFILES:\n- ./rich/text.py:1-9 (split)\n- /workspace/rich/style.py (Style)\n" \
            "ALSO: none\nCAUSE: c\nFIX: edit rich/text.py\nREPRO: none\nTESTS: tests/test_text.py"
    assert _s(reply, "l_gold_files_in_files_line")["score"] == 1.0
    assert _s(reply, "l_files_named_n")["score"] == 3.0          # text.py, style.py, tests/test_text.py (distinct)
    assert _s("FILES: none\nCAUSE: c", "l_gold_files_in_files_line")["score"] == 0.0
    assert _s("no plan words", "l_gold_files_in_files_line")["score"] == 0.0
    assert _s("FILES: rich/text.pyc", "l_files_named_n")["score"] == 0.0


def test_no_reply_is_inapplicable_for_files_named_n():
    assert not GM.explain(_s("", "l_files_named_n"))[0]
    assert GM.explain(_s("", "l_gold_files_in_files_line"))[0]           # a lost plan names no gold file: 0


def test_gen_config_is_in_sync():
    import gen_config
    assert gen_config.main(["--check"]) == 0


# ------------------------------------------------------------------------------------------------------------ E4
def _l_trace(task, reply, cmds=(), status="ok"):
    """An L trace case whose locator ran `cmds` [(command, stdout)] then replied `reply` ('' for none)."""
    c = s_case("L", task)
    ev = [e for e in c["agent_data"]["turns"][0]["events"] if e["author"] != "locator"]
    for cmd, out in cmds:
        ev.append({"author": "locator", "content": {"role": "model", "parts": [
            {"function_call": {"name": "run_command", "args": {"command": cmd}}}]}})
        ev.append({"author": "locator", "content": {"role": "user", "parts": [
            {"function_response": {"name": "run_command", "response": {"status": "ok", "stdout": out}}}]}})
    if reply:
        ev.append({"author": "locator", "content": {"role": "model", "parts": [{"text": reply}]}})
    c["agent_data"]["turns"][0]["events"] = ev
    c["responses"][0]["response"]["parts"][0]["text"] = reply
    c["golden"]["status"] = status
    return c


REPRO_CMD = "python3 /tmp/swe/verify.py --repro-only <<'EOF'\nfrom rich import x\nassert x() == 1\nEOF"


def _f_dataset(tmp_path, tasks, split="dev"):
    cases = []
    for t in tasks:
        c = s_case("F", t)
        g = {k: v for k, v in c["golden"].items() if k not in ("case_id", "sample", "status", "llm_calls", "run")}
        g.update(split=split, plan="FILES: gold", plan_source="template", repro=None)
        g.pop("fixture_sha")
        import fixture_lib as FL
        g["fixture_sha"] = FL.sha_obj(g)
        cases.append({"eval_case_id": "F__" + t, "golden": g})
    p = tmp_path / "F_dev.json"
    p.write_text(json.dumps({"eval_cases": cases}))
    return p


def _split(tmp_path, dev, hold=()):
    p = tmp_path / "split.json"
    p.write_text(json.dumps({"tasks": dict([(t, {"split": "dev"}) for t in dev]
                                           + [(t, {"split": "holdout"}) for t in hold])}))
    return p


def test_chain_carries_plans_and_failing_repros_only(tmp_path):
    traces = [_l_trace("rich_1", "FILES: rich/text.py\nREPRO: fails on original",
                       [(REPRO_CMD, "REPRO: fails on original (AssertionError)\n[t=40s]")]),
              _l_trace("rich_2", "FILES: rich/a.py", [(REPRO_CMD, "REPRO: passes on original\n[t=40s]")]),
              _l_trace("rich_3", ""),                                                   # lost reply
              _l_trace("rich_4", "x", status="infra_error")]
    lrun = write_run(tmp_path / "L", traces, run={"run_id": "Lx", "suite": "L", "split": "dev"})
    ds, rep = CP.build(Path(lrun), 0, _f_dataset(tmp_path, ["rich_1", "rich_2", "rich_3", "rich_4"]),
                       _split(tmp_path, ["rich_1", "rich_2", "rich_3", "rich_4"]))
    g = {c["golden"]["task"]: c["golden"] for c in ds["eval_cases"]}
    assert set(g) == {"rich_1", "rich_2", "rich_3"} and "rich_4" in rep["dropped"]
    assert g["rich_1"]["plan"].startswith("FILES: rich/text.py") and g["rich_1"]["repro"] == \
        "from rich import x\nassert x() == 1\n"
    assert g["rich_2"]["repro"] is None and g["rich_3"]["plan"] == "" and rep["lost_plans"] == 1
    assert g["rich_1"]["plan_source"] == "chain:Lx:s0" and g["rich_1"]["plan_basis"] == "chain"
    import fixture_lib as FL
    for x in g.values():
        y = dict(x)
        sha = y.pop("fixture_sha")
        assert sha == FL.sha_obj(y)


def test_chain_refuses_holdout(tmp_path):
    traces = [_l_trace("rich_1", "FILES: a.py")]
    lrun = write_run(tmp_path / "L", traces, run={"run_id": "Lh", "suite": "L", "split": "holdout"})
    with pytest.raises(CP.Refused, match="holdout"):
        CP.build(Path(lrun), 0, _f_dataset(tmp_path, ["rich_1"]), _split(tmp_path, ["rich_1"]))
    lrun = write_run(tmp_path / "L2", traces, run={"run_id": "Ld", "suite": "L", "split": "dev"})
    with pytest.raises(CP.Refused, match="holdout"):
        CP.build(Path(lrun), 0, _f_dataset(tmp_path, ["rich_1"]), _split(tmp_path, [], ["rich_1"]))
    with pytest.raises(CP.Refused, match="holdout"):
        CP.build(Path(lrun), 0, _f_dataset(tmp_path, ["rich_1"], split="holdout"), _split(tmp_path, ["rich_1"]))


def test_heredoc_body():
    assert CP.heredoc_body(REPRO_CMD) == "from rich import x\nassert x() == 1\n"
    assert CP.heredoc_body('python3 /tmp/swe/verify.py --repro-only << "PY"\na=1\nPY\n') == "a=1\n"
    assert CP.heredoc_body("python3 /tmp/swe/verify.py --repro-only") is None


@pytest.mark.skipif(not (L_V101 / "traces").is_dir(), reason="L_dev_v101 run not present")
def test_chain_round_trip_on_L_dev_v101():
    ds, rep = CP.build(L_V101, 0)
    assert rep["cases"] == 27 and rep["repros"] >= 1
    for c in ds["eval_cases"]:
        assert c["golden"]["suite"] == "F" and c["golden"]["split"] == "dev"


def test_compare_pair_by_task_keeps_differing_fixtures(tmp_path):
    base = write_run(tmp_path / "b", [s_case("F", "rich_%d" % i, fixture_sha="a%d" % i, passed=i < 2)
                                      for i in range(4)], run={"suite": "F", "split": "dev", "label": "PROXY"})
    cand = write_run(tmp_path / "c", [s_case("F", "rich_%d" % i, fixture_sha="b%d" % i, passed=i < 3)
                                      for i in range(4)], run={"suite": "F", "split": "dev", "label": "PROXY"})
    _, R = SM.compare(base, cand)
    assert R["paired_cases"] == 0 and len(R["fixture_changed_dropped"]) == 4      # without the flag: dropped
    _, R = SM.compare(base, cand, pair_by_task=True)
    assert R["paired_cases"] == 4 and R["pairing"].startswith("CHAIN")
    assert R["fixture_shas"]["F__rich_0"] == [["a0"], ["b0"]]
    assert R["metrics"]["f_hidden_pass"]["mean_diff"] == 0.25
    md = SM.compare_md(R)
    assert "(CHAIN)" in md and "F__rich_2: a2 / b2" in md


# ------------------------------------------------------------------------------------------------------------ E7
def _cmp(**metrics):
    base = {"x_crash": (0, 0)}
    base.update({x: (0, 0) for x in VG.G5_METRICS})
    out = {}
    for k, v in list(base.items()) + list(metrics.items()):
        if isinstance(v, tuple):
            out[k] = {"base_total": v[0], "cand_total": v[1], "n": 30, "mean_diff": (v[1] - v[0]) / 30.0}
        else:
            out[k] = dict({"n": 30}, **v)
    return {"metrics": out}


def _info(name, clock="model", spent=0.5, crashes=None, **run):
    r = {"run_id": name, "suite": "L", "split": "dev", "endpoint": "openrouter", "upstream_model": "g",
         "or_provider": "crusoe/bf16", "upstream_extra": {}, "seed_mode": "off", "samples": 2, "l4_scale": 1.0,
         "l4_clock": clock, "dataset_sha": "d", "task_filter": ["t%d" % i for i in range(30)], "agent_env": "kpar",
         "faithful_env": False, "harness_verify": False, "budgets": {"max_tool_calls": 100}}
    r.update(run)
    return {"dir": "/runs/" + name, "run": r, "spent_usd": spent, "crash_classes": dict(crashes or {}),
            "statuses": {"ok": 60}}


def _inp(L=None, F=None, chain=None, **kw):
    L = L or _cmp(l_all_gold_files_named={"mean_diff": 0.10}, l_files_named_n={"mean_diff": 1.0},
                  l_repro_valid={"mean_diff": -0.1, "n": 30})
    F = F or _cmp(f_hidden_pass={"mean_diff": -0.05})
    inp = {"L": {"compare": L, "why": [], "base": _info("L101"), "cand": _info("L102")},
           "F": {"compare": F, "why": [], "base": _info("F101", suite="F"), "cand": _info("F102", suite="F")},
           "chain": None, "canaries": [], "extra": [], "holdout_lines": 0, "holdout_baseline": 0,
           "preconditions_skipped": []}
    if chain is not None:
        inp["chain"] = {"compare": chain, "why": [], "base": _info("C101", suite="F", dataset_sha="x"),
                        "cand": _info("C102", suite="F", dataset_sha="y")}
    inp.update(kw)
    return inp


def test_gate_edges_pass_exactly_at_the_thresholds():
    G = VG.decide(_inp())
    assert G["verdict"] == "SHIP-TO-POD" and not G["failing_gates"] and G["gates"]["G6"]["detail"]["diff_x_n"] == -3.0
    assert G["chain"] == {"ran": False}


@pytest.mark.parametrize("which,L,F,fail", [
    ("G1", {"l_all_gold_files_named": {"mean_diff": 0.0999}}, None, "G1"),
    ("G2", None, {"f_hidden_pass": {"mean_diff": -0.0501}}, "G2"),
    ("G4", {"l_files_named_n": {"mean_diff": 1.01}}, None, "G4"),
    ("G6", {"l_repro_valid": {"mean_diff": -0.1034, "n": 30}}, None, "G6"),
])
def test_gate_edges_fail_just_past_the_thresholds(which, L, F, fail):
    Lc = _cmp(**dict({"l_all_gold_files_named": {"mean_diff": 0.2}, "l_files_named_n": {"mean_diff": 0.5},
                      "l_repro_valid": {"mean_diff": 0.0, "n": 30}}, **(L or {})))
    Fc = _cmp(**dict({"f_hidden_pass": {"mean_diff": 0.0}}, **(F or {})))
    G = VG.decide(_inp(Lc, Fc))
    assert G["verdict"] == "NOT READY" and G["failing_gates"] == [fail]


def test_gate_g5_allows_one_extra_x_event_not_two():
    ok = VG.decide(_inp(F=_cmp(f_hidden_pass={"mean_diff": 0.0}, x_invented_tool_calls=(2, 3))))
    assert ok["gates"]["G5"]["pass"]
    bad = VG.decide(_inp(F=_cmp(f_hidden_pass={"mean_diff": 0.0}, x_runaway_outputs=(2, 4))))
    assert bad["failing_gates"] == ["G5"] and bad["gates"]["G5"]["detail"]["over"] == {"F": {"x_runaway_outputs": [2, 4]}}


def test_gate_g3_new_crash_class_and_higher_crash_total():
    inp = _inp(canaries=[_info("can", crashes={"context_overflow": 1})])
    G = VG.decide(inp)
    assert G["failing_gates"] == ["G3"] and G["gates"]["G3"]["detail"]["new_crash_classes"] == ["context_overflow"]
    inp = _inp(canaries=[_info("can", crashes={"context_overflow": 1})])
    inp["L"]["base"]["crash_classes"] = {"context_overflow": 2}
    assert VG.decide(inp)["gates"]["G3"]["pass"]                 # v10.1 shows the class too
    inp = _inp(F=_cmp(f_hidden_pass={"mean_diff": 0.0}, x_crash=(1, 2)))
    assert VG.decide(inp)["failing_gates"] == ["G3"]


def test_gate_chain_veto_and_missing_chain():
    veto = _cmp(f_hidden_pass={"mean_diff": -0.10})
    G = VG.decide(_inp(chain=veto))
    assert G["verdict"] == "NOT READY" and G["chain_veto"] and not G["failing_gates"]
    G = VG.decide(_inp(chain=_cmp(f_hidden_pass={"mean_diff": -0.0999})))
    assert G["verdict"] == "SHIP-TO-POD" and G["chain"]["ran"]
    G = VG.decide(_inp(chain_skipped_reason="budget"))
    assert G["verdict"] == "SHIP-TO-POD" and G["chain"] == {"ran": False, "not_run": "budget"}


def test_gate_instrument_problems_make_it_inconclusive():
    G = VG.decide(_inp(canaries=[_info("can", spent=0.02)], extra=[_info("x", spent=2.0)]))
    assert G["verdict"] == "INCONCLUSIVE (instrument)" and G["spend_usd"] == pytest.approx(4.02)
    inp = _inp()
    inp["L"]["why"] = ["candidate run has 4 of 60 infra_error cases (> 5 %): the comparison is invalid"]
    assert VG.decide(inp)["verdict"] == "INCONCLUSIVE (instrument)"
    inp = _inp(L=_cmp(l_all_gold_files_named={"mean_diff": 0.5, "n": 26}, l_files_named_n={"mean_diff": 0.0},
                      l_repro_valid={"mean_diff": 0.0, "n": 26}))
    G = VG.decide(inp)
    assert G["verdict"] == "INCONCLUSIVE (instrument)" and G["dropped"]["L"] == 4
    inp["L"]["compare"]["metrics"]["l_all_gold_files_named"]["n"] = 27
    assert VG.decide(inp)["verdict"] == "SHIP-TO-POD"             # 3 dropped is allowed
    inp = _inp()
    inp["F"]["cand"]["run"]["samples"] = 1
    assert "differ in more than the bundle" in VG.decide(inp)["inconclusive_reasons"][0]
    inp = _inp()
    inp["L"]["base"]["run"]["l4_clock"] = "wall"
    inp["L"]["cand"]["run"]["l4_clock"] = "wall"
    assert any("P2" in r for r in VG.decide(inp)["inconclusive_reasons"])
    assert VG.decide(_inp(holdout_lines=1))["verdict"] == "INCONCLUSIVE (instrument)"
    assert VG.decide(_inp(preconditions_skipped=["P3"]))["verdict"] == "INCONCLUSIVE (instrument)"
    ch = _inp(chain=_cmp(f_hidden_pass={"mean_diff": 0.0}))
    assert VG.decide(ch)["verdict"] == "SHIP-TO-POD"             # chain datasets differ by design


def test_gate_md_names_the_verdict():
    G = VG.decide(_inp(L=_cmp(l_all_gold_files_named={"mean_diff": 0.0}, l_files_named_n={"mean_diff": 0.0},
                              l_repro_valid={"mean_diff": 0.0, "n": 30})))
    md = VG.gate_md(G)
    assert "**NOT READY**" in md and "| G1 | FAIL |" in md
