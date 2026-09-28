"""Counterfactual L4 replay (SPEC 9.1, R116, R117) and the race-2 KPIs (SPEC 10.3, R118). Stdlib only, <1 s per run.

Ports docs/v10/design_B_replay.py (loader, collapse rules, cost model) and docs/v10/final_replay.py (the final v10
rules) without changing a number, so both reproduce SPEC section 9's table.

Cost model (research/time_model.md 2, fitted on 6,730 Kaggle 4xL4 calls; own_data.md 11 for the x1.08):
    call = 1.08 x (0.085 s + 28.5 ms x output tokens + 0.65 ms x uncached prompt tokens) + tool seconds from the trace.

Modes (all print one summary line; --json prints a machine-readable object instead):
  --baseline [--base r_v4]                        v4 as-is, 150.2 s/task on eval/race1/runs
  --design final [--base r_v9_eog] [--stretch 2] [--pessimistic] [--loc-cut 150] [--measured] [--no-cuts]
                                                  the SPEC 9.1 v10 counterfactual (154.0 on r_v9_eog). --measured keeps
                                                  each trajectory's measured stage replies, cut only at v10's
                                                  max_output_tokens; --no-cuts drops the footer-time cuts (review
                                                  round 2: the real pessimistic row, 172.6 on r_v9_eog)
  --run DIR [--against r_v4] [--ratio 1.08]       ship gate R117 (restated in review round 2 for the cap-saturated
                                                  regime): re-time every call of a real run with the L4 model (plus
                                                  5.6 s per detected compaction, time_model 3.4). PASS = no task past
                                                  cap + 10 s and the N=130 hidden-run projection under 12 h. The mean
                                                  against the --against run's as-is replay on the SAME task ids is
                                                  reported; above --ratio it names the pre-registered knob to apply.
                                                  Exit 0 = PASS, 1 = FAIL.
  --race2 DIR [--control r2_v9_eog] [--treatment r2_v10] [--runs 2]
                                                  every pre-registered KPI of docs/v10/race2_checklist.md. Exit 0 only
                                                  when every row passes.
  --kill-check DIR                                the chain's kill rule after run 1 (SPEC 10.3): exit 3 = KILL.
A run name without a slash is resolved under --runs-dir (default eval/race1/runs).
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(ROOT, "eval", "race1", "runs")
OVH, DEC, PRE, FUDGE, CAP = 0.085, 0.0285, 0.00065, 1.08, 300.0
RUNS = ("r_v4", "r_v9_eog", "r_v9_c", "r_v9_eg", "r_v9_eo", "r_v9_og")
REPLY_CAP = {"locator": 200, "fixer": 100, "verifier": 60}
OUT_CAP = {"locator": 1536}
COMPACTION_LINE = 14336        # Kaggle token_threshold (HARNESS_README 553-561)
COMPACTION_EXTRA_S = 5.6       # median extra seconds of the call after a compaction on L4 (time_model 3.4)
GATE_RATIO, GATE_OVER_S = 1.08, 10.0
# R117 cliff projection (SPEC 9.2): hidden tasks take about 1.9x the public ones and are cap-saturated (v4: about
# 308 s/task on Kaggle); per task the wall is setup 3.6 + min(agent, cap + 5 s run_command overshoot) + teardown 1.
CLIFF_N, CLIFF_H, HIDDEN_STRETCH = 130, 12.0, 1.9
STARTUP_S, SETUP_S, TEARDOWN_S, OVERSHOOT_S = 600.0, 3.6, 1.0, 5.0
# Pre-registered (review round 2), applied in this order when the replayed mean is above GATE_RATIO x r_v4.
KNOBS = ("verifier repair rounds 2 -> 1 (prompts/verifier.md)", "LOCATOR banner 75 s -> 60 s (T_LOCATOR)")
# v10's max_output_tokens per stage (configs/gen_*.yaml): what --measured cuts measured replies at (review round 2).
MEASURED_REPLY_CAP = {"locator": 768, "fixer": 2048, "verifier": 2048}

# Pre-registered race-2 thresholds (docs/v10/race2_checklist.md; tests/test_v10_runner.py keeps the two in sync).
KPI = {
    "resolved_sum_margin": 6,       # v10 sum over the paired runs >= v9_eog sum + 6
    "resolved_run_floor": -3,       # no single run with v10 < v9_eog - 3
    "crashes_max": 0,               # per crash class, v10 runs
    "helper_ok_min": 0.98,          # install or bootstrap succeeded, share of tasks
    "cant_open_per_task_max": 1 / 50,
    "malformed_edit_per_task_max": 1.0,
    "protected_patches_max": 0,
    "scratch_patches_max": 0,
    "empty_patches_max": 2,         # per 74-task run
    "stage_under_line_min": 0.95,   # stage-runs whose max prompt < 14,336
    "prompt_max": 26000,
    "verdict_share_min": 0.90,      # tasks with a VERIFY verdict line
    "time_ratio_max": GATE_RATIO,   # the knob trigger since review round 2, not a ship blocker
    "time_over_s": GATE_OVER_S,
    "time_proj_h_max": CLIFF_H,
    "time_n_hidden": CLIFF_N,
    "kill_floor": -3,               # after run 1: v10 < v9_eog - 3 kills the chain
}
CRASH = {
    "context_overflow": re.compile(r"ContextWindowExceeded|maximum context length|prompt contains at least", re.I),
    "unknown_tool": re.compile(r"Tool '[^']+' not found"),
    "key_error": re.compile(r"KeyError|Context variable not found"),
    "post_invocation": re.compile(r"No LlmAgent model available"),
}
SCRATCH_ROOT = re.compile(r"^(repro|reproduce|scratch|debug|tmp|temp|try|demo)[^/]*$|^test_[^/]*\.py$|^[^/]*_test\.py$", re.I)
SCRATCH_ANY = re.compile(r"\.(log|orig|rej|bak|swp)$|(^|/)\.coverage$")
VENDORED = re.compile(r"(^|/)(site-packages|_pytest|[^/]+\.dist-info)(/|$)")
VERDICT = re.compile(r"VERIFY: (GREEN|AMBER|RED|UNKNOWN)")
# The v10 footer hints (_swe_common: LOCATOR_HINT, EDIT_NOW_HINT, CONTEXT_HINT, FINISH_HINT, TIME_HINT). Review round 2:
# the time projection assumed the stages obey them; race 2 measures how often they do (reported, no threshold).
HINTS = (("LOCATOR", "LOCATOR: 75s used"), ("EDIT NOW", "EDIT NOW: no source file changed"),
         ("CONTEXT", "CONTEXT: this stage's context is nearly full"), ("FINISH", "FINISH: t>=210s"),
         ("TIME", "TIME: t>=250s"))


def resolve(run, runs_dir=RUNS_DIR):
    """A bare run name lives under runs_dir; anything with a path separator is a path."""
    if os.sep in run or os.path.isabs(run):
        return run
    cand = os.path.join(runs_dir, run)
    return cand if os.path.isdir(cand) else run


# ---------------------------------------------------------------------------------------------------------------------
# Loader (design_B_replay.load, extended with the fields the KPIs need)
# ---------------------------------------------------------------------------------------------------------------------
def _obs_text(s):
    o = s.get("observation")
    if isinstance(o, dict):
        return str(o.get("content") or "")
    return str(o or "")


def load(run, runs_dir=RUNS_DIR, keep_obs=False):
    d = resolve(run, runs_dir)
    res = {}
    rp = os.path.join(d, "task_results.jsonl")
    if os.path.isfile(rp):
        for line in open(rp):
            if line.strip():
                r = json.loads(line)
                res[r["instance_id"]] = r
    out = {}
    for fp in sorted(glob.glob(os.path.join(d, "traces", "trace_*.json"))):
        iid = os.path.basename(fp)[6:-5]
        steps, prev = [], {}
        for s in json.load(open(fp)).get("steps") or []:
            if s.get("source") != "agent":
                continue
            m, ex, tcs = s.get("metrics") or {}, s.get("extra") or {}, s.get("tool_calls") or []
            author = ex.get("author") or (tcs and (tcs[0].get("extra") or {}).get("author")) or "?"
            pt, ct = m.get("prompt_tokens"), m.get("completion_tokens") or 0
            if pt is None:
                continue
            p = prev.get(author)
            unc = max(0, pt - p[0] - p[1]) if p and pt >= p[0] else pt
            prev = {author: (pt, ct)}
            obs = str(s.get("observation") or "")   # design B matched on the repr (it carries extra.timestamp)
            ts = (tcs and (tcs[0].get("extra") or {}).get("timestamp")) or ex.get("timestamp")
            mo = re.search(r"'timestamp': ([0-9.]+)", obs[-400:])
            tool_s = max(0.0, float(mo.group(1)) - ts) if (mo and ts and tcs) else 0.0
            fn = tcs[0]["function_name"] if tcs else None
            args = json.dumps(tcs[0].get("arguments"), sort_keys=True) if tcs else ""
            kind = "ok"
            if not tcs:
                kind = "text"
            elif "mandatory input parameters are not present" in obs:
                kind = "malformed"
            elif fn == "edit_file" and ("not found" in obs or "No changes" in obs or '\\"status\\": \\"error' in obs):
                kind = "editfail"
            elif "BudgetExceeded" in obs or "budget exhausted" in obs.lower():
                kind = "postcap"
            step = dict(author=author, ct=ct, pt=pt, unc=unc, tool_s=min(tool_s, 180.0), fn=fn, args=args, kind=kind)
            if keep_obs:
                step["obs"] = _obs_text(s)[:20000]
            steps.append(step)
        rr = res.get(iid) or {}
        out[iid] = dict(steps=steps, resolved=bool(rr.get("resolved")), patch=int(rr.get("agent_patch_size") or 0),
                        row=rr)
    for iid, rr in res.items():   # a task without a trace (setup crash) still counts in the KPIs
        out.setdefault(iid, dict(steps=[], resolved=bool(rr.get("resolved")), patch=int(rr.get("agent_patch_size") or 0),
                                 row=rr))
    return out


def cost(s, ct=None):
    return FUDGE * (OVH + DEC * (s["ct"] if ct is None else ct) + PRE * s["unc"]) + s["tool_s"]


def asis(task):
    return min(CAP, sum(cost(s) for s in task["steps"]))


def compactions(task):
    """In-flow compactions visible in a trace: a call >= 14,336 prompt tokens followed by the same author's next call
    with a prompt under 70 % of it (gap_4 section 2 detection rule)."""
    n, last = 0, {}
    for s in task["steps"]:
        p = last.get(s["author"])
        if p is not None and p >= COMPACTION_LINE and s["pt"] < 0.7 * p:
            n += 1
        last[s["author"]] = s["pt"]
    return n


def retime(task):
    """Unclamped L4 projection of a real run: every call re-timed plus the measured compaction overhead."""
    return sum(cost(s) for s in task["steps"]) + COMPACTION_EXTRA_S * compactions(task)


# ---------------------------------------------------------------------------------------------------------------------
# design B collapse rules + the final v10 design (final_replay.final)
# ---------------------------------------------------------------------------------------------------------------------
def stages(task, drop_vgate=True, reply_cap=None, out_cap=None):
    reply_cap = REPLY_CAP if reply_cap is None else reply_cap
    out_cap = OUT_CAP if out_cap is None else out_cap
    stt, seen, streak, nchecks = collections.defaultdict(float), collections.Counter(), False, 0
    for s in task["steps"]:
        a = s["author"] if s["author"] in ("locator", "fixer", "verifier") else "fixer"
        if s["kind"] in ("malformed", "editfail"):
            if streak:
                continue
            streak = True
        elif s["fn"] is not None:
            streak = False
        if s["kind"] == "postcap":
            continue
        seen[(a, s["fn"], s["args"])] += 1
        if s["fn"] in ("run_command", "read_file") and seen[(a, s["fn"], s["args"])] >= 3:
            continue
        ct = min(s["ct"], out_cap.get(a, 2048))
        if s["kind"] == "text":
            ct = min(ct, reply_cap[a])
        if a == "verifier":
            if s["fn"] in ("submit_patch", "get_status") or s["kind"] == "text" or "git diff" in s["args"] or "preflight" in s["args"]:
                continue
            if drop_vgate and ("gate.py" in s["args"] or "repro" in s["args"] or "pytest" in s["args"]):
                nchecks += 1
                continue
            a = "fixer"
        stt[a] += cost(s, ct=ct)
    stt["check"] = max(1, nchecks // 2) * (FUDGE * (OVH + DEC * 40 + PRE * 700) + 5.0)
    return stt


def call(n, out, unc, tool=0.0):
    return FUDGE * (n * OVH + out * DEC + unc * PRE) + tool


REPRO = 1.3 * call(1, 300, 500, 2.0)   # repro heredoc + one verify --repro-only run
CLAIMS = call(0, 60, 0, 0.5)           # '# CLAIM n:' header lines + per-claim processes


def final(task, stretch=1.0, loc_cut=95.0, pessim=False, measured=False, cuts=True):
    """The SPEC 9.1 v10 counterfactual. measured: stage replies as measured, cut only at MEASURED_REPLY_CAP (the default
    caps them at REPLY_CAP 200/100/60). cuts=False: no footer-time cuts, every stage runs its whole replayed length
    (review round 2: the default cuts make '0 tasks at the cap' a property of the model)."""
    caps = (MEASURED_REPLY_CAP, {"locator": MEASURED_REPLY_CAP["locator"]}) if measured else (None, None)
    s = stages(task, drop_vgate=not pessim, reply_cap=caps[0], out_cap=caps[1])
    t = call(2, 40, 6000, 0.4)                                        # setup
    loc = stretch * (s["locator"] + REPRO + CLAIMS)
    fix = stretch * (s["fixer"] + call(1, 40, 700, 2.0))              # + one verify.py (cached original)
    ver = call(5, 190, 3000 + 4 * 600, 8.0) + stretch * s["check"]    # status, verify, finalize, submit, reply
    sub = 0.05 * call(3, 60, 3500, 1.0)                               # submitter backstop
    if not cuts:
        return min(CAP, t + loc + fix + ver + sub)
    t += min(loc, (150.0 if pessim else loc_cut) - t)                 # LOCATOR banner at 75 s -> reply by ~95 s
    t += min(fix, max(0.0, 210.0 - t))                                # FINISH footer at 210 s
    t += min(ver, max(12.0, 262.0 - t))                               # TIME footer at 250 s -> finalize + submit
    t += sub
    return min(CAP, t)


# ---------------------------------------------------------------------------------------------------------------------
# R117 gate
# ---------------------------------------------------------------------------------------------------------------------
def cliff_hours(raw, n=CLIFF_N, stretch=HIDDEN_STRETCH, cap=CAP):
    """Whole-run wall (h) of n hidden tasks shaped like `raw` (re-timed seconds per task): startup, then per task
    setup + min(stretch x agent, cap + overshoot) + teardown (SPEC 9.2, H1). At most (600 + n x 309.6) / 3600."""
    vals = list(raw)
    if not vals:
        return 0.0
    per = st.mean(SETUP_S + min(cap + OVERSHOOT_S, stretch * x) + TEARDOWN_S for x in vals)
    return (STARTUP_S + n * per) / 3600.0


def gate(run_data, base_data, ratio=GATE_RATIO, over_s=GATE_OVER_S, cap=CAP):
    """R117, restated in review round 2 for the cap-saturated regime the 12 h cliff lives in. PASS = no task projected
    past cap + over_s AND the CLIFF_N hidden-run projection under CLIFF_H. The replayed mean against base_data on the
    same ids is reported; above `ratio` (ratio_ok False) the first pre-registered knob is named. On public-like tasks
    v10 projects 0.93-1.09 x v4 with the footers obeyed and 0.96-1.15 x without (SPEC 9.1), about 6.3 h in total, so
    the ratio says nothing about the cliff; the cap does."""
    ids = sorted(set(run_data) & set(base_data))
    if not ids:
        return {"pass": False, "why": "no common task ids", "n": 0}
    raw = {i: retime(run_data[i]) for i in ids}
    run_mean = st.mean(min(cap, raw[i]) for i in ids)
    base_mean = st.mean(asis(base_data[i]) for i in ids)
    over = sorted(i for i in ids if raw[i] > cap + over_s)
    r = run_mean / base_mean if base_mean else float("inf")
    proj = cliff_hours(raw.values(), cap=cap)
    ratio_ok = r <= ratio
    return {"pass": not over and proj < CLIFF_H, "n": len(ids), "run_mean": round(run_mean, 1),
            "base_mean": round(base_mean, 1), "ratio": round(r, 3), "limit": ratio, "ratio_ok": ratio_ok,
            "knob": None if ratio_ok else KNOBS[0], "proj_h": round(proj, 2), "proj_limit_h": CLIFF_H,
            "over_cap": over, "max_task_s": round(max(raw.values()), 1),
            "compactions": sum(compactions(run_data[i]) for i in ids)}


# ---------------------------------------------------------------------------------------------------------------------
# Race-2 KPIs
# ---------------------------------------------------------------------------------------------------------------------
def is_protected(rel):
    """swegemma.harness.verification._is_protected_test_or_config_path, copied (stdlib only)."""
    parts = rel.split("/")
    name = parts[-1]
    if name in {"conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini", "sitecustomize.py",
                "usercustomize.py", "_swegemma_stubs.py"} or name.endswith(".pth"):
        return True
    if (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py"):
        return True
    return bool({"tests", "test", "testing"} & {p.lower() for p in parts[:-1]} and name.endswith(".py"))


def patch_files(text):
    """[(path, is_new)] from a git diff (quoted paths unquoted)."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', line)
        if m:
            cur = [m.group(2), False]
            out.append(cur)
        elif cur is not None and line.startswith("new file mode"):
            cur[1] = True
    return [(p, n) for p, n in out]


