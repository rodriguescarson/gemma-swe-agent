"""Design B time analysis: counterfactual L4 replay of the race-1 trajectories (reproduces every number in
docs/v10/design_B.md section 7).

Run:  .venv/bin/python docs/v10/design_B_replay.py        (reads eval/race1/runs/*/traces, ~20 s, stdlib only)

Cost model (research/time_model.md sect. 2, fitted on 6,730 Kaggle 4xL4 calls):
    call = 0.085 s + 28.5 ms x output tokens + 0.65 ms x uncached prompt tokens, times 1.08
    (own_data.md sect. 11: the model runs ~7-8 % low against real L4), plus the tool time measured in the trace.
v10 counterfactual per trajectory (every rule is a design-B mechanism, see design_B.md 7.3):
    - edit_file failure streaks (malformed args / not found) collapse to one replace.py call (no edit_file in v10);
    - calls after the tool-call cap are dropped (v10 budget 120 is never reached);
    - the 3rd+ identical run_command/read_file call in a stage is dropped (REPEAT banner);
    - stage-final replies are capped (locator 200, fixer 100 tokens), locator output at 1,536, others 2,048;
    - the v9 verifier's gate/repro/pytest calls become check.py calls (1 per 2), its git diff/preflight/submit/reply
      are replaced by the judge stage; its edits stay (they move into the fixer);
    - + setup stage, + judge stage, + retry path with probability p_fail when the judge is reached by the window.
The design's clock rules (locator hand-off by ~90 s, fixer reply by ~235 s) are applied unless cut=False.
"""
import collections
import glob
import json
import os
import re
import statistics as st

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "eval", "race1", "runs")
OVH, DEC, PRE, FUDGE, CAP = 0.085, 0.0285, 0.00065, 1.08, 300.0
RUNS = ("r_v4", "r_v9_eog", "r_v9_c", "r_v9_eg", "r_v9_eo", "r_v9_og")
REPLY_CAP = {"locator": 200, "fixer": 100, "verifier": 60}
OUT_CAP = {"locator": 1536}


def load(run):
    res = {}
    for line in open(os.path.join(BASE, run, "task_results.jsonl")):
        r = json.loads(line)
        res[r["instance_id"]] = r
    out = {}
    for fp in glob.glob(os.path.join(BASE, run, "traces", "trace_*.json")):
        iid = os.path.basename(fp)[6:-5]
        steps, prev = [], {}
        for s in json.load(open(fp))["steps"]:
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
            obs = str(s.get("observation") or "")
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
            steps.append(dict(author=author, ct=ct, unc=unc, tool_s=min(tool_s, 180.0), fn=fn, args=args, kind=kind))
        rr = res.get(iid) or {}
        out[iid] = dict(steps=steps, resolved=bool(rr.get("resolved")), patch=int(rr.get("agent_patch_size") or 0))
    return out


def cost(s, ct=None):
    return FUDGE * (OVH + DEC * (s["ct"] if ct is None else ct) + PRE * s["unc"]) + s["tool_s"]


def asis(task):
    return min(CAP, sum(cost(s) for s in task["steps"]))


def p_fail(task):
    """Probability that the v10 judge says FAIL: empty -> 1; unresolved non-empty -> 0.6; resolved -> 0.12 (false FAIL)."""
    if task["patch"] == 0:
        return 1.0
    return 0.12 if task["resolved"] else 0.6


def stages(task, drop_vgate=True):
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
        ct = min(s["ct"], OUT_CAP.get(a, 2048))
        if s["kind"] == "text":
            ct = min(ct, REPLY_CAP[a])
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


SETUP = FUDGE * (2 * OVH + DEC * 40 + PRE * 5600) + 0.2           # harness-prompt prefill + install call
JUDGE = FUDGE * (3 * OVH + DEC * 90 + PRE * (2200 + 900)) + 3.0   # 3 calls + gate tool time


def v10(task, stretch=1.0, win=175.0, deadline=255.0, cut=True, drop_vgate=True, retry_calls=8, retry_out=1000, retry=True):
    stt = stages(task, drop_vgate)
    loc = stretch * stt["locator"]
    loc = min(loc, 90.0) if cut else loc
    t = SETUP + loc
    fix = stretch * (stt["fixer"] + stt["check"])
    fix = min(fix, max(0.0, 235.0 - t)) if cut else fix
    t += fix + JUDGE
    tj, fired = t, 0.0
    if retry and tj <= win:
        fired = p_fail(task)
        rc = FUDGE * (retry_calls * OVH + retry_out * DEC + (3300 + retry_calls * 700) * PRE) + 12.0
        rc = min(rc * stretch, max(0.0, deadline - tj)) + 9.0   # + finalizer
        t = tj + fired * rc
    return min(CAP, t), tj, fired


def main():
    data = {r: load(r) for r in RUNS}
    v4 = st.mean(asis(t) for t in data["r_v4"].values())
    print("1. as-is L4 replay, mean agent s/task:", "  ".join(f"{r}:{st.mean(asis(t) for t in data[r].values()):.1f}" for r in RUNS))

    def row(label, **kw):
        cells = []
        for r in RUNS:
            v = [v10(t, **kw) for t in data[r].values()]
            m = st.mean(x[0] for x in v)
            cells.append(f"{r[2:]}:{m:5.1f} ({m / v4:.2f}) fire {sum(x[2] for x in v) / len(v):.2f}")
        print(f"   {label:46s} " + " | ".join(cells))

    print("2. v10 counterfactual from each base trajectory: mean s/task (ratio to v4 as-is) and retry fire rate")
    row("no retry", retry=False)
    row("DESIGN: window 175 s, retry deadline 255 s")
    row("window 190 s, deadline 262 s", win=190, deadline=262)
    row("pessimistic: clock rules ignored, v9 verifier calls kept", cut=False, drop_vgate=False)
    row("pessimistic + retry 12 calls / 1,800 tokens", cut=False, drop_vgate=False, retry_calls=12, retry_out=1800)
    print("3. hidden-like tasks (every stage x2, then the design's clock rules)")
    row("x2 stretch, design settings", stretch=2.0)
    print("   v4 as-is x2 capped at 300 s:", "  ".join(f"{r[2:]}:{st.mean(min(CAP, 2 * asis(t)) for t in data[r].values()):.1f}" for r in RUNS))
    print("4. per-stage projection (design settings, no retry)")
    for r in ("r_v4", "r_v9_eog"):
        ss = [stages(t) for t in data[r].values()]
        tj = [v10(t, retry=False)[1] for t in data[r].values()]
        tj2 = [v10(t, retry=False, stretch=2.0)[1] for t in data[r].values()]
        n = len(ss)
        print(f"   {r}: setup {SETUP:.1f} s | locator {st.mean(s['locator'] for s in ss):.1f} s | fixer+checks "
              f"{st.mean(s['fixer'] + s['check'] for s in ss):.1f} s | judge {JUDGE:.1f} s | judge reached by 175 s: "
              f"{sum(x <= 175 for x in tj)}/{n} (x2 stretch: {sum(x <= 175 for x in tj2)}/{n}), median {st.median(tj):.0f} s")
    print("5. 12 h, every task at the cap (600 s startup + N x (300 + 3.6 setup + 5 overshoot + 1 teardown)):",
          "  ".join(f"N={n}: {(600 + n * 309.6) / 3600:.2f} h" for n in (120, 130)))


if __name__ == "__main__":
    main()
