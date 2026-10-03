"""Golden-eval run summary and paired comparison (docs/eval/GOLDEN_EVALS_SPEC.md v1.1 section 8).

    .venv/bin/python scripts/golden/summary.py RUN_DIR [--out DIR] [--holdout-log PATH] [--no-l4-ref]
    .venv/bin/python scripts/golden/summary.py compare BASE_RUN CAND_RUN [--allow-mixed] [--pair-by-task] [--out DIR]
    .venv/bin/python scripts/golden/summary.py ablation A0_RUN B2_RUN A0P_RUN [--allow-unscaled] [--out DIR]

summary: loads RUN_DIR/traces/*.json (grading-input EvaluationDatasets, spec 6.2) and RUN_DIR/cases/*.json (flat
per-case records, spec 6.3), scores every case with eval/golden/golden_metrics.py (the library the generated
agents-cli metric files are pasted from), and writes RUN_DIR/summary.json and summary.md: per metric over applicable
cases n and mean, a Wilson 95 % interval for binary metrics, median and p90 for numeric ones, per-case means and a
case-cluster bootstrap interval when a case has several samples, slices by repo, stratum, variant (V) and
reproducible (L), and a header with label, model, providers, bundle sha, population, cost, wall time and holdout
looks. When RUN_DIR/grade/results_*.json exists it asserts that agents-cli's per-case scores equal the library's.

compare: pairs two runs by dataset_case_id and, per metric, counts wins, losses and ties, runs the exact sign test
(ties dropped) and gives a verdict at two-sided p <= 0.05; for binary metrics with one sample per case it also gives
the 2x2 transition table (1->1, 0->1, 1->0, 0->0, with the flipped case ids), because ties lump 1->1 and 0->0
together; it also evaluates the pre-registered decision rule. It
refuses (exit 2) mismatched suites or splits; mismatched labels, models or providers seen unless --allow-mixed; an
interrupted run; any run with more than 5 % infra_error cases; and runs made on different L4 clocks (run.json l4_clock,
missing = wall; SPEC_v10_2 E1). A case whose fixture differs between the runs is dropped, except with --pair-by-task
(SPEC_v10_2 E4, the L-to-F chain: each arm's F case carries its own locator's plan, so the fixtures differ by design):
the cases are then paired by case id, both shas are listed, and the result is labelled CHAIN. `agents-cli eval
compare` is only a key-level JSON diff (no pairing, no statistics).

ablation: the repair ablation of docs/eval/ABLATION_REPAIR.md (addendum 2026-09-30). It intersects the three F dev runs'
paired cases first (applicable f_hidden_pass, every sample present, same fixture in all three), takes each case's
majority over its samples, and gives the A0 -> B2 and A0 -> A0' transition tables (also sliced by golden.reproducible),
the sign tests, the calibration and compliance checks, per-arm pass rates and costs, and the verdict of the addendum's
rule (KEEP / CUT / INCONCLUSIVE) next to the superseded original rule's. It refuses arms whose pinned settings differ.

Exit codes: 0 ok; 2 refused or unreadable input; 3 metric errors (a metric raised on some case); 4 agents-cli scores
differ from the library's. Stdlib only.
"""
import argparse
import collections
import glob
import json
import math
import os
import random
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, os.path.join(ROOT, "tests"), os.path.join(ROOT, "eval", "golden")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import golden_metrics as GM  # noqa: E402

Z = 1.96
BOOT_REPS = 2000
BOOT_SEED = 20260929
INFRA_MAX = 0.05
VERDICT_P = 0.05
RULE_P_ONE_SIDED = 0.10
RULE_MIN_NET_WINS = 3
# docs/eval/ABLATION_REPAIR.md, addendum 2026-09-30
ABL_HEADLINE = "f_hidden_pass"
ABL_MAX_DAMAGE = 1
ABL_CAL_NET = 3                  # identical arms showing |net| >= 3 at one-sided p <= 0.10 fail calibration
ABL_COMPLIANCE_MAX = 0.10        # A0 case samples that edit after their first verify.py, as a share
ABL_SETTINGS = ("suite", "split", "label", "endpoint", "upstream_model", "or_provider", "upstream_extra", "l4_scale",
                "seed_mode", "samples", "dataset_sha", "task_filter", "agent_env", "faithful_env", "harness_verify",
                "l4_clock")
L4_STEP_S, L4_TOKEN_S = 1.4, 0.035   # research/time_model.md: about 1.4 s per step plus 35 ms per output token
HOLDOUT_LOG = os.path.join(ROOT, "eval", "golden", "holdout_log.jsonl")
L4_TRACE_DIRS = (os.path.join(ROOT, "eval", "kaggle", "g4-l4-v4", "results", "traces"),
                 os.path.join(ROOT, "eval", "kaggle", "g4-l4-v9-eog", "results", "traces"))
DECISION_RULE = (
    "Pre-registered decision rule (spec section 8): adopt a prompt change on PROXY evidence only if, on the dev split, "
    "the target suite's headline improves with one-sided sign-test p <= 0.10 and wins - losses >= 3, no X count metric "
    "has a higher total, and the other suites' headlines have no 'worse' verdict; then confirm once on the holdout "
    "(and FAITHFUL when an L4 is available) before shipping.")
DEVIATIONS = (
    "PROXY runs use another quantization and tool-call parser: X metrics are indicative, time metrics are comparable "
    "to L4 only with --l4-scale set to the measured latency ratio.",
    "Journal times of scripted steps are compressed; only the handoff clock is exact.",
    "Scripted stages use fewer of the 100 tool calls / 200 turns than real ones.",
    "The baseline commit is dated one day back (visible only through git log).",
    "A compaction during the live stage summarises scripted events, not a real stage's.",
    "The golden plan is better than a real locator's: F measures the fixer's ceiling, not the pipeline.",
    "Race-2 repros came from v10.0 helpers and were re-validated with the v10.1 helpers.",
    "fastapi is runnable since 2026-09-30 (all 74 snapshots local; its kpar venv is the 41-package Kaggle-freeze "
    "closure, built online once). Runs made before that date cover rich and requests only: compare them on the cases "
    "both have (summary.py compare pairs by case id).",
    "The live stage ends at helper t=300 by the router cap; the scripted submit then includes new files (a real "
    "timeout's fallback diff would not).",
    "Hidden tests run in the kpar venv (Kaggle pip freeze), not the full Kaggle image; requests_6644 differs.",
)


# ---------------------------------------------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------------------------------------------
def wilson(k, n, z=Z):
    """Wilson score interval, the eval/compare.py formula; n = 0 gives (0, 0)."""
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def sign_p(wins, losses):
    """One-sided exact sign test P(W >= wins | n = wins + losses, p = 0.5) (scripts/ab_l4_decide.sign_p)."""
    n = wins + losses
    return sum(math.comb(n, w) for w in range(wins, n + 1)) / 2 ** n if n else 1.0


def sign_two_sided(wins, losses):
    """min(1, 2 x the smaller tail)."""
    return min(1.0, 2 * min(sign_p(wins, losses), sign_p(losses, wins)))


def quantile(values, q):
    """Linear-interpolation quantile of an unsorted list (0.0 for an empty one)."""
    s = sorted(values)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def bootstrap_ci(values, reps=BOOT_REPS, seed=BOOT_SEED, alpha=0.05):
    """Case-cluster bootstrap of the mean: resample the per-case values with replacement, `reps` times, with a fresh
    random.Random(seed) per call, so the interval is deterministic. Empty input gives (0.0, 0.0)."""
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(vals)
    means = [sum(rng.choices(vals, k=n)) / n for _ in range(reps)]
    return (quantile(means, alpha / 2), quantile(means, 1 - alpha / 2))


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


# ---------------------------------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------------------------------
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sample_of(case_id):
    m = re.search(r"__s(\d+)$", case_id or "")
    return int(m.group(1)) if m else 0


def _base_id(case_id):
    return re.sub(r"__s\d+$", "", case_id or "")


