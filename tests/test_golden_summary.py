"""Golden-eval summary and paired comparison (docs/eval/GOLDEN_EVALS_SPEC.md v1.1 sections 8, 12c).

Known values of the statistics (Wilson, exact sign test, bootstrap), the summary over synthetic run directories in
the trace and flat schemas of spec 6.2-6.3 (single and multiple samples, status exclusion, population sentence,
metric errors), the agents-cli score check through the merged-dataset index (gotcha 5), the compare refusals and
verdicts, and one real agents-cli grade of a synthetic trace set with the generated configs (skipped when
/Users/carson/.local/bin/agents-cli is absent; gotchas 3, 4, 5). No network, no model, no GPU.
"""
import ast
import copy
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "eval" / "golden", ROOT / "scripts" / "golden", ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import golden_metrics as GM  # noqa: E402
import summary as SM  # noqa: E402
import ab_l4_decide  # noqa: E402

AGENTS_CLI = "/Users/carson/.local/bin/agents-cli"
AGENT = {"L": "locator", "F": "fixer", "V": "verifier"}


# ---------------------------------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------------------------------
def _eval_compare_wilson():
    """eval/compare.py runs its CLI at import, so take only its wilson() source."""
    src = (ROOT / "eval" / "compare.py").read_text()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "wilson")
    ns = {"math": math}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "compare.py", "exec"), ns)
    return ns["wilson"]


def test_wilson_known_values_and_eval_compare_formula():
    lo, hi = SM.wilson(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = SM.wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-12) and round(hi, 4) == 0.2775
    lo, hi = SM.wilson(10, 10)
    assert round(lo, 4) == 0.7225 and hi == pytest.approx(1.0, abs=1e-12)
    assert SM.wilson(0, 0) == (0, 0)
    ref = _eval_compare_wilson()
    for n in (1, 2, 7, 29, 74):
        for k in range(n + 1):
            assert SM.wilson(k, n) == ref(k, n), (k, n)


def test_sign_test_known_values_and_ab_l4_decide_formula():
    assert SM.sign_p(6, 5) == 0.5
    assert round(SM.sign_p(8, 0), 4) == 0.0039 and SM.sign_p(8, 0) == 1 / 256
    assert SM.sign_p(0, 0) == 1.0 and SM.sign_p(0, 8) == 1.0
    assert SM.sign_two_sided(8, 0) == SM.sign_two_sided(0, 8) == 2 / 256
    assert SM.sign_two_sided(6, 5) == 1.0 and SM.sign_two_sided(3, 3) == 1.0      # capped at 1
    assert SM.sign_two_sided(0, 0) == 1.0
    assert round(SM.sign_p(5, 0), 3) == 0.031 and round(SM.sign_p(8, 1), 3) == 0.020   # spec 9 power line
    for w in range(12):
        for l in range(12):
            assert SM.sign_p(w, l) == ab_l4_decide.sign_p(w, l)


def test_quantile_and_bootstrap_are_deterministic():
    assert SM.quantile([], 0.5) == 0.0 and SM.quantile([3, 1, 2], 0.5) == 2
    assert SM.quantile([0, 10], 0.9) == pytest.approx(9.0) and SM.quantile([5], 0.9) == 5
    vals = [0, 1, 1, 0, 1, 0.5, 1, 1]
    a, b = SM.bootstrap_ci(vals), SM.bootstrap_ci(list(vals))
    assert a == b and a[0] < sum(vals) / len(vals) < a[1]
    assert SM.bootstrap_ci([]) == (0.0, 0.0) and SM.bootstrap_ci([1, 1, 1]) == (1.0, 1.0)
    assert SM.bootstrap_ci(vals, seed=1) != a                                          # the seed matters
    assert SM.BOOT_SEED == 20260929 and SM.BOOT_REPS == 2000


# ---------------------------------------------------------------------------------------------------------------------
# Synthetic runs in the spec 6.2 / 6.3 schemas
# ---------------------------------------------------------------------------------------------------------------------
def case(suite, task, sample=0, variant="-", status="ok", passed=True, repo=None, stratum=None, runnable=True,
         gradable=True, reproducible=False, fixture_sha="fx1", label="PROXY", split="dev", x_bad=False, why=""):
    agent = AGENT[suite]
    repo = repo or task.split("_")[0]
    dcid = "%s__%s" % (suite, task) + ("__%s" % variant if suite == "V" else "")
    cid = "%s__s%d" % (dcid, sample)
    if suite == "L":
        reply = "FILES: rich/text.py:1-2 (split)\nCAUSE: c\nFIX: f\nREPRO: none\nTESTS: none" if passed else "no idea"
    else:
        reply = "CHANGED: rich/text.py split (1-2)\nVERIFY: GREEN"
    live = [{"author": agent, "content": {"role": "model", "parts": [{"function_call": {
        "name": "locate" if x_bad else "run_command", "args": {"command": "python3 /tmp/swe/view.py a.py 1 2"}}}]}},
        {"author": agent, "content": {"role": "user", "parts": [{"function_response": {
            "name": "run_command", "response": {"status": "ok", "stdout": "x\n[t=60s]\n"}}}]}},
        {"author": agent, "content": {"role": "model", "parts": [{"text": reply}]}}]
    events = [{"author": "user", "content": {"role": "user", "parts": [{"text": "task"}]}},
              {"author": "setup", "content": {"role": "model", "parts": [{"text": "READY"}]}}] + live
    ec = None
    if status in ("ok", "model_error") and runnable:
        ec = {"patch_files": [["rich/text.py", False]] if passed or suite != "V" else [], "applies": True,
              "compiles": True, "hidden_pass": bool(passed), "hidden_nodes_total": 2, "hidden_nodes_pass": 2 if passed
              else 0, "pre_hidden_nodes_pass": 0, "repro_text": None, "repro_fails_orig": None,
              "repro_passes_gold": None}
    golden = {"schema": "golden-case-v1", "suite": suite, "task": task, "variant": variant, "split": split,
              "repo": repo, "stratum": stratum or "%s/none" % repo, "runnable": runnable, "runnable_why": why,
              "gradable": gradable, "gradable_why": "", "fixture_sha": fixture_sha, "reproducible": reproducible,
              "gold_files": ["rich/text.py"], "gold_functions": [{"name": "split"}], "pre_hidden_nodes_pass": 0,
              "case_id": cid, "dataset_case_id": dcid, "sample": sample, "live_agents": [agent], "status": status,
              "status_detail": "", "crash_class": "unknown_tool" if status == "model_error" else None,
              "final_patch": "", "run": {"run_id": "r", "endpoint": "openrouter", "label": label,
                                         "upstream_model": "google/gemma-4-31b-it", "bundle_sha": "b" * 64,
                                         "max_output_tokens": {agent: 2048}},
              "llm_calls": [{"i": 0, "t_in": 0.0, "agent": agent, "kind": "agent", "live": True, "stage_run": 0,
                             "served": "upstream", "prompt_tokens": 3000, "completion_tokens": 40,
                             "finish_reason": "stop", "latency_s": 2.0, "cost_usd": 0.0003}],
              "exec_checks": ec, "writer_warnings": []}
    return {"eval_case_id": cid, "responses": [{"response": {"role": "model", "parts": [{"text": reply}]}}],
            "reference": {"response": {"role": "model", "parts": [{"text": "gold"}]}},
            "agent_data": {"agents": {agent: {"agent_id": agent, "agent_type": "LlmAgent"}},
                           "turns": [{"turn_index": 0, "events": events}]},
            "golden": golden}