def scratch_files(files):
    return [p for p, new in files if new and (SCRATCH_ROOT.search(p) and "/" not in p or SCRATCH_ANY.search(p)
                                               or VENDORED.search(p))]


def _obeyed(hint, author, nxt):
    """Did the author's next steps (at most 2) do what `hint` asks of that stage? None when it does not address the
    stage. Locator: reply (text). Fixer: EDIT NOW -> an edit.py call; CONTEXT -> reply within 2 steps (one missing edit
    allowed); FINISH/TIME -> reply. Verifier and submitter: EDIT NOW -> an edit; CONTEXT/FINISH/TIME -> finalize.py or
    submit_patch next (FINISH also accepts a reply)."""
    text = lambda x: x["kind"] == "text"
    edit = lambda x: "edit.py" in x["args"]
    fin = lambda x: "finalize.py" in x["args"] or x["fn"] == "submit_patch"
    first = nxt[:1]
    if author == "locator":
        return any(text(x) for x in first)
    if author == "fixer":
        if hint == "LOCATOR":
            return None
        if hint == "EDIT NOW":
            return any(edit(x) for x in nxt[:2])
        if hint == "CONTEXT":
            return any(text(x) for x in nxt[:2])
        return any(text(x) for x in first)
    if author in ("verifier", "submitter"):
        if hint == "LOCATOR":
            return None
        if hint == "EDIT NOW":
            return any(edit(x) for x in nxt[:2])
        if hint == "FINISH":
            return any(fin(x) or text(x) for x in first)
        return any(fin(x) for x in first)
    return None


