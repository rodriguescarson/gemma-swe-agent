import json, collections, statistics as st
rows = [json.loads(l) for l in open("inventory_rows.jsonl")]
R = [r for r in rows if r["resolved"]]
def q(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))] if xs else 0
print("## per source")
for s in sorted({r["source"] for r in rows}):
    a = [r for r in rows if r["source"] == s]; b = [r for r in a if r["resolved"]]
    print(f"| {s} | {len({r['run'] for r in a})} | {len(a)} | {len(b)} | {len({r['task'] for r in b})} |")
print("## per run (bundle)")
for run in sorted({(r["source"].split()[0], r["run"], r["bundle"]) for r in rows}):
    a = [r for r in rows if (r["source"].split()[0], r["run"], r["bundle"]) == run]; b = [r for r in a if r["resolved"]]
    print(f"| {run[0]} | {run[1]} | {run[2]} | {len(a)} | {len(b)} |")
print("## per bundle version (resolved)")
bc = collections.Counter(r["bundle"] for r in R); print(sorted(bc.items()))
print("## per task")
tc = collections.Counter(r["task"] for r in R)
print("tasks with >=1:", len(tc), " histogram of resolved-runs-per-task:", sorted(collections.Counter(tc.values()).items()))
print("top:", tc.most_common(15)); print("bottom:", sorted(tc.items(), key=lambda x: x[1])[:15])
repo = collections.Counter(t.rsplit("_", 1)[0] for t in tc); print("repos (tasks):", repo, " runs:", collections.Counter(r["task"].rsplit("_",1)[0] for r in R))
print("## stages (resolved)")
pat = collections.Counter("/".join(r["stages"]) for r in R); print(pat.most_common(12))
print("stage restarts (a stage name appearing twice):", sum(1 for r in R if len(r["stages"]) != len(set(r["stages"]))))
print("nudges in resolved:", sum(r["nudges"] for r in R), "runs with nudges:", sum(1 for r in R if r["nudges"]))
print("compaction detected (prompt drop) in resolved:", sum(1 for r in R if r["compactions_detected"]), "of", len(R), "; kaggle resolved:", sum(1 for r in R if r["source"].startswith("kaggle")), "kaggle resolved with compaction:", sum(1 for r in R if r["source"].startswith("kaggle") and r["compactions_detected"]))
print("## tokens (resolved)")
for k in ("calls", "n_llm_calls", "sum_completion", "max_prompt", "sum_prompt"):
    xs = [r[k] for r in R]; print(k, "sum", sum(xs), "median", q(xs, .5), "p90", q(xs, .9), "max", max(xs))
# per stage calls
sc = collections.defaultdict(list)
for r in R:
    for a, c in zip(r["stages"], r["stage_calls"]): sc[a].append(c)
print("calls per stage-segment:", {a: (len(v), q(v, .5), q(v, .9), max(v)) for a, v in sc.items()})
print("## validity (resolved)")
nb = [r for r in R if r["bad_calls"]]
print("resolved runs with >=1 malformed call:", len(nb), "/", len(R), "; malformed calls:", sum(r["bad_calls"] for r in R), "/", sum(r["calls"] for r in R))
print("kinds:", sum((collections.Counter(r["bad_kinds"]) for r in R), collections.Counter()))
print("runs with >=5 malformed:", sum(1 for r in R if r["bad_calls"] >= 5), "; quoted-arg calls:", sum(r["quoted_arg_calls"] for r in R), "runs:", sum(1 for r in R if r["quoted_arg_calls"]))
print("multi-call steps:", sum(r["multi_call_steps"] for r in R), "unparsed-text steps:", sum(r["unparsed_text_steps"] for r in R))
print("all runs malformed share:", sum(r["bad_calls"] for r in rows), "/", sum(r["calls"] for r in rows))
print("## duplicates")
hc = collections.Counter(r["seq_hash"] for r in R)
dups = {h: [ (r["run"], r["source"].split()[0], r["task"]) for r in R if r["seq_hash"] == h] for h, c in hc.items() if c > 1}
print("identical tool-call sequences among resolved:", sum(c - 1 for c in hc.values() if c > 1), "extra copies in", len(dups), "groups")
for h, v in list(dups.items())[:10]: print(h, v)
hall = collections.Counter(r["seq_hash"] for r in rows)
print("all runs: identical groups", sum(1 for c in hall.values() if c > 1), "extra copies", sum(c - 1 for c in hall.values() if c > 1))
print("## errors field on resolved:", collections.Counter(str(r["error"])[:60] for r in R).most_common(5))