def _record(case_id, g, flat, inst):
    g, flat = g or {}, flat or {}
    task = g.get("task") or flat.get("task") or ""
    run = g.get("run") if isinstance(g.get("run"), dict) else {}
    rec = {
        "case_id": case_id,
        "eval_case_id": (inst or {}).get("eval_case_id") or case_id,
        "dataset_case_id": g.get("dataset_case_id") or flat.get("dataset_case_id") or _base_id(case_id),
        "sample": g.get("sample") if isinstance(g.get("sample"), int) else flat.get("sample", _sample_of(case_id)),
        "suite": g.get("suite") or flat.get("suite") or GM._suite_from_id(case_id),
        "split": g.get("split") or flat.get("split"),
        "task": task,
        "variant": g.get("variant") or flat.get("variant") or "-",
        "repo": g.get("repo") or (task.split("_")[0] if task else ""),
        "stratum": g.get("stratum"),
        "reproducible": g.get("reproducible"),
        "runnable": g.get("runnable"),
        "runnable_why": g.get("runnable_why") or flat.get("status_detail") or "",
        "gradable": g.get("gradable"),
        "status": g.get("status") or flat.get("status") or "ok",
        "fixture_sha": g.get("fixture_sha") or flat.get("fixture_sha"),
        "label": run.get("label") or flat.get("label"),
        "model": run.get("upstream_model") or flat.get("upstream_model"),
        "bundle_sha": run.get("bundle_sha") or flat.get("bundle_sha"),
        "providers": flat.get("providers") or [],
        "cost_usd": (flat.get("live") or {}).get("cost_usd") if isinstance(flat.get("live"), dict) else None,
        "wall_s": flat.get("wall_s") if isinstance(flat.get("wall_s"), (int, float)) else None,
        "latencies": [c.get("latency_s") for c in (g.get("llm_calls") or []) if isinstance(c, dict) and c.get("live")
                      and c.get("served") in GM.LIVE_SERVED and isinstance(c.get("latency_s"), (int, float))],
        "instance": inst,
    }
    live_calls = [c for c in (g.get("llm_calls") or []) if isinstance(c, dict) and c.get("live")
                  and c.get("served") in GM.LIVE_SERVED]
    rec["live_llm_calls"] = len(live_calls)
    rec["live_completion_tokens"] = sum(int(c.get("completion_tokens") or 0) for c in live_calls)
    rec["scores"] = GM.score_all(inst) if inst is not None else {}
    return rec


def load_run(run_dir):
    """{"dir", "run" (run.json), "records": [...]} with every case scored once by the library."""
    run = _read_json(os.path.join(run_dir, "run.json")) or {}
    flats = {}
    for fp in sorted(glob.glob(os.path.join(run_dir, "cases", "*.json"))):
        d = _read_json(fp)
        if isinstance(d, dict) and d.get("case_id"):
            flats[d["case_id"]] = d
    records = []
    for fp in sorted(glob.glob(os.path.join(run_dir, "traces", "*.json"))):
        ds = _read_json(fp)
        if not isinstance(ds, dict):
            raise ValueError("unreadable trace file %s" % fp)
        for case in ds.get("eval_cases") or []:
            inst = GM.make_instance(case)
            g = case.get("golden") if isinstance(case.get("golden"), dict) else {}
            cid = g.get("case_id") or case.get("eval_case_id")
            records.append(_record(cid, g, flats.pop(cid, None), inst))
    for cid, flat in sorted(flats.items()):   # flat-only cases (never traced) still count in the population
        records.append(_record(cid, {}, flat, None))
    return {"dir": run_dir, "run": run, "records": records}


def _one(values, what):
    vals = sorted(set(v for v in values if v))
    return vals[0] if len(vals) == 1 else (",".join(vals) if vals else None)


def run_meta(R):
    run, recs = R["run"], R["records"]
    return {"run_id": run.get("run_id") or os.path.basename(os.path.normpath(R["dir"])),
            "suite": run.get("suite") or _one([r["suite"] for r in recs], "suite"),
            "split": run.get("split") or _one([r["split"] for r in recs], "split"),
            "label": run.get("label") or _one([r["label"] for r in recs], "label"),
            "model": run.get("upstream_model") or _one([r["model"] for r in recs], "model"),
            "bundle_sha": run.get("bundle_sha") or _one([r["bundle_sha"] for r in recs], "bundle_sha"),
            "task_filter": run.get("task_filter") or None, "variant_filter": run.get("variant_filter") or None,
            "dataset_tasks": run.get("dataset_tasks")}


# ---------------------------------------------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------------------------------------------
def per_case(records, name):
    """{dataset_case_id: [applicable scores]} for one metric."""
    out = collections.OrderedDict()
    for r in sorted(records, key=lambda r: (r["dataset_case_id"], r["sample"] or 0)):
        res = r["scores"].get(name)
        if res is None:
            continue
        ok, _ = GM.explain(res)
        if ok:
            out.setdefault(r["dataset_case_id"], []).append(res["score"])
    return out


def aggregate(records, name, multi, boot=True):
    kind = GM.METRICS[name]["kind"]
    pc = per_case(records, name)
    vals = [sum(v) / len(v) for v in pc.values()]
    n = len(vals)
    out = {"n": n, "n_samples": sum(len(v) for v in pc.values()), "mean": _r(sum(vals) / n) if n else None}
    if kind == "binary" and not multi:
        k = int(round(sum(vals)))
        lo, hi = wilson(k, n)
        out.update(k=k, wilson=[_r(lo), _r(hi)])
    if kind in ("numeric", "count"):
        out.update(median=_r(quantile(vals, 0.5)) if n else None, p90=_r(quantile(vals, 0.9)) if n else None,
                   total=_r(sum(vals)))
    if multi and boot and n:
        lo, hi = bootstrap_ci(vals)
        out["bootstrap"] = [_r(lo), _r(hi)]
    return out


def relevant_metrics(records):
    suites = set(r["suite"] for r in records if r["suite"] in ("L", "F", "V"))
    return [n for n in GM.metric_names() if n.startswith("x_") or GM.METRICS[n]["suites"] in suites]


def metric_errors(records):
    errs = []
    for r in records:
        for name, res in sorted(r["scores"].items()):
            ok, detail = GM.explain(res)
            if not ok and isinstance(detail, dict) and "error" in detail:
                errs.append({"case_id": r["case_id"], "metric": name, "error": detail["error"]})
    return errs


def population(records, meta):
    """The population sentence, e.g. 'F dev: 29 gradable of 30 runnable of 55 tasks (rich 28, requests 1); fastapi 0
    of 24 runnable: snapshots missing'."""
    tasks = collections.OrderedDict()
    for r in sorted(records, key=lambda r: r["task"]):
        if not r["task"]:
            continue
        t = tasks.setdefault(r["task"], {"repo": r["repo"], "runnable": False, "gradable": False, "why": []})
        t["runnable"] = t["runnable"] or r["runnable"] is True or (r["runnable"] is None and r["status"] != "skipped")
        t["gradable"] = t["gradable"] or r["gradable"] is True
        if r["runnable_why"]:
            t["why"].append(r["runnable_why"])
    suite, split = meta["suite"] or "?", meta["split"] or "?"
    total = collections.Counter(t["repo"] for t in tasks.values())
    runn = collections.Counter(t["repo"] for t in tasks.values() if t["runnable"])
    grad = collections.Counter(t["repo"] for t in tasks.values() if t["runnable"] and t["gradable"])
    fmt = lambda c: ", ".join("%s %d" % (k, v) for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) if v)
    if suite in ("F", "V"):
        s = "%s %s: %d gradable of %d runnable of %d tasks (%s)" % (suite, split, sum(grad.values()),
                                                                     sum(runn.values()), len(tasks), fmt(grad))
    else:
        s = "%s %s: %d runnable of %d tasks (%s)" % (suite, split, sum(runn.values()), len(tasks), fmt(runn))
    for repo in sorted(total):
        if runn[repo] < total[repo]:
            whys = collections.Counter(w for t in tasks.values() if t["repo"] == repo and not t["runnable"]
                                       for w in t["why"])
            why = whys.most_common(1)[0][0] if whys else "not runnable"
            s += "; %s %d of %d runnable: %s" % (repo, runn[repo], total[repo], why[:80])
    if suite == "V":
        v = collections.Counter(r["variant"] for r in records if r["status"] != "skipped")
        s += "; cases gold %d, wrong %d, empty %d" % (v["gold"], v["wrong"], v["empty"])
    # a run_suite --tasks / --variants run is a subset: say so, or '2 of 2 tasks' reads as the population
    if meta.get("task_filter"):
        of = meta.get("dataset_tasks")
        s += "; SUBSET: %d of %s dataset tasks selected with --tasks, not a population rate" % (
            len(meta["task_filter"]), of if isinstance(of, int) else "?")
    if meta.get("variant_filter") and suite == "V":
        s += "; SUBSET: variants %s only (--variants)" % ", ".join(meta["variant_filter"])
    return s


