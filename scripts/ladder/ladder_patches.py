"""Step 2 (CPU kernel, no GPU quota): turn the ladder run's snapshots into a rescore job for make_eval_kernel.py --patches.
Input : <L1>/results.jsonl (final patch per task) and <L1>/snapshots.jsonl.
Output: labels.json = list of {task, cfg, patch}; cfg = "v<j>" where j is the index of the distinct non-empty tree of that task in time order,
        plus versions.json = {task: [sha,...]} so ladder_analyze.py can map sha -> cfg.
Usage : python ladder_patches.py <L1_dir> <out_dir>   then   python scripts/make_eval_kernel.py <any v12b bundle> g4-ladder-rescore --patches <out_dir>/labels.json --oracle? (see PLAN)"""
import json, sys, hashlib, os
L1, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
final = {}
for l in open(os.path.join(L1, "results.jsonl")):
    r = json.loads(l); final[r["id"]] = r.get("patch") or ""
trees = {t: {} for t in final}     # task -> sha -> patch (insertion order = time order)
for l in open(os.path.join(L1, "snapshots.jsonl")):
    r = json.loads(l)
    if "patch" in r and r["task"] in trees and r["patch"].strip():
        trees[r["task"]].setdefault(r["sha"], r["patch"])
for t, p in final.items():
    if p.strip(): trees[t].setdefault(hashlib.sha1(p.encode()).hexdigest(), p)
labels, versions = [], {}
for t, d in trees.items():
    versions[t] = list(d)
    for j, (sha, p) in enumerate(d.items()): labels.append(dict(task=t, cfg="v%d" % j, patch=p))
json.dump(labels, open(os.path.join(OUT, "labels.json"), "w")); json.dump(versions, open(os.path.join(OUT, "versions.json"), "w"))
print("tasks", len(trees), "distinct non-empty trees", len(labels), "max versions per task", max((len(v) for v in versions.values()), default=0))