def footer_obedience(steps):
    """{hint: [obeyed, seen]} over the first time each hint reaches each stage in one task. A hint after which the
    stage makes no further step (the task was cut) is not counted."""
    out, seen = {}, set()
    for i, s in enumerate(steps):
        obs = s.get("obs") or ""
        if not obs or s["fn"] is None:
            continue
        for hint, needle in HINTS:
            if needle not in obs or (s["author"], hint) in seen:
                continue
            seen.add((s["author"], hint))
            nxt = [x for x in steps[i + 1:] if x["author"] == s["author"]][:2]
            ok = _obeyed(hint, s["author"], nxt) if nxt else None
            if ok is None:
                continue
            c = out.setdefault(hint, [0, 0])
            c[0] += bool(ok)
            c[1] += 1
    return out


def run_kpis(d, name):
    data = load(d, keep_obs=True)
    n = len(data)
    crashes = {k: sorted(i for i, t in data.items() if rx.search(str(t["row"].get("error") or ""))) for k, rx in CRASH.items()}
    helper_ok = cant_open = malformed = verdicts = restores = 0
    stage_max, empty, protected, scratch = [], [], [], []
    obey = {}
    for iid, t in data.items():
        for h, (o, n_) in footer_obedience(t["steps"]).items():
            c = obey.setdefault(h, [0, 0])
            c[0] += o
            c[1] += n_
        ok = seen_verdict = False
        run_stage = (None, 0)
        for s in t["steps"]:
            obs, args = s.get("obs", ""), s["args"]
            if s["fn"] == "run_skill_script" and '"status": "success"' in obs.replace('\\"', '"'):
                ok = True
            if s["fn"] == "run_command" and "/tmp/swe/" in args:
                if "can't open file" in obs:
                    cant_open += 1
                elif "No such file or directory" not in obs:
                    ok = True
            if s["fn"] == "edit_file" and s["kind"] == "malformed":
                malformed += 1
            if VERDICT.search(obs):
                seen_verdict = True
            restores += obs.count("RESTORED")
            if s["author"] != run_stage[0]:
                if run_stage[0] is not None:
                    stage_max.append(run_stage[1])
                run_stage = (s["author"], s["pt"])
            else:
                run_stage = (run_stage[0], max(run_stage[1], s["pt"]))
        if run_stage[0] is not None:
            stage_max.append(run_stage[1])
        helper_ok += ok
        verdicts += seen_verdict
        pp = os.path.join(resolve(d), "patches", f"{iid}.patch")
        text = open(pp, errors="replace").read() if os.path.isfile(pp) else ""
        if t["patch"] == 0 and not text.strip():
            empty.append(iid)
        files = patch_files(text)
        if any(is_protected(p) for p, _ in files):
            protected.append(iid)
        if scratch_files(files):
            scratch.append(iid)
    return {"run": name, "n": n, "resolved": sum(t["resolved"] for t in data.values()),
            "resolved_ids": sorted(i for i, t in data.items() if t["resolved"]),
            "crashes": {k: len(v) for k, v in crashes.items()}, "crash_ids": crashes,
            "helper_ok": helper_ok / n if n else 0.0, "cant_open_per_task": cant_open / n if n else 0.0,
            "malformed_edit_per_task": malformed / n if n else 0.0, "protected_patches": protected,
            "scratch_patches": scratch, "empty_patches": empty,
            "stage_under_line": (sum(m < COMPACTION_LINE for m in stage_max) / len(stage_max)) if stage_max else 1.0,
            "prompt_max": max(stage_max) if stage_max else 0, "compactions": sum(compactions(t) for t in data.values()),
            "verdict_share": verdicts / n if n else 0.0, "restores": restores, "footer_obedience": obey}