def holdout_looks(meta, path=HOLDOUT_LOG):
    rows = []
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return {"log": os.path.relpath(path, ROOT) if path and path.startswith(ROOT) else path, "total": len(rows),
            "suite": sum(1 for x in rows if x.get("suite") == meta["suite"]),
            "suite_and_bundle": sum(1 for x in rows if x.get("suite") == meta["suite"]
                                    and x.get("bundle_sha") == meta["bundle_sha"])}


def l4_reference(dirs=L4_TRACE_DIRS):
    """Per-call latency reference from the Kaggle 4xL4 ATIF traces: the gap between each agent step and the step or
    tool result before it (one LLM call plus ADK overhead)."""
    gaps, used = [], []
    for d in dirs:
        files = sorted(glob.glob(os.path.join(d, "*.json")))
        if files:
            used.append(os.path.relpath(d, ROOT))
        for fp in files:
            prev = None
            for s in (_read_json(fp) or {}).get("steps") or []:
                ts = (s.get("extra") or {}).get("timestamp")
                if s.get("source") == "agent" and prev is not None and isinstance(ts, (int, float)) and ts >= prev:
                    gaps.append(ts - prev)
                o = s.get("observation")
                ots = (o.get("extra") or {}).get("timestamp") if isinstance(o, dict) else None
                prev = ots if isinstance(ots, (int, float)) else (ts if isinstance(ts, (int, float)) else prev)
    if not gaps:
        return None
    return {"mean_s": _r(statistics.mean(gaps), 3), "median_s": _r(statistics.median(gaps), 3), "n_calls": len(gaps),
            "sources": used}


def check_agents_cli(R):
    """Compare the newest grade/results_*.json with the library. agents-cli merges every trace file of --traces into
    one dataset in glob (directory) order, not file-name order, so eval_case_index is mapped through the results
    file's own evaluation_dataset[0].eval_cases."""
    files = sorted(glob.glob(os.path.join(R["dir"], "grade", "results_*.json")))
    if not files:
        return None
    fp = files[-1]
    res = _read_json(fp) or {}
    ds = res.get("evaluation_dataset")
    ds0 = ds[0] if isinstance(ds, list) and ds else ds
    ids = [c.get("eval_case_id") for c in ((ds0 or {}).get("eval_cases") or [])]
    by_eid = {}
    for r in R["records"]:
        if r["instance"] is not None:
            by_eid.setdefault(r["eval_case_id"], r)
    compared, mismatches, unknown = 0, [], set()
    for cr in res.get("eval_case_results") or []:
        idx = cr.get("eval_case_index")
        eid = ids[idx] if isinstance(idx, int) and 0 <= idx < len(ids) else None
        rec = by_eid.get(eid)
        for cand in cr.get("response_candidate_results") or []:
            for mname, mr in (cand.get("metric_results") or {}).items():
                if mname not in GM.METRICS:
                    unknown.add(mname)
                    continue
                compared += 1
                theirs = (mr or {}).get("score")
                if rec is None:
                    mismatches.append({"index": idx, "eval_case_id": eid, "metric": mname, "why": "case not in traces"})
                    continue
                ours = rec["scores"].get(mname) or GM._score(mname, rec["instance"])
                if theirs is None or abs(float(theirs) - ours["score"]) > 1e-9:
                    mismatches.append({"index": idx, "eval_case_id": eid, "metric": mname, "agents_cli": theirs,
                                       "library": ours["score"], "error": (mr or {}).get("error_message")})
    return {"file": os.path.relpath(fp, R["dir"]), "compared": compared, "n_mismatches": len(mismatches),
            "mismatches": mismatches[:50], "unknown_metrics": sorted(unknown)}


# ---------------------------------------------------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------------------------------------------------
def summarize(run_dir, holdout_log=HOLDOUT_LOG, l4_ref=True):
    R = load_run(run_dir)
    meta = run_meta(R)
    recs = R["records"]
    run = R["run"]
    status = collections.Counter(r["status"] for r in recs)
    attempted = sum(v for k, v in status.items() if k != "skipped")
    counted = [r for r in recs if r["status"] in GM.COUNTED_STATUS and r["instance"] is not None]
    samples = collections.Counter(r["dataset_case_id"] for r in counted)
    multi = bool(samples) and max(samples.values()) > 1
    names = relevant_metrics(recs)
    metrics = collections.OrderedDict((n, aggregate(counted, n, multi)) for n in names)
    slices = collections.OrderedDict()
    keys = ["repo", "stratum"]
    if any(r["suite"] == "V" for r in recs):
        keys.append("variant")
    if any(r["suite"] == "L" for r in recs):
        keys.append("reproducible")
    for key in keys:
        vals = sorted(set(str(r[key]) for r in counted))
        slices[key] = collections.OrderedDict()
        for v in vals:
            sub = [r for r in counted if str(r[key]) == v]
            slices[key][v] = collections.OrderedDict(
                (n, aggregate(sub, n, multi, boot=GM.METRICS[n]["headline"])) for n in names)
    lat = [x for r in recs for x in r["latencies"]]
    costs = [r["cost_usd"] for r in recs if isinstance(r["cost_usd"], (int, float))]
    providers = run.get("providers_seen") or sorted(set(p for r in recs for p in (r["providers"] or []) if p))
    header = collections.OrderedDict([
        ("run_id", meta["run_id"]), ("suite", meta["suite"]), ("split", meta["split"]), ("label", meta["label"]),
        ("model", meta["model"]), ("providers", providers), ("endpoint", run.get("endpoint")),
        ("bundle_sha", meta["bundle_sha"]), ("population", population(recs, meta)),
        ("cases", dict(total=len(recs), **status)), ("infra_error_share", _r(status["infra_error"] / attempted)
                                                     if attempted else 0.0),
        ("samples", max(samples.values()) if samples else 0),
        ("cost_usd", _r(run.get("spent_usd") if isinstance(run.get("spent_usd"), (int, float)) else sum(costs), 4)),
        ("wall_s", run.get("wall_s")),
        ("mean_live_latency_s", run.get("mean_live_latency_s") if run.get("mean_live_latency_s") is not None
         else (_r(statistics.mean(lat), 3) if lat else None)),
        ("l4_reference_latency", l4_reference() if l4_ref else None),
        ("holdout_looks", holdout_looks(meta, holdout_log)),
        ("l4_scale", run.get("l4_scale")),
    ])
    errs = metric_errors(recs)
    out = collections.OrderedDict([
        ("schema", "golden-summary-v1"), ("header", header),
        ("headlines", [n for n in names if GM.METRICS[n]["headline"]]),
        ("metrics", metrics), ("slices", slices), ("metric_errors", errs[:100]), ("n_metric_errors", len(errs)),
        ("agents_cli_check", check_agents_cli(R)), ("decision_rule", DECISION_RULE),
        ("known_deviations", list(DEVIATIONS)),
    ])
    return out


def _ci_text(m, kind):
    if m.get("bootstrap"):
        return "[%.3f, %.3f] boot" % tuple(m["bootstrap"])
    if kind == "binary" and m.get("wilson"):
        return "[%.3f, %.3f]" % tuple(m["wilson"])
    return ""