def write_run(d, cases, run=None, files=("a_part.json",), grade=None):
    d = Path(d)
    (d / "traces").mkdir(parents=True, exist_ok=True)
    (d / "cases").mkdir(exist_ok=True)
    k = len(files)
    for j, fn in enumerate(files):
        part = [c for i, c in enumerate(cases) if i % k == j]
        (d / "traces" / fn).write_text(json.dumps({"eval_cases": part}))
    for c in cases:
        g = c["golden"]
        flat = {"case_id": g["case_id"], "dataset_case_id": g["dataset_case_id"], "suite": g["suite"],
                "task": g["task"], "variant": g["variant"], "sample": g["sample"], "split": g["split"],
                "status": g["status"], "status_detail": "", "label": g["run"]["label"], "providers": ["Prov"],
                "bundle_sha": g["run"]["bundle_sha"], "fixture_sha": g["fixture_sha"],
                "live": {"agent": AGENT[g["suite"]], "cost_usd": 0.001}, "exec_checks": g["exec_checks"]}
        (d / "cases" / (g["case_id"] + ".json")).write_text(json.dumps(flat))
    if run is not None:
        (d / "run.json").write_text(json.dumps(run))
    return str(d)


def f_run(tmp, name, results, label="PROXY", split="dev", extra=(), **kw):
    """An F run: results = {task: passed}; extra = more cases."""
    cases = [case("F", t, passed=p, label=label, split=split, **kw) for t, p in sorted(results.items())] + list(extra)
    return write_run(tmp / name, cases, run={"run_id": name, "suite": "F", "split": split, "label": label,
                                             "upstream_model": "google/gemma-4-31b-it", "bundle_sha": "b" * 64,
                                             "spent_usd": 0.0123, "wall_s": 321.0, "providers_seen": ["Prov"],
                                             "samples": 1})


def test_summary_single_sample(tmp_path):
    res = {"rich_%d" % i: i < 5 for i in range(10)}
    extra = [case("F", "rich_90", status="infra_error"),
             case("F", "fastapi_1", status="skipped", runnable=False, gradable=None, why="snapshot missing"),
             case("F", "fastapi_2", status="skipped", runnable=False, gradable=None, why="snapshot missing"),
             case("F", "requests_1", passed=False, gradable=False)]
    d = f_run(tmp_path, "F_dev_a", res, extra=extra)
    log = tmp_path / "holdout_log.jsonl"
    log.write_text(json.dumps({"suite": "F", "bundle_sha": "b" * 64}) + "\n" + json.dumps({"suite": "L"}) + "\n")
    assert SM.main([d, "--holdout-log", str(log), "--no-l4-ref"]) == 0
    s = json.loads(Path(d, "summary.json").read_text())
    h, m = s["header"], s["metrics"]["f_hidden_pass"]
    assert (m["n"], m["k"], m["mean"]) == (10, 5, 0.5) and m["wilson"] == [0.2366, 0.7634]
    assert "bootstrap" not in m
    assert h["population"] == ("F dev: 11 gradable of 12 runnable of 14 tasks (rich 11); fastapi 0 of 2 runnable: "
                               "snapshot missing")
    assert h["cases"] == {"total": 14, "ok": 11, "infra_error": 1, "skipped": 2}
    assert h["infra_error_share"] == round(1 / 12, 4) and h["samples"] == 1
    assert (h["label"], h["model"], h["providers"], h["cost_usd"], h["wall_s"]) == (
        "PROXY", "google/gemma-4-31b-it", ["Prov"], 0.0123, 321.0)
    assert h["holdout_looks"]["suite"] == 1 and h["holdout_looks"]["suite_and_bundle"] == 1
    assert h["mean_live_latency_s"] == 2.0 and h["l4_reference_latency"] is None
    assert s["metrics"]["x_clean"]["n"] == 11            # X covers the non-gradable case too; infra/skipped never
    assert s["metrics"]["f_calls"]["median"] == 1 and s["metrics"]["f_calls"]["total"] == 10   # F: gradable only
    assert s["slices"]["repo"]["rich"]["f_hidden_pass"]["n"] == 10
    assert s["agents_cli_check"] is None and s["n_metric_errors"] == 0
    md = Path(d, "summary.md").read_text()
    assert "**PROXY**" in md and "f_hidden_pass | 10 | 0.500 | [0.237, 0.763]" in md and "Known deviations" in md
    assert SM.DECISION_RULE in md and "Holdout looks: 1 for suite F" in md


def test_summary_l_and_v_slices_and_population(tmp_path):
    cases = [case("L", "rich_1", reproducible=True), case("L", "rich_2", passed=False, reproducible=False),
             case("L", "fastapi_1", status="skipped", runnable=False, why="kpar venv missing")]
    d = write_run(tmp_path / "L", cases)
    S = SM.summarize(d, holdout_log=None, l4_ref=False)
    assert S["header"]["population"] == ("L dev: 2 runnable of 3 tasks (rich 2); fastapi 0 of 1 runnable: kpar venv "
                                         "missing")
    assert set(S["slices"]) == {"repo", "stratum", "reproducible"}
    assert S["slices"]["reproducible"]["True"]["l_plan_format"]["mean"] == 1.0
    assert S["slices"]["reproducible"]["False"]["l_plan_format"]["mean"] == 0.0
    assert S["headlines"] == ["l_all_gold_files_named", "x_clean"]
    vc = [case("V", "rich_1", variant="gold"), case("V", "rich_1", variant="empty", passed=False),
          case("V", "rich_1", variant="wrong", passed=False)]
    d = write_run(tmp_path / "V", vc)
    S = SM.summarize(d, holdout_log=None, l4_ref=False)
    assert S["header"]["population"].endswith("; cases gold 1, wrong 1, empty 1")
    assert S["slices"]["variant"]["gold"]["v_variant_goal"]["mean"] == 1.0
    assert S["slices"]["variant"]["empty"]["v_variant_goal"]["mean"] == 0.0
    assert S["metrics"]["v_variant_goal"]["n"] == 3