def race2(d, control="r2_v9_eog", treatment="r2_v10", runs=2, against="r_v4"):
    """Every KPI of SPEC 10.3 over <d>/<arm>_<k>. Returns (all_pass, rows, per_run)."""
    per = {}
    for arm in (control, treatment):
        for k in range(1, runs + 1):
            p = os.path.join(d, f"{arm}_{k}")
            if os.path.isdir(p):
                per[(arm, k)] = run_kpis(p, f"{arm}_{k}")
    rows = []

    def row(name, value, ok, note=""):
        rows.append({"kpi": name, "value": value, "pass": bool(ok), "note": note})

    ks = [k for k in range(1, runs + 1) if (control, k) in per and (treatment, k) in per]
    if not ks:
        row("runs present", sorted(per), False, f"need {control}_k and {treatment}_k")
        return False, rows, per
    paired = []
    for k in ks:
        c, t = per[(control, k)]["resolved"], per[(treatment, k)]["resolved"]
        paired.append((k, c, t))
    tsum, csum = sum(t for _, _, t in paired), sum(c for _, c, _ in paired)
    row("resolved sum", f"v10 {tsum} vs v9_eog {csum} over {len(ks)} run(s)", tsum >= csum + KPI["resolved_sum_margin"],
        f">= +{KPI['resolved_sum_margin']}")
    worst = min(t - c for _, c, t in paired)
    row("resolved per run", ", ".join(f"run{k}: {t}-{c}" for k, c, t in paired), worst >= KPI["resolved_run_floor"],
        f"no run below {KPI['resolved_run_floor']}")
    tr = [per[(treatment, k)] for k in ks]
    crash_tot = {c: sum(r["crashes"][c] for r in tr) for c in CRASH}
    row("crashes", crash_tot, all(v <= KPI["crashes_max"] for v in crash_tot.values()), "0 per class")
    row("helper availability", round(min(r["helper_ok"] for r in tr), 3), min(r["helper_ok"] for r in tr) >= KPI["helper_ok_min"])
    row("can't open file per task", round(max(r["cant_open_per_task"] for r in tr), 4),
        max(r["cant_open_per_task"] for r in tr) <= KPI["cant_open_per_task_max"])
    row("malformed edit_file per task", round(max(r["malformed_edit_per_task"] for r in tr), 3),
        max(r["malformed_edit_per_task"] for r in tr) <= KPI["malformed_edit_per_task_max"])
    prot = sum(len(r["protected_patches"]) for r in tr)
    row("protected-file patches", prot, prot <= KPI["protected_patches_max"])
    scr = sum(len(r["scratch_patches"]) for r in tr)
    row("scratch/vendored patches", scr, scr <= KPI["scratch_patches_max"])
    emp = max(len(r["empty_patches"]) * 74 / max(1, r["n"]) for r in tr)
    row("empty patches per 74", round(emp, 2), emp <= KPI["empty_patches_max"])
    under = min(r["stage_under_line"] for r in tr)
    pmax = max(r["prompt_max"] for r in tr)
    row("stage-runs under 14,336", round(under, 3), under >= KPI["stage_under_line_min"])
    row("max prompt tokens", pmax, pmax < KPI["prompt_max"])
    row("compaction events", {r["run"]: r["compactions"] for r in per.values()}, True, "reported only")
    base = load(against)
    gates = [gate(load(os.path.join(d, f"{treatment}_{k}")), base) for k in ks]
    row("time (R117 replay)", [{k: g.get(k) for k in ("ratio", "run_mean", "base_mean", "n", "over_cap", "proj_h", "knob")}
                               for g in gates],
        all(g["pass"] for g in gates),
        f"none past cap + {GATE_OVER_S:.0f} s, N={CLIFF_N} projection < {CLIFF_H:.0f} h; above {GATE_RATIO} x r_v4 "
        f"apply the knob named")
    fo = {}
    for r in tr:
        for h, (o, n_) in (r.get("footer_obedience") or {}).items():
            c = fo.setdefault(h, [0, 0])
            c[0] += o
            c[1] += n_
    row("footer obedience", {h: f"{o}/{n_}" for h, (o, n_) in sorted(fo.items())}, True, "reported only (SPEC 9.2)")
    vs = min(r["verdict_share"] for r in tr)
    row("verify verdict line", round(vs, 3), vs >= KPI["verdict_share_min"], f"restores: {sum(r['restores'] for r in tr)}")
    return all(r["pass"] for r in rows), rows, per