def _fmt(x):
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)) and float(x).is_integer():
        return "%d" % x
    return "%.3f" % x if isinstance(x, float) else str(x)


def summary_md(S):
    h = S["header"]
    lines = ["# Golden eval summary: %s" % h["run_id"], "",
             "**%s** | suite %s, split %s | model %s | providers %s | bundle %s" % (
                 h["label"] or "UNLABELLED", h["suite"], h["split"], h["model"] or "-",
                 ", ".join(h["providers"]) or "-", (h["bundle_sha"] or "-")[:12]), "",
             "Population: %s." % h["population"], "",
             "Cases: %s; infra_error share %.1f %%; samples per case %s; cost $%s; wall %s s." % (
                 ", ".join("%s %s" % (k, v) for k, v in h["cases"].items()), 100 * (h["infra_error_share"] or 0),
                 h["samples"], _fmt(h["cost_usd"]), _fmt(h["wall_s"]))]
    ref = h.get("l4_reference_latency")
    lines.append("Mean live-call latency %s s%s." % (
        _fmt(h["mean_live_latency_s"]), "" if not ref else " (Kaggle 4xL4 reference: mean %s s, median %s s over %d "
                                                             "calls)" % (ref["mean_s"], ref["median_s"], ref["n_calls"])))
    hl = h["holdout_looks"]
    lines += ["Holdout looks: %d for suite %s (%d with this bundle), %d in total." % (
        hl["suite"], h["suite"], hl["suite_and_bundle"], hl["total"]), ""]
    chk = S.get("agents_cli_check")
    if chk is None:
        lines.append("agents-cli check: no grade/results_*.json in this run.")
    else:
        lines.append("agents-cli check (%s): %d scores compared, %d mismatches%s." % (
            chk["file"], chk["compared"], chk["n_mismatches"], "" if not chk["n_mismatches"] else " -- MISMATCH"))
    if S["n_metric_errors"]:
        lines.append("METRIC ERRORS: %d (see summary.json metric_errors)." % S["n_metric_errors"])
    lines += ["", "## Headlines", "", "| metric | n | mean | 95 % CI |", "|---|---|---|---|"]
    for n in S["headlines"]:
        m = S["metrics"][n]
        lines.append("| %s | %d | %s | %s |" % (n, m["n"], _fmt(m["mean"]), _ci_text(m, GM.METRICS[n]["kind"])))
    lines += ["", "## All metrics (applicable cases only)", "",
              "| metric | kind | better | n | mean | 95 % CI | median | p90 | total |", "|---|---|---|---|---|---|---|---|---|"]
    for n, m in S["metrics"].items():
        meta = GM.METRICS[n]
        lines.append("| %s | %s | %s | %d | %s | %s | %s | %s | %s |" % (
            n, meta["kind"], meta["better"], m["n"], _fmt(m["mean"]), _ci_text(m, meta["kind"]),
            _fmt(m.get("median")), _fmt(m.get("p90")), _fmt(m.get("total"))))
    for key, vals in S["slices"].items():
        lines += ["", "## Headlines by %s" % key, "", "| %s | metric | n | mean | 95 %% CI |" % key, "|---|---|---|---|---|"]
        for v, ms in vals.items():
            for n in S["headlines"]:
                m = ms[n]
                if m["n"]:
                    lines.append("| %s | %s | %d | %s | %s |" % (v, n, m["n"], _fmt(m["mean"]),
                                                                 _ci_text(m, GM.METRICS[n]["kind"])))
    lines += ["", "## Reading this", "",
              "Statistics cover applicable cases only; agents-cli's own mean_score also averages the inapplicable "
              "zeros, so decisions read this file and `summary.py compare`, never agents-cli's table.", "",
              S["decision_rule"], "", "## Known deviations", ""]
    lines += ["%d. %s" % (i + 1, d) for i, d in enumerate(S["known_deviations"])]
    return "\n".join(lines) + "\n"


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=1, sort_keys=False, default=str)
            f.write("\n")


def cmd_summary(a):
    try:
        S = summarize(a.run_dir, a.holdout_log, not a.no_l4_ref)
    except ValueError as e:
        print("summary: %s" % e, file=sys.stderr)
        return 2
    out = a.out or a.run_dir
    os.makedirs(out, exist_ok=True)
    _write(os.path.join(out, "summary.json"), S)
    _write(os.path.join(out, "summary.md"), summary_md(S))
    h = S["header"]
    for n in S["headlines"]:
        m = S["metrics"][n]
        print("%s %s %s: %s n=%d mean=%s %s" % (h["label"], h["suite"], h["split"], n, m["n"], _fmt(m["mean"]),
                                                _ci_text(m, GM.METRICS[n]["kind"])))
    print("population: " + h["population"])
    chk = S["agents_cli_check"]
    if chk and chk["n_mismatches"]:
        print("AGENTS-CLI MISMATCH: %d of %d scores differ (summary.json agents_cli_check)" % (
            chk["n_mismatches"], chk["compared"]), file=sys.stderr)
        return 4
    if S["n_metric_errors"]:
        print("METRIC ERRORS: %d (summary.json metric_errors)" % S["n_metric_errors"], file=sys.stderr)
        return 3
    return 0


# ---------------------------------------------------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------------------------------------------------
def l4_clock_of(R):
    """run.json l4_clock; runs made before SPEC_v10_2 E1 ran on the wall clock."""
    return R["run"].get("l4_clock") or "wall"


def refusals(A, B, allow_mixed=False):
    ma, mb = run_meta(A), run_meta(B)
    why = []
    if l4_clock_of(A) != l4_clock_of(B):
        why.append("L4 clocks differ: %s vs %s (run_suite.py --l4-clock): time metrics and caps are not comparable"
                   % (l4_clock_of(A), l4_clock_of(B)))
    if ma["suite"] != mb["suite"]:
        why.append("suites differ: %s vs %s" % (ma["suite"], mb["suite"]))
    if ma["split"] != mb["split"]:
        why.append("splits differ: %s vs %s" % (ma["split"], mb["split"]))
    if ma["label"] != mb["label"] and not allow_mixed:
        why.append("labels differ: %s vs %s (pass --allow-mixed to compare anyway)" % (ma["label"], mb["label"]))
    if ma["model"] != mb["model"] and not allow_mixed:
        why.append("models differ: %s vs %s (pass --allow-mixed to compare anyway)" % (ma["model"], mb["model"]))
    if providers_of(A) != providers_of(B) and not allow_mixed:
        why.append("providers differ: %s vs %s: another provider can serve another quantization (pin one with "
                   "run_suite.py --or-provider, or pass --allow-mixed)" % (providers_of(A), providers_of(B)))
    for name, R in (("base", A), ("candidate", B)):
        if R["run"].get("status") == "interrupted":
            why.append("%s run was interrupted: finish it with run_suite.py ... --resume first" % name)
        st = collections.Counter(r["status"] for r in R["records"])
        att = sum(v for k, v in st.items() if k != "skipped")
        if att and st["infra_error"] / att > INFRA_MAX:
            why.append("%s run has %d of %d infra_error cases (> %d %%): the comparison is invalid" % (
                name, st["infra_error"], att, int(INFRA_MAX * 100)))
    return why


def providers_of(R):
    """The providers that served a run: run.json providers_seen, else the union over its flat records."""
    seen = R["run"].get("providers_seen")
    if not isinstance(seen, list):
        seen = [p for r in R["records"] for p in (r["providers"] or [])]
    return sorted(set(p for p in seen if p))


TRANSITION_KEYS = ("1->1", "0->1", "1->0", "0->0")


def transitions(pa, pb, ids):
    """The 2x2 table of a binary metric over paired cases, base -> candidate: {"1->1", "0->1", "1->0", "0->0"}
    counts plus the case ids of the two flip cells. For f_hidden_pass "0->1" is a new solve and "1->0" a damaged
    patch; the diagonal is what wins/losses/ties lump together as ties. None when any paired case has more than one
    sample on either side (per-case means are not 0/1; read wins/losses and the bootstrap instead)."""
    if any(len(pa[i]) != 1 or len(pb[i]) != 1 for i in ids):
        return None
    counts = collections.OrderedDict((k, 0) for k in TRANSITION_KEYS)
    flips = collections.OrderedDict((k, []) for k in ("0->1", "1->0"))
    for i in ids:
        k = "%d->%d" % (int(round(pa[i][0])), int(round(pb[i][0])))
        counts[k] += 1
        if k in flips:
            flips[k].append(i)
    return collections.OrderedDict([("counts", counts), ("flips", flips)])


