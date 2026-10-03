import json, itertools, random, statistics, collections
import os
feat = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "feat.json")))
R = "/Users/carson/Projects/gemma-swe-agent"
valid = list(feat)
# per-run solve sets (same 12 runs as strata.py)
import importlib.util, sys
runs = {}
def lk(p, cfg=None):
    d = {}
    for l in open(p):
        r = json.loads(l)
        if cfg and r.get("cfg") != cfg: continue
        d[r["id"]] = r
    return d
for n in ("e74_v2","e74_v3","g4-l4-v4","g4-l4-v9-eog"):
    d = lk(R+"/eval/kaggle/%s/results.jsonl"%n); runs[n] = {i for i in valid if d.get(i,{}).get("resolved")}
for c in ("p_v4","p_v6","p_v7","p_v8"):
    d = lk(R+"/eval/kaggle/rescore_fair/results.jsonl", c); runs[c] = {i for i in valid if d.get(i,{}).get("resolved")}
for n,p in (("p1_v4","pair1/eval/runs/p1_v4"),("p1_v10","pair1/eval/runs/p1_v10"),("r2_v10","race2/eval/runs/r2_v10_1"),("r2_v9eog","race2/eval/runs/r2_v9_eog_1")):
    d = {json.loads(l)["instance_id"]: json.loads(l) for l in open(R+"/eval/"+p+"/task_results.jsonl")}
    runs[n] = {i for i in valid if d.get(i,{}).get("resolved")}
names = list(runs)
single = statistics.mean(len(runs[n]) for n in names)
print("single-run mean %.1f / 74" % single)
random.seed(0)
for k in (1,2,3,4,6,12):
    us = []
    for _ in range(2000):
        pick = random.sample(names, k)
        us.append(len(set().union(*[runs[n] for n in pick])))
    print("union of %2d random runs: mean %.1f (ratio to single %.2f)" % (k, statistics.mean(us), statistics.mean(us)/single))
# time by stratum on the faithful L4 v4 run
d = lk(R+"/eval/kaggle/g4-l4-v4/results.jsonl")
def bucket(f): 
    w=f["words"]; return "<25" if w<25 else "<60" if w<60 else "<150" if w<150 else ">=150"
g = collections.defaultdict(list)
for i,f in feat.items():
    r = d[i]; g[bucket(f)].append((r["secs"], "timeout" in (r["err"] or ""), r["resolved"], not (r.get("patch") or "").strip()))
for b in ("<25","<60","<150",">=150"):
    xs = g[b]
    print("words %-6s n=%2d mean secs %.0f capped %d solved %d empty %d" % (b, len(xs), statistics.mean(x[0] for x in xs), sum(x[1] for x in xs), sum(x[2] for x in xs), sum(x[3] for x in xs)))
g = collections.defaultdict(list)
for i,f in feat.items():
    r = d[i]; g[f["tier"]].append((r["secs"], "timeout" in (r["err"] or ""), r["resolved"]))
for b in ("Easy","Medium","Hard","Extreme"):
    xs = g[b]
    print("tier %-8s n=%2d mean secs %.0f capped %d solved %d" % (b, len(xs), statistics.mean(x[0] for x in xs), sum(x[1] for x in xs), sum(x[2] for x in xs)))
# solved vs unsolved time
s = [d[i]["secs"] for i in valid if d[i]["resolved"]]; u = [d[i]["secs"] for i in valid if not d[i]["resolved"]]
print("v4 L4 mean secs solved %.0f (n=%d) unsolved %.0f (n=%d)" % (statistics.mean(s), len(s), statistics.mean(u), len(u)))
# examples of <25-word statements
import json as J
tasks = {J.loads(l)["instance_id"]: J.loads(l) for l in open(R+"/data/tasks.jsonl")}
short = [i for i,f in feat.items() if f["words"] < 25]
for i in short[:6]:
    print(i, repr(tasks[i]["problem_statement"][:160]))