def kill_check(d, control="r2_v9_eog", treatment="r2_v10"):
    """SPEC 10.3 kill rule after run 1: v10 below v9_eog - 3, or any v10 crash."""
    c, t = run_kpis(os.path.join(d, f"{control}_1"), control), run_kpis(os.path.join(d, f"{treatment}_1"), treatment)
    reasons = []
    for r in (c, t):   # fail closed: a run that produced no rows (crashed eval, wrong path) never lets run 2 start
        if r["n"] == 0:
            reasons.append(f"{r['run']}_1 has no task results")
    if c["n"] and t["n"] and abs(c["n"] - t["n"]) > 0:
        reasons.append(f"task counts differ: {c['n']} vs {t['n']}")
    if t["resolved"] - c["resolved"] < KPI["kill_floor"]:
        reasons.append(f"v10 {t['resolved']} < v9_eog {c['resolved']} {KPI['kill_floor']}")
    reasons += [f"{k}={v}" for k, v in t["crashes"].items() if v > KPI["crashes_max"]]
    return (not reasons), {"control": c["resolved"], "treatment": t["resolved"], "crashes": t["crashes"], "reasons": reasons}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--design", choices=["final"])
    g.add_argument("--run")
    g.add_argument("--race2")
    g.add_argument("--kill-check")
    ap.add_argument("--base")
    ap.add_argument("--against", default="r_v4")
    ap.add_argument("--ratio", type=float, default=GATE_RATIO)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--loc-cut", type=float, default=95.0)
    ap.add_argument("--pessimistic", action="store_true")
    ap.add_argument("--measured", action="store_true")
    ap.add_argument("--no-cuts", action="store_true")
    ap.add_argument("--control", default="r2_v9_eog")
    ap.add_argument("--treatment", default="r2_v10")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--runs-dir", default=RUNS_DIR)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    say = (lambda obj, line: print(json.dumps(obj, default=str))) if a.json else (lambda obj, line: print(line))
    if a.baseline:
        base = a.base or "r_v4"
        data = load(base, a.runs_dir)
        m = st.mean(asis(t) for t in data.values())
        say({"mode": "baseline", "base": base, "mean": round(m, 2), "n": len(data)}, f"BASELINE {base} as-is L4 mean {m:.1f} s/task (n={len(data)})")
        return 0
    if a.design:
        base = a.base or "r_v9_eog"
        data = load(base, a.runs_dir)
        vals = [final(t, stretch=a.stretch, loc_cut=a.loc_cut, pessim=a.pessimistic, measured=a.measured,
                      cuts=not a.no_cuts) for t in data.values()]
        m = st.mean(vals)
        at_cap = sum(v >= CAP - 5 for v in vals)
        v4 = st.mean(asis(t) for t in load("r_v4", a.runs_dir).values()) if os.path.isdir(resolve("r_v4", a.runs_dir)) else None
        ratio = m / v4 if v4 else None
        say({"mode": "design", "design": a.design, "base": base, "mean": round(m, 2), "n": len(data),
             "ratio_to_v4": round(ratio, 4) if ratio else None, "at_cap": at_cap},
            f"DESIGN {a.design} on {base}: mean {m:.1f} s/task (n={len(data)}, {at_cap} at >= {CAP - 5:.0f} s)"
            + (f", {ratio:.2f} x v4 as-is" if ratio else ""))
        return 0
    if a.run:
        r = gate(load(a.run, a.runs_dir), load(a.against, a.runs_dir), ratio=a.ratio)
        say({"mode": "gate", **r}, f"GATE R117 {'PASS' if r['pass'] else 'FAIL'} " + json.dumps({k: v for k, v in r.items() if k != 'pass'}))
        return 0 if r["pass"] else 1
    if a.race2:
        ok, rows, per = race2(a.race2, a.control, a.treatment, a.runs, a.against)
        if a.json:
            print(json.dumps({"mode": "race2", "pass": ok, "rows": rows,
                              "runs": {f"{k[0]}_{k[1]}": {kk: vv for kk, vv in v.items() if kk != "crash_ids"} for k, v in per.items()}},
                             default=str))
        else:
            for r in rows:
                print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['kpi']:30s} {r['value']}  {r['note']}")
            print("RACE2", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    ok, info = kill_check(a.kill_check, a.control, a.treatment)
    say({"mode": "kill", "continue": ok, **info}, ("CONTINUE " if ok else "KILL ") + json.dumps(info))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
