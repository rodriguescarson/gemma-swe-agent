"""Decision table for runs on the same task set: solved, empty patches, timeouts, avg/median seconds, tool calls/task,
per-stage calls/task (from traces), and paired wins/losses + exact sign test vs a baseline run.
Usage: python eval/summary.py <baseline_run_dir> <run_dir> [<run_dir> ...]"""
import glob, json, math, os, statistics, sys, collections
def load(d):
    R = {}
    for p in glob.glob(os.path.join(d, "task_results.jsonl")):
        for l in open(p):
            x = json.loads(l); R[x["instance_id"]] = x
    return R
def stage_calls(d):
    c = collections.Counter(); n = 0
    for f in glob.glob(os.path.join(d, "traces", "trace_*.json")):
        n += 1
        for s in json.load(open(f)).get("steps", []):
            for tc in (s.get("tool_calls") or []):
                c[(tc.get("extra") or {}).get("author", "?")] += 1
    return {k: round(v / max(1, n), 1) for k, v in c.most_common(4)}
def sign_p(a, b):
    n = a + b
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, j) for j in range(min(a, b) + 1)) / 2 ** n)
runs = [(os.path.basename(d.rstrip("/")), d, load(d)) for d in sys.argv[1:]]
base_name, _, base = runs[0]
print(f"{'run':10} {'n':>3} {'solved':>6} {'empty':>5} {'tmout':>5} {'avg_s':>6} {'med_s':>6} {'calls':>6}  vs {base_name}: wins/losses p   stage calls/task")
for name, d, R in runs:
    v = list(R.values()); n = len(v)
    solved = sum(bool(x["resolved"]) for x in v); empty = sum(1 for x in v if not x.get("agent_patch_size"))
    tmo = sum(1 for x in v if "timeout" in (x.get("error") or "").lower())
    secs = [x.get("duration_seconds") or 0 for x in v]; calls = [x.get("tool_calls") or 0 for x in v]
    ids = set(R) & set(base)
    w = sum(1 for i in ids if R[i]["resolved"] and not base[i]["resolved"]); l = sum(1 for i in ids if base[i]["resolved"] and not R[i]["resolved"])
    print(f"{name:10} {n:>3} {solved:>6} {empty:>5} {tmo:>5} {statistics.mean(secs):>6.0f} {statistics.median(secs):>6.0f} {statistics.mean(calls):>6.1f}  {w:>3}/{l:<3} p={sign_p(w, l):.2f}   {stage_calls(d)}")