def test_population_names_a_task_or_variant_subset(tmp_path):
    """Regression (integration smoke 2026-09-30): a `run_suite.py --tasks` run printed 'F dev: 2 gradable of 2
    runnable of 2 tasks (rich 2)', which reads as the dev population. The filter from run.json is now named."""
    run = {"run_id": "s", "suite": "F", "split": "dev", "label": "CONTROL", "task_filter": ["rich_1", "rich_2"],
           "variant_filter": None, "dataset_tasks": 55}
    d = write_run(tmp_path / "F", [case("F", "rich_1"), case("F", "rich_2", passed=False)], run=run)
    pop = SM.summarize(d, holdout_log=None, l4_ref=False)["header"]["population"]
    assert pop == ("F dev: 2 gradable of 2 runnable of 2 tasks (rich 2); SUBSET: 2 of 55 dataset tasks selected with "
                   "--tasks, not a population rate")
    vc = [case("V", "rich_1", variant="gold"), case("V", "rich_1", variant="wrong", passed=False)]
    d = write_run(tmp_path / "V", vc, run={"run_id": "v", "suite": "V", "split": "dev", "label": "CONTROL",
                                           "task_filter": None, "variant_filter": ["gold", "wrong"],
                                           "dataset_tasks": 1})
    pop = SM.summarize(d, holdout_log=None, l4_ref=False)["header"]["population"]
    assert pop.endswith("; cases gold 1, wrong 1, empty 0; SUBSET: variants gold, wrong only (--variants)")
    # an unfiltered run (and a run.json written before the filter was recorded) keeps the plain sentence
    for extra in ({"task_filter": None, "variant_filter": None, "dataset_tasks": 1}, {}):
        d = write_run(tmp_path / ("P%d" % len(extra)), [case("F", "rich_1")],
                      run=dict({"run_id": "p", "suite": "F", "split": "dev", "label": "CONTROL"}, **extra))
        assert SM.summarize(d, holdout_log=None, l4_ref=False)["header"]["population"] == \
            "F dev: 1 gradable of 1 runnable of 1 tasks (rich 1)"


def test_summary_aggregates_samples_per_case(tmp_path):
    cases = []
    for t, passes in (("rich_1", (1, 1, 0)), ("rich_2", (0, 0, 0)), ("rich_3", (1, 1, 1))):
        cases += [case("F", t, sample=k, passed=bool(p)) for k, p in enumerate(passes)]
    d = write_run(tmp_path / "F3", cases, files=("z.json", "a.json"))
    S = SM.summarize(d, holdout_log=None, l4_ref=False)
    m = S["metrics"]["f_hidden_pass"]
    assert (m["n"], m["n_samples"]) == (3, 9) and m["mean"] == round((2 / 3 + 0 + 1) / 3, 4)
    assert "wilson" not in m and m["bootstrap"][0] < m["mean"] < m["bootstrap"][1]
    assert m["bootstrap"] == [SM._r(x) for x in SM.bootstrap_ci([2 / 3, 0.0, 1.0])]
    assert S["header"]["samples"] == 3


def test_summary_reports_metric_errors(tmp_path, monkeypatch):
    d = f_run(tmp_path, "err", {"rich_1": True})
    monkeypatch.setattr(GM, "m_f_applies", lambda instance, _c=None: {}["boom"])
    assert SM.main([d, "--holdout-log", str(tmp_path / "none"), "--no-l4-ref"]) == 3
    s = json.loads(Path(d, "summary.json").read_text())
    assert s["n_metric_errors"] == 1 and s["metric_errors"][0]["metric"] == "f_applies"
    assert s["metrics"]["f_applies"]["n"] == 0            # an errored case is never counted as a score


def _fake_results(run_dir, order, tamper=None, missing=None):
    """A grade/results_*.json as agents-cli 1.7.0 writes it: evaluation_dataset[0].eval_cases in merge order and one
    eval_case_results entry per index."""
    R = SM.load_run(run_dir)
    by = {r["eval_case_id"]: r for r in R["records"] if r["instance"] is not None}
    ids = [i for i in order if i in by] + ([missing] if missing else [])
    results = []
    for idx, eid in enumerate(ids):
        mr = {}
        for n in GM.metric_names("F"):
            sc = GM._score(n, by[eid]["instance"])["score"] if eid in by else 0.0
            if tamper == (eid, n):
                sc = 1.0 - sc
            mr[n] = {"metric_name": n, "score": sc, "explanation": "", "error_message": None}
        results.append({"eval_case_index": idx, "response_candidate_results": [{"response_index": 0,
                                                                                "metric_results": mr}]})
    out = {"eval_case_results": results, "evaluation_dataset": [{"eval_cases": [{"eval_case_id": i} for i in ids]}]}
    os.makedirs(os.path.join(run_dir, "grade"), exist_ok=True)
    Path(run_dir, "grade", "results_20260929_120000.json").write_text(json.dumps(out))


def test_agents_cli_check_maps_merged_index(tmp_path):
    """Gotcha 5: agents-cli merges trace files in glob (directory) order, not by file name. The check maps each
    eval_case_index through the results file's own evaluation_dataset, so any merge order matches."""
    d = f_run(tmp_path, "m", {"rich_%d" % i: i % 2 == 0 for i in range(6)})
    names = sorted(r["eval_case_id"] for r in SM.load_run(d)["records"])
    _fake_results(d, list(reversed(names)))              # a merge order unlike the file-name order
    assert SM.main([d, "--holdout-log", str(tmp_path / "x"), "--no-l4-ref"]) == 0
    chk = json.loads(Path(d, "summary.json").read_text())["agents_cli_check"]
    assert chk["compared"] == 6 * len(GM.metric_names("F")) and chk["n_mismatches"] == 0
    # position-based mapping in file order would mismatch: prove the reversed order is not an identity
    assert names != list(reversed(names))
    _fake_results(d, list(reversed(names)), tamper=(names[0], "f_hidden_pass"))
    assert SM.main([d, "--holdout-log", str(tmp_path / "x"), "--no-l4-ref"]) == 4
    chk = json.loads(Path(d, "summary.json").read_text())["agents_cli_check"]
    assert chk["n_mismatches"] == 1 and chk["mismatches"][0]["eval_case_id"] == names[0]
    _fake_results(d, names, missing="F__ghost__s0")
    assert SM.main([d, "--holdout-log", str(tmp_path / "x"), "--no-l4-ref"]) == 4
    chk = json.loads(Path(d, "summary.json").read_text())["agents_cli_check"]
    assert {m["why"] for m in chk["mismatches"] if "why" in m} == {"case not in traces"}