def compare(base_dir, cand_dir, allow_mixed=False, pair_by_task=False):
    """-> (refusal reasons, result). The result pairs the runs by dataset_case_id; a case whose fixture differs is
    dropped unless pair_by_task (the L-to-F chain, labelled CHAIN)."""
    A, B = load_run(base_dir), load_run(cand_dir)
    why = refusals(A, B, allow_mixed)
    if why:
        return why, None
    ma, mb = run_meta(A), run_meta(B)
    ok = lambda R: [r for r in R["records"] if r["status"] in GM.COUNTED_STATUS and r["instance"] is not None]
    ra, rb = ok(A), ok(B)
    fa, fb = collections.defaultdict(set), collections.defaultdict(set)
    for r in ra:
        fa[r["dataset_case_id"]].add(r["fixture_sha"])
    for r in rb:
        fb[r["dataset_case_id"]].add(r["fixture_sha"])
    common = sorted(set(fa) & set(fb))
    changed = [i for i in common if fa[i] != fb[i]]
    chain_shas = collections.OrderedDict()
    if pair_by_task:
        chain_shas = collections.OrderedDict((i, [sorted(x or "" for x in fa[i]), sorted(x or "" for x in fb[i])])
                                             for i in common)
        changed = []
    keep = set(common) - set(changed)
    ra = [r for r in ra if r["dataset_case_id"] in keep]
    rb = [r for r in rb if r["dataset_case_id"] in keep]
    multi = any(max(collections.Counter(r["dataset_case_id"] for r in rr).values() or [0]) > 1 for rr in (ra, rb)
                if rr)
    names = relevant_metrics(ra + rb)
    rows = collections.OrderedDict()
    for n in names:
        meta = GM.METRICS[n]
        pa, pb = per_case(ra, n), per_case(rb, n)
        ids = [i for i in pa if i in pb]
        diffs = [sum(pb[i]) / len(pb[i]) - sum(pa[i]) / len(pa[i]) for i in ids]
        sgn = 1 if meta["better"] == "higher" else -1
        wins = sum(1 for d in diffs if sgn * d > 1e-12)
        losses = sum(1 for d in diffs if sgn * d < -1e-12)
        ties = len(diffs) - wins - losses
        p1, p2 = sign_p(wins, losses), sign_two_sided(wins, losses)
        verdict = "no evidence"
        if p2 <= VERDICT_P and wins != losses:
            verdict = "better" if wins > losses else "worse"
        row = collections.OrderedDict([
            ("n", len(ids)), ("base_mean", _r(sum(sum(pa[i]) / len(pa[i]) for i in ids) / len(ids)) if ids else None),
            ("cand_mean", _r(sum(sum(pb[i]) / len(pb[i]) for i in ids) / len(ids)) if ids else None),
            ("mean_diff", _r(sum(diffs) / len(diffs)) if diffs else None),
            ("base_total", _r(sum(sum(pa[i]) / len(pa[i]) for i in ids))),
            ("cand_total", _r(sum(sum(pb[i]) / len(pb[i]) for i in ids))),
            ("wins", wins), ("losses", losses), ("ties", ties), ("p_one_sided", _r(p1, 6)),
            ("p_two_sided", _r(p2, 6)), ("verdict", verdict)])
        if multi and diffs:
            lo, hi = bootstrap_ci(diffs)
            row["mean_diff_bootstrap"] = [_r(lo), _r(hi)]
        if meta["kind"] == "binary":
            row["transitions"] = transitions(pa, pb, ids)
        rows[n] = row
    suite = ma["suite"]
    hl = GM.headline(suite) if suite in ("L", "F", "V") else None
    h = rows.get(hl) or {}
    x_up = [n for n in names if n.startswith("x_") and GM.METRICS[n]["kind"] == "count"
            and (rows[n]["cand_total"] or 0) > (rows[n]["base_total"] or 0)]
    headline_ok = bool(h) and h["p_one_sided"] <= RULE_P_ONE_SIDED and h["wins"] - h["losses"] >= RULE_MIN_NET_WINS
    rule = collections.OrderedDict([
        ("text", DECISION_RULE), ("headline", hl), ("headline_ok", headline_ok),
        ("headline_wins_minus_losses", (h.get("wins", 0) - h.get("losses", 0)) if h else None),
        ("headline_p_one_sided", h.get("p_one_sided")),
        ("x_count_totals_not_higher", not x_up), ("x_count_metrics_higher", x_up),
        ("dev_split", ma["split"] == "dev"),
        ("other_suites", "not checked here: run summary.py compare on the other suites' runs; none may show a "
                         "'worse' headline verdict"),
        ("eligible_on_this_suite", headline_ok and not x_up and ma["split"] == "dev"),
        ("next", "confirm once on the holdout (and FAITHFUL when an L4 is available) before shipping"),
    ])
    result = collections.OrderedDict([
        ("schema", "golden-compare-v1"),
        ("base", dict(ma, dir=base_dir, providers=providers_of(A))),
        ("candidate", dict(mb, dir=cand_dir, providers=providers_of(B))),
        ("mixed_labels", ma["label"] != mb["label"]), ("mixed_models", ma["model"] != mb["model"]),
        ("mixed_providers", providers_of(A) != providers_of(B)),
        ("paired_cases", len(keep)), ("only_in_base", sorted(set(fa) - set(fb))),
        ("only_in_candidate", sorted(set(fb) - set(fa))), ("fixture_changed_dropped", changed),
        ("samples_gt_1", multi), ("pairing", "CHAIN: paired by case id, fixture shas differ by design"
                                  if pair_by_task else "by dataset_case_id and fixture sha"),
        ("fixture_shas", chain_shas), ("metrics", rows), ("decision_rule", rule),
        ("note", "agents-cli eval compare is a key-level JSON diff with no pairing or statistics; decisions use this "
                 "file."),
    ])
    return [], result


def transition_md(name, tr):
    """The headline's 2x2 transition table as markdown lines (a note when it has several samples per case)."""
    if not name:
        return []
    if not tr:
        return ["Transition table for %s: not shown (more than one sample per case; read wins and losses)." % name, ""]
    k = tr["counts"]
    lines = ["Transition table for %s (paired cases, base rows -> candidate columns):" % name, "",
             "| base \\ candidate | 1 | 0 |", "|---|---|---|",
             "| 1 | %d | %d |" % (k["1->1"], k["1->0"]), "| 0 | %d | %d |" % (k["0->1"], k["0->0"]), ""]
    for key, what in (("0->1", "0 -> 1"), ("1->0", "1 -> 0")):
        ids = tr["flips"][key]
        lines.append("%s (%d): %s" % (what, len(ids), ", ".join(ids[:20]) + (" ..." if len(ids) > 20 else "")
                                      if ids else "none"))
    return lines + [""]


