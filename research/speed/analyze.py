"""Speed tables for speed.md from steps.jsonl / tasks.jsonl (extract.py). Stdlib only.
All seconds are L4 seconds: Kaggle real; pod runs x scale (1.7 pair1/race2, 1.72 race1)."""
import collections
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
S = [json.loads(l) for l in open(os.path.join(HERE, "steps.jsonl"))]
T = {(t["run"], t["tid"]): t for t in (json.loads(l) for l in open(os.path.join(HERE, "tasks.jsonl")))}
BY = collections.defaultdict(list)
for s in S:
    BY[(s["run"], s["tid"])].append(s)
CAP = 300.0
STAGES = ("setup", "locator", "fixer", "verifier", "submitter")
V10_MAX = {"setup": 256, "locator": 768, "fixer": 2048, "verifier": 2048, "submitter": 1024}


def sc(run):
    return T[next(k for k in T if k[0] == run)]["scale"]


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def dur(s, k):
    return (s["llm_s"] + s["tool_s"]) * k


def task_metrics(run, tid):
    k = T[(run, tid)]["scale"]
    L = BY[(run, tid)]
    t = T[(run, tid)]
    out = dict(run=run, tid=tid, resolved=t["resolved"], patch=t["patch"], err=t["err"] or "")
    end = max([s["t_end"] for s in L] or [0]) * k
    out["end"] = end
    out["capped"] = ("timeout" in (t["err"] or "")) or end >= CAP - 3
    out["n"] = len(L)
    edits = [s for s in L if s.get("src_edit")]
    out["t_first_edit"] = edits[0]["t_end"] * k if edits else None
    out["t_last_edit"] = edits[-1]["t_end"] * k if edits else None
    rst = [s["restored_t"] for s in L if s.get("restored_t") is not None]
    if rst and out["t_last_edit"] is not None:
        # the graded tree is the restored checkpoint: its time is the helper clock (already L4-scaled)
        out["t_final_patch"] = min(out["t_last_edit"], float(rst[-1]))
    else:
        out["t_final_patch"] = out["t_last_edit"]
    ver = [s for s in L if s.get("helper") == "verify" and s.get("vk") not in (None, "repro")]
    out["t_first_verify"] = ver[0]["t_end"] * k if ver else None
    fin = [s for s in L if s.get("cat") == "finalize_ready"]
    out["t_finalize"] = fin[0]["t_end"] * k if fin else None
    sub = [s for s in L if s.get("fn") == "submit_patch"]
    out["t_submit"] = sub[0]["t_end"] * k if sub else None
    stg = collections.defaultdict(lambda: dict(n=0, s=0.0, llm=0.0, tool=0.0, ct=0, text_ct=0, t0=None, t1=None))
    for s in L:
        a = s["author"]
        d = stg[a]
        d["n"] += 1
        d["s"] += dur(s, k)
        d["llm"] += s["llm_s"] * k
        d["tool"] += s["tool_s"] * k
        d["ct"] += s["ct"]
        if s["fn"] is None:
            d["text_ct"] += s["ct"]
        d["t0"] = (s["t_end"] - (s["llm_s"] + s["tool_s"])) * k if d["t0"] is None else d["t0"]
        d["t1"] = s["t_end"] * k
    out["stages"] = {a: dict(v) for a, v in stg.items()}
    out["attributed"] = sum(v["s"] for v in stg.values())
    return out


def waste(run, tid):
    """Per-step waste category (first match wins) -> {cat: [steps, L4 s, output tokens]}."""
    k = T[(run, tid)]["scale"]
    L = BY[(run, tid)]
    w = collections.defaultdict(lambda: [0, 0.0, 0])
    last_out = {}
    for s in L:
        c = None
        cat = s.get("cat")
        key = (s["author"], s["fn"], s.get("cmd"))
        if cat in ("malformed", "cant_open", "postcap"):
            c = "failed call (" + cat + ")"
        elif cat in ("edit_fail", "native_edit_fail"):
            c = "failed edit"
        elif cat == "edit_repeat":
            c = "edit ALREADY TRIED"
        elif cat == "verify_same":
            c = "verify SAME AS LAST RUN"
        elif cat == "repeat_note":
            c = "helper repeat NOTE"
        elif s["fn"] is not None and s.get("oh") is not None and last_out.get(key) == s.get("oh"):
            c = "exact repeat, same output"
        elif s.get("reread_stage"):
            c = "re-read (same stage)"
        elif cat == "pseudo_call_text":
            c = "tool call written as text"
        elif s["author"] == "setup":
            c = "setup stage"
        elif s["fn"] is None:
            c = "stage-ending text reply"
        if s["fn"] is not None and s.get("oh") is not None:
            last_out[key] = s.get("oh")
        if c:
            w[c][0] += 1
            w[c][1] += dur(s, k)
            w[c][2] += s["ct"]
    return w