# ---------------------------------------------------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------------------------------------------------
def test_compare_wins_verdict_and_decision_rule(tmp_path):
    tasks = ["rich_%d" % i for i in range(10)]
    base = f_run(tmp_path, "base", {t: False for t in tasks[:8]} | {t: True for t in tasks[8:]})
    cand = f_run(tmp_path, "cand", {t: True for t in tasks})
    assert SM.main(["compare", base, cand]) == 0
    C = json.loads(Path(cand, "compare.json").read_text())
    h = C["metrics"]["f_hidden_pass"]
    assert (h["n"], h["wins"], h["losses"], h["ties"]) == (10, 8, 0, 2)
    assert h["p_one_sided"] == round(1 / 256, 6) and h["p_two_sided"] == round(2 / 256, 6) and h["verdict"] == "better"
    assert h["mean_diff"] == 0.8 and "mean_diff_bootstrap" not in h
    rule = C["decision_rule"]
    assert rule["headline"] == "f_hidden_pass" and rule["headline_ok"] and rule["eligible_on_this_suite"]
    assert rule["x_count_totals_not_higher"] and rule["dev_split"]
    md = Path(cand, "compare.md").read_text()
    assert "ELIGIBLE on this suite" in md
    assert h["transitions"]["counts"] == {"1->1": 2, "0->1": 8, "1->0": 0, "0->0": 0}
    assert "| 1 | 2 | 0 |\n| 0 | 8 | 0 |" in md and "0 -> 1 (8): F__rich_0, F__rich_1," in md and "1 -> 0 (0): none" in md
    # reversed: worse; an X count metric going up blocks the rule even with a better headline
    _, R = SM.compare(cand, base)
    assert R["metrics"]["f_hidden_pass"]["verdict"] == "worse" and not R["decision_rule"]["eligible_on_this_suite"]
    bad = f_run(tmp_path, "bad", {t: True for t in tasks}, x_bad=True)
    _, R = SM.compare(base, bad)
    assert R["metrics"]["x_invented_tool_calls"]["verdict"] == "worse"
    assert R["decision_rule"]["headline_ok"] and R["decision_rule"]["x_count_metrics_higher"] == [
        "x_invented_tool_calls", "x_bare_helper_calls"]
    assert not R["decision_rule"]["eligible_on_this_suite"]


def test_compare_drops_ties_and_needs_net_wins(tmp_path):
    tasks = ["rich_%02d" % i for i in range(14)]
    b = {t: (i >= 6 and i < 11) for i, t in enumerate(tasks)}        # base wins 5 (6..10)
    c = {t: (i < 6) for i, t in enumerate(tasks)}                    # cand wins 6 (0..5); 11..13 tie at 0
    _, R = SM.compare(f_run(tmp_path, "b", b), f_run(tmp_path, "c", c))
    h = R["metrics"]["f_hidden_pass"]
    assert (h["wins"], h["losses"], h["ties"], h["p_one_sided"], h["p_two_sided"]) == (6, 5, 3, 0.5, 1.0)
    assert h["verdict"] == "no evidence" and not R["decision_rule"]["headline_ok"]


def test_compare_refusals(tmp_path):
    res = {"rich_%02d" % i: True for i in range(20)}
    base = f_run(tmp_path, "base", res)
    other_split = f_run(tmp_path, "hold", res, split="holdout")
    other_label = f_run(tmp_path, "ctl", res, label="CONTROL")
    lcase = write_run(tmp_path / "L", [case("L", t) for t in res], run={"suite": "L", "split": "dev", "label": "PROXY"})
    assert any("suites differ" in w for w in SM.compare(base, lcase)[0])
    assert any("splits differ" in w for w in SM.compare(base, other_split)[0])
    assert any("labels differ" in w for w in SM.compare(base, other_label)[0])
    assert SM.compare(base, other_label, allow_mixed=True)[0] == []
    assert SM.main(["compare", base, other_label]) == 2 and not Path(other_label, "compare.json").exists()
    assert SM.main(["compare", base, other_label, "--allow-mixed"]) == 0
    assert json.loads(Path(other_label, "compare.json").read_text())["mixed_labels"] is True
    one = f_run(tmp_path, "infra1", {t: True for t in list(res)[:19]}, extra=[case("F", "rich_99", status="infra_error")])
    assert SM.compare(base, one)[0] == []                                   # 1 of 20 = 5 %: allowed
    two = f_run(tmp_path, "infra2", {t: True for t in list(res)[:18]},
                extra=[case("F", "rich_98", status="infra_error"), case("F", "rich_99", status="infra_error")])
    why = SM.compare(base, two)[0]
    assert len(why) == 1 and "2 of 20 infra_error" in why[0]
    assert SM.main(["compare", two, base]) == 2


def test_compare_drops_changed_fixtures_and_bootstraps_samples(tmp_path):
    base_cases, cand_cases = [], []
    for i in range(4):
        t = "rich_%d" % i
        for k in range(3):
            base_cases.append(case("F", t, sample=k, passed=k == 0))
            cand_cases.append(case("F", t, sample=k, passed=k < 2, fixture_sha="fx2" if i == 3 else "fx1"))
    base = write_run(tmp_path / "b", base_cases, run={"suite": "F", "split": "dev", "label": "PROXY"})
    cand = write_run(tmp_path / "c", cand_cases, run={"suite": "F", "split": "dev", "label": "PROXY"})
    _, R = SM.compare(base, cand)
    assert R["fixture_changed_dropped"] == ["F__rich_3"] and R["paired_cases"] == 3 and R["samples_gt_1"]
    h = R["metrics"]["f_hidden_pass"]
    assert (h["n"], h["wins"], h["losses"]) == (3, 3, 0) and h["mean_diff"] == round(1 / 3, 4)
    assert h["mean_diff_bootstrap"] == [round(1 / 3, 4), round(1 / 3, 4)]
    assert h["transitions"] is None                        # per-case means of 3 samples are not 0/1
    assert "Transition table for f_hidden_pass: not shown" in SM.compare_md(R)


