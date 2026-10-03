"""Public-task strata vs solve rate: what features of a task predict our agent's success, so we can reason
about how a hidden set with different features would score. Read-only; stdlib + the installed swegemma."""
import json, re, sys, collections, statistics
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/.venv/lib/python3.12/site-packages")
from swegemma.difficulty import analyze_task

R = "/Users/carson/Projects/gemma-swe-agent"
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(R + "/data/tasks.jsonl")}
valid = [l.strip() for l in open(R + "/data/kaggle_valid_ids.txt") if l.strip()]

def load_kaggle(path, cfg=None):
    out = {}
    for l in open(path):
        r = json.loads(l)
        if cfg and r.get("cfg") != cfg:
            continue
        out[r["id"]] = r
    return out

def load_pod(path):
    return {json.loads(l)["instance_id"]: json.loads(l) for l in open(path)}

runs = {}
for name in ("e74_v2", "e74_v3", "g4-l4-v4", "g4-l4-v9-eog"):
    d = load_kaggle(R + "/eval/kaggle/%s/results.jsonl" % name)
    runs["K:" + name] = {i: bool(d[i]["resolved"]) for i in valid if i in d}
rs = R + "/eval/kaggle/rescore_fair/results.jsonl"
for cfg in ("p_v4", "p_v6", "p_v7", "p_v8"):
    d = load_kaggle(rs, cfg)
    runs["RS:" + cfg] = {i: bool(d.get(i, {}).get("resolved", False)) for i in valid}
for name, p in (("P:p1_v4", "/eval/pair1/eval/runs/p1_v4"), ("P:p1_v10", "/eval/pair1/eval/runs/p1_v10"),
                ("P:r2_v10_1", "/eval/race2/eval/runs/r2_v10_1"), ("P:r2_v9eog_1", "/eval/race2/eval/runs/r2_v9_eog_1")):
    d = load_pod(R + p + "/task_results.jsonl")
    runs[name] = {i: bool(d[i]["resolved"]) for i in valid if i in d}

for k, v in runs.items():
    print("%-16s n=%d solved=%d (%.0f%%)" % (k, len(v), sum(v.values()), 100.0 * sum(v.values()) / len(v)))

def p_of(i):
    xs = [v[i] for v in runs.values() if i in v]
    return sum(xs) / len(xs) if xs else None

v4 = runs["K:g4-l4-v4"]

def gold_funcs(patch):
    return set(re.findall(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", patch, re.M))

feat = {}
for i in valid:
    t = tasks[i]
    d = analyze_task(t)
    m = d.metrics
    patch = t["patch"]
    names = gold_funcs(patch)
    st = t["problem_statement"]
    feat[i] = dict(
        repo=t["repo"].split("/")[-1],
        year=t["created_at"][:4],
        post_cutoff=t["created_at"] >= "2025-02-01",
        words=m.prompt_words,
        overlap=m.has_lexical_overlap,
        tb=m.has_traceback_or_code,
        files=m.num_files,
        churn=m.total_churn,
        tier=d.difficulty_tier,
        comp=d.composite_score,
        async_touch=bool(re.search(r"^[+\- ].*async\s+def", patch, re.M)) or "async def" in patch,
        names_symbol=any(n in st for n in names),
        p=p_of(i),
        v4=v4.get(i),
    )

def table(key, fn=None, order=None):
    groups = collections.defaultdict(list)
    for i, f in feat.items():
        groups[fn(f) if fn else f[key]].append(i)
    print("\n%s" % key)
    print("  %-14s %4s %8s %10s" % ("value", "n", "v4 L4", "pooled p"))
    for g in (order or sorted(groups, key=str)):
        ids = groups.get(g, [])
        if not ids:
            continue
        s = sum(1 for i in ids if feat[i]["v4"])
        pp = statistics.mean(feat[i]["p"] for i in ids)
        print("  %-14s %4d %4d/%-3d %9.2f" % (g, len(ids), s, len(ids), pp))

table("repo")
table("post_cutoff")
table("year")
table("tier", order=["Easy", "Medium", "Hard", "Extreme"])
table("overlap")
table("tb")
table("words", lambda f: "<25" if f["words"] < 25 else "<60" if f["words"] < 60 else "<150" if f["words"] < 150 else ">=150",
      order=["<25", "<60", "<150", ">=150"])
table("files", lambda f: "1" if f["files"] <= 1 else "2" if f["files"] == 2 else "3+", order=["1", "2", "3+"])
table("churn", lambda f: "<=10" if f["churn"] <= 10 else "<=40" if f["churn"] <= 40 else ">40", order=["<=10", "<=40", ">40"])
table("async_touch")
table("names_symbol")

# pooled mean p overall
allp = [f["p"] for f in feat.values()]
print("\npooled mean p over %d runs: %.3f ; v4 L4 = %d/74" % (len(runs), statistics.mean(allp), sum(1 for f in feat.values() if f["v4"])))
dist = collections.Counter(round(f["p"], 1) for f in feat.values())
print("per-task p histogram (rounded):", sorted(dist.items()))
json.dump(feat, open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "feat.json"), "w"), indent=1)