def runaway(run, tid, thr=1000):
    k = T[(run, tid)]["scale"]
    return [(s["author"], s["ct"], dur(s, k)) for s in BY[(run, tid)] if s["ct"] >= thr]


def tasks_of(run):
    return sorted(t for (r, t) in T if r == run)


if __name__ == "__main__":
    runs = sys.argv[1:] or ["p1_v10", "r2_v10_1", "p1_v4", "k_v4", "k_v9_eog", "r2_v9_eog_1"]
    for run in runs:
        M = [task_metrics(run, t) for t in tasks_of(run)]
        n = len(M)
        solved = [m for m in M if m["resolved"]]
        print(f"\n=== {run}: n={n} solved={len(solved)} capped={sum(m['capped'] for m in M)} "
              f"capped&solved={sum(m['capped'] and m['resolved'] for m in M)}")
        e = [m["end"] for m in M]
        print(f"agent end L4 s: mean {st.mean(e):.1f} p50 {q(e,.5):.1f} p90 {q(e,.9):.1f}; solved mean "
              f"{st.mean([m['end'] for m in solved]):.1f} p50 {q([m['end'] for m in solved],.5):.1f}; "
              f"unsolved mean {st.mean([m['end'] for m in M if not m['resolved']]):.1f}")
        att = [m["attributed"] / max(m["end"], 1e-9) for m in M if m["end"] > 0]
        print(f"attributed share (LLM+tool of end) mean {st.mean(att):.3f}")
        # per stage
        print("stage      steps/task  s/task  llm   tool  ct/task textct  share")
        tot = sum(m["end"] for m in M)
        for a in STAGES + ("?",):
            rows = [m["stages"].get(a) for m in M]
            rows = [r for r in rows if r]
            if not rows:
                continue
            ns = sum(r["n"] for r in rows) / n
            ss = sum(r["s"] for r in rows) / n
            print(f"{a:10} {ns:10.1f} {ss:7.1f} {sum(r['llm'] for r in rows)/n:5.1f} {sum(r['tool'] for r in rows)/n:5.1f} "
                  f"{sum(r['ct'] for r in rows)/n:7.0f} {sum(r['text_ct'] for r in rows)/n:6.0f}  {ss*n/tot:5.1%}")
        for key in ("t_first_edit", "t_first_verify", "t_final_patch", "t_finalize", "t_submit"):
            allv = [m[key] for m in M if m[key] is not None]
            sv = [m[key] for m in solved if m[key] is not None]
            print(f"{key:15} all n={len(allv):2} p50 {q(allv,.5):6.1f} p90 {q(allv,.9):6.1f} | solved n={len(sv):2} "
                  f"p50 {q(sv,.5):6.1f} p75 {q(sv,.75):6.1f} p90 {q(sv,.9):6.1f} max {max(sv) if sv else float('nan'):6.1f}")
        post = [m["end"] - m["t_final_patch"] for m in solved if m["t_final_patch"] is not None]
        print(f"solved: time after final patch: mean {st.mean(post):.1f} p50 {q(post,.5):.1f} p90 {q(post,.9):.1f}")
        # waste
        W = collections.defaultdict(lambda: [0, 0.0, 0])
        for m in M:
            for c, v in waste(run, m["tid"]).items():
                for i in range(3):
                    W[c][i] += v[i]
        print("waste category                 steps/task  L4 s/task  ct/task")
        for c, v in sorted(W.items(), key=lambda kv: -kv[1][1]):
            print(f"  {c:30} {v[0]/n:8.2f} {v[1]/n:9.1f} {v[2]/n:8.0f}")
        rw = [x for m in M for x in runaway(run, m["tid"])]
        print(f"calls >=1000 output tokens: {len(rw)} ({sum(x[2] for x in rw)/n:.1f} L4 s/task) by stage "
              f"{collections.Counter(x[0] for x in rw)}")