def test_compare_transition_table(tmp_path):
    """The 2x2 table a paired binary comparison is read by (docs/eval/ABLATION_REPAIR.md reads A0 -> B2 and A0 -> A0'):
    0->1 = a new solve, 1->0 = a damaged patch, and the diagonal that wins/losses/ties lump together as ties."""
    tasks = ["rich_%02d" % i for i in range(12)]
    base = {t: i < 5 for i, t in enumerate(tasks)}                        # 00..04 pass
    cand = {t: i < 4 or 5 <= i < 9 for i, t in enumerate(tasks)}          # 04 damaged, 05..08 new, 09..11 still fail
    b = f_run(tmp_path, "a0", base, extra=[case("F", "rich_20", status="model_error", passed=False)])
    c = f_run(tmp_path, "b2", cand, extra=[case("F", "rich_20", passed=False)])
    why, C = SM.compare(b, c)
    assert why == []
    h = C["metrics"]["f_hidden_pass"]
    tr = h["transitions"]
    assert tr["counts"] == {"1->1": 4, "0->1": 4, "1->0": 1, "0->0": 4}
    assert tr["flips"] == {"0->1": ["F__rich_05", "F__rich_06", "F__rich_07", "F__rich_08"], "1->0": ["F__rich_04"]}
    # higher is better: wins = 0->1, losses = 1->0, ties = the diagonal
    assert (h["wins"], h["losses"], h["ties"]) == (4, 1, 8) and sum(tr["counts"].values()) == h["n"] == 13
    # lower is better (x_crash): the model_error in base that is gone in the candidate is 1->0 and a win
    x = C["metrics"]["x_crash"]
    assert x["transitions"]["counts"]["1->0"] == 1 and (x["wins"], x["losses"]) == (1, 0)
    # only binary metrics carry a table
    assert "transitions" not in C["metrics"]["f_calls"] and "transitions" not in C["metrics"]["x_invented_tool_calls"]
    md = SM.compare_md(C)
    assert "Transition table for f_hidden_pass" in md and "| 1 | 4 | 1 |\n| 0 | 4 | 4 |" in md
    assert "1 -> 0 (1): F__rich_04" in md
    assert SM.transition_md(None, None) == []


def test_compare_refuses_other_models_providers_and_interrupted_runs(tmp_path):
    """Regression (review 2026-09-30): compare checked suite, split, label and infra share only, so two PROXY runs
    served by different OpenRouter providers (fp4 vs bf16) or models were paired silently, and an interrupted run
    (few cases, few infra errors) passed as a population."""
    res = {"rich_%02d" % i: True for i in range(6)}
    base = f_run(tmp_path, "base", res)
    other = f_run(tmp_path, "prov", res)
    rj = json.loads(Path(other, "run.json").read_text())
    Path(other, "run.json").write_text(json.dumps(dict(rj, providers_seen=["Crusoe", "DeepInfra"])))
    why = SM.compare(base, other)[0]
    assert len(why) == 1 and "providers differ" in why[0] and "--or-provider" in why[0]
    assert SM.compare(base, other, allow_mixed=True)[0] == []
    _, C = SM.compare(base, other, allow_mixed=True)
    assert C["mixed_providers"] and not C["mixed_models"] and C["candidate"]["providers"] == ["Crusoe", "DeepInfra"]
    model = f_run(tmp_path, "model", res)
    Path(model, "run.json").write_text(json.dumps(dict(rj, upstream_model="google/gemma-4-26b")))
    assert any("models differ" in w for w in SM.compare(base, model)[0])
    intr = f_run(tmp_path, "intr", res)
    Path(intr, "run.json").write_text(json.dumps(dict(rj, status="interrupted")))
    why = SM.compare(base, intr, allow_mixed=True)[0]
    assert len(why) == 1 and "interrupted" in why[0] and "--resume" in why[0]
    assert SM.main(["compare", base, intr]) == 2
    # a run.json without providers_seen falls back to the flat records' providers ("Prov" in every synthetic case)
    Path(base, "run.json").write_text(json.dumps({"suite": "F", "split": "dev", "label": "PROXY"}))
    assert SM.providers_of(SM.load_run(base)) == ["Prov"]


# ---------------------------------------------------------------------------------------------------------------------
# The repair ablation (docs/eval/ABLATION_REPAIR.md, addendum 2026-09-30)
# ---------------------------------------------------------------------------------------------------------------------
def T(w, l, same=0):
    """Transition counts with w 0->1 and l 1->0."""
    return {"1->1": same, "0->1": w, "1->0": l, "0->0": 0}


def test_ablation_rule_known_values():
    v = lambda ab, aa=T(0, 0), share=0.0: SM.ablation_verdict(ab, aa, share)["verdict"]
    assert v(T(4, 0)) == "KEEP"                                 # p 1/16 = 0.0625
    assert v(T(3, 0)) == "INCONCLUSIVE"                         # p 1/8 = 0.125: not evidence at 0.10
    assert v(T(5, 2)) == "INCONCLUSIVE"                         # net 3 but p 29/128 = 0.227
    assert v(T(8, 2)) == "INCONCLUSIVE"                         # p 56/1024 = 0.055 and net 6, but damage 2 > 1
    assert v(T(7, 1)) == "KEEP" and SM.ablation_verdict(T(7, 1), T(0, 0))["damage"] == 1
    assert v(T(0, 0)) == "CUT" and v(T(1, 3)) == "CUT" and v(T(2, 2)) == "CUT"
    assert v(T(2, 1)) == "INCONCLUSIVE"
    # calibration: identical arms showing a KEEP-sized effect in either direction void the run
    assert v(T(6, 0), T(4, 0)) == "INCONCLUSIVE" and v(T(6, 0), T(0, 4)) == "INCONCLUSIVE"
    assert v(T(6, 0), T(3, 0)) == "KEEP" and v(T(6, 0), T(5, 4)) == "KEEP"   # p 0.125, and net 1
    assert not SM.calibration(T(4, 0))["ok"] and SM.calibration(T(3, 0))["ok"] and SM.calibration(T(9, 6))["ok"]
    # compliance: an A0 arm that repairs anyway is not the designed contrast
    assert v(T(6, 0), share=0.10) == "KEEP" and v(T(6, 0), share=0.11) == "INCONCLUSIVE"
    r = SM.ablation_verdict(T(6, 0), T(1, 1), 0.2)
    assert not r["compliance_ok"] and "compliance failed" in r["why"]
    # the superseded rule compares the signed net with the unsigned flip total: 4 clean solves are CUT by 5 flips
    assert SM.original_rule(T(4, 0), T(3, 2))["verdict"] == "CUT" and v(T(4, 0), T(3, 2)) == "KEEP"
    assert SM.original_rule(T(5, 0), T(1, 1))["verdict"] == "KEEP"


def sim_rules(U, S, trials, samples=1, seed=1, n=29, always=10):
    """Share of KEEP / CUT / INCONCLUSIVE per rule on n F-dev cases: `always` pass in every arm, U pass with p = 0.5 in
    every arm (sampling flips), S that repair solves for certain (A0 never, B2 always), the rest never pass. Each case's
    outcome is the majority over `samples`. The addendum's table is this at trials=20000."""
    import collections
    import random
    rng = random.Random(seed)
    pa = [1.0] * always + [0.5] * U + [0.0] * S + [0.0] * (n - always - U - S)
    pb = [1.0] * always + [0.5] * U + [1.0] * S + [0.0] * (n - always - U - S)

    def draw(ps):
        return [int(sum(rng.random() < p for _ in range(samples)) * 2 > samples) for p in ps]

    def table(a, b):
        c = collections.Counter("%d->%d" % (x, y) for x, y in zip(a, b))
        return {k: c[k] for k in SM.TRANSITION_KEYS}
    out = {"original": collections.Counter(), "addendum": collections.Counter()}
    for _ in range(trials):
        a0, a0p, b2 = draw(pa), draw(pa), draw(pb)
        ab, aa = table(a0, b2), table(a0, a0p)
        out["original"][SM.original_rule(ab, aa)["verdict"]] += 1
        out["addendum"][SM.ablation_verdict(ab, aa)["verdict"]] += 1
    return {k: {x: v[x] / trials for x in ("KEEP", "CUT", "INCONCLUSIVE")} for k, v in out.items()}