def compare_md(C):
    b, c, rule = C["base"], C["candidate"], C["decision_rule"]
    chain = str(C.get("pairing") or "").startswith("CHAIN")
    lines = ["# Golden eval comparison%s: %s -> %s" % (" (CHAIN)" if chain else "", b["run_id"], c["run_id"]), "",
             "Suite %s, split %s, labels %s -> %s%s. Paired cases: %d (only in base %d, only in candidate %d, fixture "
             "changed and dropped %d%s)." % (
                 b["suite"], b["split"], b["label"], c["label"], " (MIXED)" if C["mixed_labels"] else "",
                 C["paired_cases"], len(C["only_in_base"]), len(C["only_in_candidate"]),
                 len(C["fixture_changed_dropped"]),
                 (": " + ", ".join(C["fixture_changed_dropped"][:10])) if C["fixture_changed_dropped"] else ""), "",
             "Decision rule on this suite: headline %s %s (wins - losses %s, one-sided p %s); X count totals not "
             "higher: %s%s; dev split: %s -> **%s**." % (
                 rule["headline"], "met" if rule["headline_ok"] else "not met", rule["headline_wins_minus_losses"],
                 rule["headline_p_one_sided"], rule["x_count_totals_not_higher"],
                 (" (higher: " + ", ".join(rule["x_count_metrics_higher"]) + ")") if rule["x_count_metrics_higher"]
                 else "", rule["dev_split"], "ELIGIBLE on this suite" if rule["eligible_on_this_suite"]
                 else "NOT ELIGIBLE"),
             "Other suites: %s. Then: %s." % (rule["other_suites"], rule["next"]), "",
             "The verdict column uses two-sided p <= 0.05; the pre-registered rule uses one-sided p <= 0.10 with "
             "wins - losses >= 3, so a change can be eligible while its verdict reads 'no evidence'.", ""]
    if chain:
        lines += ["CHAIN pairing: each arm's F cases carry that arm's own locator plan, so the fixtures differ by design "
                  "and the cases are paired by case id. Fixture shas (base / candidate):", ""]
        lines += ["- %s: %s / %s" % (i, ",".join(x[:12] for x in v[0]), ",".join(x[:12] for x in v[1]))
                  for i, v in (C.get("fixture_shas") or {}).items()]
        lines += [""]
    lines += transition_md(rule["headline"], (C["metrics"].get(rule["headline"]) or {}).get("transitions"))
    lines += ["| metric | better | n | base | cand | diff | W | L | T | p one-sided | p two-sided | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in C["metrics"].items():
        lines.append("| %s | %s | %d | %s | %s | %s | %d | %d | %d | %s | %s | %s |" % (
            n, GM.METRICS[n]["better"], r["n"], _fmt(r["base_mean"]), _fmt(r["cand_mean"]), _fmt(r["mean_diff"]),
            r["wins"], r["losses"], r["ties"], _fmt(r["p_one_sided"]), _fmt(r["p_two_sided"]), r["verdict"]))
    lines += ["", DECISION_RULE, "", C["note"]]
    return "\n".join(lines) + "\n"


def cmd_compare(a):
    try:
        why, C = compare(a.base, a.cand, a.allow_mixed, getattr(a, "pair_by_task", False))
    except ValueError as e:
        print("compare: %s" % e, file=sys.stderr)
        return 2
    if why:
        for w in why:
            print("REFUSED: " + w, file=sys.stderr)
        return 2
    out = a.out or a.cand
    os.makedirs(out, exist_ok=True)
    _write(os.path.join(out, "compare.json"), C)
    _write(os.path.join(out, "compare.md"), compare_md(C))
    rule = C["decision_rule"]
    hl = C["metrics"].get(rule["headline"]) or {}
    print("%s: W %s L %s T %s, p one-sided %s, two-sided %s -> %s; rule on this suite: %s" % (
        rule["headline"], hl.get("wins"), hl.get("losses"), hl.get("ties"), hl.get("p_one_sided"),
        hl.get("p_two_sided"), hl.get("verdict"), "ELIGIBLE" if rule["eligible_on_this_suite"] else "NOT ELIGIBLE"))
    return 0


# ---------------------------------------------------------------------------------------------------------------------
# ablation (docs/eval/ABLATION_REPAIR.md, addendum 2026-09-30)
# ---------------------------------------------------------------------------------------------------------------------
def original_rule(ab, aa):
    """The 2026-09-29 rule, SUPERSEDED (biased toward CUT: a signed net against an unsigned flip total). Kept so the
    output shows what it would have said. ab, aa: transition counts {"0->1", "1->0", ...} of A0->B2 and A0->A0'."""
    net = ab["0->1"] - ab["1->0"]
    noise = aa["0->1"] + aa["1->0"]
    if net - noise >= 3 and ab["1->0"] <= 1:
        verdict = "KEEP"
    elif net <= noise:
        verdict = "CUT"
    else:
        verdict = "INCONCLUSIVE"
    return collections.OrderedDict([("verdict", verdict), ("net", net), ("noise_flip_total", noise)])


def calibration(aa):
    """A0 -> A0' (identical arms): FAILS when |net'| >= 3 and the one-sided sign test in net's direction is <= 0.10."""
    w, l = aa["0->1"], aa["1->0"]
    net = w - l
    p = sign_p(w, l) if net > 0 else sign_p(l, w)
    ok = not (abs(net) >= ABL_CAL_NET and p <= RULE_P_ONE_SIDED)
    return collections.OrderedDict([("wins", w), ("losses", l), ("net", net), ("p_one_sided_in_direction", _r(p, 6)),
                                    ("ok", ok)])


def ablation_verdict(ab, aa, a0_repair_share=0.0):
    """The addendum's rule on A0 -> B2 (ab) with A0 -> A0' (aa) as calibration and the A0 compliance share."""
    w, l = ab["0->1"], ab["1->0"]
    net, p1 = w - l, sign_p(w, l)
    cal = calibration(aa)
    compliant = a0_repair_share <= ABL_COMPLIANCE_MAX + 1e-12
    if not cal["ok"]:
        verdict, why = "INCONCLUSIVE", "calibration failed: identical arms A0 and A0' differ by net %d (one-sided p " \
                                       "%s); check the provider pin and settings, rerun all three arms" % (
                                           cal["net"], cal["p_one_sided_in_direction"])
    elif not compliant:
        verdict, why = "INCONCLUSIVE", "compliance failed: %.0f %% of A0 case samples edited after their first " \
                                       "verify.py (> %d %%); the arms differ less than designed" % (
                                           100 * a0_repair_share, int(100 * ABL_COMPLIANCE_MAX))
    elif p1 <= RULE_P_ONE_SIDED and net >= RULE_MIN_NET_WINS and l <= ABL_MAX_DAMAGE:
        verdict, why = "KEEP", "one-sided p %s <= %.2f, net %d >= %d, damage %d <= %d" % (
            _r(p1, 6), RULE_P_ONE_SIDED, net, RULE_MIN_NET_WINS, l, ABL_MAX_DAMAGE)
    elif net <= 0:
        verdict, why = "CUT", "net %d <= 0: repair adds no solves over the first attempt" % net
    else:
        verdict, why = "INCONCLUSIVE", "net %d, one-sided p %s, damage %d: run one more A0/B2 pair at the same " \
                                       "settings and read it alone by this rule" % (net, _r(p1, 6), l)
    return collections.OrderedDict([
        ("verdict", verdict), ("why", why), ("wins", w), ("losses", l), ("net", net), ("damage", l),
        ("p_one_sided", _r(p1, 6)), ("p_two_sided", _r(sign_two_sided(w, l), 6)), ("calibration", cal),
        ("a0_repair_share", _r(a0_repair_share)), ("compliance_ok", compliant)])


def repair_edits(inst):
    """Edit calls (edit.py, or the forbidden edit_file/write_file) after the fixer's first verify.py run without
    --repro-only, in its first stage-run: the repair the A0 prompt forbids. 0 when verify never ran."""
    if inst is None:
        return 0
    c = GM._ctx(inst)
    seen, n = False, 0
    for u in GM._uses(GM._stage(c)):
        cmd = u["cmd"] if u["name"] == "run_command" else ""
        if not seen:
            seen = bool(GM.VERIFY_CMD.search(cmd)) and "--repro-only" not in cmd
        elif GM.EDIT_CMD.search(cmd) or u["name"] in ("edit_file", "write_file"):
            n += 1
    return n


def _arm_cases(R):
    """{dataset_case_id: {scores, fixture, reproducible, repairs, calls, llm_calls, tokens, wall}} over counted
    records whose f_hidden_pass applies."""
    out = collections.OrderedDict()
    for r in sorted(R["records"], key=lambda r: (r["dataset_case_id"], r["sample"] or 0)):
        if r["status"] not in GM.COUNTED_STATUS or r["instance"] is None:
            continue
        res = r["scores"].get(ABL_HEADLINE)
        if res is None or not GM.explain(res)[0]:
            continue
        c = out.setdefault(r["dataset_case_id"], {"scores": [], "fixture": set(), "reproducible": r["reproducible"],
                                                  "repairs": [], "calls": [], "llm_calls": [], "tokens": [],
                                                  "wall": []})
        c["scores"].append(res["score"])
        c["fixture"].add(r["fixture_sha"])
        c["repairs"].append(repair_edits(r["instance"]))
        fc = r["scores"].get("f_calls")
        if fc is not None and GM.explain(fc)[0]:
            c["calls"].append(fc["score"])
        c["llm_calls"].append(r["live_llm_calls"])
        c["tokens"].append(r["live_completion_tokens"])
        if r["wall_s"] is not None:
            c["wall"].append(r["wall_s"])
    return out


def _majority(scores):
    return 1 if sum(scores) / len(scores) > 0.5 else 0


def _table(xa, xb, ids):
    counts = collections.OrderedDict((k, 0) for k in TRANSITION_KEYS)
    flips = collections.OrderedDict((k, []) for k in ("0->1", "1->0"))
    for i in ids:
        k = "%d->%d" % (xa[i], xb[i])
        counts[k] += 1
        if k in flips:
            flips[k].append(i)
    return collections.OrderedDict([("counts", counts), ("flips", flips)])


def _mean(xs):
    return _r(sum(xs) / len(xs)) if xs else None


def ablation_refusals(runs, allow_unscaled=False):
    """runs: [("A0", R), ("B2", R), ("A0'", R)]."""
    why = []
    for name, R in runs:
        run, meta = R["run"], run_meta(R)
        if meta["suite"] != "F":
            why.append("%s is suite %s: the addendum narrows the ablation to suite F (the fixer's loop)" % (
                name, meta["suite"]))
        if meta["split"] != "dev":
            why.append("%s is split %s: the ablation runs on dev only (the holdout stays untouched)" % (
                name, meta["split"]))
        if run.get("status") == "interrupted":
            why.append("%s was interrupted: finish it with run_suite.py ... --resume first" % name)
        st = collections.Counter(r["status"] for r in R["records"])
        att = sum(v for k, v in st.items() if k != "skipped")
        if att and st["infra_error"] / att > INFRA_MAX:
            why.append("%s has %d of %d infra_error cases (> %d %%)" % (name, st["infra_error"], att,
                                                                      int(INFRA_MAX * 100)))
        samples = run.get("samples")
        if isinstance(samples, int) and samples % 2 == 0:
            why.append("%s has --samples %d: the per-case majority needs an odd count (1 or 3)" % (name, samples))
        if meta["label"] == "PROXY":
            if not run.get("or_provider"):
                why.append("%s is PROXY without a provider pin (run_suite.py --or-provider): its calls can land on "
                           "fp4, fp8 or bf16 deployments" % name)
            if float(run.get("l4_scale") or 1.0) == 1.0 and not allow_unscaled:
                why.append("%s is PROXY at --l4-scale 1.0: the helper clock and the t=300 cap run on proxy wall "
                           "time, so the rounds that fit are the proxy's; pass the smoke's measured L4/proxy ratio "
                           "(or --allow-unscaled)" % name)
    base = runs[0][1]["run"]
    for name, R in runs[1:]:
        for k in ABL_SETTINGS:
            a_v = base.get(k) if k != "label" else run_meta(runs[0][1])["label"]
            b_v = R["run"].get(k) if k != "label" else run_meta(R)["label"]
            if k == "l4_clock":
                a_v, b_v = a_v or "wall", b_v or "wall"
            if a_v != b_v:
                why.append("%s differs from A0 in %s: %r vs %r (every arm pins the same settings)" % (name, k, b_v, a_v))
        if providers_of(R) != providers_of(runs[0][1]):
            why.append("%s was served by providers %s, A0 by %s" % (name, providers_of(R), providers_of(runs[0][1])))
    sha = {name: run_meta(R)["bundle_sha"] for name, R in runs}
    if sha["A0"] != sha["A0'"]:
        why.append("A0' must repeat A0's bundle: bundle sha %s vs %s" % (str(sha["A0'"])[:12], str(sha["A0"])[:12]))
    if sha["B2"] == sha["A0"]:
        why.append("B2 has A0's bundle (%s): build A0 with make_variant.py --repair-rounds 0" % str(sha["A0"])[:12])
    return why


def ablation(a0_dir, b2_dir, a0p_dir, allow_unscaled=False):
    """-> (refusal reasons, result)."""
    runs = [("A0", load_run(a0_dir)), ("B2", load_run(b2_dir)), ("A0'", load_run(a0p_dir))]
    why = ablation_refusals(runs, allow_unscaled)
    if why:
        return why, None
    arms = collections.OrderedDict((name, _arm_cases(R)) for name, R in runs)
    samples = [R["run"].get("samples") for _, R in runs if isinstance(R["run"].get("samples"), int)]
    want = samples[0] if samples else max((len(c["scores"]) for a in arms.values() for c in a.values()), default=1)
    ids, dropped = [], collections.OrderedDict()
    for i in sorted(set().union(*[set(a) for a in arms.values()])):
        miss = [n for n, a in arms.items() if i not in a]
        if miss:
            dropped[i] = "not applicable or not ok in " + ", ".join(miss)
            continue
        short = ["%s %d" % (n, len(a[i]["scores"])) for n, a in arms.items() if len(a[i]["scores"]) != want]
        if short:
            dropped[i] = "samples %s of %d" % (", ".join(short), want)
            continue
        fx = [a[i]["fixture"] for a in arms.values()]
        if any(f != fx[0] or len(f) != 1 for f in fx):
            dropped[i] = "fixture changed between arms"
            continue
        ids.append(i)
    if not ids:        # net 0 on no data would read as CUT
        return ["no case is paired across the three arms (%d dropped): nothing to decide on" % len(dropped)], None
    out = {n: {i: _majority(a[i]["scores"]) for i in ids} for n, a in arms.items()}
    ab, aa = _table(out["A0"], out["B2"], ids), _table(out["A0"], out["A0'"], ids)
    a0_samples = sum(len(arms["A0"][i]["repairs"]) for i in ids)
    a0_repaired = sum(1 for i in ids for x in arms["A0"][i]["repairs"] if x > 0)
    share = a0_repaired / a0_samples if a0_samples else 0.0
    rule = ablation_verdict(ab["counts"], aa["counts"], share)
    slices = collections.OrderedDict()
    for key in ("True", "False", "None"):
        sub = [i for i in ids if str(arms["A0"][i]["reproducible"]) == key]
        if sub:
            slices[key] = collections.OrderedDict([("n", len(sub)), ("A0->B2", _table(out["A0"], out["B2"], sub)),
                                                   ("A0->A0'", _table(out["A0"], out["A0'"], sub))])
    per_arm = collections.OrderedDict()
    for n, a in arms.items():
        k = sum(out[n][i] for i in ids)
        lo, hi = wilson(k, len(ids))
        flat = lambda key: [x for i in ids for x in a[i][key]]
        calls, llm, tok = flat("calls"), flat("llm_calls"), flat("tokens")
        per_arm[n] = collections.OrderedDict([
            ("majority_pass", k), ("n", len(ids)), ("wilson", [_r(lo), _r(hi)]),
            ("sample_pass_rate", _mean(flat("scores"))),
            ("repair_share", _r(sum(1 for x in flat("repairs") if x > 0) / len(flat("repairs"))) if ids else None),
            ("tool_calls_mean", _mean(calls)), ("llm_calls_mean", _mean(llm)), ("completion_tokens_mean", _mean(tok)),
            ("wall_s_mean", _mean(flat("wall"))),
            ("l4_projected_s_mean", _r(L4_STEP_S * sum(llm) / len(llm) + L4_TOKEN_S * sum(tok) / len(tok))
             if llm else None)])
    meta = {n: dict(run_meta(R), dir=d, providers=providers_of(R), l4_scale=R["run"].get("l4_scale"),
                    or_provider=R["run"].get("or_provider"), samples=R["run"].get("samples"))
            for (n, R), d in zip(runs, (a0_dir, b2_dir, a0p_dir))}
    unscaled = any(m["label"] == "PROXY" and float(m["l4_scale"] or 1.0) == 1.0 for m in meta.values())
    result = collections.OrderedDict([
        ("schema", "golden-ablation-v1"), ("preregistration", "docs/eval/ABLATION_REPAIR.md (addendum 2026-09-30)"),
        ("arms", meta), ("samples", want), ("paired_cases", len(ids)), ("dropped", dropped),
        ("A0->B2", ab), ("A0->A0'", aa), ("by_reproducible", slices), ("rule", rule),
        ("original_rule_superseded", original_rule(ab["counts"], aa["counts"])), ("per_arm", per_arm),
        ("unscaled_proxy_clock", unscaled),
        ("notes", ["Scope: the fixer's repair loop only; suite F scripts the verifier, whose loop never runs here.",
                   "Damage is measured without finalize: F grades the fixer's raw tree, while the pipeline's "
                   "finalize.py restores the best checkpoint when the current tree scores worse, so F's damage is an "
                   "upper bound of the pipeline's.",
                   "Reproducible cases carry a gold-validated reproduction, a better repair signal than a real "
                   "locator's; read the by_reproducible tables.",
                   "Per-case outcome = majority over its samples; A PROXY verdict is a screen: KEEP or CUT is "
                   "confirmed with one paired Kaggle-L4 FAITHFUL run before it ships."]),
    ])
    return [], result


def _table_md(title, tr):
    k = tr["counts"]
    lines = ["%s:" % title, "", "| \\ | 1 | 0 |", "|---|---|---|", "| 1 | %d | %d |" % (k["1->1"], k["1->0"]),
             "| 0 | %d | %d |" % (k["0->1"], k["0->0"]), ""]
    for key in ("0->1", "1->0"):
        ids = tr["flips"][key]
        lines.append("%s (%d): %s" % (key.replace("->", " -> "), len(ids), ", ".join(ids) if ids else "none"))
    return lines + [""]


def ablation_md(A):
    rule, orig = A["rule"], A["original_rule_superseded"]
    lines = ["# Repair ablation: %s" % rule["verdict"], "",
             "Pre-registration: %s. Arms: A0 %s, B2 %s, A0' %s (label %s, provider pin %s, --l4-scale %s, samples %s)."
             % (A["preregistration"], A["arms"]["A0"]["run_id"], A["arms"]["B2"]["run_id"], A["arms"]["A0'"]["run_id"],
                A["arms"]["A0"]["label"], A["arms"]["A0"]["or_provider"], A["arms"]["A0"]["l4_scale"], A["samples"]),
             "", "Paired cases: %d (dropped %d%s)." % (
                 A["paired_cases"], len(A["dropped"]),
                 (": " + "; ".join("%s: %s" % kv for kv in list(A["dropped"].items())[:10])) if A["dropped"] else ""),
             "", "**Verdict: %s** (%s)." % (rule["verdict"], rule["why"]),
             "A0 -> B2: wins %d, losses %d, net %d, damage %d, one-sided p %s, two-sided p %s." % (
                 rule["wins"], rule["losses"], rule["net"], rule["damage"], rule["p_one_sided"], rule["p_two_sided"]),
             "Calibration A0 -> A0': net %d, one-sided p in its direction %s: %s." % (
                 rule["calibration"]["net"], rule["calibration"]["p_one_sided_in_direction"],
                 "ok" if rule["calibration"]["ok"] else "FAILED"),
             "Compliance: %.0f %% of A0 case samples edited after their first verify.py: %s." % (
                 100 * (rule["a0_repair_share"] or 0), "ok" if rule["compliance_ok"] else "FAILED"),
             "Original 2026-09-29 rule (SUPERSEDED, biased toward CUT): %s (net %d against flip total %d)." % (
                 orig["verdict"], orig["net"], orig["noise_flip_total"])]
    if A["unscaled_proxy_clock"]:
        lines.append("WARNING: PROXY at --l4-scale 1.0 (--allow-unscaled): the rounds that fit are the proxy's.")
    lines.append("")
    lines += _table_md("A0 -> B2 (A0 rows, B2 columns)", A["A0->B2"])
    lines += _table_md("A0 -> A0' (noise floor)", A["A0->A0'"])
    for key, sl in A["by_reproducible"].items():
        lines += _table_md("A0 -> B2, reproducible %s (%d cases)" % (key, sl["n"]), sl["A0->B2"])
        lines += _table_md("A0 -> A0', reproducible %s" % key, sl["A0->A0'"])
    lines += ["| arm | majority pass | Wilson 95 % | sample pass rate | repair share | tool calls | LLM calls | "
              "completion tokens | wall s | L4-projected s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n, m in A["per_arm"].items():
        lines.append("| %s | %d/%d | [%s, %s] | %s | %s | %s | %s | %s | %s | %s |" % (
            n, m["majority_pass"], m["n"], _fmt(m["wilson"][0]), _fmt(m["wilson"][1]), _fmt(m["sample_pass_rate"]),
            _fmt(m["repair_share"]), _fmt(m["tool_calls_mean"]), _fmt(m["llm_calls_mean"]),
            _fmt(m["completion_tokens_mean"]), _fmt(m["wall_s_mean"]), _fmt(m["l4_projected_s_mean"])))
    lines += [""] + ["- " + x for x in A["notes"]]
    return "\n".join(lines) + "\n"


def cmd_ablation(a):
    try:
        why, A = ablation(a.a0, a.b2, a.a0p, a.allow_unscaled)
    except ValueError as e:
        print("ablation: %s" % e, file=sys.stderr)
        return 2
    if why:
        for w in why:
            print("REFUSED: " + w, file=sys.stderr)
        return 2
    out = a.out or a.b2
    os.makedirs(out, exist_ok=True)
    _write(os.path.join(out, "ablation.json"), A)
    _write(os.path.join(out, "ablation.md"), ablation_md(A))
    r = A["rule"]
    print("ablation (%d paired cases): A0->B2 W %d L %d net %d, one-sided p %s; A0->A0' net %d (calibration %s); "
          "compliance %s -> %s; original rule (superseded) %s" % (
              A["paired_cases"], r["wins"], r["losses"], r["net"], r["p_one_sided"], r["calibration"]["net"],
              "ok" if r["calibration"]["ok"] else "FAILED", "ok" if r["compliance_ok"] else "FAILED", r["verdict"],
              A["original_rule_superseded"]["verdict"]))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compare":
        ap = argparse.ArgumentParser(prog="summary.py compare", description="paired comparison of two golden runs")
        ap.add_argument("base")
        ap.add_argument("cand")
        ap.add_argument("--allow-mixed", action="store_true", help="compare runs with different labels")
        ap.add_argument("--pair-by-task", action="store_true",
                        help="pair by case id although fixture shas differ (the L-to-F chain; labelled CHAIN)")
        ap.add_argument("--out", help="directory for compare.json and compare.md (default: CAND_RUN)")
        return cmd_compare(ap.parse_args(argv[1:]))
    if argv and argv[0] == "ablation":
        ap = argparse.ArgumentParser(prog="summary.py ablation",
                                     description="the repair ablation of docs/eval/ABLATION_REPAIR.md (A0, B2, A0')")
        ap.add_argument("a0")
        ap.add_argument("b2")
        ap.add_argument("a0p")
        ap.add_argument("--allow-unscaled", action="store_true", help="accept PROXY arms at --l4-scale 1.0 (flagged)")
        ap.add_argument("--out", help="directory for ablation.json and ablation.md (default: B2_RUN)")
        return cmd_ablation(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(prog="summary.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--out", help="directory for summary.json and summary.md (default: RUN_DIR)")
    ap.add_argument("--holdout-log", default=HOLDOUT_LOG)
    ap.add_argument("--no-l4-ref", action="store_true", help="skip the Kaggle L4 latency reference")
    return cmd_summary(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