def test_ablation_rule_is_not_biased_toward_cut():
    """Regression (review 2026-09-30): the pre-registered rule compared a signed net (fail->pass minus pass->fail,
    centred on 0 under the null) with the unsigned A0->A0' flip total (never negative), so a real repair benefit
    smaller than the flip count was CUT. The addendum's rule reads A0->B2 with the sign test and A0->A0' as a net."""
    null = sim_rules(5, 0, 4000)
    assert null["original"]["CUT"] >= 0.88                      # measured 94 % at 20k trials
    assert null["addendum"]["KEEP"] <= 0.05                     # false KEEP stays rare
    real4 = sim_rules(5, 4, 4000)                               # 4 certain solves among 5 coin-flip cases
    assert real4["original"]["CUT"] >= 0.20 and real4["original"]["KEEP"] <= 0.40
    assert real4["addendum"]["CUT"] <= 0.05 and real4["addendum"]["KEEP"] > real4["original"]["KEEP"]
    noisy = sim_rules(10, 4, 4000)
    assert noisy["original"]["CUT"] >= 0.60 and noisy["addendum"]["CUT"] <= 0.10
    three = sim_rules(0, 3, 500)                                # no noise at all: 3-0 is p 0.125, not evidence
    assert three["original"]["KEEP"] == 1.0 and three["addendum"]["INCONCLUSIVE"] == 1.0


VERIFY = "python3 /tmp/swe/verify.py"
EDIT = "python3 /tmp/swe/edit.py rich/text.py --lines 1-2 <<'EOF'\nx\nEOF"
PIN = {"endpoint": "openrouter", "or_provider": "crusoe/bf16", "upstream_extra": {"reasoning": {"enabled": False}},
       "l4_scale": 1.9, "seed_mode": "off", "dataset_sha": "d" * 64, "task_filter": None, "agent_env": "kpar",
       "faithful_env": False, "harness_verify": False, "providers_seen": ["Crusoe"], "status": "written"}


def with_uses(c, cmds):
    """Put run_command uses into the fixer's stage-run, before its reply."""
    ev = c["agent_data"]["turns"][0]["events"]
    extra = []
    for cmd in cmds:
        extra += [{"author": "fixer", "content": {"role": "model", "parts": [{"function_call": {
                      "name": "run_command", "args": {"command": cmd}}}]}},
                  {"author": "fixer", "content": {"role": "user", "parts": [{"function_response": {
                      "name": "run_command", "response": {"status": "ok", "stdout": "OK\n[t=90s]\n"}}}]}}]
    c["agent_data"]["turns"][0]["events"] = ev[:-1] + extra + ev[-1:]
    return c


def abl_run(tmp, name, results, bundle="a" * 64, samples=1, repair=(), repro=(), extra=(), **run):
    """An F run of the ablation: results = {task: pass or [pass per sample]}; `repair` tasks edit after verify."""
    cases = []
    for t, ps in sorted(results.items()):
        for k, ok in enumerate(ps if isinstance(ps, (list, tuple)) else [ps]):
            c = case("F", t, sample=k, passed=bool(ok), reproducible=t in repro)
            cases.append(with_uses(c, [VERIFY, EDIT] if t in repair else [VERIFY]))
    rj = dict(PIN, run_id=name, suite="F", split="dev", label="PROXY", upstream_model="google/gemma-4-31b-it",
              bundle_sha=bundle, samples=samples)
    rj.update(run)
    return write_run(tmp / name, cases + list(extra), run=rj)


def test_repair_edits_counts_edits_after_the_first_full_verify():
    c = lambda cmds: SM.repair_edits(GM.make_instance(with_uses(case("F", "rich_1"), cmds)))
    assert c([VERIFY, EDIT]) == 1 and c([VERIFY, EDIT, VERIFY, EDIT]) == 2
    assert c([EDIT, VERIFY]) == 0 and c([EDIT]) == 0 and c([]) == 0          # the first attempt is not repair
    assert c([VERIFY + " --repro-only <<'EOF'\nx\nEOF", EDIT]) == 0          # a repro run is not the verdict
    assert c([VERIFY + " --repro-only", EDIT, VERIFY, "python3 /tmp/swe/view.py a.py 1 2"]) == 0
    assert SM.repair_edits(None) == 0


def test_ablation_end_to_end_where_the_original_rule_would_cut(tmp_path):
    """Three synthetic F dev arms: A0 -> B2 has 5 new solves and no damage, A0 -> A0' has 5 flips (3 up, 2 down).
    The superseded rule says CUT (net 5 <= flip total 5); the addendum's says KEEP (p 1/32, net 5, damage 0,
    calibration net 1). A case that is infra_error in A0' is dropped from all three arms and listed."""
    tasks = ["rich_%02d" % i for i in range(20)]
    a0 = {t: i < 6 for i, t in enumerate(tasks)}                      # 00..05 pass
    b2 = {t: i < 11 for i, t in enumerate(tasks)}                     # + 06..10: 5 new solves
    a0p = {t: (i < 4 or 6 <= i < 9) for i, t in enumerate(tasks)}     # 04, 05 lost; 06, 07, 08 gained
    repro = {"rich_06", "rich_07", "rich_00"}
    d0 = abl_run(tmp_path, "A0", a0, repro=repro)
    d2 = abl_run(tmp_path, "B2", b2, bundle="b" * 64, repro=repro, repair={"rich_06", "rich_07"})
    dp = abl_run(tmp_path, "A0p", {t: v for t, v in a0p.items() if t != "rich_19"}, repro=repro,
                 extra=[case("F", "rich_19", status="infra_error")])
    assert SM.main(["ablation", d0, d2, dp]) == 0
    A = json.loads(Path(d2, "ablation.json").read_text())
    assert A["paired_cases"] == 19 and A["dropped"] == {"F__rich_19": "not applicable or not ok in A0'"}
    assert A["A0->B2"]["counts"] == {"1->1": 6, "0->1": 5, "1->0": 0, "0->0": 8}
    assert A["A0->B2"]["flips"]["0->1"] == ["F__rich_06", "F__rich_07", "F__rich_08", "F__rich_09", "F__rich_10"]
    assert A["A0->A0'"]["counts"] == {"1->1": 4, "0->1": 3, "1->0": 2, "0->0": 10}
    r = A["rule"]
    assert (r["verdict"], r["wins"], r["losses"], r["net"], r["damage"]) == ("KEEP", 5, 0, 5, 0)
    assert r["p_one_sided"] == round(1 / 32, 6) and r["calibration"]["net"] == 1 and r["calibration"]["ok"]
    assert A["original_rule_superseded"] == {"verdict": "CUT", "net": 5, "noise_flip_total": 5}
    # sliced by golden.reproducible (finding: F's repro-carrying cases give repair a better signal than a locator)
    sl = A["by_reproducible"]
    assert sl["True"]["n"] == 3 and sl["True"]["A0->B2"]["counts"]["0->1"] == 2 and sl["False"]["n"] == 16
    assert A["per_arm"]["A0"]["majority_pass"] == 6 and A["per_arm"]["B2"]["majority_pass"] == 11
    assert A["per_arm"]["A0"]["repair_share"] == 0 and A["per_arm"]["B2"]["repair_share"] == round(2 / 19, 4)
    assert A["per_arm"]["A0"]["l4_projected_s_mean"] == round(1.4 * 1 + 0.035 * 40, 4)   # 1 call of 40 tokens
    md = Path(d2, "ablation.md").read_text()
    assert "# Repair ablation: KEEP" in md and "SUPERSEDED" in md and "without finalize" in md
    assert "reproducible True (3 cases)" in md and "0 -> 1 (5): F__rich_06" in md
    assert not A["unscaled_proxy_clock"]


def test_ablation_with_three_samples_uses_the_majority(tmp_path):
    a0 = {"rich_1": [1, 1, 0], "rich_2": [0, 0, 1], "rich_3": [0, 0, 0], "rich_4": [1, 1, 1]}
    b2 = {"rich_1": [1, 0, 0], "rich_2": [1, 1, 0], "rich_3": [0, 1, 1], "rich_4": [1, 1, 1]}
    a0p = {"rich_1": [1, 0, 1], "rich_2": [0, 1, 0], "rich_3": [0, 0, 1], "rich_4": [1, 1]}   # rich_4 short a sample
    why, A = SM.ablation(abl_run(tmp_path, "A0", a0, samples=3),
                         abl_run(tmp_path, "B2", b2, samples=3, bundle="b" * 64),
                         abl_run(tmp_path, "A0p", a0p, samples=3))
    assert why == [] and A["samples"] == 3 and A["dropped"] == {"F__rich_4": "samples A0' 2 of 3"}
    assert A["A0->B2"]["counts"] == {"1->1": 0, "0->1": 2, "1->0": 1, "0->0": 0}
    assert A["A0->B2"]["flips"] == {"0->1": ["F__rich_2", "F__rich_3"], "1->0": ["F__rich_1"]}
    assert A["per_arm"]["A0"]["sample_pass_rate"] == round(3 / 9, 4)
    assert A["rule"]["verdict"] == "INCONCLUSIVE"


def test_ablation_refuses_unpinned_or_mismatched_arms(tmp_path):
    """Regression (review 2026-09-30): the three arms were to run with --l4-scale 1.0 (the helper clock and the t=300
    cap on proxy wall time), with no provider pin and no fixed reasoning setting, so the repair rounds that fit and
    the model's quantization could differ between arms. summary.py ablation now refuses such arms."""
    res = {"rich_%d" % i: i < 3 for i in range(6)}
    ok = lambda name, **kw: abl_run(tmp_path, name, res, **kw)
    a0, b2, a0p = ok("A0"), ok("B2", bundle="b" * 64), ok("A0p")
    assert SM.ablation(a0, b2, a0p)[0] == []

    def refused(pattern, **kw):
        bad = ok("bad_" + pattern.split()[0] + str(len(kw)), **kw)
        why = SM.ablation(a0, b2, bad)[0]
        assert any(pattern in w for w in why), why
    refused("l4_scale", l4_scale=2.5)
    refused("or_provider", or_provider="novita/bf16")
    refused("upstream_extra", upstream_extra={})
    refused("seed_mode", seed_mode="case")
    refused("dataset_sha", dataset_sha="e" * 64)
    refused("providers", providers_seen=["Crusoe", "Novita"])
    refused("repeat A0's bundle", bundle="c" * 64)
    refused("interrupted", status="interrupted")
    refused("suite L", suite="L")
    refused("split holdout", split="holdout")
    refused("--samples 2", samples=2)
    why = SM.ablation(a0, ok("B2same"), a0p)[0]
    assert any("B2 has A0's bundle" in w for w in why)
    # PROXY needs a pin and a scaled clock; --allow-unscaled accepts the clock and flags it
    np = [ok(n, or_provider=None) for n in ("np0", "np2", "npp")]
    assert any("without a provider pin" in w for w in SM.ablation(*np)[0])
    un = [ok(n, l4_scale=1.0, bundle=("b" if n == "u2" else "a") * 64) for n in ("u0", "u2", "up")]
    assert any("--l4-scale 1.0" in w for w in SM.ablation(*un)[0])
    why, A = SM.ablation(*un, allow_unscaled=True)
    assert why == [] and A["unscaled_proxy_clock"] and "WARNING: PROXY at --l4-scale 1.0" in SM.ablation_md(A)
    assert SM.main(["ablation"] + un) == 2 and SM.main(["ablation"] + un + ["--allow-unscaled"]) == 0
    # nothing paired is refused rather than read as net 0 -> CUT
    e = [abl_run(tmp_path, n, {t: True}, bundle=("b" if n == "e2" else "a") * 64)
         for n, t in (("e0", "rich_1"), ("e2", "rich_2"), ("ep", "rich_3"))]
    why, A = SM.ablation(*e)
    assert A is None and why == ["no case is paired across the three arms (3 dropped): nothing to decide on"]


def test_ablation_compliance_voids_an_a0_that_repairs_anyway(tmp_path):
    """verify.py's RED lines tell the fixer to fix and rerun whatever its prompt says, so an A0 that still edits
    after its first verify is not the designed contrast: more than 10 % of A0 case samples doing so -> INCONCLUSIVE."""
    tasks = ["rich_%02d" % i for i in range(20)]
    a0 = {t: i < 6 for i, t in enumerate(tasks)}
    b2 = {t: i < 11 for i, t in enumerate(tasks)}
    d2 = abl_run(tmp_path, "B2", b2, bundle="b" * 64)
    dp = abl_run(tmp_path, "A0p", a0)
    two = abl_run(tmp_path, "A0_2", a0, repair={"rich_00", "rich_01"})               # 2 of 20 = 10 %: allowed
    three = abl_run(tmp_path, "A0_3", a0, repair={"rich_00", "rich_01", "rich_02"})  # 15 %
    assert SM.ablation(two, d2, dp)[1]["rule"]["verdict"] == "KEEP"
    A = SM.ablation(three, d2, dp)[1]
    assert A["rule"]["verdict"] == "INCONCLUSIVE" and not A["rule"]["compliance_ok"]
    assert A["per_arm"]["A0"]["repair_share"] == 0.15 and "Compliance: 15 %" in SM.ablation_md(A)


# ---------------------------------------------------------------------------------------------------------------------
# One real agents-cli grade with the generated configs (gotchas 3, 4, 5)
# ---------------------------------------------------------------------------------------------------------------------
def _no_network_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "OPENROUTER", "OPENAI_", "CLOUDSDK_"))}
    env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9",
               NO_PROXY="", GCE_METADATA_HOST="127.0.0.1:9", GCE_METADATA_IP="127.0.0.1:9", NO_GCE_CHECK="True")
    return env


def _mixed_cases():
    cases = [case("L", "rich_1", reproducible=True), case("L", "rich_2", passed=False),
             case("F", "rich_1"), case("F", "rich_2", passed=False, x_bad=True),
             case("V", "rich_1", variant="gold"), case("V", "rich_1", variant="empty", passed=False),
             case("V", "rich_1", variant="wrong", passed=False, status="model_error")]
    empty = case("F", "rich_3")
    empty["agent_data"] = {"agents": {}, "turns": []}
    empty["responses"] = [{"response": {"role": "model", "parts": [{"text": ""}]}}]
    return cases + [empty]


SUITE_CASES = {"L": lambda: [case("L", "rich_1"), case("L", "rich_2", passed=False)],
               "F": lambda: [case("F", "rich_1"), case("F", "rich_2", passed=False)],
               "V": lambda: [case("V", "rich_1", variant="gold"), case("V", "rich_1", variant="empty", passed=False)]}


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """Four agents-cli grades run concurrently (about 7 s instead of about 35 s one after another): the union config
    on a trace set that mixes suites across three files, and each per-suite config on that suite's traces."""
    if not os.path.exists(AGENTS_CLI):
        pytest.skip("agents-cli not installed at %s" % AGENTS_CLI)
    base = tmp_path_factory.mktemp("agents_cli")
    jobs = {"mixed": (write_run(base / "mixed", _mixed_cases(), files=("b_second.json", "a_first.json",
                                                                       "0_third.json")), "eval_config.yaml")}
    for s in "LFV":
        jobs[s] = (write_run(base / s, SUITE_CASES[s](), files=("%s_dev.json" % s,)), "eval_config_%s.yaml" % s)
    procs = {}
    for k, (d, cfg) in jobs.items():
        procs[k] = subprocess.Popen([AGENTS_CLI, "eval", "grade", "--traces", os.path.join(d, "traces"), "--config",
                                     str(ROOT / "eval" / "golden" / cfg), "--output", os.path.join(d, "grade"),
                                     "--qps", "500"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    env=_no_network_env(), cwd=str(base))
    out = {}
    try:
        for k, p in procs.items():
            so, se = p.communicate(timeout=240)
            out[k] = (jobs[k][0], p.returncode, so, se)
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.kill()
                p.wait()
    return out


def _results(d):
    files = sorted(Path(d, "grade").glob("results_*.json"))
    assert len(files) == 1, files
    return files[0], json.loads(files[0].read_text())


def test_agents_cli_grades_generated_configs_equal_to_library(graded, tmp_path):
    d, rc, so, se = graded["mixed"]
    assert rc == 0, (so[-2000:], se[-2000:])
    cases = _mixed_cases()
    res_file, res = _results(d)
    assert len(res["eval_case_results"]) == len(cases)
    for s in res["summary_metrics"]:
        assert s["num_cases_error"] == 0 and s["num_cases_valid"] == len(cases), s
    for cr in res["eval_case_results"]:
        for mr in cr["response_candidate_results"][0]["metric_results"].values():
            assert mr["error_message"] is None and isinstance(mr["score"], float), mr
    # the library's scores equal agents-cli's for every case and metric (summary exits 4 otherwise)
    assert SM.main([d, "--holdout-log", str(tmp_path / "none"), "--no-l4-ref"]) == 0
    chk = json.loads(Path(d, "summary.json").read_text())["agents_cli_check"]
    assert chk["compared"] == len(cases) * len(GM.METRICS) and chk["n_mismatches"] == 0 and not chk["unknown_metrics"]
    # gotcha 3: the golden block reached the metrics (a score that needs it is non-zero)
    ids = [c["eval_case_id"] for c in res["evaluation_dataset"][0]["eval_cases"]]
    assert set(ids) == {c["eval_case_id"] for c in cases}
    f1 = next(cr for cr in res["eval_case_results"] if cr["eval_case_index"] == ids.index("F__rich_1__s0"))
    assert f1["response_candidate_results"][0]["metric_results"]["f_hidden_pass"]["score"] == 1.0
    # gotcha 4: agents-cli eval compare is a key-level diff with no pairing and no statistics
    tampered = copy.deepcopy(res)
    tampered["summary_metrics"][0]["mean_score"] = 0.123
    other = tmp_path / "other.json"
    other.write_text(json.dumps(tampered))
    p = subprocess.run([AGENTS_CLI, "eval", "compare", str(res_file), str(other)], capture_output=True, text=True,
                       timeout=60, env=_no_network_env())
    assert p.returncode == 0, p.stderr[-1000:]
    diff = json.loads(p.stdout)
    assert set(diff) == {"baseline_keys", "candidate_keys", "differences", "changed_keys", "unchanged_keys"}
    assert "summary_metrics" in diff["changed_keys"]
    assert not any(k in p.stdout for k in ("p_value", "wins", "losses", "sign", "wilson"))


@pytest.mark.parametrize("suite", ["L", "F", "V"])
def test_agents_cli_grades_each_suite_config(graded, tmp_path, suite):
    """The per-suite configs (the ones spec 9's commands use) load in agents-cli and grade that suite's traces with
    0 errors and the library's scores."""
    d, rc, so, se = graded[suite]
    assert rc == 0, (so[-2000:], se[-2000:])
    _, res = _results(d)
    assert [s["metric_name"] for s in res["summary_metrics"]] == GM.metric_names(suite)
    assert all(s["num_cases_error"] == 0 for s in res["summary_metrics"])
    assert SM.main([d, "--holdout-log", str(tmp_path / "none"), "--no-l4-ref"]) == 0
    chk = json.loads(Path(d, "summary.json").read_text())["agents_cli_check"]
    assert chk["compared"] == len(SUITE_CASES[suite]()) * len(GM.metric_names(suite)) and chk["n_mismatches"] == 0
